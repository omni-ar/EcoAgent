import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ecoagent.controller.constants import (
    COMFORT_TRIGGER_LOW, COMFORT_TRIGGER_HIGH,
    NORMAL_STEP, AGGRESSIVE_STEP,
    AGGRESSIVE_ENTRY_THRESHOLD, AGGRESSIVE_EXIT_THRESHOLD,
)
from ecoagent.controller.zone_state import ZoneState
from ecoagent.controller.zone_controller import ZoneController


def test_emergency_hysteresis():
    print("=" * 60)
    print("Test Suite: Magnitude-Scaled Step & Emergency Hysteresis")
    print("=" * 60)

    zc = ZoneController("SPACE1-1")

    # --- CASE A: Deviation = 1.5 C (<= 2.0 C) ---
    zs_a = ZoneState("SPACE1-1")
    zs_a.current_temperature = COMFORT_TRIGGER_LOW - 1.5  # 20.0 C
    zs_a.current_heating_setpoint = 22.0
    zs_a.current_cooling_setpoint = 24.0

    cmd_a = zc.evaluate(zs_a)
    deviation_a = COMFORT_TRIGGER_LOW - zs_a.current_temperature
    step_a = cmd_a.heating_setpoint - 22.0

    print(f"\n[Case A] Temp={zs_a.current_temperature:.1f} C, Dev={deviation_a:.1f} C")
    print(f"  Aggressive Mode: {zs_a.aggressive_mode} (Expected: False)")
    print(f"  Step Size: {step_a:.1f} C (Expected: {NORMAL_STEP:.1f} C)")

    assert not zs_a.aggressive_mode, "Case A Failed: aggressive_mode should be False"
    assert abs(step_a - NORMAL_STEP) < 0.001, f"Case A Failed: expected step {NORMAL_STEP}, got {step_a}"
    print("  => PASS: Case A Verified (0.5 C Normal Step)")

    # --- CASE B: Deviation = 2.5 C (> 2.0 C) ---
    zs_b = ZoneState("SPACE1-1")
    zs_b.current_temperature = COMFORT_TRIGGER_LOW - 2.5  # 19.0 C
    zs_b.current_heating_setpoint = 22.0
    zs_b.current_cooling_setpoint = 24.0

    cmd_b = zc.evaluate(zs_b)
    deviation_b = COMFORT_TRIGGER_LOW - zs_b.current_temperature
    step_b = cmd_b.heating_setpoint - 22.0

    print(f"\n[Case B] Temp={zs_b.current_temperature:.1f} C, Dev={deviation_b:.1f} C")
    print(f"  Aggressive Mode: {zs_b.aggressive_mode} (Expected: True)")
    print(f"  Step Size: {step_b:.1f} C (Expected: {AGGRESSIVE_STEP:.1f} C)")

    assert zs_b.aggressive_mode, "Case B Failed: aggressive_mode should be True"
    assert abs(step_b - AGGRESSIVE_STEP) < 0.001, f"Case B Failed: expected step {AGGRESSIVE_STEP}, got {step_b}"
    print("  => PASS: Case B Verified (1.0 C Aggressive Step)")

    # --- CASE C: Emergency Entered, Deviation drops to 1.8 C (between 1.5 C and 2.0 C) ---
    # Continuation from Case B state where aggressive_mode is True
    zs_c = zs_b
    zs_c.current_temperature = COMFORT_TRIGGER_LOW - 1.8  # 19.7 C
    zs_c.current_heating_setpoint = 22.0

    cmd_c = zc.evaluate(zs_c)
    deviation_c = COMFORT_TRIGGER_LOW - zs_c.current_temperature
    step_c = cmd_c.heating_setpoint - 22.0

    print(f"\n[Case C] Temp={zs_c.current_temperature:.1f} C, Dev={deviation_c:.1f} C (Hysteresis Band)")
    print(f"  Aggressive Mode: {zs_c.aggressive_mode} (Expected: True due to hysteresis)")
    print(f"  Step Size: {step_c:.1f} C (Expected: {AGGRESSIVE_STEP:.1f} C)")

    assert zs_c.aggressive_mode, "Case C Failed: aggressive_mode should REMAIN True (hysteresis)"
    assert abs(step_c - AGGRESSIVE_STEP) < 0.001, f"Case C Failed: expected step {AGGRESSIVE_STEP}, got {step_c}"
    print("  => PASS: Case C Verified (Hysteresis hold in Aggressive Mode)")

    # --- CASE D: Deviation drops below exit threshold (1.2 C < 1.5 C) ---
    zs_d = zs_c
    zs_d.current_temperature = COMFORT_TRIGGER_LOW - 1.2  # 20.3 C
    zs_d.current_heating_setpoint = 22.0

    cmd_d = zc.evaluate(zs_d)
    deviation_d = COMFORT_TRIGGER_LOW - zs_d.current_temperature
    step_d = cmd_d.heating_setpoint - 22.0

    print(f"\n[Case D] Temp={zs_d.current_temperature:.1f} C, Dev={deviation_d:.1f} C (< Exit Threshold 1.5 C)")
    print(f"  Aggressive Mode: {zs_d.aggressive_mode} (Expected: False after exit)")
    print(f"  Step Size: {step_d:.1f} C (Expected: {NORMAL_STEP:.1f} C)")

    assert not zs_d.aggressive_mode, "Case D Failed: aggressive_mode should exit to False"
    assert abs(step_d - NORMAL_STEP) < 0.001, f"Case D Failed: expected step {NORMAL_STEP}, got {step_d}"
    print("  => PASS: Case D Verified (Exited Aggressive Mode, returned to 0.5 C Normal Step)")

    print("\n" + "=" * 60)
    print("ALL 4 HYSTERESIS CASES PASSED SUCCESSFULLY")
    print("=" * 60)


if __name__ == "__main__":
    test_emergency_hysteresis()
