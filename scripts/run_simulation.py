import sys
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ecoagent.simulation.energyplus import EnergyPlusRunner
from ecoagent.controller.orchestrator import Orchestrator


def main():
    config_path = Path(__file__).resolve().parent.parent / "config" / "default.yaml"

    if not config_path.exists():
        print(f"Config file not found at {config_path}")
        sys.exit(1)

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    runner = EnergyPlusRunner(config)
    orchestrator = Orchestrator()

    print("Launching EnergyPlus in-process simulation with Phase 2 controller...")
    result = runner.run(callback_fn=orchestrator.create_callback())
    orchestrator.finalize()

    summary = orchestrator.get_summary()

    print(f"\nExecution Status Success: {result['success']}")
    print(f"Return Code: {result['returncode']}")
    print(f"Total Controller Callbacks: {summary['total_callbacks']}")
    print(f"Final Scheduler Status: {summary['final_status']}")
    print(f"Controller Log: {summary['log_path']}")
    print(f"Output Directory: {result['output_dir']}")

    for zone_name, zone_info in summary["zones"].items():
        print(
            f"  {zone_name}: state={zone_info['final_state']} "
            f"h_sp={zone_info['final_heating_sp']:.1f} "
            f"c_sp={zone_info['final_cooling_sp']:.1f} "
            f"degraded={zone_info['degraded']} "
            f"saturated={zone_info['saturation_flag']}"
        )

    if result["errors"]:
        print("Execution Errors/Warnings Detected:")
        for err in result["errors"]:
            print(f"  - {err}")

    if not result["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
