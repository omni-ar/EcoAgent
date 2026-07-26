from ecoagent.controller.constants import (
    COMFORT_HEATING, COMFORT_COOLING, ZONE_NAMES,
    STATE_IDLE, READBACK_FAILURE_LIMIT,
)


class ZoneState:
    def __init__(self, zone_name):
        self.zone_name = zone_name
        self.current_temperature = float("nan")
        self.last_valid_temperature = COMFORT_HEATING
        self.current_heating_setpoint = COMFORT_HEATING
        self.current_cooling_setpoint = COMFORT_COOLING
        self.previous_actuator_command = (COMFORT_HEATING, COMFORT_COOLING)
        self.previous_decision = STATE_IDLE
        self.controller_state = STATE_IDLE
        self.aggressive_mode = False
        self.deadband_status = "INSIDE"
        self.dwell_timer = DWELL_CYCLES_INIT
        self.saturation_flag = False
        self.saturation_counter = 0
        self.saturation_reference_temp = float("nan")
        self.degraded = False
        self.consecutive_readback_failures = 0
        self.verification_history = []

    def record_verification(self, result):
        self.verification_history.append(result)
        if len(self.verification_history) > 10:
            self.verification_history.pop(0)

    def mark_degraded(self, reason=""):
        self.degraded = True
        self.controller_state = "DEGRADED"

    def record_readback_success(self):
        self.consecutive_readback_failures = 0

    def record_readback_failure(self):
        self.consecutive_readback_failures += 1
        if self.consecutive_readback_failures >= READBACK_FAILURE_LIMIT:
            self.mark_degraded(reason="readback_failure_limit")


DWELL_CYCLES_INIT = 999


def create_zone_states():
    return {name: ZoneState(name) for name in ZONE_NAMES}
