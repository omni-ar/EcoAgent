import sys
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ecoagent.controller.constants import (
    ZONE_NAMES, STATE_IDLE, STATE_HEATING, STATE_COOLING,
    HEATING_BOUND_MIN, HEATING_BOUND_MAX,
    COOLING_BOUND_MIN, COOLING_BOUND_MAX,
    READBACK_TOLERANCE, DWELL_CYCLES,
)
from ecoagent.controller.zone_state import create_zone_states
from ecoagent.controller.zone_controller import ZoneController, create_zone_controllers
from ecoagent.controller.safety_guard import validate_command
from ecoagent.supervisor.supervisor import SupervisorInterface, SetpointProposal
from ecoagent.supervisor.events import (
    EventBus, CycleCompleted,
    SupervisorProposalAccepted, SupervisorProposalModified,
    SupervisorProposalRejected,
)
from ecoagent.supervisor.history_buffer import HistoryBuffer
from ecoagent.supervisor.constants import STATE_SUPERVISOR
from ecoagent.controller.orchestrator import Orchestrator


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


class MockAPIExchange:
    def __init__(self):
        self._warmup = False
        self._month = 1
        self._day = 15
        self._hour = 12
        self._minute = 0
        self._actuator_values = {}
        self._variable_values = {}
        self._fail_readback = False

    def warmup_flag(self, state):
        return self._warmup

    def month(self, state):
        return self._month

    def day_of_month(self, state):
        return self._day

    def hour(self, state):
        return self._hour

    def minutes(self, state):
        return self._minute

    def get_actuator_handle(self, state, component_type, control_type, name):
        h = abs(hash((component_type, control_type, name))) % 10000 + 100
        return h

    def get_variable_handle(self, state, variable_name, key):
        h = abs(hash((variable_name, key))) % 10000 + 100
        return h

    def set_actuator_value(self, state, handle, value):
        self._actuator_values[handle] = value

    def get_actuator_value(self, state, handle):
        if self._fail_readback:
            return -999.0
        return self._actuator_values.get(handle, float("nan"))

    def get_variable_value(self, state, handle):
        return 22.0


class MockAPI:
    def __init__(self):
        self.exchange = MockAPIExchange()


print("=" * 60)
print("Phase 3 Integration Tests (Hardening Pass)")
print("=" * 60)

print("\n--- Test 1: Pre-Evaluate Supervisor Check Prevents Phantom Mutation ---")

zs_dict = create_zone_states()
zc_dict = create_zone_controllers()
si = SupervisorInterface()

zs = zs_dict["SPACE1-1"]
zc = zc_dict["SPACE1-1"]

zs.current_temperature = 19.0
zs.current_heating_setpoint = 22.0
zs.current_cooling_setpoint = 24.0
zs.aggressive_mode = False
zs.dwell_timer = 999

proposal = si.get_pending_proposal("SPACE1-1")
check(proposal is None, "no proposal when none submitted")

proposed = zc.evaluate(zs)
check(proposed.state == STATE_HEATING, "deterministic eval produces HEATING at 19.0C")
check(zs.aggressive_mode is True, "evaluate() mutated aggressive_mode to True")

zs.aggressive_mode = False

p = SetpointProposal("SPACE1-1", 20.0, 25.0, source="test")
si.submit_proposal(p)

proposal = si.get_pending_proposal("SPACE1-1")
check(proposal is not None, "supervisor proposal retrieved")
check(zs.aggressive_mode is False, "aggressive_mode remains False when zc.evaluate() is skipped")
si.consume_proposal("SPACE1-1")

print("\n--- Test 2: Three-Way Outcome — Accepted (Values Match) ---")

zs2 = create_zone_states()["SPACE2-1"]
zs2.current_temperature = 22.5
zs2.current_heating_setpoint = 21.0
zs2.current_cooling_setpoint = 24.0
zs2.dwell_timer = 999

proposed_h = 21.0
proposed_c = 24.0
validated = validate_command(zs2, proposed_h, proposed_c)
check(validated.approved is True, "safety guard approves in-bounds proposal")
check(validated.reason == "approved", f"reason is 'approved' ({validated.reason})")

h_match = abs(validated.heating_setpoint - proposed_h) < READBACK_TOLERANCE
c_match = abs(validated.cooling_setpoint - proposed_c) < READBACK_TOLERANCE
check(h_match and c_match, "validated values match proposed — ACCEPTED outcome")

print("\n--- Test 3: Three-Way Outcome — Modified by Bounds Clamping ---")

zs3 = create_zone_states()["SPACE3-1"]
zs3.current_temperature = 22.5
zs3.current_heating_setpoint = 22.0
zs3.current_cooling_setpoint = 24.0
zs3.dwell_timer = 999

proposed_h = 15.0
proposed_c = 30.0
validated = validate_command(zs3, proposed_h, proposed_c)
check(validated.approved is True, "safety guard approves (bounds-clamped)")
check(validated.heating_setpoint == HEATING_BOUND_MIN, f"heating clamped to {HEATING_BOUND_MIN}")
check(validated.cooling_setpoint == COOLING_BOUND_MAX, f"cooling clamped to {COOLING_BOUND_MAX}")

h_match = abs(validated.heating_setpoint - proposed_h) < READBACK_TOLERANCE
c_match = abs(validated.cooling_setpoint - proposed_c) < READBACK_TOLERANCE
check(not (h_match and c_match), "validated != proposed — MODIFIED outcome")

print("\n--- Test 4: Three-Way Outcome — Modified by Dwell Hold ---")

zs4 = create_zone_states()["SPACE4-1"]
zs4.current_temperature = 22.5
zs4.current_heating_setpoint = 22.0
zs4.current_cooling_setpoint = 24.0
zs4.dwell_timer = 0

proposed_h = 20.0
proposed_c = 25.0
validated = validate_command(zs4, proposed_h, proposed_c)
check(validated.approved is True, f"dwell_hold returns approved=True")
check(validated.reason == "dwell_hold", f"reason is 'dwell_hold'")
check(validated.heating_setpoint == 22.0, "dwell_hold reverts to current heating")
check(validated.cooling_setpoint == 24.0, "dwell_hold reverts to current cooling")

h_match = abs(validated.heating_setpoint - proposed_h) < READBACK_TOLERANCE
c_match = abs(validated.cooling_setpoint - proposed_c) < READBACK_TOLERANCE
check(not (h_match and c_match), "validated != proposed — MODIFIED (not falsely ACCEPTED)")

print("\n--- Test 5: Three-Way Outcome — Rejected (zone_degraded) ---")

zs7 = create_zone_states()["SPACE2-1"]
zs7.current_temperature = 22.5
zs7.degraded = True
zs7.controller_state = "DEGRADED"

proposed_h = 20.0
proposed_c = 25.0
validated = validate_command(zs7, proposed_h, proposed_c)
check(validated.approved is False, "zone_degraded returns approved=False")
check(validated.reason == "zone_degraded", f"reason is zone_degraded ({validated.reason})")

print("\n--- Test 6: Full Orchestrator Integration — Readback Failure Rejection ---")

si_mock = SupervisorInterface()
orch_mock = Orchestrator(supervisor=si_mock)
mock_api = MockAPI()
mock_state = "mock_state"

orch_mock._execute_cycle(mock_api, mock_state)
orch_mock._execute_cycle(mock_api, mock_state)
check(orch_mock.scheduler.simulation_status == "RUNNING", "orchestrator handles resolved, status RUNNING")

p_rf = SetpointProposal("SPACE1-1", 20.0, 25.0, source="test")
si_mock.submit_proposal(p_rf)

mock_api.exchange._fail_readback = True

rejected_events = []
orch_mock.event_bus.subscribe(SupervisorProposalRejected, lambda e: rejected_events.append(e))

orch_mock._execute_cycle(mock_api, mock_state)

check(len(rejected_events) == 1, "SupervisorProposalRejected event emitted on readback failure")
check(rejected_events[0].reason == "readback_failure", "rejection reason is readback_failure")
check(si_mock.get_pending_proposal("SPACE1-1") is None, "proposal consumed after readback failure")

print("\n--- Test 7: Expiry during Scheduler DISABLED State ---")

si_dis = SupervisorInterface()
orch_dis = Orchestrator(supervisor=si_dis)
mock_api_dis = MockAPI()

orch_dis.scheduler.simulation_status = "DISABLED"
p_dis = SetpointProposal("SPACE1-1", 20.0, 25.0, source="test", ttl_cycles=2)
si_dis.submit_proposal(p_dis, current_callback=0)

check(p_dis.status == "PENDING", "proposal is PENDING")

orch_dis._execute_cycle(mock_api_dis, "state") # cb counter = 1, diff = 1 < 2
check(p_dis.status == "PENDING", "survives tick 1 (diff 1 < ttl 2)")

orch_dis._execute_cycle(mock_api_dis, "state") # cb counter = 2, diff = 2 >= 2
check(p_dis.status == "EXPIRED", "expired at tick 2 while DISABLED")
check(si_dis.get_pending_proposal("SPACE1-1") is None, "expired proposal cannot be retrieved")

print("\n--- Test 8: Expiry after TTL — Never Executes ---")

si_exp = SupervisorInterface()
orch_exp = Orchestrator(supervisor=si_exp)
mock_api_exp = MockAPI()

orch_exp._execute_cycle(mock_api_exp, "state")

p_exp = SetpointProposal("SPACE1-1", 20.0, 25.0, source="test", ttl_cycles=1)
si_exp.submit_proposal(p_exp, current_callback=orch_exp.scheduler.callback_counter)

orch_exp._execute_cycle(mock_api_exp, "state")
orch_exp._execute_cycle(mock_api_exp, "state")

check(p_exp.status == "EXPIRED", "proposal expired before execution")

executed_proposals = []
orch_exp.event_bus.subscribe(SupervisorProposalAccepted, lambda e: executed_proposals.append(e))

orch_exp._execute_cycle(mock_api_exp, "state")
check(len(executed_proposals) == 0, "expired proposal never executed")


print("\n" + "=" * 60)
print(f"Results: {passed} PASS, {failed} FAIL out of {passed + failed} assertions")
print("=" * 60)

if failed > 0:
    sys.exit(1)
