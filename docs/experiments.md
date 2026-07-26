# Runtime Experiments & Empirical Findings

## Overview

Prior to freezing Phase 2 implementation, empirical runtime experiments were conducted on `data/5ZoneAirCooled.idf` and `pyenergyplus.api` to validate C-API behavior, actuator responsiveness, handle lifecycle, and out-of-bounds failure modes.

---

## Experiment 1: Actuator Write Immediacy & Persistence

### Hypothesis
Actuator writes via `api.exchange.set_actuator_value()` take effect immediately within the current timestep and persist across subsequent timesteps.

### Test Setup
Inside `callback_begin_system_timestep_before_predictor`:
1. Read actuator value before write (`get_actuator_value`).
2. Issue write command (`set_actuator_value`).
3. Read actuator value in same callback (`get_actuator_value`).
4. Read actuator value in next timestep callback before write.

### Empirical Results

```text
Step 1: Written=23.0°C | Actuator Before=0.0°C  | Actuator After=23.0°C | Zone Temp=16.95°C
Step 2: Written=24.0°C | Actuator Before=23.0°C | Actuator After=24.0°C | Zone Temp=16.95°C
Step 3: Written=25.0°C | Actuator Before=24.0°C | Actuator After=25.0°C | Zone Temp=16.99°C
```

### Conclusions
- Setpoint memory updates occur **immediately** within the same callback.
- Setpoint values **persist** across subsequent timesteps until explicitly overwritten.

---

## Experiment 2: Out-Of-Bounds Actuator Behavior

### Hypothesis
EnergyPlus C-API does not validate setpoint bounds, delegating enforcement to the Python application.

### Test Setup
1. Step 4: Write extreme high setpoint (`999.0°C`).
2. Step 5: Write extreme low setpoint (`-100.0°C`) violating setpoint deadband (`Heating Setpoint > Cooling Setpoint`).

### Empirical Results
- **Step 4 (`999.0°C`)**: C-API accepted `999.0°C` write without raising a Python exception. Readback confirmed `999.0°C`.
- **Step 5 (`-100.0°C`)**: Upon entering HVAC predictor evaluation, EnergyPlus detected a deadband violation:
  ```text
  ** Severe  ** DualSetPointWithDeadBand: Effective heating set-point higher than effective cooling set-point
  ** FATAL: Program terminates due to above conditions.
  EnergyPlus Return Code: 1
  ```

### Conclusions
- The C-API does not reject physical bound violations at the function call boundary.
- Deadband violations cause fatal EnergyPlus termination (`returncode = 1`).
- Mandatory Safety Guard validation is required to protect EnergyPlus runtime stability.

---

## Experiment 3: Plant Capacity & Chiller Readout Timing

### Hypothesis
`Chiller Electricity Rate` reads `0.0 W` at `callback_begin_system_timestep_before_predictor` because plant loop iteration occurs after the predictor callback.

### Test Setup
Compared `Chiller Electricity Rate` reads across two API callback insertion points during summer months (June–August):
- Insertion Point A: `callback_begin_system_timestep_before_predictor`
- Insertion Point B: `callback_end_system_timestep_after_hvac_reporting`

### Empirical Results
- **Insertion Point A (Before Predictor)**: Non-zero reads = `3,640 / 8,832`.
- **Insertion Point B (After HVAC Reporting)**: Non-zero reads = `5,056 / 11,711` (Active power readings: 728.0 W, 683.7 W, 652.4 W).

### Conclusions
- Plant rate variables are updated during/after HVAC loop resolution.
- Telemetry collected at `before_predictor` reflects pre-HVAC state for the current timestep. See [docs/telemetry.md](file:///c:/Users/arjit/Desktop/EcoAgent/docs/telemetry.md).
