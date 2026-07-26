import sys
import json
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ecoagent.supervisor.runtime_snapshot import RuntimeSnapshot, ZoneSnapshot, create_snapshot
from ecoagent.supervisor.history_buffer import HistoryBuffer
from ecoagent.supervisor.events import (
    EventBus, CycleCompleted, SafetyTriggered,
    SupervisorProposalAccepted, SupervisorProposalModified,
    SupervisorProposalRejected,
)
from ecoagent.supervisor.supervisor import SupervisorInterface, SetpointProposal
from ecoagent.supervisor.analytics import (
    compute_comfort_percentage, compute_safety_summary,
    compute_oscillation_count, compute_full_summary,
)
from ecoagent.supervisor.constants import STATE_SUPERVISOR
from ecoagent.supervisor.tools import ToolRegistry
from ecoagent.controller.constants import (
    STATE_IDLE, STATE_HEATING, STATE_COOLING, ZONE_NAMES,
)


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


def make_snapshot(callback=1, status="RUNNING", outdoor=20.0, chiller=0.0, zones=None):
    if zones is None:
        zones = {name: make_zone_snapshot(name) for name in ZONE_NAMES}
    return RuntimeSnapshot(
        callback_number=callback,
        simulated_timestamp=(1, 1, 0, 15),
        scheduler_status=status,
        outdoor_temp_c=outdoor,
        chiller_power_w=chiller,
        zones=zones,
    )


print("=" * 60)
print("Phase 3 Unit Tests (Hardening Pass)")
print("=" * 60)

print("\n--- ZoneSnapshot ---")
zs = make_zone_snapshot("SPACE1-1", temp=21.0, state=STATE_HEATING)
d = zs.to_dict()
check(d["zone_name"] == "SPACE1-1", "zone_name field")
check(d["temperature_c"] == 21.0, "temperature_c field")
check(d["controller_state"] == STATE_HEATING, "controller_state field")
check(d["actuator_written"] is True, "actuator_written field")
check(isinstance(json.dumps(d), str), "to_dict is JSON-serializable")

print("\n--- RuntimeSnapshot ---")
snap = make_snapshot(callback=42, outdoor=5.0, chiller=1200.0)
d = snap.to_dict()
check(d["callback_number"] == 42, "callback_number field")
check(d["outdoor_temp_c"] == 5.0, "outdoor_temp_c field")
check(d["chiller_power_w"] == 1200.0, "chiller_power_w field")
check("SPACE1-1" in d["zones"], "zones dict contains SPACE1-1")
check(d["simulated_timestamp"]["month"] == 1, "simulated_timestamp month")
check(isinstance(json.dumps(d, default=str), str), "full snapshot JSON-serializable")

print("\n--- HistoryBuffer ---")
hb = HistoryBuffer(max_size=3)
check(hb.size() == 0, "empty buffer size is 0")
check(hb.latest() is None, "empty buffer latest is None")
check(hb.get(0) is None, "empty buffer get(0) is None")
check(hb.capacity() == 3, "capacity matches max_size")

s1 = make_snapshot(callback=1)
s2 = make_snapshot(callback=2)
s3 = make_snapshot(callback=3)
s4 = make_snapshot(callback=4)

hb.append(s1)
hb.append(s2)
hb.append(s3)
check(hb.size() == 3, "size is 3 after 3 appends")
check(hb.latest().callback_number == 3, "latest is most recent")
check(hb.get(0).callback_number == 3, "get(0) is most recent")
check(hb.get(1).callback_number == 2, "get(1) is second most recent")
check(hb.get(2).callback_number == 1, "get(2) is oldest")
check(hb.get(3) is None, "get(3) out of range returns None")

hb.append(s4)
check(hb.size() == 3, "size stays 3 after eviction")
check(hb.latest().callback_number == 4, "latest is 4 after eviction")
check(hb.get(2).callback_number == 2, "oldest is 2 after eviction (1 evicted)")

r = hb.get_range(0, 2)
check(len(r) == 2, "get_range(0,2) returns 2 entries")
check(r[0].callback_number == 4, "get_range[0] is most recent")
check(r[1].callback_number == 3, "get_range[1] is second most recent")

hb.clear()
check(hb.size() == 0, "clear empties buffer")

print("\n--- EventBus & Observability ---")
eb = EventBus()
received = []
eb.subscribe(CycleCompleted, lambda e: received.append(e))
snap = make_snapshot(callback=10)
eb.emit(CycleCompleted(snap))
check(len(received) == 1, "listener receives emitted event")
check(received[0].snapshot.callback_number == 10, "event payload correct")

received2 = []
eb.subscribe(SafetyTriggered, lambda e: received2.append(e))
eb.emit(SafetyTriggered("SPACE1-1", "critical_clamp_cold", 5))
check(len(received2) == 1, "safety event received")
check(len(received) == 1, "cycle listener not triggered by safety event")

crash_count = [0]
def crashing_listener(e):
    crash_count[0] += 1
    raise RuntimeError("simulated_listener_crash")

safe_count = [0]
def safe_listener(e):
    safe_count[0] += 1

eb2 = EventBus()
eb2.subscribe(CycleCompleted, crashing_listener)
eb2.subscribe(CycleCompleted, safe_listener)
eb2.emit(CycleCompleted(make_snapshot()))

check(crash_count[0] == 1, "crashing listener was executed")
check(safe_count[0] == 1, "remaining listener executed despite prior crash")
check(eb2.listener_error_count == 1, "listener_error_count incremented to 1")
check(eb2.last_listener_error is not None, "last_listener_error is populated")
check(eb2.last_listener_error["listener"] == "crashing_listener", "last_listener_error captures listener name")
check(eb2.last_listener_error["error_message"] == "simulated_listener_crash", "last_listener_error captures message")

eb2.clear()
check(eb2.listener_error_count == 0, "clear resets error counter")
check(eb2.last_listener_error is None, "clear resets last error")

print("\n--- SupervisorInterface & TTL Lifecycle ---")
si = SupervisorInterface()

p1 = SetpointProposal("SPACE1-1", 20.0, 25.0, source="test", ttl_cycles=1)
check(si.submit_proposal(p1, current_callback=10) is True, "proposal submitted at cb 10")
check(p1.status == "PENDING", "proposal status is PENDING")
check(p1.submitted_at_callback == 10, "submitted_at_callback stamped with 10")

si.clear_expired(10)
check(si.get_pending_proposal("SPACE1-1") is not None, "proposal survives at cb 10 (diff = 0 < 1)")

si2 = SupervisorInterface()
p2 = SetpointProposal("SPACE1-1", 20.0, 25.0, source="test", ttl_cycles=1)
si2.submit_proposal(p2, current_callback=10)
si2.clear_expired(11)
check(si2.get_pending_proposal("SPACE1-1") is None, "proposal EXPIRED at cb 11 (diff = 1 >= 1)")
check(p2.status == "EXPIRED", "proposal status is EXPIRED")

si3 = SupervisorInterface()
p3 = SetpointProposal("SPACE1-1", 20.0, 25.0, source="test", ttl_cycles=2)
si3.submit_proposal(p3, current_callback=10)
si3.clear_expired(11)
check("SPACE1-1" in si3.get_all_pending(), "ttl_cycles=2 survives at cb 11 (diff = 1 < 2)")
si3.clear_expired(12)
check("SPACE1-1" not in si3.get_all_pending(), "ttl_cycles=2 EXPIRED at cb 12 (diff = 2 >= 2)")
check(p3.status == "EXPIRED", "status updated to EXPIRED")

si4 = SupervisorInterface()
p_async = SetpointProposal("SPACE1-1", 20.0, 25.0, source="async", ttl_cycles=1)
si4.submit_proposal(p_async)
check(p_async.submitted_at_callback == -1, "async proposal initialized with -1")
si4.clear_expired(5)
check(p_async.submitted_at_callback == 5, "clear_expired stamped -1 proposal with current cb 5")
check(si4.get_pending_proposal("SPACE1-1") is not None, "survives cb 5")
si4.clear_expired(6)
check(si4.get_pending_proposal("SPACE1-1") is None, "expires at cb 6")

si5 = SupervisorInterface()
p_m1 = SetpointProposal("SPACE1-1", 20.0, 25.0)
p_m2 = SetpointProposal("SPACE2-1", 19.0, 26.0)
si5.submit_proposal(p_m1)
si5.submit_proposal(p_m2)
pending_map = si5.get_all_pending()
check(len(pending_map) == 2, "multiple pending proposals tracked simultaneously")
check("SPACE1-1" in pending_map and "SPACE2-1" in pending_map, "both zones present in pending map")

print("\n--- Analytics ---")
hb_a = HistoryBuffer(max_size=10)

for i in range(5):
    hb_a.append(make_snapshot(callback=i + 1))
check(compute_comfort_percentage(hb_a) == 100.0, "100% comfort when all zones IDLE")

zones_mixed = {name: make_zone_snapshot(name) for name in ZONE_NAMES}
zones_mixed["SPACE1-1"] = make_zone_snapshot("SPACE1-1", state=STATE_HEATING, reason="critical_clamp_cold")
hb_a.append(make_snapshot(callback=6, zones=zones_mixed))
pct = compute_comfort_percentage(hb_a)
check(pct < 100.0, f"comfort < 100% with heating zone ({pct:.1f}%)")

safety = compute_safety_summary(hb_a)
check(safety.get("critical_clamp_cold", 0) == 1, "safety summary counts critical_clamp_cold")

zones_sup = {name: make_zone_snapshot(name) for name in ZONE_NAMES}
zones_sup["SPACE3-1"] = make_zone_snapshot("SPACE3-1", state=STATE_SUPERVISOR)
hb_a.append(make_snapshot(callback=7, zones=zones_sup))
pct2 = compute_comfort_percentage(hb_a)
check(pct2 == compute_comfort_percentage(hb_a), "SUPERVISOR cycles excluded from comfort calc")

print("\n--- ToolRegistry ---")
hb_t = HistoryBuffer()
si_t = SupervisorInterface()
eb_t = EventBus()
snap_t = [None]

def get_snap():
    return snap_t[0]

tr = ToolRegistry(hb_t, si_t, eb_t, get_snap)
r = tr.get_runtime_state()
check("error" in r, "no_data error when no snapshot exists")

snap_t[0] = make_snapshot(callback=100, outdoor=30.0)
hb_t.append(snap_t[0])
r = tr.get_runtime_state()
check(r["callback_number"] == 100, "get_runtime_state returns current snapshot")

r = tr.propose_setpoint("SPACE1-1", 20.0, 25.0, source="test_tool")
check(r["status"] == "pending", "propose_setpoint returns pending")

tools = tr.list_tools()
check(len(tools) == 6, f"list_tools returns 6 tools ({len(tools)})")

print("\n" + "=" * 60)
print(f"Results: {passed} PASS, {failed} FAIL out of {passed + failed} assertions")
print("=" * 60)

if failed > 0:
    sys.exit(1)
