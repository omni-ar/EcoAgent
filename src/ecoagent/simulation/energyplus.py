import os
import sys
import pandas as pd
from pathlib import Path

class EnergyPlusRunner:
    def __init__(self, config):
        self.energyplus_path = Path(config.get("energyplus_path", ""))
        self.weather_path = Path(config.get("weather_path", ""))
        self.idf_path = Path(config.get("idf_path", ""))
        self.output_dir = Path(config.get("output_dir", "logs/simulation_output"))
        self.handles = {}

        if self.energyplus_path.is_dir() and str(self.energyplus_path) not in sys.path:
            sys.path.insert(0, str(self.energyplus_path))

    def run(self, callback_fn=None):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            from pyenergyplus.api import EnergyPlusAPI
        except ImportError:
            return {
                "success": False,
                "returncode": -1,
                "stdout": "",
                "stderr": "Could not import pyenergyplus.api",
                "errors": ["PyEnergyPlus API not found. Verify energyplus_path in config/default.yaml."],
                "output_dir": str(self.output_dir.resolve())
            }

        api = EnergyPlusAPI()
        state = api.state_manager.new_state()

        if callback_fn is not None:
            def internal_callback(s):
                if api.exchange.api_data_fully_ready(s):
                    callback_fn(api, s)

            api.runtime.callback_begin_system_timestep_before_predictor(state, internal_callback)

        cmd = [
            "-w", str(self.weather_path.resolve()),
            "-d", str(self.output_dir.resolve()),
            "-r",
            str(self.idf_path.resolve())
        ]

        returncode = api.runtime.run_energyplus(state, cmd)
        api.state_manager.delete_state(state)

        err_file = self.output_dir / "eplusout.err"
        errors = []
        if err_file.exists():
            with open(err_file, "r") as f:
                for line in f:
                    if "**  Fatal  **" in line or "** Severe  **" in line:
                        errors.append(line.strip())

        success = returncode == 0 and not any("**  Fatal  **" in e for e in errors)

        return {
            "success": success,
            "returncode": returncode,
            "stdout": "",
            "stderr": "",
            "errors": errors,
            "output_dir": str(self.output_dir.resolve())
        }

    def get_simulation_results(self):
        csv_file = self.output_dir / "eplusout.csv"
        if not csv_file.exists():
            return None

        df = pd.read_csv(csv_file)
        df.columns = [c.strip() for c in df.columns]

        zone_temp_cols = [c for c in df.columns if "Zone Mean Air Temperature" in c or "Zone Air Temperature" in c]
        hvac_cols = [c for c in df.columns if "Electricity" in c or "Energy" in c or "HVAC" in c or "Chiller" in c]

        return {
            "columns": list(df.columns),
            "zone_temperature_columns": zone_temp_cols,
            "hvac_columns": hvac_cols,
            "data": df
        }
