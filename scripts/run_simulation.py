import sys
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ecoagent.simulation.energyplus import EnergyPlusRunner

def main():
    config_path = Path(__file__).resolve().parent.parent / "config" / "default.yaml"

    if not config_path.exists():
        print(f"Config file not found at {config_path}")
        sys.exit(1)

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    runner = EnergyPlusRunner(config)

    callback_state = {
        "count": 0,
        "temp_handle": -1,
        "actuator_handle": -1,
        "initialized": False
    }

    def live_control_callback(api, state):
        callback_state["count"] += 1
        
        if not callback_state["initialized"]:
            callback_state["temp_handle"] = api.exchange.get_variable_handle(state, "Zone Air Temperature", "SPACE1-1")
            callback_state["actuator_handle"] = api.exchange.get_actuator_handle(state, "Schedule:Compact", "Schedule Value", "CLGSETP_SCH")
            if callback_state["actuator_handle"] == -1:
                callback_state["actuator_handle"] = api.exchange.get_actuator_handle(state, "Schedule:Constant", "Schedule Value", "CLGSETP_SCH")
            callback_state["initialized"] = True

        if callback_state["temp_handle"] != -1:
            current_temp = api.exchange.get_variable_value(state, callback_state["temp_handle"])
            if callback_state["count"] <= 5 or callback_state["count"] % 5000 == 0:
                print(f"[Live Timestep Callback #{callback_state['count']}] Zone Air Temp: {current_temp:.2f} C")

        if callback_state["actuator_handle"] != -1:
            api.exchange.set_actuator_value(state, callback_state["actuator_handle"], 24.0)

    print("Launching EnergyPlus in-process simulation with live runtime callbacks...")
    result = runner.run(callback_fn=live_control_callback)

    print(f"\nExecution Status Success: {result['success']}")
    print(f"Return Code: {result['returncode']}")
    print(f"Total Live Timestep Callbacks Processed: {callback_state['count']}")
    print(f"Output Directory: {result['output_dir']}")

    if result["errors"]:
        print("Execution Errors/Warnings Detected:")
        for err in result["errors"]:
            print(f"  - {err}")

    if result["success"]:
        data = runner.get_simulation_results()
        if data is not None:
            print("\nSimulation Telemetry Metrics Extracted Successfully:")
            print(f"Zone Temperature Columns: {data['zone_temperature_columns']}")
            print(f"HVAC Energy Columns: {data['hvac_columns']}")
            print(f"Total Output Rows: {len(data['data'])}")
        else:
            print("CSV output eplusout.csv not found in output directory.")
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
