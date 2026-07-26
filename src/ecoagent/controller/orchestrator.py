from ecoagent.controller.constants import (
    ZONE_NAMES, DWELL_CYCLES,
    HEATING_BOUND_MIN, HEATING_BOUND_MAX,
    COOLING_BOUND_MIN, COOLING_BOUND_MAX,
    SATURATION_CYCLE_THRESHOLD,
    COMFORT_TRIGGER_LOW, COMFORT_TRIGGER_HIGH,
    READBACK_TOLERANCE,
)
from ecoagent.controller.scheduler import Scheduler
from ecoagent.controller.zone_state import create_zone_states
from ecoagent.controller.zone_controller import ZoneController, create_zone_controllers
from ecoagent.controller.safety_guard import validate_command
from ecoagent.controller.actuator import ActuatorManager
from ecoagent.controller.logger import ControllerLogger
from ecoagent.supervisor.runtime_snapshot import create_snapshot
from ecoagent.supervisor.history_buffer import HistoryBuffer
from ecoagent.supervisor.events import (
    EventBus, CycleCompleted,
    SupervisorProposalAccepted, SupervisorProposalModified,
    SupervisorProposalRejected,
)
from ecoagent.supervisor.constants import STATE_SUPERVISOR


class Orchestrator:
    def __init__(self, log_dir="logs/controller_output", supervisor=None, history_size=96):
        self.scheduler = Scheduler()
        self.zone_states = create_zone_states()
        self.zone_controllers = create_zone_controllers()
        self.actuator_manager = ActuatorManager()
        self.logger = ControllerLogger(output_dir=log_dir)
        self.supervisor = supervisor
        self.history_buffer = HistoryBuffer(max_size=history_size)
        self.event_bus = EventBus()

    def create_callback(self):
        def callback(api, state):
            try:
                self._execute_cycle(api, state)
            except Exception as e:
                self.logger.log_exception(self.scheduler.callback_counter, e)
        return callback

    def _execute_cycle(self, api, state):
        should_run = self.scheduler.tick(api, state)

        if self.supervisor:
            self.supervisor.clear_expired(self.scheduler.callback_counter)

        if not should_run:
            if self.scheduler.timeout_triggered:
                self.logger.log_event(
                    self.scheduler.callback_counter,
                    "CRITICAL_INITIALIZATION_TIMEOUT",
                    f"Initialization timed out after {self.scheduler.init_timeout} callbacks without handle resolution; controller DISABLED.",
                )
                self.scheduler.timeout_triggered = False
            elif self.scheduler.should_log_reminder:
                self.logger.log_event(
                    self.scheduler.callback_counter,
                    "CONTROLLER_DISABLED_REMINDER",
                    "Controller is in DISABLED status. Control actions suppressed.",
                )
            return

        if not self.actuator_manager.resolved:
            all_failed = self.actuator_manager.resolve_handles(api, state, self.zone_states)
            self.scheduler.notify_handles_resolved(all_failed)
            if all_failed:
                self.logger.log_event(
                    self.scheduler.callback_counter,
                    "all_zones_degraded",
                    "all actuator handles failed to resolve",
                )
                return
            else:
                self.logger.log_event(
                    self.scheduler.callback_counter,
                    "HANDLE_RESOLUTION_SUCCESS",
                    "All 10 actuator handles and 7 sensor handles resolved and cached successfully.",
                )

        sensor_reading = self.actuator_manager.read_sensors(api, state, self.zone_states)

        for zone_name in ZONE_NAMES:
            self.zone_states[zone_name].current_temperature = sensor_reading.zone_temperatures[zone_name]

        zone_results = {}

        for zone_name in ZONE_NAMES:
            zs = self.zone_states[zone_name]
            zc = self.zone_controllers[zone_name]

            proposal = self.supervisor.get_pending_proposal(zone_name) if self.supervisor else None

            if proposal is not None:
                proposed_heating = proposal.heating_setpoint
                proposed_cooling = proposal.cooling_setpoint
                zs.controller_state = STATE_SUPERVISOR
                zs.previous_decision = f"supervisor_proposal_{proposal.source}"
            else:
                proposed = zc.evaluate(zs)
                proposed_heating = proposed.heating_setpoint
                proposed_cooling = proposed.cooling_setpoint
                zs.controller_state = proposed.state
                zs.previous_decision = proposed.decision_reason

            validated = validate_command(zs, proposed_heating, proposed_cooling)

            result = {
                "proposed_heating": proposed_heating,
                "proposed_cooling": proposed_cooling,
                "validated_heating": validated.heating_setpoint,
                "validated_cooling": validated.cooling_setpoint,
                "safety_reason": validated.reason,
                "written": False,
                "readback_ok": False,
            }

            if validated.approved and not zs.degraded:
                setpoints_changed = (
                    abs(validated.heating_setpoint - zs.current_heating_setpoint) > 0.001
                    or abs(validated.cooling_setpoint - zs.current_cooling_setpoint) > 0.001
                )

                write_result = self.actuator_manager.write_and_verify(
                    api, state, zone_name,
                    validated.heating_setpoint,
                    validated.cooling_setpoint,
                )

                result["written"] = True
                result["readback_ok"] = write_result.success

                zs.record_verification({
                    "written_h": write_result.written_heating,
                    "readback_h": write_result.readback_heating,
                    "written_c": write_result.written_cooling,
                    "readback_c": write_result.readback_cooling,
                    "success": write_result.success,
                })

                if write_result.success:
                    zs.record_readback_success()

                    if setpoints_changed:
                        zs.dwell_timer = 0
                    else:
                        zs.dwell_timer += 1

                    zs.current_heating_setpoint = validated.heating_setpoint
                    zs.current_cooling_setpoint = validated.cooling_setpoint
                    zs.previous_actuator_command = (validated.heating_setpoint, validated.cooling_setpoint)

                    if proposal is not None:
                        self._emit_supervisor_outcome(proposal, validated, zs)
                else:
                    zs.record_readback_failure()
                    zs.dwell_timer += 1

                    if proposal is not None:
                        self.event_bus.emit(SupervisorProposalRejected(
                            zone_name, "readback_failure", self.scheduler.callback_counter,
                        ))
                        self.supervisor.consume_proposal(zone_name)
            else:
                zs.dwell_timer += 1

                if proposal is not None:
                    self.event_bus.emit(SupervisorProposalRejected(
                        zone_name, validated.reason, self.scheduler.callback_counter,
                    ))
                    self.supervisor.consume_proposal(zone_name)

            self._update_saturation(zs, validated)

            zone_results[zone_name] = result

        if sensor_reading.anomalies:
            self.logger.log_event(
                self.scheduler.callback_counter,
                "sensor_anomalies",
                str(sensor_reading.anomalies),
            )

        snapshot = create_snapshot(self.scheduler, self.zone_states, sensor_reading, zone_results)
        self.history_buffer.append(snapshot)
        self.event_bus.emit(CycleCompleted(snapshot))

        self.logger.log_cycle(self.scheduler, self.zone_states, sensor_reading, zone_results)

    def _emit_supervisor_outcome(self, proposal, validated, zs):
        h_match = abs(validated.heating_setpoint - proposal.heating_setpoint) < READBACK_TOLERANCE
        c_match = abs(validated.cooling_setpoint - proposal.cooling_setpoint) < READBACK_TOLERANCE

        if h_match and c_match:
            self.event_bus.emit(SupervisorProposalAccepted(
                zs.zone_name,
                validated.heating_setpoint,
                validated.cooling_setpoint,
                self.scheduler.callback_counter,
            ))
        else:
            self.event_bus.emit(SupervisorProposalModified(
                zs.zone_name,
                proposal.heating_setpoint,
                proposal.cooling_setpoint,
                validated.heating_setpoint,
                validated.cooling_setpoint,
                validated.reason,
                self.scheduler.callback_counter,
            ))

        self.supervisor.consume_proposal(zs.zone_name)

    def _update_saturation(self, zs, validated):
        at_heating_bound = abs(validated.heating_setpoint - HEATING_BOUND_MAX) < 0.001
        at_cooling_bound = abs(validated.cooling_setpoint - COOLING_BOUND_MIN) < 0.001
        at_bound = at_heating_bound or at_cooling_bound

        if not at_bound:
            zs.saturation_counter = 0
            zs.saturation_flag = False
            zs.saturation_reference_temp = zs.current_temperature
            return

        if zs.saturation_counter == 0:
            zs.saturation_reference_temp = zs.current_temperature

        temp_improving = False
        if at_heating_bound and zs.current_temperature > zs.saturation_reference_temp:
            temp_improving = True
        if at_cooling_bound and zs.current_temperature < zs.saturation_reference_temp:
            temp_improving = True

        if temp_improving:
            zs.saturation_counter = 0
            zs.saturation_flag = False
            zs.saturation_reference_temp = zs.current_temperature
        else:
            zs.saturation_counter += 1
            if zs.saturation_counter >= SATURATION_CYCLE_THRESHOLD:
                zs.saturation_flag = True

    def finalize(self):
        self.logger.close()

    def get_summary(self):
        return {
            "total_callbacks": self.scheduler.callback_counter,
            "final_status": self.scheduler.simulation_status,
            "zones": {
                name: {
                    "final_state": zs.controller_state,
                    "final_heating_sp": zs.current_heating_setpoint,
                    "final_cooling_sp": zs.current_cooling_setpoint,
                    "degraded": zs.degraded,
                    "saturation_flag": zs.saturation_flag,
                }
                for name, zs in self.zone_states.items()
            },
            "log_path": str(self.logger.log_path),
        }
