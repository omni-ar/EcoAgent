"""Measure Turn 0 warm latency by running two back-to-back LLM calls.
The first call loads the model (cold). The second measures true warm latency.
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

# Setup
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

config = {'model': 'qwen2.5:7b', 'base_url': 'http://localhost:11434/v1', 'api_key': 'ollama', 'temperature': 0.0}
client = openai.OpenAI(base_url='http://localhost:11434/v1', api_key='ollama')

ctx_builder = ContextBuilder(adapter)
loop = AgentLoop(adapter, AgentTraceLogger(output_dir='logs/manual_test', run_id='warm'),
                 queue.Queue(), threading.Event(), config, dispatcher)
openai_tools = loop._build_openai_tools()

context = ctx_builder.build()
user_message = prompts.build_user_message(context)
messages = [
    {"role": "system", "content": prompts.SYSTEM_PROMPT},
    {"role": "user", "content": user_message},
]

print("=== Warm-up Measurement: 3 consecutive Turn 0 calls ===", flush=True)
print(f"Prompt tokens expected: ~1320", flush=True)
print(f"Completion tokens expected: ~17 (tool call)", flush=True)
print(flush=True)

for i in range(3):
    t0 = time.perf_counter()
    response = client.chat.completions.create(
        model='qwen2.5:7b', messages=messages, tools=openai_tools,
        temperature=0.0, max_tokens=1024, timeout=60,
    )
    elapsed = time.perf_counter() - t0
    u = response.usage
    tc = [t.function.name for t in (response.choices[0].message.tool_calls or [])]
    label = "COLD" if i == 0 else "WARM"
    print(f"  Call {i} [{label}]: {elapsed:.3f}s | p={u.prompt_tokens} c={u.completion_tokens} | tools={tc} | {u.completion_tokens/elapsed:.1f} tok/s", flush=True)

# Now measure Turn 1 warm (after a Turn 0)
print(flush=True)
print("=== Turn 1 warm measurement ===", flush=True)

# Do a Turn 0
t0 = time.perf_counter()
resp0 = client.chat.completions.create(
    model='qwen2.5:7b', messages=messages, tools=openai_tools,
    temperature=0.0, max_tokens=1024, timeout=60,
)
t_t0 = time.perf_counter() - t0
print(f"  Turn 0 (warm): {t_t0:.3f}s | p={resp0.usage.prompt_tokens} c={resp0.usage.completion_tokens}", flush=True)

# Construct Turn 1 messages
msg0 = resp0.choices[0].message
tc0 = msg0.tool_calls[0]
args0 = json.loads(tc0.function.arguments)
tool_result = loop._execute_tool(tc0.function.name, args0)
tool_result_json = json.dumps(tool_result, default=str)

msgs_t1 = list(messages)
msgs_t1.append({
    "role": "assistant", "content": msg0.content or "",
    "tool_calls": [{"id": tc0.id, "type": "function", "function": {"name": tc0.function.name, "arguments": tc0.function.arguments}}],
})
msgs_t1.append({"role": "tool", "tool_call_id": tc0.id, "content": tool_result_json})

t0 = time.perf_counter()
resp1 = client.chat.completions.create(
    model='qwen2.5:7b', messages=msgs_t1, tools=openai_tools,
    temperature=0.0, max_tokens=1024, timeout=60,
)
t_t1 = time.perf_counter() - t0
print(f"  Turn 1 (warm): {t_t1:.3f}s | p={resp1.usage.prompt_tokens} c={resp1.usage.completion_tokens}", flush=True)
print(f"  Total cycle:   {t_t0 + t_t1:.3f}s", flush=True)

print(flush=True)
print("=== Comparison ===", flush=True)
print(f"  Pre-ReAct warm (from trace): 2.78s (1 turn, 1186 prompt, 17 completion)", flush=True)
print(f"  Post-ReAct Turn 0 warm:      {t_t0:.2f}s (1320 prompt, {resp0.usage.completion_tokens} completion)", flush=True)
print(f"  Post-ReAct Turn 1 warm:      {t_t1:.2f}s ({resp1.usage.prompt_tokens} prompt, {resp1.usage.completion_tokens} completion)", flush=True)
print(f"  Post-ReAct total warm:        {t_t0 + t_t1:.2f}s", flush=True)
print(f"  Slowdown vs pre-ReAct:        {(t_t0 + t_t1)/2.78:.1f}x", flush=True)
print("DONE", flush=True)
