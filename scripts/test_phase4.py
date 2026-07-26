"""Phase 4 Unit Tests — McpAdapter and AgentTraceLogger.

Run: python scripts/test_phase4.py
"""

import sys
import json
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ecoagent.supervisor.runtime_snapshot import RuntimeSnapshot, ZoneSnapshot
from ecoagent.supervisor.history_buffer import HistoryBuffer
from ecoagent.supervisor.events import EventBus, CycleCompleted
from ecoagent.supervisor.supervisor import SupervisorInterface
from ecoagent.supervisor.tools import ToolRegistry
from ecoagent.controller.constants import (
    STATE_IDLE, STATE_HEATING, STATE_COOLING, ZONE_NAMES,
)

from ecoagent.mcp.adapter import McpAdapter
from ecoagent.agent.trace_logger import AgentTraceLogger


passed = 0
failed = 0


def check(condition, label):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


# ── Test Helpers ─────────────────────────────────────────────────

def make_zone_snapshot(zone_name, temp=22.0, h_sp=22.0, c_sp=24.0,
                       state=STATE_IDLE, aggressive=False, dwell=4,
                       sat=False, degraded=False, reason="approved",
                       prop_h=22.0, prop_c=24.0, val_h=22.0, val_c=24.0,
                       written=True, readback=True):
    return ZoneSnapshot(
        zone_name=zone_name, temperature_c=temp,
        heating_setpoint=h_sp, cooling_setpoint=c_sp,
        controller_state=state, aggressive_mode=aggressive,
        dwell_timer=dwell, saturation_flag=sat, degraded=degraded,
        safety_guard_reason=reason,
        proposed_heating=prop_h, proposed_cooling=prop_c,
        validated_heating=val_h, validated_cooling=val_c,
        actuator_written=written, readback_verified=readback,
    )


def make_snapshot(callback=1, status="RUNNING", outdoor=20.0, chiller=0.0,
                  month=1, day=1, hour=0, minute=15, zones=None):
    if zones is None:
        zones = {name: make_zone_snapshot(name) for name in ZONE_NAMES}
    return RuntimeSnapshot(
        callback_number=callback,
        simulated_timestamp=(month, day, hour, minute),
        scheduler_status=status,
        outdoor_temp_c=outdoor,
        chiller_power_w=chiller,
        zones=zones,
    )


def make_wired_adapter(history_size=96):
    """Create a fully wired McpAdapter with ToolRegistry, buffer, supervisor."""
    history = HistoryBuffer(max_size=history_size)
    supervisor = SupervisorInterface()
    event_bus = EventBus()
    registry = ToolRegistry(history, supervisor, event_bus, history.latest)
    adapter = McpAdapter(registry)
    return adapter, history, supervisor, event_bus


# ══════════════════════════════════════════════════════════════════
print("=" * 60)
print("Phase 4 Unit Tests")
print("=" * 60)

# ── McpAdapter Passthrough Tests ─────────────────────────────────

print("\n--- McpAdapter: get_runtime_state passthrough ---")
adapter, history, _, _ = make_wired_adapter()
result = adapter.get_runtime_state()
check("error" in result, "returns error when buffer empty")
check(result["error"] == "no_data", "error type is no_data")

snap = make_snapshot(callback=42, outdoor=5.0, chiller=1200.0)
history.append(snap)
result = adapter.get_runtime_state()
check(result["callback_number"] == 42, "callback_number matches")
check(result["outdoor_temp_c"] == 5.0, "outdoor_temp_c matches")
check("SPACE1-1" in result["zones"], "zones contain SPACE1-1")


print("\n--- McpAdapter: get_zone passthrough ---")
result = adapter.get_zone("SPACE1-1")
check(result["zone_name"] == "SPACE1-1", "zone_name matches")
check(result["temperature_c"] == 22.0, "temperature_c matches")

result = adapter.get_zone("INVALID_ZONE")
check("error" in result, "returns error for invalid zone")
check(result["error"] == "unknown_zone", "error type is unknown_zone")


print("\n--- McpAdapter: get_scheduler_status passthrough ---")
result = adapter.get_scheduler_status()
check(result["status"] == "RUNNING", "status matches")
check(result["callback_number"] == 42, "callback_number matches")
check(result["simulated_timestamp"]["month"] == 1, "month matches")


print("\n--- McpAdapter: get_history passthrough ---")
snap2 = make_snapshot(callback=43, outdoor=6.0, chiller=1300.0)
history.append(snap2)
result = adapter.get_history(0, 2)
check(isinstance(result, list), "returns list")
check(len(result) == 2, "returns 2 snapshots")
check(result[0]["callback_number"] == 43, "first is most recent (43)")
check(result[1]["callback_number"] == 42, "second is older (42)")


print("\n--- McpAdapter: get_analytics_summary passthrough ---")
result = adapter.get_analytics_summary()
check("comfort_percentage" in result, "has comfort_percentage")
check("safety_triggers" in result, "has safety_triggers")
check("energy" in result, "has energy")
check("history_window_size" in result, "has history_window_size")
check(result["history_window_size"] == 2, "window_size is 2")


print("\n--- McpAdapter: propose_setpoint passthrough ---")
adapter2, history2, supervisor2, _ = make_wired_adapter()
history2.append(make_snapshot(callback=1))

result = adapter2.propose_setpoint("SPACE1-1", 21.0, 25.0, source="test")
check(result.get("status") == "pending", "proposal accepted")
check(result.get("zone") == "SPACE1-1", "zone matches")

pending = supervisor2.get_pending_proposal("SPACE1-1")
check(pending is not None, "proposal retrievable from supervisor")
check(pending.heating_setpoint == 21.0, "heating matches")
check(pending.cooling_setpoint == 25.0, "cooling matches")
check(pending.source == "test", "source matches")

result = adapter2.propose_setpoint("INVALID", 21.0, 25.0)
check("error" in result, "returns error for invalid zone")


# ── McpAdapter Composite Tool Tests ──────────────────────────────

print("\n--- McpAdapter: get_zone_trend ---")
adapter3, history3, _, _ = make_wired_adapter()

# Empty buffer
result = adapter3.get_zone_trend("SPACE1-1", 4)
check("error" in result, "returns error on empty buffer")

# Populate buffer with 4 snapshots
for i in range(4):
    zones = {name: make_zone_snapshot(name, temp=20.0 + i) for name in ZONE_NAMES}
    history3.append(make_snapshot(callback=100 + i, outdoor=10.0 + i, zones=zones))

result = adapter3.get_zone_trend("SPACE1-1", 4)
check(result["zone_name"] == "SPACE1-1", "zone_name in result")
check(result["window"] == 4, "window in result")
check(result["callback_number"] == 103, "callback_number is latest")
check(len(result["data_points"]) == 4, "4 data points returned")
check(result["data_points"][0]["temperature_c"] == 23.0, "first point temp is latest (23.0)")
check(result["data_points"][0]["outdoor_temp_c"] == 13.0, "first point outdoor is latest")

# Invalid zone
result = adapter3.get_zone_trend("INVALID", 4)
check("error" in result, "returns error for invalid zone name")
check(result["error"] == "unknown_zone", "error type is unknown_zone")

# Invalid window
result = adapter3.get_zone_trend("SPACE1-1", 0)
check("error" in result, "returns error for window=0")
result = adapter3.get_zone_trend("SPACE1-1", 97)
check("error" in result, "returns error for window=97")


print("\n--- McpAdapter: get_building_summary ---")
result = adapter3.get_building_summary()
check("callback_number" in result, "has callback_number")
check(result["callback_number"] == 103, "callback_number is latest")
check("scheduler" in result, "has scheduler")
check("zones" in result, "has zones")
check("analytics" in result, "has analytics")
check("outdoor_temp_c" in result, "has outdoor_temp_c")
check("chiller_power_w" in result, "has chiller_power_w")
check(result["scheduler"]["status"] == "RUNNING", "scheduler status correct")
check("SPACE1-1" in result["zones"], "zones has SPACE1-1")
check("comfort_percentage" in result["analytics"], "analytics has comfort_percentage")

# Empty buffer
adapter_empty, _, _, _ = make_wired_adapter()
result = adapter_empty.get_building_summary()
check("error" in result, "returns error on empty buffer")


print("\n--- McpAdapter: get_building_summary error propagation ---")
adapter_err, history_err, _, _ = make_wired_adapter()
result = adapter_err.get_building_summary()
check(result["error"] == "composition_failed", "error type is composition_failed")
check("detail" in result, "contains detail sub-dict")


print("\n--- McpAdapter: list_tools ---")
result = adapter3.list_tools()
check(isinstance(result, list), "returns list")
check(len(result) == 8, "8 tools total")
names = [t["name"] for t in result]
check("get_runtime_state" in names, "has get_runtime_state")
check("get_zone" in names, "has get_zone")
check("get_zone_trend" in names, "has get_zone_trend")
check("get_building_summary" in names, "has get_building_summary")
check("propose_setpoint" in names, "has propose_setpoint")


# ── AgentTraceLogger Tests ───────────────────────────────────────

print("\n--- AgentTraceLogger: basic write ---")
tmp_dir = tempfile.mkdtemp()
try:
    logger = AgentTraceLogger(output_dir=f"{tmp_dir}/agent", run_id="test_run_001")
    check(logger.log_path.exists(), "trace file created")
    check(logger.run_id == "test_run_001", "run_id stored correctly")
    check(logger.log_path.name == "trace.jsonl", "filename is trace.jsonl")

    entry1 = {
        "run_id": "test_run_001",
        "cycle_callback": 100,
        "policy_state": {
            "policy_version": 1,
            "active_zones": {"SPACE1-1": {"heating": 21.0, "cooling": 25.0}},
            "released_zones": {},
        },
        "error": None,
    }
    entry2 = {
        "run_id": "test_run_001",
        "cycle_callback": 116,
        "policy_state": {
            "policy_version": 2,
            "active_zones": {},
            "released_zones": {"SPACE1-1": {"release_reason": "zone_not_proposed"}},
        },
        "error": None,
    }
    logger.log_cycle(entry1)
    logger.log_cycle(entry2)
    logger.close()

    # Re-read and verify
    with open(logger.log_path, "r") as f:
        lines = f.readlines()
    check(len(lines) == 2, "2 lines written")

    parsed1 = json.loads(lines[0])
    check(parsed1["run_id"] == "test_run_001", "entry1 run_id matches")
    check(parsed1["cycle_callback"] == 100, "entry1 callback matches")
    check(parsed1["policy_state"]["policy_version"] == 1, "entry1 policy_version is 1")
    check("SPACE1-1" in parsed1["policy_state"]["active_zones"], "entry1 has active zone")

    parsed2 = json.loads(lines[1])
    check(parsed2["policy_state"]["policy_version"] == 2, "entry2 policy_version is 2")
    check("SPACE1-1" in parsed2["policy_state"]["released_zones"], "entry2 has released zone")


    print("\n--- AgentTraceLogger: directory creation ---")
    nested_dir = f"{tmp_dir}/deep/nested/path"
    logger2 = AgentTraceLogger(output_dir=nested_dir, run_id="test_run_002")
    check(Path(nested_dir).exists(), "nested directory created")
    logger2.log_cycle({"test": True})
    logger2.close()
    with open(logger2.log_path, "r") as f:
        check(json.loads(f.readline())["test"] is True, "nested write succeeds")


    print("\n--- AgentTraceLogger: close idempotency ---")
    logger3 = AgentTraceLogger(output_dir=f"{tmp_dir}/idem", run_id="test_run_003")
    logger3.close()
    logger3.close()  # should not raise
    check(True, "double close does not raise")

finally:
    shutil.rmtree(tmp_dir, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print(f"Phase 4 Unit Tests: {passed} passed, {failed} failed")
print("=" * 60)

if failed > 0:
    sys.exit(1)
