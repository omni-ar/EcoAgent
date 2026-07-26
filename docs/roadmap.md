# Multi-Phase Project Execution Roadmap

## Overview

EcoAgent is structured around an 8-phase milestone execution plan. Progression between phases requires successful completion, verification, and code freeze of all preceding milestones.

---

## Phase Execution Roadmap

```mermaid
timeline
    title EcoAgent Milestone Execution Plan
    Phase 0 : Repository Skeleton & Environment Setup (Complete)
    Phase 1 : EnergyPlus In-Process API Bring-Up (Complete)
    Phase 2 : Deterministic Closed-Loop Controller & Safety Guard (Frozen)
    Phase 3 : Supervisory Infrastructure & Tool Layer (Frozen)
    Phase 4 : Model Context Protocol (MCP) Server & Data Pipeline (Planned)
    Phase 5 : Open-Source LLM Supervisory Agent (Planned)
    Phase 6 : Multi-Agent System & Dynamic Load Shedding (Planned)
    Phase 7 : Operator Dashboard & Real-Time Visualization (Planned)
    Phase 8 : Final System Benchmarking & Freeze (Planned)
```

---

## Milestone Descriptions

### Phase 0 — Repository Foundation & Environment Setup
- **Status**: **COMPLETE & FROZEN**
- **Objectives**: Establish standard Python package layout, configuration management (`config/default.yaml`), dependency manifests, and workspace hygiene.

### Phase 1 — EnergyPlus API Integration & In-Process Execution
- **Status**: **COMPLETE & FROZEN**
- **Objectives**: Verify EnergyPlus v26.1.0 installation, load `pyenergyplus.api` in-process, establish weather file integration (`data/USA_CO_Golden-NREL.epw`), execute annual simulation (`data/5ZoneAirCooled.idf`), and verify callback mechanics.

### Phase 2 — Deterministic Closed-Loop Controller & Safety Guard
- **Status**: **COMPLETE & FROZEN Baseline**
- **Objectives**: Implement deterministic rule-based zone controllers, shared runtime scheduler, handle caching, per-zone Safety Guard validation, immediate readback verification, degraded mode isolation, and structured JSON-lines telemetry.

### Phase 3 — Supervisory Infrastructure & Internal Tool API
- **Status**: **COMPLETE & APPROVED Baseline**
- **Objectives**: Implement `RuntimeSnapshot` factory, `HistoryBuffer` ring buffer, `EventBus` synchronous event streaming, `SupervisorInterface` advisory proposal tracking, `Analytics` metrics layer, and `ToolRegistry` internal tool API mapping 1:1 to future MCP tool definitions.

### Phase 4 — Model Context Protocol (MCP) Server & Data Pipeline
- **Status**: **PLANNED**
- **Objectives**: Expose `ToolRegistry` functions via standardized Model Context Protocol (MCP) stdio/HTTP/SSE server tools, implement post-HVAC reporting telemetry synchronization, and persistent database storage.

### Phase 5 — Open-Source LLM Supervisory Agent Integration
- **Status**: **PLANNED**
- **Objectives**: Connect an open-source LLM supervisory agent to evaluate building state and propose high-level setpoint optimizations via MCP tools, subject to mandatory Phase 2 Safety Guard validation.

### Phase 6 — Multi-Agent Supervisory Control & Peak Load Management
- **Status**: **PLANNED**
- **Objectives**: Deploy specialized sub-agents (e.g. Comfort Agent, Energy Agent, Demand Response Agent) to negotiate zone setpoints during peak utility demand periods while maintaining thermal safety.

### Phase 7 — Operator Interface & Telemetry Dashboard
- **Status**: **PLANNED**
- **Objectives**: Build a real-time web dashboard displaying zone temperatures, setpoints, safety guard interventions, chiller power demand, and agent reasoning traces.

### Phase 8 — Final System Benchmarking & Freeze
- **Status**: **PLANNED**
- **Objectives**: Perform annual baseline vs agentic energy consumption comparisons, calculate total kWh energy savings and occupant thermal comfort compliance, and freeze final system package.
