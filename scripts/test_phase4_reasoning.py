"""Phase 4 Unit Tests — AgentLoop._run_reasoning() coverage.

Run: python scripts/test_phase4_reasoning.py

Tests the LLM reasoning path using a mock OpenAI client injection.
Covers single-turn, multi-turn ReAct, max turn limit, malformed args, and trace logging.
"""

import sys
import json
import queue
import threading
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ecoagent.supervisor.runtime_snapshot import RuntimeSnapshot, ZoneSnapshot
from ecoagent.supervisor.history_buffer import HistoryBuffer
from ecoagent.supervisor.events import EventBus
from ecoagent.supervisor.supervisor import SupervisorInterface
from ecoagent.supervisor.tools import ToolRegistry
from ecoagent.controller.constants import STATE_IDLE, ZONE_NAMES
from ecoagent.mcp.adapter import McpAdapter
from ecoagent.mcp.server import McpToolDispatcher
from ecoagent.agent.trace_logger import AgentTraceLogger
from ecoagent.agent.loop import AgentLoop

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


# ── Mocks ────────────────────────────────────────────────────────

class MockChoice:
    def __init__(self, message, finish_reason="stop"):
        self.message = message
        self.finish_reason = finish_reason

class MockUsage:
    def __init__(self, prompt=10, completion=20, total=30):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = total

class MockMessage:
    def __init__(self, content, tool_calls):
        self.content = content
        self.tool_calls = tool_calls

class MockResponse:
    def __init__(self, content="", tool_calls=None, finish_reason="stop"):
        self.choices = [MockChoice(MockMessage(content, tool_calls), finish_reason)]
        self.usage = MockUsage()

class MockToolCall:
    def __init__(self, name, arguments, tc_id=None):
        self.id = tc_id or f"call_{name}"
        class MockFunction:
            def __init__(self, n, a):
                self.name = n
                self.arguments = a
        self.function = MockFunction(name, arguments)

class MockOpenAIClient:
    def __init__(self, responses, exceptions=None):
        self.chat = self.Chat(responses, exceptions)

    class Chat:
        def __init__(self, responses, exceptions):
            self.completions = self.Completions(responses, exceptions)

        class Completions:
            def __init__(self, responses, exceptions):
                self.responses = list(responses)
                self.exceptions = exceptions or []
                self.call_count = 0
                self.created_kwargs = []

            def create(self, **kwargs):
                self.created_kwargs.append(kwargs)
                if self.call_count < len(self.exceptions) and self.exceptions[self.call_count]:
                    ex = self.exceptions[self.call_count]
                    self.call_count += 1
                    raise ex
                resp = self.responses[min(self.call_count, len(self.responses) - 1)]
                self.call_count += 1
                return resp


# ── Test Helpers ─────────────────────────────────────────────────

def make_wired_stack():
    history = HistoryBuffer(max_size=96)
    supervisor = SupervisorInterface()
    event_bus = EventBus()
    registry = ToolRegistry(history, supervisor, event_bus, history.latest)
    adapter = McpAdapter(registry)
    dispatcher = McpToolDispatcher(adapter)
    return adapter, dispatcher, history, supervisor, event_bus


def make_snapshot(callback=1):
    zones = {n: ZoneSnapshot(n, 22.0, 22.0, 24.0, STATE_IDLE, False, 4, False, False, "approved", 22.0, 24.0, 22.0, 24.0, True, True) for n in ZONE_NAMES}
    return RuntimeSnapshot(callback, (1, 1, 0, 15), "RUNNING", 20.0, 0.0, zones)


# ══════════════════════════════════════════════════════════════════
print("=" * 60)
print("Phase 4 Unit Tests: _run_reasoning() with ReAct Loop")
print("=" * 60)

tmp_dir = tempfile.mkdtemp()
try:

    # ── Test 1: Direct proposal (single turn) ────────────────────
    print("\n--- Test: Direct proposal in single turn ---")
    adapter, dispatcher, history, supervisor, _ = make_wired_stack()
    history.append(make_snapshot(100))
    trace_logger = AgentTraceLogger(output_dir=f"{tmp_dir}/t1", run_id="t1")
    loop = AgentLoop(adapter, trace_logger, queue.Queue(), threading.Event(), {"model": "test"}, dispatcher)

    mock_resp = MockResponse(
        content="Setting heating.",
        tool_calls=[MockToolCall("propose_setpoint", '{"zone_name": "SPACE1-1", "heating": 21.0, "cooling": 25.0}')],
        finish_reason="tool_calls",
    )
    mock_client = MockOpenAIClient([mock_resp])
    loop._get_client = lambda: mock_client
    loop._run_reasoning(make_snapshot(100))

    check(mock_client.chat.completions.call_count == 1, "LLM called once (direct proposal)")
    pending = supervisor.get_pending_proposal("SPACE1-1")
    check(pending is not None, "Proposal submitted to supervisor")
    check(pending.heating_setpoint == 21.0, "Heating setpoint correct")
    check("SPACE1-1" in loop.current_policy, "Policy contains zone")
    check(loop.current_policy["SPACE1-1"] == (21.0, 25.0), "Policy values correct")
    trace_logger.close()


    # ── Test 2: Multi-turn observe → act ─────────────────────────
    print("\n--- Test: Multi-turn observe -> act (ReAct) ---")
    adapter2, dispatcher2, history2, supervisor2, _ = make_wired_stack()
    history2.append(make_snapshot(200))
    trace_logger2 = AgentTraceLogger(output_dir=f"{tmp_dir}/t2", run_id="t2")
    loop2 = AgentLoop(adapter2, trace_logger2, queue.Queue(), threading.Event(), {"model": "test"}, dispatcher2)

    # Turn 0: LLM calls get_building_summary
    turn0_resp = MockResponse(
        content="",
        tool_calls=[MockToolCall("get_building_summary", "{}", tc_id="call_0")],
        finish_reason="tool_calls",
    )
    # Turn 1: LLM proposes setpoint after seeing summary
    turn1_resp = MockResponse(
        content="Zone is cold, adjusting.",
        tool_calls=[MockToolCall("propose_setpoint", '{"zone_name": "SPACE1-1", "heating": 21.5, "cooling": 25.5}', tc_id="call_1")],
        finish_reason="tool_calls",
    )
    mock_client2 = MockOpenAIClient([turn0_resp, turn1_resp])
    loop2._get_client = lambda: mock_client2
    loop2._run_reasoning(make_snapshot(200))

    check(mock_client2.chat.completions.call_count == 2, "LLM called twice (observe then act)")
    pending2 = supervisor2.get_pending_proposal("SPACE1-1")
    check(pending2 is not None, "Proposal submitted after multi-turn")
    check(pending2.heating_setpoint == 21.5, "Multi-turn heating correct")
    check("SPACE1-1" in loop2.current_policy, "Policy updated from multi-turn")
    check(loop2.current_policy["SPACE1-1"] == (21.5, 25.5), "Multi-turn policy values correct")

    # Verify trace has turn info
    with open(trace_logger2.log_path) as f:
        trace2 = json.loads(f.readline())
    check(trace2["turn_count"] == 2, "Trace records 2 turns")
    check(len(trace2["turns"]) == 2, "Turns array has 2 entries")
    check(trace2["turns"][0]["tool_calls"][0]["name"] == "get_building_summary", "Turn 0 tool = get_building_summary")
    check(trace2["turns"][1]["tool_calls"][0]["name"] == "propose_setpoint", "Turn 1 tool = propose_setpoint")
    check(trace2["proposal_submitted"] is True, "Trace shows proposal_submitted=true")

    # Verify messages grew (tool results were fed back)
    second_call_kwargs = mock_client2.chat.completions.created_kwargs[1]
    msgs = second_call_kwargs["messages"]
    check(any(m.get("role") == "tool" for m in msgs), "Tool result message fed back to LLM")
    check(any(m.get("role") == "assistant" and "tool_calls" in m for m in msgs), "Assistant message with tool_calls appended")
    trace_logger2.close()


    # ── Test 3: No tool call (observation only) ──────────────────
    print("\n--- Test: No tool call (terminal on first turn) ---")
    adapter3, dispatcher3, history3, supervisor3, _ = make_wired_stack()
    history3.append(make_snapshot(300))
    trace_logger3 = AgentTraceLogger(output_dir=f"{tmp_dir}/t3", run_id="t3")
    loop3 = AgentLoop(adapter3, trace_logger3, queue.Queue(), threading.Event(), {"model": "test"}, dispatcher3)

    no_tool_resp = MockResponse(content="All zones are comfortable. No action needed.", tool_calls=None, finish_reason="stop")
    mock_client3 = MockOpenAIClient([no_tool_resp])
    loop3._get_client = lambda: mock_client3
    loop3._run_reasoning(make_snapshot(300))

    check(mock_client3.chat.completions.call_count == 1, "LLM called once (no tools)")
    check(loop3.current_policy == {}, "Policy stays empty (no tool calls)")
    with open(trace_logger3.log_path) as f:
        trace3 = json.loads(f.readline())
    check(trace3["turn_count"] == 1, "Single turn recorded")
    check(trace3["proposal_submitted"] is False, "No proposal submitted")
    trace_logger3.close()


    # ── Test 4: Max turn limit ───────────────────────────────────
    print("\n--- Test: Max turn limit enforcement ---")
    adapter4, dispatcher4, history4, supervisor4, _ = make_wired_stack()
    history4.append(make_snapshot(400))
    trace_logger4 = AgentTraceLogger(output_dir=f"{tmp_dir}/t4", run_id="t4")
    loop4 = AgentLoop(adapter4, trace_logger4, queue.Queue(), threading.Event(), {"model": "test", "max_turns": 2}, dispatcher4)

    # All turns return get_building_summary (never proposes)
    obs_resp = MockResponse(
        content="",
        tool_calls=[MockToolCall("get_building_summary", "{}")],
        finish_reason="tool_calls",
    )
    mock_client4 = MockOpenAIClient([obs_resp, obs_resp, obs_resp, obs_resp])
    loop4._get_client = lambda: mock_client4
    loop4._run_reasoning(make_snapshot(400))

    check(mock_client4.chat.completions.call_count == 2, "LLM stopped at max_turns=2")
    check(loop4.current_policy == {}, "Policy empty (never proposed)")
    with open(trace_logger4.log_path) as f:
        trace4 = json.loads(f.readline())
    check(trace4["turn_count"] == 2, "2 turns recorded")
    check(trace4["proposal_submitted"] is False, "No proposal")
    trace_logger4.close()


    # ── Test 5: Timeout & Retry ──────────────────────────────────
    print("\n--- Test: Timeout & Retry ---")
    adapter5, dispatcher5, history5, supervisor5, _ = make_wired_stack()
    history5.append(make_snapshot(500))
    trace_logger5 = AgentTraceLogger(output_dir=f"{tmp_dir}/t5", run_id="t5")
    loop5 = AgentLoop(adapter5, trace_logger5, queue.Queue(), threading.Event(), {"model": "test"}, dispatcher5)

    class TestTimeout(Exception): pass
    mock_resp5 = MockResponse(content="Success on retry", tool_calls=[])
    mock_client5 = MockOpenAIClient([mock_resp5], exceptions=[TestTimeout("timeout error"), None])
    loop5._get_client = lambda: mock_client5

    loop5._run_reasoning(make_snapshot(500))
    check(mock_client5.chat.completions.call_count == 2, "LLM retried exactly once")

    with open(trace_logger5.log_path, "r") as f:
        last_trace = json.loads(f.readlines()[-1])
    check(last_trace["error"] is None, "No error logged when retry succeeds")
    trace_logger5.close()


    # ── Test 6: Total Failure (Double Exception) ─────────────────
    print("\n--- Test: Total Failure (Double Exception) ---")
    adapter6, dispatcher6, history6, supervisor6, _ = make_wired_stack()
    history6.append(make_snapshot(600))
    trace_logger6 = AgentTraceLogger(output_dir=f"{tmp_dir}/t6", run_id="t6")
    loop6 = AgentLoop(adapter6, trace_logger6, queue.Queue(), threading.Event(), {"model": "test"}, dispatcher6)
    loop6.current_policy = {"SPACE1-1": (21.0, 25.0)}

    mock_client6 = MockOpenAIClient([], exceptions=[TestTimeout("err1"), TestTimeout("err2")])
    loop6._get_client = lambda: mock_client6

    loop6._run_reasoning(make_snapshot(600))
    check(mock_client6.chat.completions.call_count == 2, "LLM attempted twice")

    with open(trace_logger6.log_path, "r") as f:
        last_trace6 = json.loads(f.readlines()[-1])
    check("llm_timeout: err2" in last_trace6["error"], "Error is logged in trace")
    check("SPACE1-1" in loop6.current_policy, "Policy is RETAINED on failure")
    trace_logger6.close()


    # ── Test 7: Malformed arguments (not JSON) ───────────────────
    print("\n--- Test: Malformed arguments (not JSON) ---")
    adapter7, dispatcher7, history7, supervisor7, _ = make_wired_stack()
    history7.append(make_snapshot(700))
    trace_logger7 = AgentTraceLogger(output_dir=f"{tmp_dir}/t7", run_id="t7")
    loop7 = AgentLoop(adapter7, trace_logger7, queue.Queue(), threading.Event(), {"model": "test"}, dispatcher7)

    mock_resp_malformed = MockResponse(
        tool_calls=[MockToolCall("propose_setpoint", "not json")],
        finish_reason="tool_calls",
    )
    mock_client7 = MockOpenAIClient([mock_resp_malformed])
    loop7._get_client = lambda: mock_client7

    loop7._run_reasoning(make_snapshot(700))
    with open(trace_logger7.log_path, "r") as f:
        last_trace7 = json.loads(f.readlines()[-1])
    tr = last_trace7["tool_results"][0]
    check(tr["args"] == {}, "Arguments fall back to empty dict")
    check(tr["result"]["error"] == "invalid_arguments", "Dispatcher rejected empty dict")
    trace_logger7.close()


    # ── Test 8: Malformed arguments (JSON array) ─────────────────
    print("\n--- Test: Malformed arguments (JSON array) ---")
    adapter8, dispatcher8, history8, supervisor8, _ = make_wired_stack()
    history8.append(make_snapshot(800))
    trace_logger8 = AgentTraceLogger(output_dir=f"{tmp_dir}/t8", run_id="t8")
    loop8 = AgentLoop(adapter8, trace_logger8, queue.Queue(), threading.Event(), {"model": "test"}, dispatcher8)

    mock_resp_array = MockResponse(
        tool_calls=[MockToolCall("propose_setpoint", "[1, 2, 3]")],
        finish_reason="tool_calls",
    )
    mock_client8 = MockOpenAIClient([mock_resp_array])
    loop8._get_client = lambda: mock_client8

    loop8._run_reasoning(make_snapshot(800))
    with open(trace_logger8.log_path, "r") as f:
        last_trace8 = json.loads(f.readlines()[-1])
    tr8 = last_trace8["tool_results"][0]
    check(tr8["args"] == [1, 2, 3], "Arguments parsed as array")
    check(tr8["result"]["error"] == "invalid_arguments", "Dispatcher rejected array safely")
    trace_logger8.close()


    # ── Test 9: Policy release (observe but don't propose) ───────
    print("\n--- Test: Policy release (observe but don't propose) ---")
    adapter9, dispatcher9, history9, supervisor9, _ = make_wired_stack()
    history9.append(make_snapshot(900))
    trace_logger9 = AgentTraceLogger(output_dir=f"{tmp_dir}/t9", run_id="t9")
    loop9 = AgentLoop(adapter9, trace_logger9, queue.Queue(), threading.Event(), {"model": "test"}, dispatcher9)
    loop9.current_policy = {"SPACE1-1": (21.0, 25.0)}
    check("SPACE1-1" in loop9.current_policy, "Setup check: SPACE1-1 is in policy")

    # LLM observes then says "no action needed"
    obs_resp9 = MockResponse(
        content="",
        tool_calls=[MockToolCall("get_building_summary", "{}")],
        finish_reason="tool_calls",
    )
    final_resp9 = MockResponse(content="Everything is fine.", tool_calls=None, finish_reason="stop")
    mock_client9 = MockOpenAIClient([obs_resp9, final_resp9])
    loop9._get_client = lambda: mock_client9

    loop9._run_reasoning(make_snapshot(900))
    check("SPACE1-1" not in loop9.current_policy, "Policy replaced/released")

    with open(trace_logger9.log_path, "r") as f:
        last_trace9 = json.loads(f.readlines()[-1])
    check("SPACE1-1" in last_trace9["policy_state"]["released_zones"], "Zone marked as released in trace")
    check(last_trace9["turn_count"] == 2, "2 turns: observe then stop")
    trace_logger9.close()


    # ── Test 10: Multiple sequential tool calls in one turn ──────
    print("\n--- Test: Multiple tool calls in one LLM response ---")
    adapter10, dispatcher10, history10, supervisor10, _ = make_wired_stack()
    history10.append(make_snapshot(1000))
    trace_logger10 = AgentTraceLogger(output_dir=f"{tmp_dir}/t10", run_id="t10")
    loop10 = AgentLoop(adapter10, trace_logger10, queue.Queue(), threading.Event(), {"model": "test"}, dispatcher10)

    multi_tc_resp = MockResponse(
        content="Adjusting two zones.",
        tool_calls=[
            MockToolCall("propose_setpoint", '{"zone_name": "SPACE1-1", "heating": 20.0, "cooling": 26.0}', tc_id="c1"),
            MockToolCall("propose_setpoint", '{"zone_name": "SPACE2-1", "heating": 20.5, "cooling": 25.5}', tc_id="c2"),
        ],
        finish_reason="tool_calls",
    )
    mock_client10 = MockOpenAIClient([multi_tc_resp])
    loop10._get_client = lambda: mock_client10
    loop10._run_reasoning(make_snapshot(1000))

    check(mock_client10.chat.completions.call_count == 1, "LLM called once (parallel proposals)")
    check("SPACE1-1" in loop10.current_policy, "SPACE1-1 in policy")
    check("SPACE2-1" in loop10.current_policy, "SPACE2-1 in policy")
    check(loop10.current_policy["SPACE1-1"] == (20.0, 26.0), "SPACE1-1 values correct")
    check(loop10.current_policy["SPACE2-1"] == (20.5, 25.5), "SPACE2-1 values correct")
    p1 = supervisor10.get_pending_proposal("SPACE1-1")
    p2 = supervisor10.get_pending_proposal("SPACE2-1")
    check(p1 is not None, "SPACE1-1 proposal in supervisor")
    check(p2 is not None, "SPACE2-1 proposal in supervisor")
    trace_logger10.close()


    # ── Test 11: Repeated observation before acting ──────────────
    print("\n--- Test: Repeated observation before acting ---")
    adapter11, dispatcher11, history11, supervisor11, _ = make_wired_stack()
    history11.append(make_snapshot(1100))
    trace_logger11 = AgentTraceLogger(output_dir=f"{tmp_dir}/t11", run_id="t11")
    loop11 = AgentLoop(adapter11, trace_logger11, queue.Queue(), threading.Event(), {"model": "test", "max_turns": 4}, dispatcher11)

    # Turn 0: get_building_summary
    # Turn 1: get_zone (repeated observation)
    # Turn 2: propose_setpoint (finally acts)
    r0 = MockResponse(content="", tool_calls=[MockToolCall("get_building_summary", "{}", tc_id="c0")], finish_reason="tool_calls")
    r1 = MockResponse(content="", tool_calls=[MockToolCall("get_zone", '{"zone_name": "SPACE1-1"}', tc_id="c1")], finish_reason="tool_calls")
    r2 = MockResponse(content="Acting now.", tool_calls=[MockToolCall("propose_setpoint", '{"zone_name": "SPACE1-1", "heating": 21.0, "cooling": 24.5}', tc_id="c2")], finish_reason="tool_calls")
    mock_client11 = MockOpenAIClient([r0, r1, r2])
    loop11._get_client = lambda: mock_client11
    loop11._run_reasoning(make_snapshot(1100))

    check(mock_client11.chat.completions.call_count == 3, "LLM called 3 times (2 observe + 1 act)")
    check("SPACE1-1" in loop11.current_policy, "Policy updated")
    check(loop11.current_policy["SPACE1-1"] == (21.0, 24.5), "Policy values correct")

    with open(trace_logger11.log_path) as f:
        trace11 = json.loads(f.readline())
    check(trace11["turn_count"] == 3, "3 turns recorded in trace")
    check(trace11["proposal_submitted"] is True, "Proposal submitted in trace")
    trace_logger11.close()


    # ── Test 12: Trace logging across turns ──────────────────────
    print("\n--- Test: Trace logging completeness across turns ---")
    adapter12, dispatcher12, history12, supervisor12, _ = make_wired_stack()
    history12.append(make_snapshot(1200))
    trace_logger12 = AgentTraceLogger(output_dir=f"{tmp_dir}/t12", run_id="t12")
    loop12 = AgentLoop(adapter12, trace_logger12, queue.Queue(), threading.Event(), {"model": "test"}, dispatcher12)

    r0_12 = MockResponse(content="", tool_calls=[MockToolCall("get_building_summary", "{}", tc_id="c0")], finish_reason="tool_calls")
    r1_12 = MockResponse(content="Done.", tool_calls=[MockToolCall("propose_setpoint", '{"zone_name": "SPACE3-1", "heating": 19.0, "cooling": 26.0}', tc_id="c1")], finish_reason="tool_calls")
    mock_client12 = MockOpenAIClient([r0_12, r1_12])
    loop12._get_client = lambda: mock_client12
    loop12._run_reasoning(make_snapshot(1200))

    with open(trace_logger12.log_path) as f:
        trace12 = json.loads(f.readline())

    # Verify all required trace fields exist
    check("run_id" in trace12, "Trace has run_id")
    check("cycle_callback" in trace12, "Trace has cycle_callback")
    check("simulated_timestamp" in trace12, "Trace has simulated_timestamp")
    check("wall_clock_iso" in trace12, "Trace has wall_clock_iso")
    check("system_prompt_hash" in trace12, "Trace has system_prompt_hash")
    check("llm_request" in trace12, "Trace has llm_request")
    check("llm_response" in trace12, "Trace has llm_response")
    check("tool_results" in trace12, "Trace has tool_results")
    check("turns" in trace12, "Trace has turns array")
    check("turn_count" in trace12, "Trace has turn_count")
    check("proposal_submitted" in trace12, "Trace has proposal_submitted")
    check("policy_state" in trace12, "Trace has policy_state")
    check("metrics" in trace12, "Trace has metrics")
    check("error" in trace12, "Trace has error field")
    check(trace12["metrics"]["prompt_tokens"] == 20, "Tokens accumulated across 2 turns (10+10)")
    check(trace12["metrics"]["completion_tokens"] == 40, "Completion tokens accumulated (20+20)")
    check(len(trace12["tool_results"]) == 2, "2 total tool results across turns")
    trace_logger12.close()


finally:
    shutil.rmtree(tmp_dir, ignore_errors=True)

# ══════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print(f"Reasoning Unit Tests: {passed} passed, {failed} failed")
print("=" * 60)

if failed > 0:
    sys.exit(1)
