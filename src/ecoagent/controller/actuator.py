import math
from ecoagent.controller.constants import (
    ZONE_NAMES, READBACK_TOLERANCE, SENSOR_TEMP_FLOOR, SENSOR_TEMP_CEILING,
)


class WriteResult:
    def __init__(self, success, written_heating, readback_heating, written_cooling, readback_cooling):
        self.success = success
        self.written_heating = written_heating
        self.readback_heating = readback_heating
        self.written_cooling = written_cooling
        self.readback_cooling = readback_cooling


class SensorReading:
    def __init__(self):
        self.zone_temperatures = {}
        self.outdoor_temperature = float("nan")
        self.chiller_power_w = 0.0
        self.anomalies = []


class ActuatorManager:
    def __init__(self):
        self._heating_handles = {}
        self._cooling_handles = {}
        self._temp_handles = {}
        self._outdoor_handle = -1
        self._chiller_handle = -1
        self._resolved = False

    def resolve_handles(self, api, state, zone_states):
        all_failed = True

        for zone_name in ZONE_NAMES:
            h_handle = api.exchange.get_actuator_handle(
                state, "Zone Temperature Control", "Heating Setpoint", zone_name
            )
            c_handle = api.exchange.get_actuator_handle(
                state, "Zone Temperature Control", "Cooling Setpoint", zone_name
            )
            t_handle = api.exchange.get_variable_handle(
                state, "Zone Air Temperature", zone_name
            )

            self._heating_handles[zone_name] = h_handle
            self._cooling_handles[zone_name] = c_handle
            self._temp_handles[zone_name] = t_handle

            if h_handle == -1 or c_handle == -1 or t_handle == -1:
                zone_states[zone_name].mark_degraded(
                    reason=f"handle_resolution_failed h={h_handle} c={c_handle} t={t_handle}"
                )
            else:
                all_failed = False

        self._outdoor_handle = api.exchange.get_variable_handle(
            state, "Site Outdoor Air Drybulb Temperature", "Environment"
        )
        self._chiller_handle = api.exchange.get_variable_handle(
            state, "Chiller Electricity Rate", "CENTRAL CHILLER"
        )

        self._resolved = True
        return all_failed

    @property
    def resolved(self):
        return self._resolved

    def read_sensors(self, api, state, zone_states):
        reading = SensorReading()

        for zone_name in ZONE_NAMES:
            handle = self._temp_handles.get(zone_name, -1)
            if handle == -1:
                reading.zone_temperatures[zone_name] = zone_states[zone_name].last_valid_temperature
                reading.anomalies.append((zone_name, "missing_handle"))
                continue

            val = api.exchange.get_variable_value(state, handle)

            if math.isnan(val) or val < SENSOR_TEMP_FLOOR or val > SENSOR_TEMP_CEILING:
                reading.zone_temperatures[zone_name] = zone_states[zone_name].last_valid_temperature
                reading.anomalies.append((zone_name, f"anomalous_value_{val}"))
            else:
                reading.zone_temperatures[zone_name] = val
                zone_states[zone_name].last_valid_temperature = val

        if self._outdoor_handle != -1:
            reading.outdoor_temperature = api.exchange.get_variable_value(state, self._outdoor_handle)
        if self._chiller_handle != -1:
            reading.chiller_power_w = api.exchange.get_variable_value(state, self._chiller_handle)

        return reading

    def write_and_verify(self, api, state, zone_name, heating_sp, cooling_sp):
        h_handle = self._heating_handles.get(zone_name, -1)
        c_handle = self._cooling_handles.get(zone_name, -1)

        if h_handle == -1 or c_handle == -1:
            return WriteResult(False, heating_sp, float("nan"), cooling_sp, float("nan"))

        api.exchange.set_actuator_value(state, h_handle, heating_sp)
        api.exchange.set_actuator_value(state, c_handle, cooling_sp)

        readback_h = api.exchange.get_actuator_value(state, h_handle)
        readback_c = api.exchange.get_actuator_value(state, c_handle)

        h_ok = abs(readback_h - heating_sp) < READBACK_TOLERANCE
        c_ok = abs(readback_c - cooling_sp) < READBACK_TOLERANCE

        return WriteResult(h_ok and c_ok, heating_sp, readback_h, cooling_sp, readback_c)
