# Architecture Specification

## Overview

EcoAgent is structured around an in-process simulation loop leveraging the PyEnergyPlus C-API (`pyenergyplus.api.EnergyPlusAPI`). Rather than running EnergyPlus as an external subprocess with post-hoc CSV analysis, EcoAgent registers Python callbacks that execute inside the EnergyPlus C runtime loop at 15-minute simulated intervals.

The architecture comprises two primary layers:
1. **Deterministic Control Layer (Phase 2 Baseline)**: Scheduler, sensor reading, deterministic state machines, safety guard validation, actuator writing, and readback verification.
2. **Supervisory Infrastructure Layer (Phase 3 Baseline)**: Advisory proposal tracking, runtime snapshotting, bounded history buffering, synchronous event emission, analytics computation, and internal tool registry.

---

## System Architecture Diagram

```mermaid
flowchart TD
    EP[EnergyPlus C Runtime Engine] -->|fires callback every 15 min| CB[callback_begin_system_timestep_before_predictor]
    CB --> SCH[Shared Scheduler tick & clear_expired]
    SCH -->|Status: INITIALIZING| INIT[Resolve Handles Once]
    INIT -->|All Handles Valid| RUN[Status: RUNNING]
    INIT -->|Init Timeout Exceeded| DIS[Status: DISABLED]
    RUN --> SENS[Read Physical Sensors]
    SENS --> SUP_CHECK{Pending Supervisor Proposal?}
    
    SUP_CHECK -->|Yes| PROP_SUP[Use Supervisor Setpoints & State: SUPERVISOR]
    SUP_CHECK -->|No| ZC[Zone Controller evaluate & State: IDLE/HEATING/COOLING]
    
    PROP_SUP --> SG[Safety Guard validate_command]
    ZC --> SG
    
    SG -->|Validated Commands| ACT[Actuator Write & Readback Verification]
    ACT -->|Write Result| SNAP[Create RuntimeSnapshot]
    SNAP --> HB[Push to HistoryBuffer 96-size deque]
    SNAP --> EB[Emit CycleCompleted & Outcome Events on EventBus]
    EB --> AN[Analytics Layer]
    LOG[ControllerLogger JSON-L] <-- Write log --> EP
    
    TR[ToolRegistry] -.->|Queries| HB
    TR -.->|Queries| SNAP
    TR -.->|Proposes| SUP_CHECK
    MCP[Future MCP Tools Server] -.-> TR
```

---

## Callback Execution Lifecycle

The primary integration point is `callback_begin_system_timestep_before_predictor`. This callback fires at the start of each system timestep, after zone temperature heat balance calculations are complete but **before** EnergyPlus computes zone load predictions and dispatches HVAC equipment controllers.

### Complete Lifecycle Sequence Diagram

```mermaid
sequenceDiagram
    participant EP as EnergyPlus Engine
    participant CB as Runtime Callback
    participant SCH as Scheduler
    participant SI as SupervisorInterface
    participant SENS as Sensor Interface
    participant ZC as Zone Controller
    participant SG as Safety Guard
    participant ACT as Actuator Interface
    participant HB as HistoryBuffer
    participant EB as EventBus
    participant LOG as ControllerLogger

    EP->>CB: Fire begin_system_timestep_before_predictor(state)
    CB->>SCH: tick(api, state)
    CB->>SI: clear_expired(current_callback)
    
    alt is Warmup or DISABLED
        SCH-->>CB: Return False
        CB-->>EP: Return control to EnergyPlus
    else is RUNNING
        SCH-->>CB: Return True
        CB->>SENS: read_sensors(api, state)
        SENS-->>CB: SensorReading (Zone Temps, Outdoor Temp)
        
        loop For Each Thermal Zone (1..5)
            CB->>SI: get_pending_proposal(zone_name)
            alt Supervisor Proposal Active
                SI-->>CB: SetpointProposal (Heating SP, Cooling SP)
                Note over CB: Skip ZC.evaluate() - aggressive_mode NOT mutated
            else No Proposal Active
                SI-->>CB: None
                CB->>ZC: evaluate(zone_state)
                ZC-->>CB: ProposedCommand (Heating SP, Cooling SP)
            end
            
            CB->>SG: validate_command(zone_state, proposed_h, proposed_c)
            SG-->>CB: ValidatedCommand (Approved SPs, Reason)
            
            alt if Approved and Not Degraded
                CB->>ACT: write_and_verify(api, state, zone, SPs)
                ACT->>EP: set_actuator_value(heating_sp)
                ACT->>EP: set_actuator_value(cooling_sp)
                ACT->>EP: get_actuator_value(heating_handle)
                ACT->>EP: get_actuator_value(cooling_handle)
                ACT-->>CB: WriteResult (Success, Readback SPs)
                
                alt Proposal Was Evaluated
                    alt Setpoints Match Proposed (READBACK_TOLERANCE)
                        CB->>EB: emit(SupervisorProposalAccepted)
                    else Setpoints Modified by Safety Rules
                        CB->>EB: emit(SupervisorProposalModified)
                    end
                    CB->>SI: consume_proposal(zone_name)
                end
            else if Rejected or Degraded
                alt Proposal Was Evaluated
                    CB->>EB: emit(SupervisorProposalRejected)
                    CB->>SI: consume_proposal(zone_name)
                end
            end
        end
        
        CB->>HB: append(create_snapshot())
        CB->>EB: emit(CycleCompleted(snapshot))
        CB->>LOG: log_cycle(scheduler, zone_states, sensor_reading)
        CB-->>EP: Return control to EnergyPlus
    end
```

---

## EnergyPlus C-API Integration

The C-API interface is managed by `ecoagent.simulation.EnergyPlusRunner`. 

### Key C-API Interaction Rules

1. **State Isolation**: Simulation state is managed via `api.state_manager.new_state()` and deleted with `delete_state(state)` upon completion.
2. **Data Availability Gate**: Handles are queried only after `api.exchange.api_data_fully_ready(state)` returns `True`.
3. **In-Process Memory Access**: Setpoint writes (`set_actuator_value`) update EnergyPlus internal setpoint arrays immediately within C memory space.

---

## Pipeline Structural Boundaries

The control pipeline enforces strict structural authority boundaries:

1. **Sensors** read physical environment data.
2. **Supervisor Pre-Check** checks for pending advisory proposals. If present, deterministic evaluation is skipped for that zone to prevent phantom state mutations.
3. **Zone Controllers** evaluate zone temperatures against the comfort band [21.5, 24.5]°C if no supervisor proposal exists.
4. **Safety Guard** validates all proposed commands against hard numerical bounds, deadbands, dwell timers, and critical boundary clamps.
5. **Actuator Layer** issues C-API writes and performs immediate readback verification.
6. **Telemetry & Event Layer** creates `RuntimeSnapshot`, updates `HistoryBuffer`, emits events to `EventBus`, and appends JSON-lines telemetry.

No external component can bypass the Safety Guard to write directly to actuators.
