# Architecture Specification

## Overview

EcoAgent is structured around an in-process simulation loop leveraging the PyEnergyPlus C-API (`pyenergyplus.api.EnergyPlusAPI`). Rather than running EnergyPlus as an external subprocess with post-hoc CSV analysis, EcoAgent registers Python callbacks that execute inside the EnergyPlus C runtime loop at 15-minute simulated intervals.

---

## System Architecture Diagram

```mermaid
flowchart TD
    EP[EnergyPlus C Runtime Engine] -->|fires callback every 15 min| CB[callback_begin_system_timestep_before_predictor]
    CB --> WF{Warmup Filter}
    WF -->|warmup_flag == True| SKIP[Skip Callback]
    WF -->|warmup_flag == False| SCH[Shared Scheduler]
    SCH -->|Status: INITIALIZING| INIT[Resolve Handles Once]
    INIT -->|All Handles Valid| RUN[Status: RUNNING]
    INIT -->|Init Timeout Exceeded| DIS[Status: DISABLED]
    RUN --> SENS[Read Physical Sensors]
    SENS --> CTRL[Zone Controllers 1..5]
    CTRL -->|Proposed Commands| SG[Safety Guard]
    SG -->|Validated Commands| ACT[Actuator Write & Readback]
    ACT -->|Immediate Verification| LOG[Structured JSON-L Logger]
    LOG --> EP
```

---

## Callback Execution Lifecycle

The primary integration point is `callback_begin_system_timestep_before_predictor`. This callback fires at the start of each system timestep, after zone temperature heat balance calculations are complete but **before** EnergyPlus computes zone load predictions and dispatches HVAC equipment controllers.

### Lifecycle Sequence

```mermaid
sequenceDiagram
    participant EP as EnergyPlus Engine
    participant CB as Runtime Callback
    participant SCH as Scheduler
    participant SENS as Sensor Interface
    participant CTRL as Zone Controller
    participant SG as Safety Guard
    participant ACT as Actuator Interface
    participant LOG as Logger

    EP->>CB: Fire begin_system_timestep_before_predictor(state)
    CB->>SCH: tick(api, state)
    alt is Warmup or DISABLED
        SCH-->>CB: Return False
        CB-->>EP: Return control to EnergyPlus
    else is RUNNING
        SCH-->>CB: Return True
        CB->>SENS: read_sensors(api, state)
        SENS-->>CB: SensorReading (Zone Temps, Outdoor Temp)
        loop For Each Thermal Zone (1..5)
            CB->>CTRL: evaluate(zone_state)
            CTRL-->>CB: ProposedCommand (Heating SP, Cooling SP)
            CB->>SG: validate_command(zone_state, proposed)
            SG-->>CB: ValidatedCommand (Approved SPs, Reason)
            alt if Approved and Actuator Write Required
                CB->>ACT: write_and_verify(api, state, zone, SPs)
                ACT->>EP: set_actuator_value(heating_sp)
                ACT->>EP: set_actuator_value(cooling_sp)
                ACT->>EP: get_actuator_value(heating_handle)
                ACT->>EP: get_actuator_value(cooling_handle)
                ACT-->>CB: WriteResult (Success, Readback SPs)
            end
        end
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

## Controller Pipeline Architecture

The controller pipeline enforces a strict unidirectional control flow:

1. **Sensors** read zone temperatures and ambient environment conditions.
2. **Zone Controllers** evaluate zone temperatures against the fixed comfort band [21.5, 24.5]°C and propose setpoint shifts.
3. **Safety Guard** validates proposed commands against hard numerical bounds, minimum deadbands, and dwell times.
4. **Actuator Layer** issues C-API writes and performs immediate readback verification.
5. **Logger** records cycle metadata and zone telemetry to disk.

No component can bypass the Safety Guard to write directly to actuators.
