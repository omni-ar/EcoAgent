# ADR-0001: Phase 3 Supervisory Infrastructure & Baseline Freeze

**Status**: APPROVED  
**Date**: 2026-07-26  
**Deciders**: EcoAgent Architecture Review Committee  
**Replaces**: N/A  
**Superseded By**: N/A  

---

## 1. Context and Problem Statement

In Phase 2, EcoAgent established an in-process simulation loop with a deterministic closed-loop controller (`ZoneController`), a per-zone safety validator (`SafetyGuard`), an actuator verification layer (`ActuatorManager`), and structured JSON-lines logging (`ControllerLogger`).

While Phase 2 provided a verified, safe baseline, it functioned as a closed control loop:
- External systems (such as AI agents or monitoring tools) had no real-time inspection interface into controller state during simulation execution.
- There was no mechanism to receive structured runtime events (e.g., safety guard clamps, degraded mode entries) as they occurred.
- External systems could not submit advisory setpoint proposals without directly mutating internal controller state or bypassing safety validation.
- Derived thermal comfort and oscillation metrics required post-simulation log parsing.

Phase 3 was initiated to design and build supervisory observation, event streaming, advisory proposal tracking, and metrics calculation infrastructure without modifying or compromising the deterministic control authority of the Phase 2 baseline.

---

## 2. Major Engineering Decisions & Architectural Principles

### Decision 1 — Strict Deterministic Control Authority (No Direct Actuation by Supervisor)

* **Context**: External AI agents or Model Context Protocol (MCP) clients require a mechanism to submit proposed setpoint optimizations.
* **Alternatives Considered**:
  - *Option A (Direct Actuation)*: Allow external supervisor modules to call PyEnergyPlus C-API setpoint functions directly.
  - *Option B (Parameter Tuning)*: Allow supervisor to adjust controller comfort band thresholds in real time.
  - *Option C (Advisory Proposal Pipeline)*: Require supervisor to submit structured advisory proposals (`SetpointProposal`) to an intermediate buffer, which pass through the existing safety validation pipeline.
* **Selected Decision**: **Option C (Advisory Proposal Pipeline)**.
* **Reasoning**: Option A creates severe safety risks by allowing unvalidated external commands to touch physical actuators. Option B violates the Phase 2 code freeze by requiring dynamic parameter modification in `ZoneController`. Option C enforces structural safety: the supervisor has propose-only authority; every setpoint must pass through `validate_command()` before reaching `ActuatorManager.write_and_verify()`.
* **Trade-offs**: Advisory proposals may be modified or rejected by the safety guard, requiring external callers to handle non-execution or setpoint adjustment asynchronously.

---

### Decision 2 — Pre-Evaluate Supervisor Proposal Check

* **Context**: When a supervisor proposal exists for a zone, the orchestrator must decide how to handle the deterministic controller's `ZoneController.evaluate()` call.
* **Alternatives Considered**:
  - *Option A (Post-Evaluate Override)*: Call `zc.evaluate(zs)` first to generate a deterministic baseline proposal, then overwrite the proposed setpoints with the supervisor's proposal before `validate_command()`.
  - *Option B (Pre-Evaluate Check)*: Check for a pending supervisor proposal *before* calling `zc.evaluate(zs)`. If a proposal exists, skip `zc.evaluate(zs)` entirely for that zone and assign `zs.controller_state = STATE_SUPERVISOR`.
  - *Option C (ZoneState Rollback Cloning)*: Shallow-copy `ZoneState` before `evaluate()`, and restore state if supervisor overrides.
* **Selected Decision**: **Option B (Pre-Evaluate Check)**.
* **Reasoning**: Source-level audit of `zone_controller.py` revealed that `zc.evaluate(zs)` mutates `zone_state.aggressive_mode` in-place inside `_update_aggressive_mode()`. Under Option A, evaluating first mutates `aggressive_mode` based on a decision that is immediately discarded. On subsequent cycles when the supervisor is inactive, the controller resumes with an unexecuted aggressive mode state (phantom state mutation). Option B skips `zc.evaluate(zs)` when a supervisor proposal is active, keeping `aggressive_mode` 100% clean and unpolluted.
* **Trade-offs**: The deterministic controller does not generate a fallback proposal on cycles where a supervisor proposal is active.

---

### Decision 3 — Three-Way Supervisor Outcome Events

* **Context**: External clients need feedback on whether a submitted proposal was executed as requested, modified by safety rules, or rejected.
* **Alternatives Considered**:
  - *Option A (Binary Accept/Reject on `validated.approved`)*: Emit `SupervisorProposalAccepted` if `approved=True`, `SupervisorProposalRejected` if `approved=False`.
  - *Option B (Three-Way Outcome Matrix)*: Compare `validated` setpoints against original `proposal` setpoints using `READBACK_TOLERANCE` (0.001°C). Emit `SupervisorProposalAccepted` (exact match), `SupervisorProposalModified` (approved=True but modified by dwell hold, clamps, or bounds), or `SupervisorProposalRejected` (approved=False).
* **Selected Decision**: **Option B (Three-Way Outcome Matrix)**.
* **Reasoning**: Audit of `safety_guard.py` confirmed that `dwell_hold`, `critical_clamp_cold`, `critical_clamp_hot`, bounds clamping, and deadband adjustment all return `approved=True`. Under a binary model, a dwell-held proposal (reverted to current setpoints) or a critically clamped proposal would emit `SupervisorProposalAccepted` — a false positive telling the supervisor its request succeeded when it was silently overridden. Option B explicitly distinguishes applied proposals from modified proposals.
* **Trade-offs**: Requires external clients (MCP/LLM) to handle a third outcome status (`MODIFIED`).

---

### Decision 4 — Proposal Expiration (TTL Lifecycle)

* **Context**: Proposals submitted by external callers must not remain pending indefinitely if simulation conditions change or if the callback loop is interrupted.
* **Alternatives Considered**:
  - *Option A (Wall-Clock Expiry)*: Expire proposals based on `time.time()`.
  - *Option B (Callback-Tick Expiry)*: Expire proposals based on simulation callback ticks (`current_callback - submitted_at_callback >= ttl_cycles`).
* **Selected Decision**: **Option B (Callback-Tick Expiry)**.
* **Reasoning**: Building thermal dynamics evolve in simulation time, not wall-clock time. A 15-minute simulated timestep represents discrete thermal progression regardless of how fast the simulation runs on host CPU. Stamping proposals with `submitted_at_callback` and evaluating `clear_expired()` on every tick guarantees deterministic expiry behavior across simulation runs.
* **Trade-offs**: Requires `Orchestrator` to call `clear_expired()` on every tick, including during `INITIALIZING` or `DISABLED` states.

---

### Decision 5 — Observable Non-Blocking EventBus

* **Context**: Event listeners subscribed to `EventBus` may raise unexpected runtime exceptions.
* **Alternatives Considered**:
  - *Option A (Silent Exception Suppression)*: Use `except Exception: pass` inside `emit()`.
  - *Option B (Uncaught Exception Propagation)*: Allow listener exceptions to bubble up and terminate the callback.
  - *Option C (Diagnostic Exception Tracking)*: Catch exceptions, increment `listener_error_count`, store structured diagnostic data in `last_listener_error`, and continue executing remaining listeners.
* **Selected Decision**: **Option C (Diagnostic Exception Tracking)**.
* **Reasoning**: Option A swallows failures silently, hindering debugging. Option B breaks the core requirement that Phase 3 infrastructure must never interrupt HVAC control execution. Option C makes listener failures fully observable without blocking the callback loop or other listeners.
* **Trade-offs**: `EventBus` retains diagnostic metadata for the most recent listener error rather than a full unbounded error log.

---

### Decision 6 — Architectural Ownership of Supervisory Constants

* **Context**: `STATE_SUPERVISOR = "SUPERVISOR"` was initially defined in `analytics.py`, causing `orchestrator.py` to import from a reporting module.
* **Alternatives Considered**:
  - *Option A (Add to `controller/constants.py`)*: Move constant to Phase 2 constants file.
  - *Option B (Leave in `analytics.py`)*: Retain existing location.
  - *Option C (Create `supervisor/constants.py`)*: Establish a dedicated constants file in the supervisor package.
* **Selected Decision**: **Option C (Create `supervisor/constants.py`)**.
* **Reasoning**: Option A violates the Phase 2 code freeze by modifying a locked file. Option B perpetuates an architectural inversion (`orchestrator` importing a reporting module). Option C establishes clean ownership within `ecoagent.supervisor` while leaving Phase 2 files untouched.
* **Trade-offs**: Adds one small module (`src/ecoagent/supervisor/constants.py`).

---

## 3. Status & Governance Statement

Phase 3 implementation, hardening, regression validation, and architectural review have been completed. All 128 test assertions across 4 test suites pass with zero failures.

Phase 3 is designated as the approved technical baseline for Phase 4 (Model Context Protocol Tool Server) development. Any subsequent modifications to Phase 3 modules require formal engineering review under Phase 4 governance.
