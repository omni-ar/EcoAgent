"""Phase 4 Integration Tests — ContextBuilder, AgentLoop, McpToolDispatcher.

Run: python scripts/test_phase4_integration.py

Tests the agent pipeline WITHOUT a real LLM. Uses mock objects to verify
drift-gated resubmission, policy lifecycle, and MCP dispatch.
"""

import sys
import json
import queue
import threading
import tempfile
import shutil
import time
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
from ecoagent.mcp.server import McpToolDispatcher
from ecoagent.agent.context import ContextBuilder
from ecoagent.agent.trace_logger import AgentTraceLogger
from ecoagent.agent.loop import AgentLoop, DRIFT_THRESHOLD
from ecoagent.agent import prompts


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
                       state=STATE_IDLE):
    return ZoneSnapshot(
        zone_name=zone_name, temperature_c=temp,
        heating_setpoint=h_sp, cooling_setpoint=c_sp,
        controller_state=state, aggressive_mode=False,
        dwell_timer=4, saturation_flag=False, degraded=False,
        safety_guard_reason="approved",
        proposed_heating=h_sp, proposed_cooling=c_sp,
        validated_heating=h_sp, validated_cooling=c_sp,
        actuator_written=True, readback_verified=True,
    )


def make_snapshot(callback=1, outdoor=20.0, chiller=0.0,
                  zone_temps=None, zone_states=None, zone_h=None, zone_c=None):
    zones = {}
    for i, name in enumerate(ZONE_NAMES):
        t = zone_temps[i] if zone_temps else 22.0
        s = zone_states[i] if zone_states else STATE_IDLE
        h = zone_h[i] if zone_h else 22.0
        c = zone_c[i] if zone_c else 24.0
        zones[name] = make_zone_snapshot(name, temp=t, h_sp=h, c_sp=c, state=s)
    return RuntimeSnapshot(
        callback_number=callback,
        simulated_timestamp=(1, 1, 0, 15),
        scheduler_status="RUNNING",
        outdoor_temp_c=outdoor,
        chiller_power_w=chiller,
        zones=zones,
    )


def make_wired_stack(history_size=96):
    """Create a fully wired Phase 4 stack without LLM."""
    history = HistoryBuffer(max_size=history_size)
    supervisor = SupervisorInterface()
    event_bus = EventBus()
    registry = ToolRegistry(history, supervisor, event_bus, history.latest)
    adapter = McpAdapter(registry)
    dispatcher = McpToolDispatcher(adapter)
    return adapter, dispatcher, history, supervisor, event_bus


# ══════════════════════════════════════════════════════════════════
print("=" * 60)
print("Phase 4 Integration Tests")
print("=" * 60)

# ── McpToolDispatcher Tests ──────────────────────────────────────

print("\n--- McpToolDispatcher: call_tool routing ---")
adapter, dispatcher, history, supervisor, _ = make_wired_stack()
history.append(make_snapshot(callback=100))

result = dispatcher.call_tool("get_runtime_state")
check(result["callback_number"] == 100, "get_runtime_state routes correctly")

result = dispatcher.call_tool("get_zone", {"zone_name": "SPACE1-1"})
check(result["zone_name"] == "SPACE1-1", "get_zone routes with args")

result = dispatcher.call_tool("get_building_summary")
check("callback_number" in result, "get_building_summary routes correctly")
check(result["callback_number"] == 100, "building_summary callback_number correct")

result = dispatcher.call_tool("get_zone_trend", {"zone_name": "SPACE1-1", "window": 4})
check("zone_name" in result or "error" in result, "get_zone_trend routes correctly")

result = dispatcher.call_tool("unknown_tool_xyz")
check(result["error"] == "unknown_tool", "unknown tool returns error")

result = dispatcher.call_tool("propose_setpoint", {
    "zone_name": "SPACE1-1", "heating": 21.0, "cooling": 25.0
})
check(result.get("status") == "pending", "propose_setpoint via dispatcher works")
pending = supervisor.get_pending_proposal("SPACE1-1")
check(pending is not None, "proposal visible in supervisor after dispatch")
check(pending.heating_setpoint == 21.0, "heating setpoint matches")


print("\n--- McpToolDispatcher: string argument coercion ---")
# LLM sometimes sends numbers as strings
result = dispatcher.call_tool("get_history", {"offset": "0", "count": "5"})
check(isinstance(result, list), "string numeric args coerced to int")

result = dispatcher.call_tool("propose_setpoint", {
    "zone_name": "SPACE2-1", "heating": "20.5", "cooling": "25.5"
})
check(result.get("status") == "pending", "string float args coerced")


print("\n--- McpToolDispatcher: list_tools ---")
tools = dispatcher.list_tools()
check(len(tools) == 8, "dispatcher exposes 8 tools")


# ── ContextBuilder Tests ─────────────────────────────────────────

print("\n--- ContextBuilder: build on empty buffer ---")
adapter2, _, history2, _, _ = make_wired_stack()
ctx_builder = ContextBuilder(adapter2)
ctx = ctx_builder.build()
check(ctx["context_error"] is not None, "reports error on empty buffer")
check(ctx["callback_number"] is None, "callback_number is None")


print("\n--- ContextBuilder: build with data ---")
history2.append(make_snapshot(callback=200, outdoor=28.0, chiller=5000.0))
ctx = ctx_builder.build()
check(ctx["callback_number"] == 200, "callback_number from summary")
check("building_summary" in ctx, "has building_summary")
check("zone_trends" in ctx, "has zone_trends")
check(ctx["context_error"] is None, "no error on valid data")

# All zones at 22.0 / IDLE → no trends needed
for zone_name in ZONE_NAMES:
    check(ctx["zone_trends"][zone_name] is None, f"no trend for comfortable {zone_name}")


print("\n--- ContextBuilder: trend for uncomfortable zone ---")
zones_hot = {}
for name in ZONE_NAMES:
    if name == "SPACE1-1":
        zones_hot[name] = make_zone_snapshot(name, temp=25.5, state=STATE_COOLING, c_sp=24.0)
    else:
        zones_hot[name] = make_zone_snapshot(name)

history2.append(RuntimeSnapshot(
    callback_number=201,
    simulated_timestamp=(7, 15, 14, 30),
    scheduler_status="RUNNING",
    outdoor_temp_c=35.0,
    chiller_power_w=8000.0,
    zones=zones_hot,
))

ctx = ctx_builder.build()
check(ctx["zone_trends"]["SPACE1-1"] is not None, "trend generated for hot SPACE1-1")
check(ctx["zone_trends"]["SPACE2-1"] is None, "no trend for comfortable SPACE2-1")


# ── Prompts Tests ────────────────────────────────────────────────

print("\n--- prompts: SYSTEM_PROMPT ---")
check("SPACE1-1" in prompts.SYSTEM_PROMPT, "system prompt mentions zone names")
check("18.0" in prompts.SYSTEM_PROMPT, "system prompt mentions heating bound min")
check("propose_setpoint" in prompts.SYSTEM_PROMPT, "system prompt mentions propose_setpoint")


print("\n--- prompts: build_user_message ---")
msg = prompts.build_user_message(ctx)
check("201" in msg, "user message contains callback number")
check("SPACE1-1" in msg, "user message mentions hot zone")
check("35.0" in msg or "35" in msg, "user message mentions outdoor temp")
check("Callback" in msg, "user message has Callback label")


# ── AgentLoop Core Logic Tests ───────────────────────────────────

print("\n--- AgentLoop: drift detection ---")
adapter3, dispatcher3, history3, supervisor3, event_bus3 = make_wired_stack()

# Populate buffer
history3.append(make_snapshot(callback=300))

tmp_dir = tempfile.mkdtemp()
try:
    trace_logger = AgentTraceLogger(output_dir=f"{tmp_dir}/agent", run_id="test_drift")
    cycle_queue = queue.Queue()
    shutdown_event = threading.Event()

    llm_config = {
        "model": "test",
        "reasoning_interval": 100,  # very high, so no reasoning is triggered
    }

    loop = AgentLoop(
        adapter=adapter3,
        trace_logger=trace_logger,
        cycle_queue=cycle_queue,
        shutdown_event=shutdown_event,
        llm_config=llm_config,
        mcp_dispatcher=dispatcher3,
    )

    # Set a manual policy
    loop.current_policy = {"SPACE1-1": (21.0, 25.0)}

    # Create snapshot where setpoints match policy → no drift
    snap_no_drift = make_snapshot(
        callback=301,
        zone_h=[21.0, 22.0, 22.0, 22.0, 22.0],
        zone_c=[25.0, 24.0, 24.0, 24.0, 24.0],
    )

    # Process iteration
    loop._process_iteration(snap_no_drift)

    # No drift → no proposal should be submitted
    pending = supervisor3.get_pending_proposal("SPACE1-1")
    check(pending is None, "no proposal when setpoints match policy (no drift)")

    # Create snapshot with drift (controller reverted SPACE1-1 to 22.0/24.0)
    snap_with_drift = make_snapshot(
        callback=302,
        zone_h=[22.0, 22.0, 22.0, 22.0, 22.0],  # drifted from 21.0
        zone_c=[24.0, 24.0, 24.0, 24.0, 24.0],   # drifted from 25.0
    )

    loop._process_iteration(snap_with_drift)

    pending = supervisor3.get_pending_proposal("SPACE1-1")
    check(pending is not None, "proposal submitted when drift detected")
    check(pending.heating_setpoint == 21.0, "resubmitted heating matches policy target")
    check(pending.cooling_setpoint == 25.0, "resubmitted cooling matches policy target")
    check(pending.source == "mcp_agent", "source is mcp_agent")


    print("\n--- AgentLoop: no drift for zones not in policy ---")
    supervisor3.consume_proposal("SPACE1-1")  # clear previous
    loop.current_policy = {"SPACE1-1": (21.0, 25.0)}  # only SPACE1-1 in policy

    snap_drift_other = make_snapshot(
        callback=303,
        zone_h=[21.0, 20.0, 22.0, 22.0, 22.0],  # SPACE2-1 drifted but not in policy
        zone_c=[25.0, 26.0, 24.0, 24.0, 24.0],
    )

    loop._process_iteration(snap_drift_other)
    pending2 = supervisor3.get_pending_proposal("SPACE2-1")
    check(pending2 is None, "no proposal for SPACE2-1 (not in policy)")
    pending1 = supervisor3.get_pending_proposal("SPACE1-1")
    check(pending1 is None, "no proposal for SPACE1-1 (no drift from policy)")


    print("\n--- AgentLoop: reasoning cadence counter ---")
    loop._cycles_since_reasoning = 0
    loop._reasoning_interval = 4
    loop.current_policy = {}

    # Process 3 iterations → no reasoning
    for i in range(3):
        loop._process_iteration(make_snapshot(callback=400 + i))
    check(loop._cycles_since_reasoning == 3, "counter increments to 3")

    # Reset counter for test
    loop._cycles_since_reasoning = 3
    # 4th iteration would trigger reasoning, but LLM not available → error logged
    # We just verify the counter resets
    loop._reasoning_interval = 999  # prevent triggering
    loop._cycles_since_reasoning = 0
    for i in range(5):
        loop._process_iteration(make_snapshot(callback=410 + i))
    check(loop._cycles_since_reasoning == 5, "counter at 5 without reasoning trigger")


    print("\n--- AgentLoop: policy update mutation safety ---")
    # Simulate policy update (Patch 1)
    loop.current_policy = {"SPACE1-1": (21.0, 25.0), "SPACE2-1": (20.0, 26.0)}
    old = dict(loop.current_policy)

    # Simulate what _run_reasoning does for policy update
    tool_results = [
        {"tool": "propose_setpoint", "args": {"zone_name": "SPACE1-1", "heating": 21.5, "cooling": 25.5}, "result": {"status": "pending"}},
        # SPACE2-1 NOT mentioned → should be released
    ]
    new_policy = {}
    for tr in tool_results:
        if tr["tool"] == "propose_setpoint" and tr["result"].get("status") == "pending":
            zone = tr["args"]["zone_name"]
            new_policy[zone] = (tr["args"]["heating"], tr["args"]["cooling"])
    loop.current_policy = new_policy

    check("SPACE1-1" in loop.current_policy, "SPACE1-1 retained in new policy")
    check("SPACE2-1" not in loop.current_policy, "SPACE2-1 released (not in tool calls)")
    check(loop.current_policy["SPACE1-1"] == (21.5, 25.5), "SPACE1-1 setpoints updated")
    check("SPACE2-1" in old, "old dict unmodified (no mutation during iteration)")


    print("\n--- AgentLoop: drift threshold boundary ---")
    loop.current_policy = {"SPACE1-1": (21.0, 25.0)}
    supervisor3.consume_proposal("SPACE1-1")  # clear

    # Drift below threshold -- should NOT trigger
    snap_boundary = make_snapshot(
        callback=500,
        zone_h=[21.0 + DRIFT_THRESHOLD * 0.5, 22.0, 22.0, 22.0, 22.0],
        zone_c=[25.0, 24.0, 24.0, 24.0, 24.0],
    )
    loop._process_iteration(snap_boundary)
    pending = supervisor3.get_pending_proposal("SPACE1-1")
    check(pending is None, "no proposal when drift < threshold")

    # Drift just over threshold
    snap_over = make_snapshot(
        callback=501,
        zone_h=[21.0 + DRIFT_THRESHOLD + 0.01, 22.0, 22.0, 22.0, 22.0],
        zone_c=[25.0, 24.0, 24.0, 24.0, 24.0],
    )
    loop._process_iteration(snap_over)
    pending = supervisor3.get_pending_proposal("SPACE1-1")
    check(pending is not None, "proposal submitted when drift > threshold")


    print("\n--- AgentLoop: OpenAI tool schema generation ---")
    tools = loop._build_openai_tools()
    check(isinstance(tools, list), "returns list")
    check(len(tools) == 8, "8 tools in schema")
    check(tools[0]["type"] == "function", "type is function")
    check("parameters" in tools[0]["function"], "has parameters")

    # Verify propose_setpoint schema
    propose_tool = next(t for t in tools if t["function"]["name"] == "propose_setpoint")
    params = propose_tool["function"]["parameters"]
    check("zone_name" in params["properties"], "has zone_name property")
    check("heating" in params["properties"], "has heating property")
    check(params["properties"]["heating"]["type"] == "number", "heating is number type")
    check("zone_name" in params["required"], "zone_name is required")


    print("\n--- AgentLoop: empty policy -> no proposals ---")
    loop.current_policy = {}
    supervisor3.consume_proposal("SPACE1-1")  # clear

    loop._process_iteration(make_snapshot(callback=600))
    for zone in ZONE_NAMES:
        pending = supervisor3.get_pending_proposal(zone)
        check(pending is None, f"no proposal for {zone} with empty policy")

    trace_logger.close()

finally:
    shutil.rmtree(tmp_dir, ignore_errors=True)


# -- EventBus -> Queue Bridge Test ---------------------------------

print("\n--- EventBus -> Queue bridge ---")
_, _, history4, _, event_bus4 = make_wired_stack()
test_queue = queue.Queue()
event_bus4.subscribe(CycleCompleted, lambda e: test_queue.put(e.snapshot))

snap = make_snapshot(callback=700, outdoor=30.0)
history4.append(snap)
event_bus4.emit(CycleCompleted(snap))

received = test_queue.get(timeout=1)
check(received.callback_number == 700, "snapshot arrives via queue bridge")
check(received.outdoor_temp_c == 30.0, "snapshot data intact through bridge")


# ══════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print(f"Phase 4 Integration Tests: {passed} passed, {failed} failed")
print("=" * 60)

if failed > 0:
    sys.exit(1)
