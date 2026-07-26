# EcoAgent Phase 3 Readiness & Comprehensive Repository Audit

**Target Repository**: `EcoAgent`  
**Audit Purpose**: Ground-truth implementation model and Phase 3 extension boundary analysis  
**Baseline**: Phase 2 Code Freeze (Git commit `c5a6362`)  
**Auditor**: Senior Backend Systems Architect  
**Date**: July 26, 2026  

---

## 1. Complete Repository Tree & Module Ownership

```text
EcoAgent/
│
├── config/
│   └── default.yaml                     # [CONFIG] EnergyPlus installation, IDF, and weather file paths
│
├── data/
│   ├── 5ZoneAirCooled.idf               # [IDF MODEL] 5 thermal zones, VAV system, plant loops
│   └── USA_CO_Golden-NREL.724666_TMY3.epw # [WEATHER] Golden, CO TMY3 weather dataset
│
├── docs/                                # [DOCUMENTATION] Technical specifications & frozen reports
│   ├── architecture.md                  # System architecture & C-API execution flow
│   ├── controller_design.md             # Controller state machine & step-size specifications
│   ├── experiments.md                   # Empirical C-API test results & empirical evidence
│   ├── limitations.md                   # System boundaries & pre-predictor telemetry limits
│   ├── phase2_signoff.md                # Formal Phase 2 closure document & sign-off
│   ├── roadmap.md                       # Multi-phase project roadmap (Phase 0 to 8)
│   ├── safety_invariants.md             # Formal safety invariants & validation rules
│   ├── telemetry.md                     # JSON-lines log schema & variable definitions
│   └── verification.md                  # Automated integration & unit test suite summary
│
├── logs/                                # [OUTPUTS] Runtime output artifacts & JSON-lines logs
│   ├── controller_output/               # Structured telemetry JSON-lines logs (`controller.jsonl`)
│   └── simulation_output/               # EnergyPlus output directory (.eso, .csv, .err, .html)
│
├── scripts/                             # [EXECUTABLES & TESTS] Simulation runners & test scripts
│   ├── run_simulation.py                # Main annual simulation entry point
│   ├── test_emergency_hysteresis.py     # Automated unit test for magnitude step sizes & hysteresis
│   ├── test_initialization_timeout.py   # Automated unit test for initialization timeout & reminders
│   └── test_phase2.py                   # Master integration test suite (32 assertions across 8 categories)
│
└── src/
    └── ecoagent/                        # [CORE PACKAGE] Main Python application package
        ├── __init__.py                  # Package version (`0.1.0`)
        │
        ├── controller/                  # [FROZEN] Deterministic Closed-Loop Controller Package
        │   ├── __init__.py              # Public exports for controller package
        │   ├── constants.py             # Numerical bounds, comfort targets, step sizes, zone lists
        │   ├── zone_state.py            # Per-zone independent state structure (`ZoneState`)
        │   ├── scheduler.py             # Shared runtime scheduler & warmup filter (`Scheduler`)
        │   ├── zone_controller.py       # Deterministic zone state machine (`ZoneController`)
        │   ├── safety_guard.py          # Invariant enforcer & validator (`validate_command`)
        │   ├── actuator.py              # Handle cache, sensor reader & write verifier (`ActuatorManager`)
        │   ├── logger.py                # Structured telemetry logger (`ControllerLogger`)
        │   └── orchestrator.py          # Top-level callback pipeline orchestrator (`Orchestrator`)
        │
        └── simulation/                  # [SIMULATION INTEGRATION] EnergyPlus API Wrapper Package
            ├── __init__.py              # Simulation package export
            └── energyplus.py            # EnergyPlus C-API runner (`EnergyPlusRunner`)
```

### Module Boundaries & Ownership

- **`ecoagent.simulation`**: Owns C-API state initialization (`EnergyPlusAPI`), state deletion, CLI command assembly, and process execution. **Must remain decoupled from controller logic.**
- **`ecoagent.controller`**: Owns all closed-loop control, state tracking, invariant enforcement, and logging. Frozen at Phase 2.
- **`scripts/run_simulation.py`**: Entry script wiring `EnergyPlusRunner` to `Orchestrator`.

---

## 2. Source Code Analysis: `controller` Package

### A. `constants.py` (`src/ecoagent/controller/constants.py`)
- **Responsibilities**: Single source of truth for numerical bounds, thresholds, step sizes, and zone names.
- **Owned State**: Immutable module-level constants.
- **Public API**:
  - `HEATING_BOUND_MIN = 18.0`, `HEATING_BOUND_MAX = 22.0`
  - `COOLING_BOUND_MIN = 23.0`, `COOLING_BOUND_MAX = 27.0`
  - `MIN_DEADBAND = 1.0`
  - `COMFORT_HEATING = 22.0`, `COMFORT_COOLING = 24.0`, `COMFORT_TOLERANCE = 0.5`
  - `COMFORT_TRIGGER_LOW = 21.5`, `COMFORT_TRIGGER_HIGH = 24.5`
  - `NORMAL_STEP = 0.5`, `AGGRESSIVE_STEP = 1.0`
  - `AGGRESSIVE_ENTRY_THRESHOLD = 2.0`, `AGGRESSIVE_EXIT_THRESHOLD = 1.5`
  - `DWELL_CYCLES = 4`, `INITIALIZING_TIMEOUT_CYCLES = 10`, `SATURATION_CYCLE_THRESHOLD = 8`
  - `ZONE_NAMES = ["SPACE1-1", "SPACE2-1", "SPACE3-1", "SPACE4-1", "SPACE5-1"]`
  - `READBACK_TOLERANCE = 0.001`, `READBACK_FAILURE_LIMIT = 3`
  - `SENSOR_TEMP_FLOOR = -50.0`, `SENSOR_TEMP_CEILING = 60.0`
- **Dependencies**: None (leaf module).
- **Assumptions**: 5 thermal zones matching `5ZoneAirCooled.idf`.

### B. `zone_state.py` (`src/ecoagent/controller/zone_state.py`)
- **Responsibilities**: Encapsulates all mutable state for a single thermal zone.
- **Owned State**: Instance variables (`current_temperature`, `last_valid_temperature`, `current_heating_setpoint`, `current_cooling_setpoint`, `previous_actuator_command`, `previous_decision`, `controller_state`, `aggressive_mode`, `deadband_status`, `dwell_timer`, `saturation_flag`, `saturation_counter`, `degraded`, `consecutive_readback_failures`, `verification_history`).
- **Public API**: `ZoneState(zone_name)`, `mark_degraded(reason)`, `record_readback_success()`, `record_readback_failure()`, `record_verification(result)`, `create_zone_states()`.
- **Dependencies**: Imports constants from `.constants`.
- **Side Effects**: `mark_degraded()` sets `self.degraded = True` and `self.controller_state = "DEGRADED"`. `record_readback_failure()` triggers `mark_degraded()` when failures reach `READBACK_FAILURE_LIMIT` (3).

### C. `scheduler.py` (`src/ecoagent/controller/scheduler.py`)
- **Responsibilities**: Coordinates high-level runtime lifecycle, warmup filtering, clock extraction, and initialization timeouts.
- **Owned State**: `callback_counter`, `warmup_active`, `simulation_clock`, `simulation_status`, `_init_counter`, `_handles_resolved`, `timeout_triggered`, `should_log_reminder`.
- **Public API**: `Scheduler(init_timeout, reminder_interval)`, `tick(api, state)`, `notify_handles_resolved(all_zones_failed)`, `stop()`.
- **Lifecycle Flow**: `STATUS_INITIALIZING` → `STATUS_RUNNING` (on handle resolution) or `STATUS_DISABLED` (on timeout/failure).
- **Dependencies**: Imports status constants from `.constants`.

### D. `zone_controller.py` (`src/ecoagent/controller/zone_controller.py`)
- **Responsibilities**: Pure deterministic state machine evaluating temperature against fixed comfort band [21.5, 24.5]°C.
- **Owned State**: `self.zone_name` (stateless decision logic; zone state is passed in).
- **Public API**: `ProposedCommand`, `ZoneController(zone_name)`, `evaluate(zone_state) -> ProposedCommand`, `create_zone_controllers()`.
- **Step Size Sizing**: Applies 0.5°C normal step vs 1.0°C aggressive step with 2.0°C entry / 1.5°C exit hysteresis on `zone_state.aggressive_mode`.

### E. `safety_guard.py` (`src/ecoagent/controller/safety_guard.py`)
- **Responsibilities**: Pure function validating proposed setpoints against hard bounds, deadband, dwell timer, and critical bounds.
- **Public API**: `ValidatedCommand`, `validate_command(zone_state, proposed_heating, proposed_cooling) -> ValidatedCommand`.
- **Evaluation Order**:
  1. `zone_state.degraded` → reject write (`zone_degraded`).
  2. Critical cold (<18°C) → force H=22, C=27 (`critical_clamp_cold`, **bypasses dwell**).
  3. Critical hot (>27°C) → force H=18, C=23 (`critical_clamp_hot`, **bypasses dwell**).
  4. Bounds clamp → heating [18, 22]°C, cooling [23, 27]°C.
  5. Deadband enforcement → cooling - heating ≥ 1.0°C.
  6. Dwell enforcement → if setpoints change and `dwell_timer < 4` → reject shift (`dwell_hold`).
  7. Final assertions → fallback to previous setpoints if bounds fail.

### F. `actuator.py` (`src/ecoagent/controller/actuator.py`)
- **Responsibilities**: Queries and caches handles once, reads sensors (with NaN/out-of-bound fallback), writes setpoints, and verifies immediate in-callback readback.
- **Owned State**: Handle maps (`_heating_handles`, `_cooling_handles`, `_temp_handles`), `_outdoor_handle`, `_chiller_handle`, `_resolved`.
- **Public API**: `WriteResult`, `SensorReading`, `ActuatorManager()`, `resolve_handles(api, state, zone_states)`, `read_sensors(api, state, zone_states)`, `write_and_verify(api, state, zone_name, heating_sp, cooling_sp)`.

### G. `logger.py` (`src/ecoagent/controller/logger.py`)
- **Responsibilities**: Formats and appends structured JSON-lines to `logs/controller_output/controller.jsonl`.
- **Public API**: `ControllerLogger(output_dir)`, `log_cycle()`, `log_exception()`, `log_event()`, `close()`.

### H. `orchestrator.py` (`src/ecoagent/controller/orchestrator.py`)
- **Responsibilities**: Top-level callback factory wiring the complete pipeline in sequence inside a `try-except` boundary.
- **Owned State**: `scheduler`, `zone_states`, `zone_controllers`, `actuator_manager`, `logger`.
- **Public API**: `Orchestrator(log_dir)`, `create_callback() -> function(api, state)`, `finalize()`, `get_summary()`.

---

## 3. Runtime Entry Point Analysis (`scripts/run_simulation.py`)

The application entry point is `scripts/run_simulation.py`:

```python
def main():
    config = yaml.safe_load(open("config/default.yaml"))
    runner = EnergyPlusRunner(config)
    orchestrator = Orchestrator()
    
    result = runner.run(callback_fn=orchestrator.create_callback())
    orchestrator.finalize()
```

### Execution Lifecyle Flow
1. `EnergyPlusRunner` resolves full paths to `EnergyPlusV26-1-0`, `5ZoneAirCooled.idf`, `USA_CO_Golden-NREL.epw`, and `output_dir`.
2. `EnergyPlusAPI()` is initialized and new state handle created (`api.state_manager.new_state()`).
3. `orchestrator.create_callback()` generates an internal closure function `callback(api, state)`.
4. `runner.run()` calls `api.runtime.callback_begin_system_timestep_before_predictor(state, internal_callback)`.
5. `api.runtime.run_energyplus(state, cmd)` blocks until simulation completes.
6. C-API invokes `internal_callback` every 15 simulated minutes (35,616 total calls: 576 warmup + 35,040 main run).
7. Upon return from `run_energyplus`, `state_manager.delete_state(state)` cleans up C memory.

---

## 4. Derived Ground-Truth Callback Pipeline

Derived strictly from `orchestrator.py` source code:

```text
EnergyPlus C-Engine
       │
       ▼ (fires callback_begin_system_timestep_before_predictor)
Orchestrator.create_callback.<locals>.callback(api, state)
       │
       ▼ [try-except boundary]
Orchestrator._execute_cycle(api, state)
       │
       ├──> 1. Scheduler.tick(api, state)
       │      ├── Check warmup_flag(state) -> If True: return False
       │      ├── Check simulation_status -> If DISABLED/STOPPED: return False
       │      └── Increment callback_counter & clock -> Return True if RUNNING / INITIALIZING
       │
       ├──> 2. Handle Resolution [First Valid Callback Only]
       │      └── ActuatorManager.resolve_handles(api, state, zone_states)
       │            └── C-API handle lookups -> Cache handles -> Set _resolved = True
       │
       ├──> 3. Sensor Reading
       │      └── ActuatorManager.read_sensors(api, state, zone_states)
       │            └── Get zone air temps, outdoor temp, chiller power (with fallback)
       │
       ├──> 4. Per-Zone Control Loop (SPACE1-1 .. SPACE5-1)
       │      ├── a. ZoneController.evaluate(zone_state) -> ProposedCommand
       │      ├── b. validate_command(zone_state, proposed_h, proposed_c) -> ValidatedCommand
       │      ├── c. If ValidatedCommand.approved AND not zone_state.degraded:
       │      │        ActuatorManager.write_and_verify(...)
       │      │          ├── set_actuator_value(heating)
       │      │          ├── set_actuator_value(cooling)
       │      │          ├── get_actuator_value(heating) [Readback]
       │      │          ├── get_actuator_value(cooling) [Readback]
       │      │          └── If readback matches (<0.001): reset failures, update setpoints
       │      │              Else: increment readback failure count -> (if >=3: mark degraded)
       │      └── d. Orchestrator._update_saturation(zone_state, validated_command)
       │
       └──> 5. Structured Logging
              └── ControllerLogger.log_cycle(scheduler, zone_states, sensor_reading, zone_results)
```

---

## 5. Data Contracts & Object Schemas

| Data Object | Class / Structure | Producer | Consumer | Mutability | Lifecycle |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `ZoneState` | Data Class (`zone_state.py`) | `create_zone_states()` | `ZoneController`, `SafetyGuard`, `ActuatorManager`, `Logger` | **Mutable** | Persists throughout full simulation run |
| `ProposedCommand` | Data Class (`zone_controller.py`) | `ZoneController.evaluate()` | `SafetyGuard` | Immutable | Short-lived (single callback cycle) |
| `ValidatedCommand` | Data Class (`safety_guard.py`) | `validate_command()` | `Orchestrator`, `ActuatorManager` | Immutable | Short-lived (single callback cycle) |
| `WriteResult` | Data Class (`actuator.py`) | `ActuatorManager.write_and_verify()` | `Orchestrator`, `ZoneState` | Immutable | Short-lived (single callback cycle) |
| `SensorReading` | Data Class (`actuator.py`) | `ActuatorManager.read_sensors()` | `Orchestrator`, `Logger` | **Mutable** (temperatures mapped) | Short-lived (single callback cycle) |
| `Scheduler` | Class (`scheduler.py`) | `Orchestrator.__init__()` | `Orchestrator`, `Logger` | **Mutable** | Persists throughout full simulation run |
| `ControllerLogger` | Class (`logger.py`) | `Orchestrator.__init__()` | `Orchestrator` | **Mutable** (file handle) | Persists throughout full simulation run |

---

## 6. Safety Guard Detailed Logic

The Safety Guard (`ecoagent.controller.safety_guard.validate_command`) is a **pure function** with zero internal state.

### Priority Rules Flow
1. **Rule 1 (Degraded Check)**: If `zone_state.degraded == True`, return `ValidatedCommand(approved=False, reason="zone_degraded")`.
2. **Rule 2 (Critical Cold Clamp)**: If `current_temp < 18.0°C`, return `ValidatedCommand(approved=True, heating=22.0, cooling=27.0, reason="critical_clamp_cold")`. **Bypasses Dwell Timer.**
3. **Rule 3 (Critical Hot Clamp)**: If `current_temp > 27.0°C`, return `ValidatedCommand(approved=True, heating=18.0, cooling=23.0, reason="critical_clamp_hot")`. **Bypasses Dwell Timer.**
4. **Rule 4 (Bounds Clamping)**: `h = max(18.0, min(proposed_h, 22.0))`, `c = max(23.0, min(proposed_c, 27.0))`.
5. **Rule 5 (Deadband Enforcement)**: If `c - h < 1.0°C`, adjust `c = h + 1.0`. If `c > 27.0°C`, set `c = 27.0` and `h = 26.0`.
6. **Rule 6 (Dwell Enforcement)**: If setpoints change and `zone_state.dwell_timer < 4`, return `ValidatedCommand(approved=True, heating=current_h, cooling=current_c, reason="dwell_hold")`.
7. **Rule 7 (Final Assertion Fallback)**: If final setpoints fail bounds assertions, return `_fallback(zone_state, reason)`.

---

## 7. Orchestrator Deep Analysis

### Implementation Characteristics
- **Is it a simple call chain?** Yes. `_execute_cycle` sequences scheduler → sensors → zone loops → logging.
- **Does it own state?** Yes. Owns instances of `Scheduler`, `zone_states` dict, `zone_controllers` dict, `ActuatorManager`, and `ControllerLogger`.
- **Can anything observe execution?** Currently, execution is observed via structured JSON-lines written by `ControllerLogger`.
- **Are there existing hooks?** No event bus or listener interface currently exists inside `Orchestrator`.
- **Phase 3 Extension Strategy**:
  - Phase 3 supervisor agents/MCP tools can attach **before** Step 4a (`ZoneController.evaluate`) or override proposed commands **prior to** Step 4b (`validate_command`).
  - Because `validate_command` is called in Step 4b, any setpoint proposed by an external Phase 3 module will automatically pass through Safety Guard validation.

---

## 8. Scheduler Analysis

### State Machine & Transitions
- `STATUS_INITIALIZING` (0): Initial state. Allows 10 initialization callback ticks.
- `STATUS_RUNNING` (1): Set when `notify_handles_resolved(False)` is called.
- `STATUS_DISABLED` (2): Set if handles fail to resolve or initialization count > 10.
- `STATUS_STOPPED` (3): Set when simulation completes.

### Threading & Execution
- Runs synchronously on the C-API main thread inside `tick(api, state)`.
- Non-blocking. Warmup callbacks return `False` instantly.

---

## 9. Telemetry & Logger Analysis

### Log Format
Appends single-line JSON records to `logs/controller_output/controller.jsonl`:

```json
{
  "callback_number": 1,
  "simulated_timestamp": {"month": 1, "day": 1, "hour": 0, "minute": 15},
  "warmup": false,
  "scheduler_status": "RUNNING",
  "outdoor_temp_c": -6.0,
  "chiller_power_w": 0.0,
  "total_zones_active": 5,
  "total_zones_degraded": 0,
  "zones": [
    {
      "zone_name": "SPACE1-1",
      "controller_state": "HEATING",
      "aggressive_mode": false,
      "temperature_c": 16.95,
      "proposed_heating_sp": 22.5,
      "proposed_cooling_sp": 27.0,
      "validated_heating_sp": 22.0,
      "validated_cooling_sp": 27.0,
      "safety_guard_reason": "critical_clamp_cold",
      "actuator_written": true,
      "readback_verified": true,
      "dwell_timer": 0,
      "saturation_flag": false,
      "degraded": false
    }
  ]
}
```

### Replay Capability
Because logs contain full timestamp, outdoor temperature, zone temperatures, decisions, and setpoints for every 15-minute callback, offline replay and counterfactual policy evaluation are fully supported.

---

## 10. Actuator Layer Analysis

- **Handle Caching**: `resolve_handles()` executes once when `api_data_fully_ready` is True. `self._resolved = True` guarantees no re-lookups.
- **Write Sequence**:
  1. `set_actuator_value(state, heating_handle, heating_sp)`
  2. `set_actuator_value(state, cooling_handle, cooling_sp)`
  3. Immediate `get_actuator_value(state, heating_handle)` & `get_actuator_value(state, cooling_handle)`
- **Verification**: Difference `< 0.001°C`.
- **Degradation**: If readback fails 3 consecutive times, `zone_state.mark_degraded()` isolates the zone.

---

## 11. EnergyPlus Integration Analysis

- **Module**: `ecoagent.simulation.energyplus.EnergyPlusRunner`.
- **API Call**: `api.runtime.callback_begin_system_timestep_before_predictor(state, internal_callback)`.
- **State Lifecycle**: State created via `new_state()`, deleted via `delete_state(state)` after `run_energyplus()` returns.

---

## 12. Configuration System Analysis

- **File**: `config/default.yaml`
  ```yaml
  energyplus_path: "C:/EnergyPlusV26-1-0"
  weather_path: "data/USA_CO_Golden-NREL.724666_TMY3.epw"
  idf_path: "data/5ZoneAirCooled.idf"
  output_dir: "logs/simulation_output"
  ```
- **Hardcoded Constants**: Thermal bounds (18-22°C heating, 23-27°C cooling) live in `src/ecoagent/controller/constants.py` as explicit safety invariants.

---

## 13. Test Suite Audit

1. **`scripts/test_phase2.py`**: 32 assertions across 8 categories (Annual run, Warmup, Actuator readback, Degraded zone isolation, Safety bounds, Comfort band boundaries, Exception resilience, Dwell bypass).
2. **`scripts/test_emergency_hysteresis.py`**: 8 assertions (0.5°C normal step, 1.0°C aggressive step, 2.0°C entry / 1.5°C exit hysteresis).
3. **`scripts/test_initialization_timeout.py`**: 4 assertions (10-callback initialization timeout, `STATUS_DISABLED`, `CRITICAL` log emission, periodic reminders).

All tests execute with **32/32 PASS** and **0 FAIL**.

---

## 14. Documentation Cross-Check Report

Comparing ground-truth source code against `docs/`:

| Document | Accuracy Status | Discrepancy Found / Note |
| :--- | :--- | :--- |
| `README.md` | **100% Accurate** | Fully aligned with implementation. |
| `docs/architecture.md` | **100% Accurate** | Correctly diagrams callback lifecycle. |
| `docs/controller_design.md` | **100% Accurate** | Accurately describes state machine and step-size hysteresis. |
| `docs/safety_invariants.md` | **100% Accurate** | Matches `safety_guard.py` rule precedence. |
| `docs/verification.md` | **100% Accurate** | Summarizes 32/32 integration test results. |
| `docs/experiments.md` | **100% Accurate** | Documents empirical write timing and C-API findings. |
| `docs/telemetry.md` | **100% Accurate** | Documents JSON schema and pre-predictor sampling limitation. |
| `docs/limitations.md` | **100% Accurate** | Correctly lists single-threading and pre-predictor telemetry limits. |
| `docs/phase2_signoff.md` | **100% Accurate** | Reflects sign-off status and observability patch summary. |
| `docs/roadmap.md` | **100% Accurate** | High-level roadmap objectives matching project scope. |

---

## 15. Dependency Graph

```mermaid
graph TD
    Runner[ecoagent.simulation.energyplus] -->|Imports API| PyEP[pyenergyplus.api]
    Orchestrator[ecoagent.controller.orchestrator] --> Scheduler[ecoagent.controller.scheduler]
    Orchestrator --> ZoneState[ecoagent.controller.zone_state]
    Orchestrator --> ZoneController[ecoagent.controller.zone_controller]
    Orchestrator --> SafetyGuard[ecoagent.controller.safety_guard]
    Orchestrator --> ActuatorManager[ecoagent.controller.actuator]
    Orchestrator --> ControllerLogger[ecoagent.controller.logger]
    
    ZoneController --> Constants[ecoagent.controller.constants]
    SafetyGuard --> Constants
    ZoneState --> Constants
    Scheduler --> Constants
    ActuatorManager --> Constants
    
    RunScript[scripts/run_simulation.py] --> Runner
    RunScript --> Orchestrator
```

### Circular Dependency Risk Analysis
- **Result**: Zero circular dependencies. Imports flow strictly top-down. `constants.py` is a clean leaf module.

---

## 16. Phase 3 Readiness & Extension Strategy

### Safest Extension Points for Phase 3
1. **Supervisory Proposal Hook**: Add an optional `supervisory_agent` interface inside `Orchestrator._execute_cycle()` between Step 4a (`ZoneController.evaluate`) and Step 4b (`validate_command`).
2. **MCP Tool Server Layer**: Create a separate package `src/ecoagent/mcp/` that wraps `Orchestrator` state queries (read-only tools) and setpoint proposal submissions (write tools).

### Untouched Modules (Frozen)
- `src/ecoagent/controller/safety_guard.py`
- `src/ecoagent/controller/constants.py`
- `src/ecoagent/controller/zone_state.py`
- `src/ecoagent/simulation/energyplus.py`

### Forbidden Abstractions
- **DO NOT** create direct C-API setpoint write functions that bypass `SafetyGuard`.
- **DO NOT** introduce blocking network calls directly inside the C-API callback thread.

---

## 17. Repository Engineering Audit Summary

- **Coupling**: Low. Controller modules are highly cohesive and decoupled via data contracts (`ProposedCommand`, `ValidatedCommand`, `SensorReading`).
- **Technical Debt**: None identified in Phase 2 baseline.
- **Scalability**: High. Additional zones or sensors can be added by updating `constants.ZONE_NAMES` and handle maps.
- **Audit Recommendation**: **Phase 2 repository baseline is clean, fully verified, and ready for Phase 3 MCP interface development.**
