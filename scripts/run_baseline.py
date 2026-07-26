"""Run EnergyPlus baseline simulation WITHOUT the LLM agent.

Usage: python scripts/run_baseline.py

Produces: logs/baseline/ with eplusout.csv and controller.jsonl
"""
import sys
from pathlib import Path
from datetime import datetime
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ecoagent.simulation.energyplus import EnergyPlusRunner
from ecoagent.controller.orchestrator import Orchestrator
from ecoagent.supervisor.supervisor import SupervisorInterface


def main():
    print("=" * 60)
    print("EcoAgent Baseline Run (No Agent)")
    print("=" * 60)

    config_path = Path(__file__).resolve().parent.parent / "config" / "default.yaml"
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    run_dir = Path("logs/baseline")
    sim_dir = run_dir / "simulation"
    ctrl_dir = run_dir / "controller"
    for d in [sim_dir, ctrl_dir]:
        d.mkdir(parents=True, exist_ok=True)

    config["output_dir"] = str(sim_dir)

    supervisor = SupervisorInterface()
    orchestrator = Orchestrator(log_dir=str(ctrl_dir), supervisor=supervisor)

    print(f"\nStarting EnergyPlus baseline simulation...")
    print(f"  IDF: {config.get('idf_path', '?')}")
    print(f"  Weather: {config.get('weather_path', '?')}")
    print(f"  Output: {sim_dir.resolve()}")

    runner = EnergyPlusRunner(config)
    result = runner.run(callback_fn=orchestrator.create_callback())

    print("\n" + "=" * 60)
    print("Baseline Run Summary")
    print("=" * 60)
    print(f"  Success:     {result.get('success', False)}")
    print(f"  Return code: {result.get('returncode', '?')}")
    print(f"  Errors:      {len(result.get('errors', []))}")

    sim_csv = sim_dir / "eplusout.csv"
    ctrl_log = ctrl_dir / "controller.jsonl"
    print(f"\n  Simulation CSV: {'EXISTS' if sim_csv.exists() else 'MISSING'} ({sim_csv})")
    print(f"  Controller log: {'EXISTS' if ctrl_log.exists() else 'MISSING'} ({ctrl_log})")

    return 0 if result.get("success", False) else 1


if __name__ == "__main__":
    sys.exit(main())
