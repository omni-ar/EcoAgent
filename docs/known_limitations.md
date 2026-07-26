# Known Limitations & Scope Boundaries

**Baseline**: Phase 3 Baseline Freeze  
**Date**: July 26, 2026  

---

## 1. Current Verified System Limitations

The following items represent verified operational and architectural boundaries of the Phase 3 implementation. They do not represent unhandled defects; rather, they document explicit design bounds established by the source code.

### 1.1 In-Process Synchronous C-API Threading
- **Constraint**: PyEnergyPlus C-API runs synchronously on the main Python thread inside `api.runtime.run_energyplus()`.
- **Impact**: Code executing inside callback functions (`Orchestrator._execute_cycle`) must execute in < 2.0 ms total to avoid delaying EnergyPlus simulation ticks.
- **Enforcement**: Phase 3 callback execution is budgeted at < 0.09 ms. Long-running computations (e.g. LLM inference) must execute on separate threads via `ToolRegistry`.

### 1.2 Pre-Predictor Telemetry Insertion Point
- **Constraint**: Telemetry sampled inside `callback_begin_system_timestep_before_predictor` reflects zone temperatures at the start of the timestep prior to HVAC load prediction.
- **Impact**: Plant-level rate variables (e.g. `chiller_power_w`) read at this callback insertion point reflect the state from the *previous* timestep solver iteration (returning `0.0 W` during initial timesteps).
- **Enforcement**: Documented in `telemetry.md`. Post-HVAC reporting callbacks are deferred to Phase 4+.

### 1.3 Single-Producer Advisory Proposal Buffer
- **Constraint**: `SupervisorInterface` maintains at most one pending `SetpointProposal` per zone key (`dict[str, SetpointProposal]`).
- **Impact**: If two external agents submit proposals for the same zone within the same callback cycle, the second proposal overwrites the first (last-writer-wins).
- **Enforcement**: Acceptable for Phase 3 single-supervisor scope. Multi-agent priority arbitration is deferred to Phase 6.

### 1.4 Listener Error Diagnostic Retention
- **Constraint**: `EventBus` tracks `listener_error_count` and stores diagnostic details for the *most recent* listener error (`last_listener_error`).
- **Impact**: If multiple event listeners throw exceptions across multiple cycles, `last_listener_error` reflects only the latest failure details.
- **Enforcement**: Designed to avoid unbounded memory accumulation inside the in-memory event bus. Full historical logging continues via `ControllerLogger` (`controller.jsonl`).

### 1.5 External Proposal TTL Validation
- **Constraint**: `SetpointProposal` requires `ttl_cycles >= 1`.
- **Impact**: `SupervisorInterface.clear_expired()` evaluates expiration based on `current_callback - submitted_at_callback >= ttl_cycles`.
- **Enforcement**: Internal callers and `ToolRegistry` initialize proposals with `ttl_cycles=1`. Phase 4 MCP tool input schemas must validate `ttl_cycles >= 1` for external callers.

### 1.6 In-Memory Bounded History Storage
- **Constraint**: `HistoryBuffer` uses `collections.deque(maxlen=96)` storing up to 96 snapshots (24 hours at 15-minute intervals).
- **Impact**: Snapshots older than 96 cycles are evicted from memory.
- **Enforcement**: Designed for lightweight in-memory analytics. Archival database persistence is deferred to Phase 4+.

---

## 2. Deferred Scope Boundaries (Out of Scope for Phase 3)

The following capabilities are explicitly deferred to subsequent project milestones:

| Capability | Deferred Milestone | Architectural Reason |
| :--- | :--- | :--- |
| **MCP Protocol Transport (stdio/HTTP/SSE)** | Phase 4 | Phase 3 establishes the internal Python function API (`ToolRegistry`). Transport wrapping is a Phase 4 responsibility. |
| **LLM Agent Inference & Prompt Engineering** | Phase 5 | Requires verified MCP server tools (Phase 4) and supervisory infrastructure (Phase 3). |
| **Multi-Agent Priority Arbitration** | Phase 6 | Requires multi-agent orchestration layer above `SupervisorInterface`. |
| **Persistent Time-Series Database (SQLite/Timescale)** | Phase 4 | Requires dedicated database I/O worker pipeline. |
| **Real-Time Operator Web Dashboard** | Phase 7 | Requires UI frontend and WebSocket event streaming. |
