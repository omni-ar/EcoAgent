import json
import traceback
from pathlib import Path


class ControllerLogger:
    def __init__(self, output_dir="logs/controller_output"):
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._output_dir / "controller.jsonl"
        self._file = open(self._log_path, "w", encoding="utf-8")

    def log_cycle(self, scheduler, zone_states, sensor_reading, zone_results):
        entry = {
            "callback_number": scheduler.callback_counter,
            "simulated_timestamp": {
                "month": scheduler.simulation_clock[0],
                "day": scheduler.simulation_clock[1],
                "hour": scheduler.simulation_clock[2],
                "minute": scheduler.simulation_clock[3],
            },
            "warmup": scheduler.warmup_active,
            "scheduler_status": scheduler.simulation_status,
            "outdoor_temp_c": sensor_reading.outdoor_temperature,
            "chiller_power_w": sensor_reading.chiller_power_w,
            "total_zones_active": sum(1 for z in zone_states.values() if not z.degraded),
            "total_zones_degraded": sum(1 for z in zone_states.values() if z.degraded),
            "zones": [],
        }

        for zone_name, zs in zone_states.items():
            zr = zone_results.get(zone_name, {})
            zone_entry = {
                "zone_name": zone_name,
                "controller_state": zs.controller_state,
                "aggressive_mode": zs.aggressive_mode,
                "temperature_c": zs.current_temperature,
                "proposed_heating_sp": zr.get("proposed_heating"),
                "proposed_cooling_sp": zr.get("proposed_cooling"),
                "validated_heating_sp": zr.get("validated_heating"),
                "validated_cooling_sp": zr.get("validated_cooling"),
                "safety_guard_reason": zr.get("safety_reason"),
                "actuator_written": zr.get("written", False),
                "readback_verified": zr.get("readback_ok", False),
                "dwell_timer": zs.dwell_timer,
                "saturation_flag": zs.saturation_flag,
                "degraded": zs.degraded,
            }
            entry["zones"].append(zone_entry)

        self._write(entry)

    def log_exception(self, callback_counter, exception):
        entry = {
            "callback_number": callback_counter,
            "event": "controller_exception",
            "exception_type": type(exception).__name__,
            "exception_message": str(exception),
            "traceback": traceback.format_exc(),
        }
        self._write(entry)

    def log_event(self, callback_counter, event_type, details, warmup=False):
        entry = {
            "callback_number": callback_counter,
            "warmup": warmup,
            "event": event_type,
            "details": details,
        }
        self._write(entry)

    def _write(self, entry):
        self._file.write(json.dumps(entry, default=str) + "\n")
        self._file.flush()

    def close(self):
        if self._file and not self._file.closed:
            self._file.close()

    @property
    def log_path(self):
        return self._log_path
