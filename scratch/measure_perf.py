"""Phase 4.6 — Production Performance Measurement.

Measures each component of the reasoning cycle independently.
Does NOT modify any production code.
"""
import sys
import time
import json
import queue
import threading
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from ecoagent.supervisor.runtime_snapshot import RuntimeSnapshot, ZoneSnapshot
from ecoagent.supervisor.history_buffer import HistoryBuffer
from ecoagent.supervisor.events import EventBus
from ecoagent.supervisor.supervisor import SupervisorInterface
from ecoagent.supervisor.tools import ToolRegistry
from ecoagent.controller.constants import STATE_COOLING, ZONE_NAMES
from ecoagent.mcp.adapter import McpAdapter
from ecoagent.mcp.server import McpToolDispatcher
from ecoagent.agent.trace_logger import AgentTraceLogger
from ecoagent.agent.loop import AgentLoop
from ecoagent.agent import prompts
from ecoagent.agent.context import ContextBuilder
import openai

# ── Setup (identical to production) ────────────────────────────────
print("=" * 60, flush=True)
print("Phase 4.6 — Performance Measurement", flush=True)
print("=" * 60, flush=True)

history = HistoryBuffer(max_size=96)
supervisor = SupervisorInterface()
event_bus = EventBus()
registry = ToolRegistry(history, supervisor, event_bus, history.latest)
adapter = McpAdapter(registry)
dispatcher = McpToolDispatcher(adapter)

zones = {}
for n in ZONE_NAMES:
    zones[n] = ZoneSnapshot(n, 23.5, 18.0, 23.0, STATE_COOLING, False, 10,
                            False, False, 'approved', 18.0, 23.0, 18.0, 23.0,
                            True, True)
snapshot = RuntimeSnapshot(5000, (7, 15, 14, 0), 'RUNNING', 28.0, 15000.0, zones)
history.append(snapshot)

config = {'model': 'qwen2.5:7b', 'base_url': 'http://localhost:11434/v1',
          'api_key': 'ollama', 'temperature': 0.0, 'max_turns': 4}
client = openai.OpenAI(base_url='http://localhost:11434/v1', api_key='ollama')

ctx_builder = ContextBuilder(adapter)
loop = AgentLoop(adapter, AgentTraceLogger(output_dir='logs/manual_test', run_id='perf'),
                 queue.Queue(), threading.Event(), config, dispatcher)
openai_tools = loop._build_openai_tools()

# ── Measurement 1: Context construction ────────────────────────────
print("\n--- M1: Context Construction ---", flush=True)
t0 = time.perf_counter()
context = ctx_builder.build()
t_ctx = time.perf_counter() - t0

t0 = time.perf_counter()
user_message = prompts.build_user_message(context)
t_prompt = time.perf_counter() - t0

system_prompt = prompts.SYSTEM_PROMPT
sys_bytes = len(system_prompt.encode('utf-8'))
sys_chars = len(system_prompt)
usr_bytes = len(user_message.encode('utf-8'))
usr_chars = len(user_message)

print(f"  Context build:     {t_ctx*1000:.2f} ms", flush=True)
print(f"  Prompt build:      {t_prompt*1000:.2f} ms", flush=True)
print(f"  System prompt:     {sys_chars} chars / {sys_bytes} bytes", flush=True)
print(f"  User message:      {usr_chars} chars / {usr_bytes} bytes", flush=True)

# ── Measurement 2: Tool schema construction ────────────────────────
print("\n--- M2: Tool Schema ---", flush=True)
t0 = time.perf_counter()
openai_tools = loop._build_openai_tools()
t_schema = time.perf_counter() - t0
schema_json = json.dumps(openai_tools)
print(f"  Schema build:      {t_schema*1000:.2f} ms", flush=True)
print(f"  Schema size:       {len(schema_json)} chars / {len(schema_json.encode('utf-8'))} bytes", flush=True)
print(f"  Tool count:        {len(openai_tools)}", flush=True)

# ── Measurement 3: Messages before Turn 0 ─────────────────────────
print("\n--- M3: Turn 0 Input ---", flush=True)
messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": user_message},
]
turn0_input_json = json.dumps(messages)
print(f"  Messages:          {len(messages)}", flush=True)
print(f"  Total chars:       {sum(len(m['content']) for m in messages)}", flush=True)
print(f"  Serialized size:   {len(turn0_input_json)} chars / {len(turn0_input_json.encode('utf-8'))} bytes", flush=True)

# ── Measurement 4: Turn 0 LLM call ────────────────────────────────
print("\n--- M4: Turn 0 LLM Call ---", flush=True)
t0 = time.perf_counter()
response0 = client.chat.completions.create(
    model='qwen2.5:7b', messages=messages, tools=openai_tools,
    temperature=0.0, max_tokens=1024, timeout=60,
)
t_turn0 = time.perf_counter() - t0

choice0 = response0.choices[0]
msg0 = choice0.message
print(f"  Wall time:         {t_turn0:.3f} s", flush=True)
print(f"  Finish reason:     {choice0.finish_reason}", flush=True)
print(f"  Prompt tokens:     {response0.usage.prompt_tokens}", flush=True)
print(f"  Completion tokens: {response0.usage.completion_tokens}", flush=True)
print(f"  Total tokens:      {response0.usage.total_tokens}", flush=True)
print(f"  Content length:    {len(msg0.content or '')} chars", flush=True)
print(f"  Tool calls:        {[tc.function.name for tc in (msg0.tool_calls or [])]}", flush=True)

# Tokens per second
if response0.usage.completion_tokens > 0:
    tps = response0.usage.completion_tokens / t_turn0
    print(f"  Tokens/sec:        {tps:.1f}", flush=True)

# ── Measurement 5: Tool execution ──────────────────────────────────
print("\n--- M5: Tool Execution ---", flush=True)
if msg0.tool_calls:
    tc0 = msg0.tool_calls[0]
    args0 = json.loads(tc0.function.arguments) if isinstance(tc0.function.arguments, str) else tc0.function.arguments
    
    t0 = time.perf_counter()
    tool_result = loop._execute_tool(tc0.function.name, args0)
    t_tool = time.perf_counter() - t0
    
    t0 = time.perf_counter()
    tool_result_json = json.dumps(tool_result, default=str)
    t_serialize = time.perf_counter() - t0
    
    tool_result_bytes = len(tool_result_json.encode('utf-8'))
    tool_result_chars = len(tool_result_json)
    
    print(f"  Tool name:         {tc0.function.name}", flush=True)
    print(f"  Execution time:    {t_tool*1000:.2f} ms", flush=True)
    print(f"  Serialization:     {t_serialize*1000:.2f} ms", flush=True)
    print(f"  Result chars:      {tool_result_chars}", flush=True)
    print(f"  Result bytes:      {tool_result_bytes}", flush=True)
else:
    print("  No tool calls to measure", flush=True)
    tool_result_json = ""
    tool_result_chars = 0
    tool_result_bytes = 0

# ── Measurement 6: Message construction for Turn 1 ────────────────
print("\n--- M6: Turn 1 Message Construction ---", flush=True)
t0 = time.perf_counter()
if msg0.tool_calls:
    tc0 = msg0.tool_calls[0]
    assistant_msg = {"role": "assistant", "content": msg0.content or ""}
    tc_list = [{
        "id": tc0.id,
        "type": "function",
        "function": {"name": tc0.function.name, "arguments": tc0.function.arguments},
    }]
    assistant_msg["tool_calls"] = tc_list
    messages.append(assistant_msg)
    messages.append({
        "role": "tool",
        "tool_call_id": tc0.id,
        "content": tool_result_json,
    })
t_msg_construct = time.perf_counter() - t0

turn1_input_json = json.dumps(messages, default=str)
turn1_chars = sum(len(json.dumps(m, default=str)) for m in messages)
print(f"  Construction time: {t_msg_construct*1000:.2f} ms", flush=True)
print(f"  Messages now:      {len(messages)}", flush=True)
print(f"  Total chars:       {turn1_chars}", flush=True)
print(f"  Serialized size:   {len(turn1_input_json)} chars / {len(turn1_input_json.encode('utf-8'))} bytes", flush=True)
print(f"  Growth from T0:    {len(turn1_input_json) - len(turn0_input_json)} chars added", flush=True)

# ── Measurement 7: Turn 1 LLM call ────────────────────────────────
print("\n--- M7: Turn 1 LLM Call ---", flush=True)
t0 = time.perf_counter()
response1 = client.chat.completions.create(
    model='qwen2.5:7b', messages=messages, tools=openai_tools,
    temperature=0.0, max_tokens=1024, timeout=60,
)
t_turn1 = time.perf_counter() - t0

choice1 = response1.choices[0]
msg1 = choice1.message
print(f"  Wall time:         {t_turn1:.3f} s", flush=True)
print(f"  Finish reason:     {choice1.finish_reason}", flush=True)
print(f"  Prompt tokens:     {response1.usage.prompt_tokens}", flush=True)
print(f"  Completion tokens: {response1.usage.completion_tokens}", flush=True)
print(f"  Total tokens:      {response1.usage.total_tokens}", flush=True)
print(f"  Content length:    {len(msg1.content or '')} chars", flush=True)
print(f"  Tool calls:        {[tc.function.name for tc in (msg1.tool_calls or [])]}", flush=True)

if response1.usage.completion_tokens > 0:
    tps1 = response1.usage.completion_tokens / t_turn1
    print(f"  Tokens/sec:        {tps1:.1f}", flush=True)

# ── Measurement 8: Total cycle time ───────────────────────────────
print("\n--- M8: Total Cycle Budget ---", flush=True)
total_cycle = t_turn0 + t_turn1
print(f"  Turn 0 LLM:        {t_turn0:.3f} s", flush=True)
print(f"  Turn 1 LLM:        {t_turn1:.3f} s", flush=True)
print(f"  Tool execution:    {t_tool*1000:.2f} ms", flush=True)
print(f"  Serialization:     {t_serialize*1000:.2f} ms", flush=True)
print(f"  Context build:     {t_ctx*1000:.2f} ms", flush=True)
print(f"  Prompt build:      {t_prompt*1000:.2f} ms", flush=True)
print(f"  Msg construction:  {t_msg_construct*1000:.2f} ms", flush=True)
print(f"  Total LLM time:    {total_cycle:.3f} s", flush=True)
print(f"  Total overhead:    {(t_tool + t_serialize + t_ctx + t_prompt + t_msg_construct)*1000:.2f} ms", flush=True)

# ── Measurement 9: Comparison with pre-ReAct ──────────────────────
print("\n--- M9: Pre-ReAct Comparison ---", flush=True)
pre_react_avg = 2.78  # From production trace (cycles 2-11, excluding cold start)
pre_react_cold = 11.49  # From production trace (cycle 1)
print(f"  Pre-ReAct avg/cycle:  {pre_react_avg:.2f} s (single turn, warm)", flush=True)
print(f"  Pre-ReAct cold start: {pre_react_cold:.2f} s (single turn, cold)", flush=True)
print(f"  Post-ReAct cycle:     {total_cycle:.2f} s (2 turns, warm)", flush=True)
print(f"  Slowdown factor:      {total_cycle / pre_react_avg:.1f}x vs warm", flush=True)

sim_duration = 70  # seconds (measured from production runs)
pre_react_cycles = 1 + int((sim_duration - pre_react_cold) / pre_react_avg)
post_react_cycles = int(sim_duration / total_cycle) if total_cycle > 0 else 0
# Account for cold start on first cycle (add ~5s extra)
cold_penalty = t_turn0  # first call includes model load
post_react_with_cold = int((sim_duration - cold_penalty) / total_cycle) if total_cycle > 0 else 0

print(f"  Sim duration:         {sim_duration} s", flush=True)
print(f"  Pre-ReAct cycles:     ~{pre_react_cycles} (measured: 11)", flush=True)
print(f"  Post-ReAct cycles:    ~{post_react_with_cold} (warm) to ~{post_react_cycles} (ideal)", flush=True)

# ── Measurement 10: Token budget comparison ───────────────────────
print("\n--- M10: Token Budget ---", flush=True)
print(f"  Turn 0 prompt tokens:     {response0.usage.prompt_tokens}", flush=True)
print(f"  Turn 0 completion tokens: {response0.usage.completion_tokens}", flush=True)
print(f"  Turn 1 prompt tokens:     {response1.usage.prompt_tokens}", flush=True)
print(f"  Turn 1 completion tokens: {response1.usage.completion_tokens}", flush=True)
print(f"  Token growth T0->T1:      +{response1.usage.prompt_tokens - response0.usage.prompt_tokens} prompt tokens", flush=True)
print(f"  Tool result contribution: ~{tool_result_chars} chars -> ~{response1.usage.prompt_tokens - response0.usage.prompt_tokens} tokens", flush=True)

# ── Summary table ─────────────────────────────────────────────────
print("\n" + "=" * 60, flush=True)
print("CAUSE-EVIDENCE TABLE", flush=True)
print("=" * 60, flush=True)
print(f"{'Cause':<30} {'Measured Impact':<25} {'Confidence'}", flush=True)
print("-" * 75, flush=True)

# Calculate contributions
total_budget = sim_duration
turn1_overhead = t_turn1 - pre_react_avg  # extra time Turn 1 adds vs old single-turn
per_cycle_increase = total_cycle - pre_react_avg

print(f"{'Turn 1 LLM latency':<30} {f'{t_turn1:.1f}s per cycle':<25} {'MEASURED'}", flush=True)
print(f"{'Turn 0 LLM latency':<30} {f'{t_turn0:.1f}s per cycle':<25} {'MEASURED'}", flush=True)
print(f"{'Context growth (tool result)':<30} {f'+{response1.usage.prompt_tokens - response0.usage.prompt_tokens} tokens':<25} {'MEASURED'}", flush=True)
print(f"{'Tool execution':<30} {f'{t_tool*1000:.1f}ms per cycle':<25} {'MEASURED'}", flush=True)
print(f"{'JSON serialization':<30} {f'{t_serialize*1000:.1f}ms per cycle':<25} {'MEASURED'}", flush=True)
print(f"{'Message construction':<30} {f'{t_msg_construct*1000:.1f}ms per cycle':<25} {'MEASURED'}", flush=True)
print(f"{'Context/prompt build':<30} {f'{(t_ctx+t_prompt)*1000:.1f}ms per cycle':<25} {'MEASURED'}", flush=True)
print("-" * 75, flush=True)
print(f"{'Pre-ReAct: 1 turn/cycle':<30} {f'{pre_react_avg:.1f}s avg':<25} {'FROM TRACE'}", flush=True)
print(f"{'Post-ReAct: 2 turns/cycle':<30} {f'{total_cycle:.1f}s total':<25} {'MEASURED'}", flush=True)
print(f"{'Per-cycle slowdown':<30} {f'+{per_cycle_increase:.1f}s ({total_cycle/pre_react_avg:.1f}x)':<25} {'COMPUTED'}", flush=True)
print(f"{'Cycles fitting in {sim_duration}s':<30} {f'{pre_react_cycles} -> {post_react_with_cold}':<25} {'COMPUTED'}", flush=True)

print("\nDONE", flush=True)
