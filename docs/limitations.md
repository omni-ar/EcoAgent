# System Limitations & Constraints

## Overview

This document explicitly details the architectural, operational, and physical limitations of the EcoAgent Phase 2 infrastructure.

---

## Technical Limitations Inventory

### 1. Pre-Predictor Telemetry Timing Boundary
- **Limitation**: Sensor data logged in `controller.jsonl` is sampled inside `callback_begin_system_timestep_before_predictor`.
- **Impact**: Plant-level rate variables (e.g. `chiller_power_w`) reflect the state prior to current step HVAC solver evaluation.
- **Reason**: The callback fires at the start of the timestep to allow setpoint writes to take effect before HVAC load calculation.
- **Future Work**: Phase 3 will introduce post-HVAC reporting telemetry caching for real-time plant power logging.

### 2. Single-Threaded Synchronous C-API
- **Limitation**: PyEnergyPlus API executes synchronously on the main Python thread.
- **Impact**: Heavy computational blocking inside callbacks hangs the EnergyPlus C simulation thread.
- **Reason**: C-API CPython binding design constraint.
- **Future Work**: Decouple complex AI agent reasoning into background worker threads communicating asynchronously via queue buffers.

### 3. Fixed Zone Setpoint Scope (No Direct Equipment Actuation)
- **Limitation**: Phase 2 restricts control actuation strictly to zone heating and cooling setpoints (`Zone Temperature Control`).
- **Impact**: Central plant equipment (chillers, boilers, supply fans) is controlled by baseline EnergyPlus managers.
- **Reason**: Safety invariant isolation—preventing direct actuation of plant hardware.
- **Future Work**: Phase 4 supervisory plant reset strategies.

### 4. Deterministic Rule-Based Control (No Predictive Optimization)
- **Limitation**: Phase 2 uses a static comfort band rule-based state machine.
- **Impact**: Setpoint shifts react to current zone temperature deviations rather than anticipating solar gains, weather forecasts, or utility price peaks.
- **Reason**: Establishing a verified deterministic baseline prior to introducing AI agents.
- **Future Work**: Phase 3 LLM supervisory agent and MCP tool integration.
