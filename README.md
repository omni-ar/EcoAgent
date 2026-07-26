# EcoAgent: Closed-Loop Building Optimization Infrastructure

EcoAgent is an open-source research and engineering framework for closed-loop building heating, ventilation, and air conditioning (HVAC) setpoint optimization. It combines the EnergyPlus simulation engine via in-process C-API runtime callbacks with deterministic control logic, rigorous safety guardrails, structured telemetry logging, and supervisory observation infrastructure.

The framework supports systematic progression from deterministic baseline control (Phase 2) to supervisory snapshotting and event streaming (Phase 3), Model Context Protocol (MCP) tool interfaces (Phase 4), and LLM-driven supervisory control (Phase 5).

---

## System Status & Milestone Progression

- **Phase 0 — Repository Foundation**: **Complete**
- **Phase 1 — EnergyPlus In-Process API Bring-Up**: **Complete**
- **Phase 2 — Deterministic Controller & Safety Guard**: **Approved Baseline (Frozen)**
- **Phase 3 — Supervisory Infrastructure & Tool Layer**: **Approved Baseline (Frozen)**
- **Phase 4 — Model Context Protocol (MCP) Server & Data Pipeline**: **Planned**

---

## Technical Architecture

```text
                           EnergyPlus C-API Runtime
                                      │
                  callback_begin_system_timestep_before_predictor
                                      │
                                      ▼
                            Warmup & State Filter
                                      │
                                      ▼
                   Shared Runtime Scheduler (tick & clear_expired)
                                      │
                  ┌───────────────────┴───────────────────┐
                  ▼                                       ▼
         Zone Controllers (1..5)                Actuator Handle Cache
         - Comfort band triggers                - Handle resolution (once)
         - Step sizing (0.5°C / 1.0°C)          - Physical sensor reads
         - Skipped if supervisor active         - Setpoint writes
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
                         - Readback tolerance check (0.001°C)
                         - Degraded mode fallback
                                      │
                                      ▼
                           Structured JSON-L Logger
                                      │
                                      ▼
                           RuntimeSnapshot Factory
                                      │
                  ┌───────────────────┴───────────────────┐
                  ▼                                       ▼
            HistoryBuffer                            EventBus
            - 96-snapshot ring buffer                - Synchronous event dispatch
            - In-memory deque                        - Three-way outcome events
                  │                                       │
                  └───────────────────┬───────────────────┘
                                      │
                                      ▼
                             SupervisorInterface
                             - Advisory proposal tracking
                             - Proposal TTL lifecycle
                                      │
                                      ▼
                               Analytics Layer
                             - Comfort % (excl. supervisor)
                             - Safety summary & oscillations
                                      │
                                      ▼
                             Internal ToolRegistry
                             - 6 JSON-serializable tools
                                      │
                                      ▼
                           Future Phase 4 MCP Tools
```

---

## Core Features & Infrastructure

### 1. Deterministic Safety Invariants (Phase 2 Baseline)
- **Hard Bounds Clamping**: Enforces heating setpoints within [18.0, 22.0]°C and cooling setpoints within [23.0, 27.0]°C.
- **Deadband Enforcement**: Guarantees cooling setpoint - heating setpoint ≥ 1.0°C.
- **Dwell Timer**: Holds setpoints for 4 callback cycles (1 hour) to prevent actuator chatter, unless overridden by emergency critical clamps (<18°C or >27°C).
- **Readback Verification**: Verifies every setpoint write against C-API readback values immediately within callback. Consecutive failures isolate degraded zones safely.

### 2. Supervisory Infrastructure (Phase 3 Baseline)
- **RuntimeSnapshot**: Creates immutable, thread-safe data copies (`RuntimeSnapshot`, `ZoneSnapshot`) of controller state, sensor values, and setpoints at each callback cycle.
- **HistoryBuffer**: Bounded ring buffer (`collections.deque(maxlen=96)`) storing up to 24 hours of snapshot records for in-memory traversal.
- **EventBus & Diagnostics**: Synchronous event stream (`CycleCompleted`, `SafetyTriggered`, `ReadbackFailure`, `ZoneDegraded`, `SupervisorProposalAccepted`, `SupervisorProposalModified`, `SupervisorProposalRejected`, `SchedulerDisabled`, `SimulationStarted`). Includes `listener_error_count` tracking for observable non-blocking failure handling.
- **SupervisorInterface**: Accepts structured setpoint proposals (`SetpointProposal`). Enforces an 8-state proposal lifecycle (`NEW` → `PENDING` → `SELECTED` → `VALIDATED` → `EXECUTED`/`REJECTED` → `CONSUMED`, or `EXPIRED`) with callback-tick TTL expiration.
- **Three-Way Proposal Outcomes**: Explicitly distinguishes applied proposals (`Accepted`), modified proposals (`Modified` due to dwell hold, bounds, or clamps), and rejected proposals (`Rejected` due to degradation).
- **Pre-Evaluate State Isolation**: Checks for active supervisor proposals *before* running `ZoneController.evaluate()`, preventing phantom aggressive mode mutations on controller state.
- **Analytics Layer**: Stateless functions computing comfort percentage (excluding supervisor-active cycles), safety trigger counts, and oscillation frequency.
- **ToolRegistry**: Provides 6 JSON-serializable query/action methods mapping 1:1 to future Phase 4 MCP tool definitions.

---

## Repository Structure

```text
EcoAgent/
├── config/
│   └── default.yaml             # Simulation and path configuration
├── data/
│   ├── 5ZoneAirCooled.idf       # EnergyPlus building model (5 thermal zones, VAV system)
│   └── USA_CO_Golden-NREL.epw   # Weather dataset (Golden, CO TMY3)
├── docs/                        # Technical documentation & ADRs
│   ├── adr/
│   │   └── ADR-0001-phase3-freeze.md # Architecture Decision Record for Phase 3
│   ├── releases/
│   │   └── phase3-freeze.md     # Phase 3 release notes
│   ├── architecture.md          # System architecture and callback lifecycle
│   ├── controller_design.md     # Controller state machine and component specs
│   ├── safety_invariants.md     # Formal safety invariants and enforcement
│   ├── verification.md          # Comprehensive verification methodology
│   ├── known_limitations.md     # System limitations and boundary constraints
│   ├── telemetry.md             # Telemetry schema, fields, and sampling bounds
│   └── roadmap.md               # Multi-phase project execution roadmap
├── logs/                        # Simulation and controller output logs
│   ├── controller_output/       # JSON-lines structured telemetry logs
│   └── simulation_output/       # EnergyPlus output files (.eso, .csv, .err, .html)
├── scripts/
│   ├── run_simulation.py        # Primary entry script to execute annual simulation
│   ├── test_phase2.py           # Phase 2 annual integration test suite (32 assertions)
│   ├── test_emergency_hysteresis.py # Emergency step size & hysteresis test (4 assertions)
│   ├── test_initialization_timeout.py # Scheduler initialization timeout test (4 assertions)
│   ├── test_phase3.py           # Phase 3 unit test suite (63 assertions)
│   └── test_phase3_integration.py # Phase 3 integration test suite (29 assertions)
└── src/
    └── ecoagent/
        ├── controller/          # Deterministic Control Package (Phase 2 Baseline)
        │   ├── __init__.py      # Public exports
        │   ├── constants.py     # Safety bounds, comfort band, timing constants
        │   ├── zone_state.py    # Per-zone independent state representation
        │   ├── scheduler.py     # Runtime scheduler and warmup filtering
        │   ├── zone_controller.py # Deterministic state machine
        │   ├── safety_guard.py  # Invariant validation function
        │   ├── actuator.py      # C-API handle cache and readback verification
        │   ├── logger.py        # Structured telemetry logger
        │   └── orchestrator.py  # Pipeline orchestrator callback
        └── supervisor/          # Supervisory Infrastructure Package (Phase 3 Baseline)
            ├── __init__.py      # Package exports
            ├── constants.py     # Supervisory constants (STATE_SUPERVISOR)
            ├── runtime_snapshot.py # Snapshot data structures and factory
            ├── history_buffer.py # Ring buffer implementation
            ├── events.py        # Event bus and structured event types
            ├── supervisor.py    # Supervisor proposal interface and TTL lifecycle
            ├── analytics.py     # Stateless metrics computation functions
            └── tools.py         # Internal tool registry for future MCP mapping
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

---

## Running the Simulation

Execute the primary annual simulation script:

```powershell
.\venv\Scripts\python.exe scripts/run_simulation.py
```

---

## Verification & Testing

Execute the complete automated test suite (132 total assertions across 5 test scripts):

```powershell
# Phase 2 Annual Integration Test Suite (32 assertions)
.\venv\Scripts\python.exe scripts/test_phase2.py

# Step-Size Scaling & Hysteresis Test Suite (4 assertions)
.\venv\Scripts\python.exe scripts/test_emergency_hysteresis.py

# Initialization Timeout Test Suite (4 assertions)
.\venv\Scripts\python.exe scripts/test_initialization_timeout.py

# Phase 3 Unit Test Suite (63 assertions)
.\venv\Scripts\python.exe scripts/test_phase3.py

# Phase 3 Integration Test Suite (29 assertions)
.\venv\Scripts\python.exe scripts/test_phase3_integration.py
```

### Verification Totals Summary

| Category | Suite | Assertions | Result |
| :--- | :--- | :--- | :--- |
| **Phase 2 Integration** | `test_phase2.py` | 32 | **32 / 32 PASS** |
| **Hysteresis Unit** | `test_emergency_hysteresis.py` | 4 | **4 / 4 PASS** |
| **Initialization Timeout**| `test_initialization_timeout.py` | 4 | **4 / 4 PASS** |
| **Phase 3 Unit** | `test_phase3.py` | 63 | **63 / 63 PASS** |
| **Phase 3 Integration** | `test_phase3_integration.py` | 29 | **29 / 29 PASS** |
| **TOTAL** | **Comprehensive Suite** | **132** | **132 / 132 PASS** |

See [docs/verification.md](file:///c:/Users/arjit/Desktop/EcoAgent/docs/verification.md) for detailed test breakdowns.

---

## System Limitations

1. **In-Process C-API Single Threading**: PyEnergyPlus API runs synchronously inside the main Python thread. Callback execution overhead is maintained under 0.09 ms per cycle.
2. **Pre-Predictor Telemetry Insertion Point**: Telemetry collected inside `callback_begin_system_timestep_before_predictor` reflects pre-HVAC heat balance state. Plant-level rate variables reflect the previous step state.
3. **Single-Producer Proposal Buffer**: `SupervisorInterface` tracks at most one pending proposal per zone key per cycle.
4. **In-Memory History Window**: `HistoryBuffer` stores up to 96 snapshots (24 hours). Database persistence is deferred to Phase 4+.

See [docs/known_limitations.md](file:///c:/Users/arjit/Desktop/EcoAgent/docs/known_limitations.md) for full limitation details.

---

## Detailed Documentation

For technical specifications, consult the documents under `docs/`:

- [Architecture Decision Record (ADR-0001)](file:///c:/Users/arjit/Desktop/EcoAgent/docs/adr/ADR-0001-phase3-freeze.md)
- [Phase 3 Release Notes](file:///c:/Users/arjit/Desktop/EcoAgent/docs/releases/phase3-freeze.md)
- [Architecture Specification](file:///c:/Users/arjit/Desktop/EcoAgent/docs/architecture.md)
- [Controller Design](file:///c:/Users/arjit/Desktop/EcoAgent/docs/controller_design.md)
- [Safety Invariants](file:///c:/Users/arjit/Desktop/EcoAgent/docs/safety_invariants.md)
- [Verification & Testing](file:///c:/Users/arjit/Desktop/EcoAgent/docs/verification.md)
- [Known Limitations](file:///c:/Users/arjit/Desktop/EcoAgent/docs/known_limitations.md)
- [Telemetry Reference & Schema](file:///c:/Users/arjit/Desktop/EcoAgent/docs/telemetry.md)
- [Multi-Phase Roadmap](file:///c:/Users/arjit/Desktop/EcoAgent/docs/roadmap.md)
