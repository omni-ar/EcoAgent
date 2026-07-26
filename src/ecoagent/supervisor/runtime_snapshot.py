class ZoneSnapshot:
    __slots__ = (
        "zone_name", "temperature_c", "heating_setpoint", "cooling_setpoint",
        "controller_state", "aggressive_mode", "dwell_timer", "saturation_flag",
        "degraded", "safety_guard_reason", "proposed_heating", "proposed_cooling",
        "validated_heating", "validated_cooling", "actuator_written", "readback_verified",
    )

    def __init__(self, zone_name, temperature_c, heating_setpoint, cooling_setpoint,
                 controller_state, aggressive_mode, dwell_timer, saturation_flag,
                 degraded, safety_guard_reason, proposed_heating, proposed_cooling,
                 validated_heating, validated_cooling, actuator_written, readback_verified):
        self.zone_name = zone_name
        self.temperature_c = temperature_c
        self.heating_setpoint = heating_setpoint
        self.cooling_setpoint = cooling_setpoint
        self.controller_state = controller_state
        self.aggressive_mode = aggressive_mode
        self.dwell_timer = dwell_timer
        self.saturation_flag = saturation_flag
        self.degraded = degraded
        self.safety_guard_reason = safety_guard_reason
        self.proposed_heating = proposed_heating
        self.proposed_cooling = proposed_cooling
        self.validated_heating = validated_heating
        self.validated_cooling = validated_cooling
        self.actuator_written = actuator_written
        self.readback_verified = readback_verified

    def to_dict(self):
        return {
            "zone_name": self.zone_name,
            "temperature_c": self.temperature_c,
            "heating_setpoint": self.heating_setpoint,
            "cooling_setpoint": self.cooling_setpoint,
            "controller_state": self.controller_state,
            "aggressive_mode": self.aggressive_mode,
            "dwell_timer": self.dwell_timer,
            "saturation_flag": self.saturation_flag,
            "degraded": self.degraded,
            "safety_guard_reason": self.safety_guard_reason,
            "proposed_heating": self.proposed_heating,
            "proposed_cooling": self.proposed_cooling,
            "validated_heating": self.validated_heating,
            "validated_cooling": self.validated_cooling,
            "actuator_written": self.actuator_written,
            "readback_verified": self.readback_verified,
        }


class RuntimeSnapshot:
    __slots__ = (
        "callback_number", "simulated_timestamp", "scheduler_status",
        "outdoor_temp_c", "chiller_power_w", "zones",
    )

    def __init__(self, callback_number, simulated_timestamp, scheduler_status,
                 outdoor_temp_c, chiller_power_w, zones):
        self.callback_number = callback_number
        self.simulated_timestamp = simulated_timestamp
        self.scheduler_status = scheduler_status
        self.outdoor_temp_c = outdoor_temp_c
        self.chiller_power_w = chiller_power_w
        self.zones = zones

    def to_dict(self):
        return {
            "callback_number": self.callback_number,
            "simulated_timestamp": {
                "month": self.simulated_timestamp[0],
                "day": self.simulated_timestamp[1],
                "hour": self.simulated_timestamp[2],
                "minute": self.simulated_timestamp[3],
            },
            "scheduler_status": self.scheduler_status,
            "outdoor_temp_c": self.outdoor_temp_c,
            "chiller_power_w": self.chiller_power_w,
            "zones": {name: zs.to_dict() for name, zs in self.zones.items()},
        }


def create_snapshot(scheduler, zone_states, sensor_reading, zone_results):
    zones = {}
    for zone_name, zs in zone_states.items():
        zr = zone_results.get(zone_name, {})
        zones[zone_name] = ZoneSnapshot(
            zone_name=zone_name,
            temperature_c=zs.current_temperature,
            heating_setpoint=zs.current_heating_setpoint,
            cooling_setpoint=zs.current_cooling_setpoint,
            controller_state=zs.controller_state,
            aggressive_mode=zs.aggressive_mode,
            dwell_timer=zs.dwell_timer,
            saturation_flag=zs.saturation_flag,
            degraded=zs.degraded,
            safety_guard_reason=zr.get("safety_reason"),
            proposed_heating=zr.get("proposed_heating"),
            proposed_cooling=zr.get("proposed_cooling"),
            validated_heating=zr.get("validated_heating"),
            validated_cooling=zr.get("validated_cooling"),
            actuator_written=zr.get("written", False),
            readback_verified=zr.get("readback_ok", False),
        )

    return RuntimeSnapshot(
        callback_number=scheduler.callback_counter,
        simulated_timestamp=scheduler.simulation_clock,
        scheduler_status=scheduler.simulation_status,
        outdoor_temp_c=sensor_reading.outdoor_temperature,
        chiller_power_w=sensor_reading.chiller_power_w,
        zones=zones,
    )
