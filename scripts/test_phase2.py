import sys
import json
import math
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ecoagent.simulation.energyplus import EnergyPlusRunner
from ecoagent.controller.orchestrator import Orchestrator
from ecoagent.controller.constants import (
    ZONE_NAMES, HEATING_BOUND_MIN, HEATING_BOUND_MAX,
    COOLING_BOUND_MIN, COOLING_BOUND_MAX, MIN_DEADBAND,
    COMFORT_TRIGGER_LOW, COMFORT_TRIGGER_HIGH, DWELL_CYCLES,
)
from ecoagent.controller.zone_state import ZoneState
from ecoagent.controller.zone_controller import ZoneController
from ecoagent.controller.safety_guard import validate_command

import yaml

results = []


def record(test_name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((test_name, status, detail))
    print(f"  [{status}] {test_name}" + (f" -- {detail}" if detail else ""))


def load_config():
    config_path = Path(__file__).resolve().parent.parent / "config" / "default.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def test_1_annual_simulation():
    print("\n=== TEST 1: Annual Simulation ===")
    config = load_config()
    runner = EnergyPlusRunner(config)
    orchestrator = Orchestrator(log_dir="logs/test_output/test1")

    result = runner.run(callback_fn=orchestrator.create_callback())
    orchestrator.finalize()
    summary = orchestrator.get_summary()

    record("Annual simulation return code 0", result["returncode"] == 0, f"got {result['returncode']}")
    record("Annual simulation success", result["success"])
    record("Total callbacks = 35040", summary["total_callbacks"] == 35040, f"got {summary['total_callbacks']}")
    record("Final status RUNNING", summary["final_status"] == "RUNNING", f"got {summary['final_status']}")
    record("All 5 zones not degraded",
           all(not z["degraded"] for z in summary["zones"].values()),
           str({n: z["degraded"] for n, z in summary["zones"].items()}))

    return orchestrator


def test_2_warmup_verification(orchestrator):
    print("\n=== TEST 2: Warmup Verification ===")
    log_path = Path(orchestrator.logger.log_path)
    lines = log_path.read_text().strip().split("\n")

    warmup_actions = 0
    for line in lines:
        entry = json.loads(line)
        if entry.get("warmup", False):
            warmup_actions += 1

    record("Zero warmup controller actions", warmup_actions == 0, f"got {warmup_actions}")
    record("First callback is non-warmup",
           json.loads(lines[0]).get("warmup") == False)


def test_3_actuator_verification(orchestrator):
    print("\n=== TEST 3: Actuator Verification ===")
    log_path = Path(orchestrator.logger.log_path)
    lines = log_path.read_text().strip().split("\n")

    total_writes = 0
    total_verified = 0
    for line in lines:
        entry = json.loads(line)
        if "zones" not in entry:
            continue
        for z in entry["zones"]:
            if z.get("actuator_written"):
                total_writes += 1
            if z.get("readback_verified"):
                total_verified += 1

    record("All writes have readback verification",
           total_writes == total_verified,
           f"writes={total_writes}, verified={total_verified}")
    record("Non-zero actuator writes", total_writes > 0, f"got {total_writes}")


def test_4_degraded_zone():
    print("\n=== TEST 4: Degraded Zone Isolation ===")
    config = load_config()
    runner = EnergyPlusRunner(config)
    orchestrator = Orchestrator(log_dir="logs/test_output/test4")

    orchestrator.zone_states["SPACE3-1"].mark_degraded(reason="test_forced_degradation")

    result = runner.run(callback_fn=orchestrator.create_callback())
    orchestrator.finalize()
    summary = orchestrator.get_summary()

    record("Simulation completes with degraded zone", result["success"])
    record("SPACE3-1 is degraded", summary["zones"]["SPACE3-1"]["degraded"])
    record("Other 4 zones not degraded",
           all(not summary["zones"][n]["degraded"] for n in ZONE_NAMES if n != "SPACE3-1"))

    log_path = Path(orchestrator.logger.log_path)
    lines = log_path.read_text().strip().split("\n")
    space3_writes = 0
    other_writes = 0
    for line in lines:
        entry = json.loads(line)
        if "zones" not in entry:
            continue
        for z in entry["zones"]:
            if z.get("actuator_written"):
                if z["zone_name"] == "SPACE3-1":
                    space3_writes += 1
                else:
                    other_writes += 1

    record("Zero writes to degraded SPACE3-1", space3_writes == 0, f"got {space3_writes}")
    record("Other zones received writes", other_writes > 0, f"got {other_writes}")


def test_5_safety_bounds():
    print("\n=== TEST 5: Safety Bounds Enforcement ===")

    zs = ZoneState("TEST-ZONE")

    zs.current_temperature = 20.0
    zs.dwell_timer = DWELL_CYCLES + 1
    v = validate_command(zs, 15.0, 30.0)
    record("Heating clamped to [18, 22]",
           HEATING_BOUND_MIN <= v.heating_setpoint <= HEATING_BOUND_MAX,
           f"got {v.heating_setpoint}")
    record("Cooling clamped to [23, 27]",
           COOLING_BOUND_MIN <= v.cooling_setpoint <= COOLING_BOUND_MAX,
           f"got {v.cooling_setpoint}")
    record("Deadband >= 1.0",
           v.cooling_setpoint - v.heating_setpoint >= MIN_DEADBAND,
           f"gap={v.cooling_setpoint - v.heating_setpoint}")

    zs.current_temperature = 22.5
    zs.dwell_timer = DWELL_CYCLES + 1
    v2 = validate_command(zs, 22.5, 23.0)
    record("Near-violation deadband enforcement",
           v2.cooling_setpoint - v2.heating_setpoint >= MIN_DEADBAND,
           f"h={v2.heating_setpoint}, c={v2.cooling_setpoint}, gap={v2.cooling_setpoint - v2.heating_setpoint}")


def test_6_comfort_band():
    print("\n=== TEST 6: Fixed Comfort Band Transitions ===")

    zc = ZoneController("TEST-ZONE")

    zs_cold = ZoneState("TEST-ZONE")
    zs_cold.current_temperature = 20.0
    proposed = zc.evaluate(zs_cold)
    record("Temp 20.0 -> HEATING", proposed.state == "HEATING", f"got {proposed.state}")

    zs_hot = ZoneState("TEST-ZONE")
    zs_hot.current_temperature = 26.0
    proposed = zc.evaluate(zs_hot)
    record("Temp 26.0 -> COOLING", proposed.state == "COOLING", f"got {proposed.state}")

    zs_ok = ZoneState("TEST-ZONE")
    zs_ok.current_temperature = 23.0
    proposed = zc.evaluate(zs_ok)
    record("Temp 23.0 -> IDLE", proposed.state == "IDLE", f"got {proposed.state}")

    zs_boundary_low = ZoneState("TEST-ZONE")
    zs_boundary_low.current_temperature = COMFORT_TRIGGER_LOW
    proposed = zc.evaluate(zs_boundary_low)
    record("Temp at 21.5 boundary -> IDLE", proposed.state == "IDLE", f"got {proposed.state}")

    zs_boundary_high = ZoneState("TEST-ZONE")
    zs_boundary_high.current_temperature = COMFORT_TRIGGER_HIGH
    proposed = zc.evaluate(zs_boundary_high)
    record("Temp at 24.5 boundary -> IDLE", proposed.state == "IDLE", f"got {proposed.state}")

    zs_just_below = ZoneState("TEST-ZONE")
    zs_just_below.current_temperature = 21.49
    proposed = zc.evaluate(zs_just_below)
    record("Temp 21.49 -> HEATING", proposed.state == "HEATING", f"got {proposed.state}")

    zs_just_above = ZoneState("TEST-ZONE")
    zs_just_above.current_temperature = 24.51
    proposed = zc.evaluate(zs_just_above)
    record("Temp 24.51 -> COOLING", proposed.state == "COOLING", f"got {proposed.state}")


def test_7_exception_resilience():
    print("\n=== TEST 7: Exception Resilience ===")
    config = load_config()
    runner = EnergyPlusRunner(config)
    orchestrator = Orchestrator(log_dir="logs/test_output/test7")

    original_evaluate = orchestrator.zone_controllers["SPACE1-1"].evaluate
    call_count = [0]

    def exploding_evaluate(zone_state):
        call_count[0] += 1
        if call_count[0] == 5:
            raise RuntimeError("TEST FORCED EXCEPTION")
        return original_evaluate(zone_state)

    orchestrator.zone_controllers["SPACE1-1"].evaluate = exploding_evaluate

    result = runner.run(callback_fn=orchestrator.create_callback())
    orchestrator.finalize()

    record("Simulation survives controller exception", result["success"],
           f"returncode={result['returncode']}")

    log_path = Path(orchestrator.logger.log_path)
    log_text = log_path.read_text()
    has_exception_log = "controller_exception" in log_text
    record("Exception logged in controller.jsonl", has_exception_log)


def test_8_dwell_bypass_critical():
    print("\n=== TEST 8: Critical Clamp Bypasses Dwell Timer ===")

    zs = ZoneState("TEST-ZONE")
    zs.current_temperature = 15.0
    zs.dwell_timer = 0
    zs.current_heating_setpoint = 20.0
    zs.current_cooling_setpoint = 25.0

    v = validate_command(zs, 20.0, 25.0)
    record("Critical cold clamp fires despite dwell_timer=0",
           v.reason == "critical_clamp_cold",
           f"reason={v.reason}, h={v.heating_setpoint}, c={v.cooling_setpoint}")
    record("Critical cold sets heating to max",
           v.heating_setpoint == HEATING_BOUND_MAX,
           f"got {v.heating_setpoint}")

    zs2 = ZoneState("TEST-ZONE")
    zs2.current_temperature = 30.0
    zs2.dwell_timer = 0
    zs2.current_heating_setpoint = 20.0
    zs2.current_cooling_setpoint = 25.0

    v2 = validate_command(zs2, 20.0, 25.0)
    record("Critical hot clamp fires despite dwell_timer=0",
           v2.reason == "critical_clamp_hot",
           f"reason={v2.reason}, h={v2.heating_setpoint}, c={v2.cooling_setpoint}")
    record("Critical hot sets cooling to min",
           v2.cooling_setpoint == COOLING_BOUND_MIN,
           f"got {v2.cooling_setpoint}")

    zs3 = ZoneState("TEST-ZONE")
    zs3.current_temperature = 22.0
    zs3.dwell_timer = 0
    zs3.current_heating_setpoint = 20.0
    zs3.current_cooling_setpoint = 25.0

    v3 = validate_command(zs3, 21.0, 25.0)
    record("Normal change blocked by dwell_timer=0",
           v3.reason == "dwell_hold",
           f"reason={v3.reason}")


def main():
    print("=" * 60)
    print("EcoAgent Phase 2 Integration Tests")
    print("=" * 60)

    test_5_safety_bounds()
    test_6_comfort_band()
    test_8_dwell_bypass_critical()

    orch = test_1_annual_simulation()
    test_2_warmup_verification(orch)
    test_3_actuator_verification(orch)

    test_4_degraded_zone()
    test_7_exception_resilience()

    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")

    for name, status, detail in results:
        line = f"  [{status}] {name}"
        if detail and status == "FAIL":
            line += f" -- {detail}"
        print(line)

    print(f"\n  Total: {len(results)} | Passed: {passed} | Failed: {failed}")

    output_path = Path("logs/phase2_test_results.txt")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write("EcoAgent Phase 2 Integration Test Results\n")
        f.write("=" * 50 + "\n\n")
        for name, status, detail in results:
            f.write(f"[{status}] {name}")
            if detail:
                f.write(f" -- {detail}")
            f.write("\n")
        f.write(f"\nTotal: {len(results)} | Passed: {passed} | Failed: {failed}\n")

    print(f"\n  Results written to: {output_path}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
