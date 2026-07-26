from ecoagent.controller.constants import (
    COMFORT_TRIGGER_LOW, COMFORT_TRIGGER_HIGH,
    COMFORT_HEATING, COMFORT_COOLING,
    NORMAL_STEP, AGGRESSIVE_STEP,
    AGGRESSIVE_ENTRY_THRESHOLD, AGGRESSIVE_EXIT_THRESHOLD,
    STATE_IDLE, STATE_HEATING, STATE_COOLING, STATE_DEGRADED,
)


class ProposedCommand:
    def __init__(self, heating_setpoint, cooling_setpoint, state, decision_reason):
        self.heating_setpoint = heating_setpoint
        self.cooling_setpoint = cooling_setpoint
        self.state = state
        self.decision_reason = decision_reason


class ZoneController:
    def __init__(self, zone_name):
        self.zone_name = zone_name

    def evaluate(self, zone_state):
        if zone_state.degraded:
            return ProposedCommand(
                zone_state.current_heating_setpoint,
                zone_state.current_cooling_setpoint,
                STATE_DEGRADED,
                "zone_degraded",
            )

        temp = zone_state.current_temperature

        if temp < COMFORT_TRIGGER_LOW:
            deviation = COMFORT_TRIGGER_LOW - temp
            aggressive = self._update_aggressive_mode(zone_state, deviation)
            step = AGGRESSIVE_STEP if aggressive else NORMAL_STEP

            proposed_heating = zone_state.current_heating_setpoint + step
            proposed_cooling = zone_state.current_cooling_setpoint

            return ProposedCommand(
                proposed_heating,
                proposed_cooling,
                STATE_HEATING,
                f"heating_deviation_{deviation:.1f}C_step_{step}C",
            )

        if temp > COMFORT_TRIGGER_HIGH:
            deviation = temp - COMFORT_TRIGGER_HIGH
            aggressive = self._update_aggressive_mode(zone_state, deviation)
            step = AGGRESSIVE_STEP if aggressive else NORMAL_STEP

            proposed_heating = zone_state.current_heating_setpoint
            proposed_cooling = zone_state.current_cooling_setpoint - step

            return ProposedCommand(
                proposed_heating,
                proposed_cooling,
                STATE_COOLING,
                f"cooling_deviation_{deviation:.1f}C_step_{step}C",
            )

        zone_state.aggressive_mode = False

        return ProposedCommand(
            zone_state.current_heating_setpoint,
            zone_state.current_cooling_setpoint,
            STATE_IDLE,
            "within_comfort_band",
        )

    def _update_aggressive_mode(self, zone_state, deviation):
        if not zone_state.aggressive_mode:
            if deviation > AGGRESSIVE_ENTRY_THRESHOLD:
                zone_state.aggressive_mode = True
        else:
            if deviation < AGGRESSIVE_EXIT_THRESHOLD:
                zone_state.aggressive_mode = False

        return zone_state.aggressive_mode


def create_zone_controllers():
    from ecoagent.controller.constants import ZONE_NAMES
    return {name: ZoneController(name) for name in ZONE_NAMES}
