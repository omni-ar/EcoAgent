# EcoAgent: Autonomous Closed-Loop Building Optimization Infrastructure

EcoAgent is an open-source research and engineering framework for closed-loop building heating, ventilation, and air conditioning (HVAC) setpoint optimization. It combines the EnergyPlus simulation engine via in-process C-API runtime callbacks with deterministic control logic, rigorous safety guardrails, and structured telemetry logging.

The repository is structured to support progression from deterministic baseline control (Phase 2) to Model Context Protocol (MCP) tool interfaces and LLM-driven supervisory control in future phases.

---

## Technical Overview

```
                          EnergyPlus C-API Runtime
                                     │
                 callback_begin_system_timestep_before_predictor
                                     │
                                     ▼
                           Warmup & State Filter
                                     │
                                     ▼
                          Shared Runtime Scheduler
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼                                       ▼
        Zone Controllers (1..5)                Actuator Handle Cache
        - State machine                        - Handle resolution (once)
        - Comfort band trigger                 - Physical sensor reads
        - Step sizing (0.5°C / 1.0°C)          - Setpoint writes
                 │                                       │
                 └───────────────────┬───────────────────┘
                                     │
                                     ▼
                           Per-Zone Safety Guard
                           - Hard bounds [18-22, 23-27]°C
                           - Deadband enforcement (≥1.0°C)
                           - Dwell timer check (4 cycles)
                           - Critical boundary clamps
                                     │
                                     ▼
                        Actuator Write & Verify
                        - Immediate in-callback readback
                        - Readback tolerance check (0.001)
                        - Degraded mode fallback
                                     │
                                     ▼
                         Structured JSON-L Logger
                         - Callback metadata
                         - Per-zone control decisions
                         - Sensor readings & status
```

---

## Problem Statement

Building thermal control systems frequently operate on static, hard-coded schedules that fail to adapt to dynamic occupancy patterns, fluctuating weather conditions, or variable energy tariffs. While Advanced Control Strategies (such as Model Predictive Control or Reinforcement Learning) offer potential energy savings, deploying unconstrained control algorithms directly to building automation systems poses thermal comfort and operational safety risks.

EcoAgent provides an in-process simulation sandbox and control architecture designed around deterministic safety invariants. Higher-level controllers or AI agents can propose setpoint modifications, but all commands pass through an immutable Safety Guard layer before actuation.

---

## Repository Structure

```text
EcoAgent/
├── config/
│   └── default.yaml             # Simulation and path configuration
├── data/
│   ├── 5ZoneAirCooled.idf       # EnergyPlus building model (5 thermal zones, VAV system)
│   └── USA_CO_Golden-NREL.epw   # Weather dataset (Golden, CO TMY3)
├── docs/                        # Complete technical documentation
│   ├── architecture.md          # System architecture and callback lifecycle
│   ├── controller_design.md     # Controller state machine and component specs
│   ├── safety_invariants.md     # Formal safety invariants and enforcement
│   ├── verification.md          # Verification suite and test methodology
│   ├── experiments.md           # Runtime experiments and empirical evidence
│   ├── telemetry.md             # Telemetry schema, fields, and sampling bounds
│   ├── limitations.md           # System limitations and boundary constraints
│   ├── phase2_signoff.md        # Formal Phase 2 sign-off document
│   └── roadmap.md               # Multi-phase project execution roadmap
├── logs/                        # Simulation and controller output logs
│   ├── controller_output/       # JSON-lines structured telemetry logs
│   └── simulation_output/       # EnergyPlus output files (.eso, .csv, .err, .html)
├── scripts/
│   ├── run_simulation.py        # Primary entry script to execute annual simulation
│   ├── test_phase2.py           # Integration test suite (32 assertions)
│   ├── test_emergency_hysteresis.py # Automated step-size hysteresis test
│   └── test_initialization_timeout.py # Automated initialization timeout test
└── src/
    └── ecoagent/
        ├── controller/          # Phase 2 Closed-Loop Controller Package
        │   ├── __init__.py      # Public exports
        │   ├── constants.py     # Hard bounds, comfort band, timing constants
        │   ├── zone_state.py    # Per-zone independent state representation
        │   ├── scheduler.py     # Runtime scheduler and warmup filtering
        │   ├── zone_controller.py # Deterministic state machine
        │   ├── safety_guard.py  # Invariant validation function
        │   ├── actuator.py      # C-API handle cache and readback verification
        │   ├── logger.py        # Structured telemetry logger
        │   └── orchestrator.py  # Pipeline orchestrator callback
        └── simulation/          # EnergyPlus API runner integration
            └── energyplus.py    # EnergyPlusAPI wrapper
```

---

## Environment Setup

### Prerequisites

- **Python**: 3.11 or higher
- **EnergyPlus**: Version 26.1.0 installed at `C:/EnergyPlusV26-1-0`
- **Operating System**: Windows 10/11 (PowerShell environment)

### Installation

1. Clone the repository:
   ```powershell
   git clone https://github.com/omni-ar/EcoAgent.git
   cd EcoAgent
   ```

2. Set up virtual environment and install dependencies:
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. Configure path mapping for development:
   Ensure `venv/Lib/site-packages/ecoagent.pth` points to `<repo_root>/src`.

---

## Running the Simulation

Execute the primary annual simulation script:

```powershell
.\venv\Scripts\python.exe scripts/run_simulation.py
```

### Execution Output

Upon completion, summary statistics are rendered to stdout:

```text
Launching EnergyPlus in-process simulation with Phase 2 controller...

Execution Status Success: True
Return Code: 0
Total Controller Callbacks: 35040
Final Scheduler Status: RUNNING
Controller Log: logs\controller_output\controller.jsonl
Output Directory: C:\Users\arjit\Desktop\EcoAgent\logs\simulation_output
  SPACE1-1: state=IDLE h_sp=22.0 c_sp=23.0 degraded=False saturated=False
  SPACE2-1: state=IDLE h_sp=22.0 c_sp=23.0 degraded=False saturated=False
  SPACE3-1: state=IDLE h_sp=22.0 c_sp=23.0 degraded=False saturated=False
  SPACE4-1: state=IDLE h_sp=22.0 c_sp=23.0 degraded=False saturated=False
  SPACE5-1: state=IDLE h_sp=22.0 c_sp=23.0 degraded=False saturated=False
```

---

## Verification & Testing

Run all automated test suites:

```powershell
# Run full integration test suite (32 assertions across 8 categories)
.\venv\Scripts\python.exe scripts/test_phase2.py

# Run magnitude-scaled step size and hysteresis test
.\venv\Scripts\python.exe scripts/test_emergency_hysteresis.py

# Run initialization timeout and periodic reminder test
.\venv\Scripts\python.exe scripts/test_initialization_timeout.py
```

See [docs/verification.md](file:///c:/Users/arjit/Desktop/EcoAgent/docs/verification.md) for full test breakdowns.

---

## Key Phase 2 Results

| Metric | Measured Value |
| :--- | :--- |
| **Annual Simulation Runtime** | ~54 seconds (365 days / 8,760 hours) |
| **Total Timestep Callbacks** | 35,040 (4 per simulated hour) |
| **Warmup Callbacks Filtered** | 576 (6 warmup days) |
| **Total Actuator Setpoint Writes** | 175,200 (35,040 × 5 zones) |
| **Readback Verification Rate** | 100.0% (175,200 / 175,200 verified) |
| **State Distribution (Zone-Steps)**| 78.2% IDLE (136,976), 17.6% HEATING (30,898), 4.2% COOLING (7,326) |
| **Safety Guard Actions** | 170,372 approved, 2,794 dwell holds, 1,571 hot clamps, 463 cold clamps |

---

## System Limitations

1. **In-Process C-API Single Threading**: PyEnergyPlus API runs synchronously inside the main Python thread. Callback execution must remain non-blocking.
2. **Pre-Predictor Telemetry Boundary**: Telemetry collected inside `callback_begin_system_timestep_before_predictor` reflects pre-HVAC heat balance state. Plant electrical demand variables (e.g. `Chiller Electricity Rate`) reflect previous step state at this insertion point. See [docs/telemetry.md](file:///c:/Users/arjit/Desktop/EcoAgent/docs/telemetry.md) for details.
3. **No Real-Time Plant Control**: Phase 2 restricts control actuation strictly to zone temperature setpoints. Central plant equipment (chillers, boilers) is controlled by baseline EnergyPlus managers.

---

## Detailed Documentation

For exhaustive technical specifications, consult the documents under `docs/`:

- [Architecture Specification](file:///c:/Users/arjit/Desktop/EcoAgent/docs/architecture.md)
- [Controller Design](file:///c:/Users/arjit/Desktop/EcoAgent/docs/controller_design.md)
- [Safety Invariants & Safety Guard](file:///c:/Users/arjit/Desktop/EcoAgent/docs/safety_invariants.md)
- [Verification & Testing](file:///c:/Users/arjit/Desktop/EcoAgent/docs/verification.md)
- [Empirical Experiments](file:///c:/Users/arjit/Desktop/EcoAgent/docs/experiments.md)
- [Telemetry Reference & Schema](file:///c:/Users/arjit/Desktop/EcoAgent/docs/telemetry.md)
- [System Limitations](file:///c:/Users/arjit/Desktop/EcoAgent/docs/limitations.md)
- [Phase 2 Final Sign-Off](file:///c:/Users/arjit/Desktop/EcoAgent/docs/phase2_signoff.md)
- [Multi-Phase Roadmap](file:///c:/Users/arjit/Desktop/EcoAgent/docs/roadmap.md)

---

## References

1. U.S. Department of Energy, *EnergyPlus™ Version 26.1.0 Documentation & Input Output Reference*, 2026.
2. National Renewable Energy Laboratory (NREL), *TMY3 Weather Data for Golden, Colorado (724666)*.
3. ASHRAE, *Standard 55-2023: Thermal Environmental Conditions for Human Occupancy*.
