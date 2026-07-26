"""Post-fix diagnostic: confirm Turn 1 latency dropped."""
import sys, time, json, queue, threading
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

history = HistoryBuffer(max_size=96)
supervisor = SupervisorInterface()
event_bus = EventBus()
registry = ToolRegistry(history, supervisor, event_bus, history.latest)
adapter = McpAdapter(registry)
dispatcher = McpToolDispatcher(adapter)

zones = {}
for n in ZONE_NAMES:
    zones[n] = ZoneSnapshot(n, 23.5, 18.0, 23.0, STATE_COOLING, False, 10,
                            False, False, 'approved', 18.0, 23.0, 18.0, 23.0, True, True)
snapshot = RuntimeSnapshot(5000, (7, 15, 14, 0), 'RUNNING', 28.0, 15000.0, zones)
history.append(snapshot)

config = {'model': 'qwen2.5:7b', 'base_url': 'http://localhost:11434/v1',
          'api_key': 'ollama', 'temperature': 0.0, 'max_tokens': 200, 'max_turns': 4}
client = openai.OpenAI(base_url='http://localhost:11434/v1', api_key='ollama')

ctx_builder = ContextBuilder(adapter)
loop = AgentLoop(adapter, AgentTraceLogger(output_dir='logs/manual_test', run_id='postfix'),
                 queue.Queue(), threading.Event(), config, dispatcher)
openai_tools = loop._build_openai_tools()

# Warm model first with 2 throwaway calls
print("Warming model...", flush=True)
warmup_msgs = [{"role": "system", "content": "Say OK."}, {"role": "user", "content": "Hello"}]
for i in range(2):
    t0 = time.perf_counter()
    client.chat.completions.create(model='qwen2.5:7b', messages=warmup_msgs, max_tokens=5, timeout=30)
    print(f"  Warmup {i}: {time.perf_counter()-t0:.1f}s", flush=True)

context = ctx_builder.build()
user_message = prompts.build_user_message(context)
messages = [
    {"role": "system", "content": prompts.SYSTEM_PROMPT},
    {"role": "user", "content": user_message},
]

print(f"\nSystem prompt: {len(prompts.SYSTEM_PROMPT)} chars", flush=True)
print(f"max_tokens: 200", flush=True)

total_start = time.perf_counter()
for turn_idx in range(4):
    print(f"\n=== TURN {turn_idx} ===", flush=True)
    t0 = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model='qwen2.5:7b', messages=messages, tools=openai_tools,
            temperature=0.0, max_tokens=200, timeout=60,
        )
    except Exception as e:
        print(f"  ERROR: {e}", flush=True)
        break
    elapsed = time.perf_counter() - t0
    choice = response.choices[0]
    msg = choice.message
    u = response.usage
    print(f"  {elapsed:.1f}s | finish={choice.finish_reason} | p={u.prompt_tokens} c={u.completion_tokens} | {u.completion_tokens/elapsed:.1f} tok/s", flush=True)
    print(f"  Content: {repr((msg.content or '')[:200])}", flush=True)
    
    if not msg.tool_calls:
        print(f"  No tool calls. DONE.", flush=True)
        break
    
    print(f"  Tools: {[tc.function.name for tc in msg.tool_calls]}", flush=True)
    
    assistant_msg = {"role": "assistant", "content": msg.content or ""}
    tc_list = []
    for tc in msg.tool_calls:
        tc_list.append({"id": tc.id, "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}})
    assistant_msg["tool_calls"] = tc_list
    messages.append(assistant_msg)
    
    for tc in msg.tool_calls:
        args = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments
        result = loop._execute_tool(tc.function.name, args)
        result_json = json.dumps(result, default=str)
        print(f"  {tc.function.name} -> {len(result_json)} chars", flush=True)
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_json})
        if tc.function.name == "propose_setpoint" and isinstance(result, dict) and result.get("status") == "pending":
            print(f"  >>> PROPOSAL SUBMITTED: {args} <<<", flush=True)

total = time.perf_counter() - total_start
print(f"\n=== TOTAL: {total:.1f}s ===", flush=True)
pending = supervisor.get_all_pending()
print(f"Proposals: {list(pending.keys())}", flush=True)
for z, p in pending.items():
    print(f"  {z}: H={p.heating_setpoint} C={p.cooling_setpoint}", flush=True)
