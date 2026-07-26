# EcoAgent — AI-Supervised Building Energy Optimization

EcoAgent is an autonomous closed-loop HVAC control system that pairs **EnergyPlus** (physics-based building simulation) with a locally-hosted **open-source LLM** (Qwen 2.5 7B via Ollama) using the **Model Context Protocol (MCP)** to optimize building energy consumption while maintaining thermal comfort.

## Quick Start

```bash
# Prerequisites: Python 3.11+, EnergyPlus 26.1, Ollama with qwen2.5:7b
pip install -r requirements.txt

# Start Ollama model
ollama serve  # in separate terminal
ollama pull qwen2.5:7b

# Run baseline (no agent)
python scripts/run_baseline.py

# Run with AI agent
python scripts/run_with_agent.py

# Compare energy savings
python scripts/compare_energy.py

# Generate dashboard
python scripts/generate_dashboard.py
# Opens docs/dashboard.html
```

## Architecture

See [docs/architecture.md](docs/architecture.md) for full system architecture document.

```
EnergyPlus (5-zone building) → Controller (Safety Guard) → Supervisor (Proposals)
    ↑                                                              ↓
    └──── Actuator Write ←── SafetyGuard ←── MCP ←── LLM (Qwen 2.5 7B)
```

## Key Results

| Metric | Value |
|---|---|
| Simulation | Full year (8760 hours), 5-zone commercial building |
| LLM | Qwen 2.5 7B (local, via Ollama) |
| Reasoning Cycles | 3 completed per run |
| Proposal Rate | 100% (3/3 cycles submitted setpoint changes) |
| Energy Reduction | Demonstrated via baseline comparison |
| Safety | All proposals validated by deterministic Safety Guard |

## Project Structure

```
src/ecoagent/
  ├── simulation/     # EnergyPlus runner (C-API integration)
  ├── controller/     # Deterministic control layer
  │   ├── orchestrator.py  # Main callback handler
  │   ├── zone_controller.py  # Per-zone FSM
  │   ├── safety_guard.py  # Bounds + deadband + dwell enforcement
  │   └── actuator.py  # EMS handle read/write
  ├── supervisor/     # Advisory supervision layer
  │   ├── supervisor.py  # Proposal lifecycle
  │   ├── runtime_snapshot.py  # Zone state capture
  │   ├── history_buffer.py  # Ring buffer for trends
  │   └── tools.py  # Tool registry (6 data + 1 action)
  ├── mcp/           # Model Context Protocol layer
  │   ├── adapter.py  # 8 MCP tools with JSON schemas
  │   └── server.py  # Tool dispatcher (validation + routing)
  └── agent/         # LLM agent layer
      ├── loop.py  # ReAct reasoning loop
      ├── prompts.py  # System/user prompt engineering
      ├── context.py  # State → prompt builder
      └── trace_logger.py  # JSONL audit trail

scripts/
  ├── run_baseline.py       # Baseline simulation (no agent)
  ├── run_with_agent.py     # Full production pipeline
  ├── compare_energy.py     # Energy savings comparison
  └── generate_dashboard.py # HTML dashboard generator

docs/
  ├── architecture.md   # System architecture document
  └── dashboard.html    # Quantitative savings dashboard

data/
  ├── 5ZoneAirCooled.idf           # EnergyPlus building model
  └── USA_CO_Golden-NREL.724666_TMY3.epw  # Weather file
```

## Evaluation Criteria Mapping

| Criteria | Weight | Implementation |
|---|---|---|
| System Integration | 30% | Full closed-loop: EnergyPlus ↔ Controller ↔ Supervisor ↔ MCP ↔ LLM |
| Energy Efficiency | 25% | Baseline vs agent comparison with kWh metrics |
| Thermal Comfort | 20% | Safety Guard enforces comfort bounds [21.5°C, 24.5°C] |
| Agentic Autonomy | 15% | ReAct loop, MCP tool calling, drift gating |
| Documentation | 10% | Architecture doc, dashboard, trace logs |

## Technology Stack

- **Simulation**: EnergyPlus 26.1 (C-API via pyenergyplus)
- **LLM**: Qwen 2.5 7B (Ollama, local inference)
- **Protocol**: MCP (Model Context Protocol)
- **Language**: Python 3.11
- **Dependencies**: openai, pyyaml
