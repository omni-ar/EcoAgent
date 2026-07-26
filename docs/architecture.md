# EcoAgent — System Architecture Document

## 1. Problem Statement

Buildings consume approximately 40% of global energy, with HVAC systems as the primary consumer. Traditional Building Management Systems (BMS) use rigid, rule-based schedules that cannot adapt dynamically to real-time conditions. EcoAgent transforms a passive energy consumer into an active, self-correcting agent using AI-driven closed-loop control.

## 2. Solution Overview

EcoAgent pairs **EnergyPlus** (a physics-based building energy simulator) with a locally-hosted **open-source LLM** (Qwen 2.5 7B via Ollama) using the **Model Context Protocol (MCP)** to create an autonomous supervisory control system. The LLM observes real-time building telemetry, reasons about energy optimization opportunities, and injects setpoint adjustments back into the running simulation — all without human intervention.

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     EnergyPlus Simulation                       │
│   5 Zones: SPACE1-1, SPACE2-1, SPACE3-1, SPACE4-1, SPACE5-1   │
│   Timestep callbacks every 15 simulated minutes (4x/hour)      │
└───────────────────────────┬─────────────────────────────────────┘
                            │  Runtime Callback
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                Controller Layer (Deterministic)                 │
│  ZoneController (FSM) → Safety Guard → Actuator (EMS R/W)      │
│  - Comfort triggers: <21.5°C heating, >24.5°C cooling          │
│  - Hard bounds: H[18,22] C[23,27], deadband ≥1°C               │
│  - Dwell timer prevents oscillation                             │
│  - Readback verification on every write                         │
└───────────────────────────┬─────────────────────────────────────┘
                            │  RuntimeSnapshot → Queue
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                 Supervisor Layer (Advisory)                      │
│  RuntimeSnapshot → HistoryBuffer (96 slots) → Analytics         │
│  SupervisorInterface: proposal lifecycle, TTL, 3-way outcome    │
│  EventBus: pub/sub for snapshot distribution                    │
│  ToolRegistry: 6 data tools + 1 action tool                    │
└───────────────────────────┬─────────────────────────────────────┘
                            │  MCP Tool Schemas
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    MCP + Agent Layer                             │
│  McpAdapter: 8 tools with JSON schemas for function calling     │
│  McpToolDispatcher: validation, type coercion, routing          │
│  AgentLoop: ReAct pattern (Observe → Reason → Act)              │
│  ContextBuilder: structured state → user message                │
│  AgentTraceLogger: JSONL audit trail per cycle                  │
└───────────────────────────┬─────────────────────────────────────┘
                            │  OpenAI-compatible API
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│           LLM: Qwen 2.5 7B (Ollama, localhost:11434)            │
│  - Local inference, zero cloud dependency                       │
│  - Function calling with tool schemas                           │
│  - Concise response format (max 200 tokens)                     │
└─────────────────────────────────────────────────────────────────┘
```

## 4. MCP Tool-Calling Design

The LLM interacts with the simulation through 8 MCP tools exposed as OpenAI function-calling schemas:

| Tool | Purpose | Returns |
|---|---|---|
| `get_building_summary` | Full building state in one call | All zones, outdoor temp, chiller power, comfort % |
| `get_runtime_state` | All zone temperatures and setpoints | Per-zone temps, setpoints, controller states |
| `get_zone` | Single zone detail | Temperature, setpoints, FSM state, safety status |
| `get_zone_trend` | Temperature trend over time | Historical temp/setpoint arrays |
| `get_scheduler_status` | Simulation clock and status | Month, day, hour, sim status |
| `get_history` | Historical snapshots | Array of past RuntimeSnapshots |
| `get_analytics_summary` | Comfort %, energy metrics | Comfort score, chiller stats |
| `propose_setpoint` | Submit heating/cooling change | Proposal status (pending/rejected) |

The `McpToolDispatcher` validates arguments against JSON schemas, coerces types (e.g., string→float for setpoints), and routes calls through `McpAdapter` to `ToolRegistry`. All tool results are JSON-serializable and returned to the LLM as `role: "tool"` messages.

## 5. Closed-Loop Execution Framework

### 5.1 Data Flow

1. **Feedback (EnergyPlus → AI)**: The simulation streams continuous performance metrics via timestep callbacks (4x per simulated hour). Each callback produces a `RuntimeSnapshot` containing zone temperatures, setpoints, controller states, outdoor temperature, and chiller power.

2. **Reasoning (AI)**: The `AgentLoop` implements a **ReAct (Reason + Act) pattern**:
   - **Turn 0 (Observe)**: LLM calls `get_building_summary` to read current building state
   - **Turn 1 (Act)**: With tool results in context, LLM decides whether to call `propose_setpoint`
   - The multi-turn loop feeds tool results back as conversation messages, enabling observe-then-act within one reasoning cycle

3. **Control Actions (AI → EnergyPlus)**: Setpoint proposals pass through Safety Guard validation before reaching actuators

4. **Forward Injection**: Validated setpoints are written to EnergyPlus via EMS actuator handles with readback verification

### 5.2 Threading Model

```
Thread 1 (EnergyPlus runtime):
  Orchestrator._execute_cycle → ZoneController → SafetyGuard → Actuator

Thread 2 (Agent worker):
  AgentLoop.run → model warmup → drain queue → drift check → LLM ReAct loop
  
Bridge: EventBus publishes RuntimeSnapshot → Queue → AgentLoop wakeup
```

### 5.3 Drift Gating

When the agent establishes a policy (e.g., "SPACE2-1 should have cooling=25°C"), it monitors for **drift** — the deterministic controller may override the LLM's setpoints. If drift exceeds 0.5°C, the agent re-submits its policy to maintain consistency. This closes the loop: the LLM doesn't just propose once and forget.

## 6. Prompt Engineering Strategy

| Technique | Purpose | Impact |
|---|---|---|
| Conciseness directive | "If no action needed, say so in under 20 words" | Reduced Turn 1 from 56.8s to 3.3s |
| max_tokens cap (200) | Prevent verbose analysis generation | Cut completion tokens from 395 to ~17-71 |
| Explicit tool strategy | "OBSERVE first, then ANALYZE, then ACT" | Model follows ReAct pattern reliably |
| Safety bounds in prompt | Heating [18,22], Cooling [23,27] | Model proposes within valid ranges |
| Zone names listed | SPACE1-1 through SPACE5-1 | Eliminates hallucinated zone names |

## 7. Latency Management

| Component | Measured Latency | Optimization |
|---|---|---|
| Model cold start | ~22s | Warmup call at agent startup |
| Turn 0 (observe, warm) | ~2.5s | Efficient prompt, minimal context |
| Turn 1 (decide, warm) | ~3-10s | max_tokens=200, brevity prompt |
| Full warm cycle | ~12s | Down from 59s pre-optimization |
| Tool execution | <1ms | In-memory function call |
| Context construction | <1ms | Pre-built snapshot |
| Reasoning cadence | Every 8th callback | Balances observability vs inference cost |
| Cycles per simulation | 3 (measured) | Up from 0 pre-optimization |

## 8. Safety Invariants

No LLM output bypasses the Safety Guard. These invariants hold regardless of agent behavior:

1. **Bounds clamping**: All setpoints clamped to [18,22]°C heating and [23,27]°C cooling
2. **Deadband enforcement**: cooling - heating ≥ 1.0°C always
3. **Dwell timer**: Prevents setpoint changes within cooldown window
4. **Critical override**: Emergency bounds for extreme temperatures bypass dwell
5. **Readback verification**: Every actuator write verified by re-reading EMS handle
6. **Zone degradation isolation**: Failed actuator handles → zone excluded from writes

## 9. Production Results

| Metric | Value |
|---|---|
| Simulation | Full year (8760 hours), 5-zone commercial building |
| Reasoning cycles completed | 3 |
| Proposals submitted | 3 (100% submission rate) |
| Proposals accepted by Safety Guard | All pending (validated) |
| Example proposal | SPACE2-1: cooling 24→25°C (energy saving) |
| Trace entries generated | 3 |
| Policy versions | 3 |
| Agent thread shutdown | Clean (no timeout) |

## 10. Technology Stack

| Component | Technology |
|---|---|
| Simulation Engine | EnergyPlus 26.1 (C-API via pyenergyplus) |
| LLM | Qwen 2.5 7B (via Ollama, local inference) |
| LLM API | OpenAI-compatible (localhost:11434/v1) |
| Protocol | MCP (Model Context Protocol) |
| Language | Python 3.11 |
| Key Libraries | openai, pyyaml, pyenergyplus |
| Logging | JSONL (trace.jsonl, controller.jsonl) |
| Version Control | Git + GitHub |
