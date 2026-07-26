from ecoagent.controller.constants import (
    HEATING_BOUND_MIN, HEATING_BOUND_MAX,
    COOLING_BOUND_MIN, COOLING_BOUND_MAX,
    MIN_DEADBAND, DWELL_CYCLES,
)


class ValidatedCommand:
    def __init__(self, approved, heating_setpoint, cooling_setpoint, reason):
        self.approved = approved
        self.heating_setpoint = heating_setpoint
        self.cooling_setpoint = cooling_setpoint
        self.reason = reason


def validate_command(zone_state, proposed_heating, proposed_cooling):
    if zone_state.degraded:
        return ValidatedCommand(
            False,
            zone_state.current_heating_setpoint,
            zone_state.current_cooling_setpoint,
            "zone_degraded",
        )

    temp = zone_state.current_temperature

    if temp < HEATING_BOUND_MIN:
        return ValidatedCommand(
            True,
            HEATING_BOUND_MAX,
            COOLING_BOUND_MAX,
            "critical_clamp_cold",
        )

    if temp > COOLING_BOUND_MAX:
        return ValidatedCommand(
            True,
            HEATING_BOUND_MIN,
            COOLING_BOUND_MIN,
            "critical_clamp_hot",
        )

    h = max(HEATING_BOUND_MIN, min(proposed_heating, HEATING_BOUND_MAX))
    c = max(COOLING_BOUND_MIN, min(proposed_cooling, COOLING_BOUND_MAX))

    if c - h < MIN_DEADBAND:
        c = h + MIN_DEADBAND
        if c > COOLING_BOUND_MAX:
            c = COOLING_BOUND_MAX
            h = c - MIN_DEADBAND

    setpoints_changed = (
        abs(h - zone_state.current_heating_setpoint) > 0.001
        or abs(c - zone_state.current_cooling_setpoint) > 0.001
    )

    if setpoints_changed and zone_state.dwell_timer < DWELL_CYCLES:
        return ValidatedCommand(
            True,
            zone_state.current_heating_setpoint,
            zone_state.current_cooling_setpoint,
            "dwell_hold",
        )

    if not (HEATING_BOUND_MIN <= h <= HEATING_BOUND_MAX):
        return _fallback(zone_state, "final_validation_heating_fail")
    if not (COOLING_BOUND_MIN <= c <= COOLING_BOUND_MAX):
        return _fallback(zone_state, "final_validation_cooling_fail")
    if c - h < MIN_DEADBAND:
        return _fallback(zone_state, "final_validation_deadband_fail")

    return ValidatedCommand(True, h, c, "approved")


def _fallback(zone_state, reason):
    return ValidatedCommand(
        True,
        zone_state.current_heating_setpoint,
        zone_state.current_cooling_setpoint,
        reason,
    )
