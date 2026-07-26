"""Phase 4 Production Bootstrap — run EnergyPlus simulation with LLM agent.

Usage:
    python scripts/run_with_agent.py

Constructs all Phase 4 objects in the correct order:
    SupervisorInterface → Orchestrator → ToolRegistry → McpAdapter →
    McpToolDispatcher → AgentTraceLogger → AgentLoop → EnergyPlusRunner

Thread model:
    Thread 1 (callback): EnergyPlus → Orchestrator._execute_cycle
    Thread 2 (agent):    AgentLoop.run → drift check + LLM reasoning
"""

import sys
import queue
import threading
import yaml
import os
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ecoagent.simulation.energyplus import EnergyPlusRunner
from ecoagent.controller.orchestrator import Orchestrator
from ecoagent.supervisor.supervisor import SupervisorInterface
from ecoagent.supervisor.events import CycleCompleted
from ecoagent.supervisor.tools import ToolRegistry
from ecoagent.mcp.adapter import McpAdapter
from ecoagent.mcp.server import McpToolDispatcher
from ecoagent.agent.loop import AgentLoop
from ecoagent.agent.trace_logger import AgentTraceLogger


def load_config():
    """Load config/default.yaml and expand environment variables."""
    config_path = Path(__file__).resolve().parent.parent / "config" / "default.yaml"
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # Expand environment variables in agent config
    agent_cfg = config.get("agent", {})
    api_key = agent_cfg.get("api_key", "ollama")
    if isinstance(api_key, str) and api_key.startswith("${") and api_key.endswith("}"):
        env_var = api_key[2:-1]
        agent_cfg["api_key"] = os.environ.get(env_var, "ollama")

    return config


def main():
    print("=" * 60)
    print("EcoAgent Phase 4 — LLM Supervisory Agent")
    print("=" * 60)

    # ── 1. Load config ───────────────────────────────────────────
    config = load_config()

    # ── 2. Generate run_id ───────────────────────────────────────
    run_id = f"run_{datetime.now():%Y%m%d_%H%M%S}"
    run_dir = Path(f"logs/runs/{run_id}")
    print(f"\nRun ID: {run_id}")
    print(f"Run directory: {run_dir.resolve()}")

    # ── 3. Create run directory structure ────────────────────────
    sim_dir = run_dir / "simulation"
    ctrl_dir = run_dir / "controller"
    agent_dir = run_dir / "agent"
    for d in [sim_dir, ctrl_dir, agent_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # ── 4. Override output paths ─────────────────────────────────
    config["output_dir"] = str(sim_dir)

    # ── 5. Construct objects (Option C ownership) ────────────────
    print("\nInitializing components...")

    # 5a. SupervisorInterface — created FIRST (shared instance)
    supervisor = SupervisorInterface()

    # 5b. Orchestrator — creates HistoryBuffer and EventBus internally
    orchestrator = Orchestrator(
        log_dir=str(ctrl_dir),
        supervisor=supervisor,
    )

    # 5c. ToolRegistry — references Orchestrator internals
    tool_registry = ToolRegistry(
        history=orchestrator.history_buffer,
        supervisor=supervisor,
        event_bus=orchestrator.event_bus,
        get_latest_snapshot=orchestrator.history_buffer.latest,
    )

    # 5d. McpAdapter — wraps ToolRegistry with composite tools
    adapter = McpAdapter(tool_registry)

    # 5e. McpToolDispatcher — hybrid MCP dispatch for LLM tool calls
    dispatcher = McpToolDispatcher(adapter)

    # 5f. AgentTraceLogger — JSONL writer
    trace_logger = AgentTraceLogger(
        output_dir=str(agent_dir),
        run_id=run_id,
    )

    # ── 6. Wire EventBus → Queue bridge ──────────────────────────
    cycle_queue = queue.Queue()
    shutdown_event = threading.Event()

    orchestrator.event_bus.subscribe(
        CycleCompleted,
        lambda e: cycle_queue.put(e.snapshot),
    )

    # ── 7. Create AgentLoop ──────────────────────────────────────
    agent_config = config.get("agent", {})
    agent_loop = AgentLoop(
        adapter=adapter,
        trace_logger=trace_logger,
        cycle_queue=cycle_queue,
        shutdown_event=shutdown_event,
        llm_config=agent_config,
        mcp_dispatcher=dispatcher,
    )

    # ── 8. Start agent thread ────────────────────────────────────
    agent_thread = threading.Thread(
        target=agent_loop.run,
        name="agent-worker",
        daemon=True,
    )
    agent_thread.start()
    print("Agent thread started.")

    # ── 9. Run EnergyPlus simulation (BLOCKS) ────────────────────
    print(f"\nStarting EnergyPlus simulation...")
    print(f"  IDF: {config.get('idf_path', '?')}")
    print(f"  Weather: {config.get('weather_path', '?')}")
    print(f"  Output: {sim_dir.resolve()}")

    runner = EnergyPlusRunner(config)
    result = runner.run(callback_fn=orchestrator.create_callback())

    # ── 10. Shutdown agent ───────────────────────────────────────
    print("\nSimulation complete. Shutting down agent...")
    shutdown_event.set()
    cycle_queue.put(None)  # sentinel
    agent_thread.join(timeout=10)

    if agent_thread.is_alive():
        print("WARNING: Agent thread did not exit within timeout.")
    else:
        print("Agent thread joined.")

    # ── 11. Finalize ─────────────────────────────────────────────
    # trace_logger is closed by AgentLoop daemon thread in its finally block

    # ── 12. Summary ──────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Run Summary")
    print("=" * 60)
    print(f"  Run ID:      {run_id}")
    print(f"  Success:     {result.get('success', False)}")
    print(f"  Return code: {result.get('returncode', '?')}")
    print(f"  Errors:      {len(result.get('errors', []))}")

    # Check output files
    ctrl_log = ctrl_dir / "controller.jsonl"
    trace_log = trace_logger.log_path
    sim_csv = sim_dir / "eplusout.csv"

    print(f"\n  Controller log:  {'EXISTS' if ctrl_log.exists() else 'MISSING'} ({ctrl_log})")
    print(f"  Agent trace:     {'EXISTS' if trace_log.exists() else 'MISSING'} ({trace_log})")
    print(f"  Simulation CSV:  {'EXISTS' if sim_csv.exists() else 'MISSING'} ({sim_csv})")

    if trace_log.exists():
        with open(trace_log) as f:
            trace_count = sum(1 for _ in f)
        print(f"  Trace entries:   {trace_count}")
        print(f"  Policy version:  {agent_loop._policy_version}")

    if result.get("errors"):
        print("\n  Simulation errors:")
        for err in result["errors"][:5]:
            print(f"    {err}")

    return 0 if result.get("success", False) else 1


if __name__ == "__main__":
    sys.exit(main())
