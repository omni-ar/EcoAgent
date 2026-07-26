"""Phase 4 Unit Tests — AgentLoop._run_reasoning() coverage.

Run: python scripts/test_phase4_reasoning.py

Tests the LLM reasoning path using a mock OpenAI client injection.
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

class MockResponse:
    def __init__(self, content="", tool_calls=None, finish_reason="stop"):
        class MockMessage:
            def __init__(self, c, tc):
                self.content = c
                self.tool_calls = tc
        self.choices = [MockChoice(MockMessage(content, tool_calls), finish_reason)]
        self.usage = MockUsage()

class MockToolCall:
    def __init__(self, name, arguments):
        class MockFunction:
            def __init__(self, n, a):
                self.name = n
                self.arguments = a
        self.function = MockFunction(name, arguments)

class MockOpenAIClient:
    def __init__(self, responses, exceptions=None):
        self.chat = self.Chat(responses, exceptions)
        self.created_kwargs = []

    class Chat:
        def __init__(self, responses, exceptions):
            self.completions = self.Completions(responses, exceptions)

        class Completions:
            def __init__(self, responses, exceptions):
                self.responses = responses
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
print("Phase 4 Unit Tests: _run_reasoning()")
print("=" * 60)

tmp_dir = tempfile.mkdtemp()
try:
    adapter, dispatcher, history, supervisor, _ = make_wired_stack()
    history.append(make_snapshot(100))

    trace_logger = AgentTraceLogger(output_dir=f"{tmp_dir}/agent", run_id="test_reasoning")
    loop = AgentLoop(adapter, trace_logger, queue.Queue(), threading.Event(), {"model": "test"}, dispatcher)

    print("\n--- Test: Successful Response with Tool Call ---")
    mock_resp = MockResponse(
        content="I will update setpoints.",
        tool_calls=[MockToolCall("propose_setpoint", '{"zone_name": "SPACE1-1", "heating": 21.0, "cooling": 25.0}')]
    )
    mock_client = MockOpenAIClient([mock_resp])
    loop._get_client = lambda: mock_client
    loop._run_reasoning(make_snapshot(100))

    check(mock_client.chat.completions.call_count == 1, "LLM called exactly once")
    kwargs = mock_client.chat.completions.created_kwargs[0]
    check(kwargs["timeout"] == 30, "timeout=30 is passed to create()")
    
    pending = supervisor.get_pending_proposal("SPACE1-1")
    check(pending is not None, "Tool executed and proposal submitted")
    check(pending.heating_setpoint == 21.0, "Heating setpoint correct")
    check("SPACE1-1" in loop.current_policy, "Policy replaced with new zone")
    check(loop.current_policy["SPACE1-1"] == (21.0, 25.0), "Policy contains correct values")


    print("\n--- Test: Timeout & Retry ---")
    supervisor.consume_proposal("SPACE1-1")
    class TestTimeout(Exception): pass
    mock_resp2 = MockResponse(content="Success on retry", tool_calls=[])
    mock_client2 = MockOpenAIClient([mock_resp2], exceptions=[TestTimeout("timeout error"), None])
    loop._get_client = lambda: mock_client2
    
    loop._run_reasoning(make_snapshot(101))
    check(mock_client2.chat.completions.call_count == 2, "LLM retried exactly once")
    
    # Read trace to verify error isn't logged if retry succeeds
    with open(trace_logger.log_path, "r") as f:
        lines = f.readlines()
    last_trace = json.loads(lines[-1])
    check(last_trace["error"] is None, "No error logged when retry succeeds")


    print("\n--- Test: Total Failure (Double Exception) ---")
    mock_client3 = MockOpenAIClient([], exceptions=[TestTimeout("err1"), TestTimeout("err2")])
    loop._get_client = lambda: mock_client3
    
    loop._run_reasoning(make_snapshot(102))
    check(mock_client3.chat.completions.call_count == 2, "LLM attempted twice")
    
    with open(trace_logger.log_path, "r") as f:
        last_trace = json.loads(f.readlines()[-1])
    check("llm_timeout: err2" in last_trace["error"], "Error is logged in trace")
    check("SPACE1-1" in loop.current_policy, "Policy is RETAINED on failure")


    print("\n--- Test: Malformed arguments (not JSON) ---")
    mock_resp_malformed = MockResponse(
        tool_calls=[MockToolCall("propose_setpoint", "not json")]
    )
    mock_client4 = MockOpenAIClient([mock_resp_malformed])
    loop._get_client = lambda: mock_client4
    
    loop._run_reasoning(make_snapshot(103))
    with open(trace_logger.log_path, "r") as f:
        last_trace = json.loads(f.readlines()[-1])
    tr = last_trace["tool_results"][0]
    check(tr["args"] == {}, "Arguments fall back to empty dict")
    check(tr["result"]["error"] == "invalid_arguments", "Dispatcher rejected empty dict")


    print("\n--- Test: Malformed arguments (JSON array) ---")
    mock_resp_array = MockResponse(
        tool_calls=[MockToolCall("propose_setpoint", "[1, 2, 3]")]
    )
    mock_client5 = MockOpenAIClient([mock_resp_array])
    loop._get_client = lambda: mock_client5
    
    loop._run_reasoning(make_snapshot(104))
    with open(trace_logger.log_path, "r") as f:
        last_trace = json.loads(f.readlines()[-1])
    tr = last_trace["tool_results"][0]
    check(tr["args"] == [1, 2, 3], "Arguments parsed as array")
    check(tr["result"]["error"] == "invalid_arguments", "Dispatcher rejected array safely")


    print("\n--- Test: Empty tool list (Policy release) ---")
    # Restore policy state that was cleared by previous test
    loop.current_policy = {"SPACE1-1": (21.0, 25.0)}
    check("SPACE1-1" in loop.current_policy, "Setup check: SPACE1-1 is in policy")
    
    # LLM calls get_building_summary but no propose_setpoint
    mock_resp_empty = MockResponse(
        tool_calls=[MockToolCall("get_building_summary", "{}")]
    )
    mock_client6 = MockOpenAIClient([mock_resp_empty])
    loop._get_client = lambda: mock_client6
    
    loop._run_reasoning(make_snapshot(105))
    check("SPACE1-1" not in loop.current_policy, "Policy replaced/released")
    
    with open(trace_logger.log_path, "r") as f:
        last_trace = json.loads(f.readlines()[-1])
    check("SPACE1-1" in last_trace["policy_state"]["released_zones"], "Zone marked as released in trace")


finally:
    trace_logger.close()
    shutil.rmtree(tmp_dir, ignore_errors=True)

# ══════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print(f"Reasoning Unit Tests: {passed} passed, {failed} failed")
print("=" * 60)

if failed > 0:
    sys.exit(1)
