import sys
from pathlib import Path
import json
import queue
import threading
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from ecoagent.agent.loop import AgentLoop
from ecoagent.agent.trace_logger import AgentTraceLogger
from ecoagent.supervisor.runtime_snapshot import RuntimeSnapshot, ZoneSnapshot
from ecoagent.controller.constants import STATE_IDLE, ZONE_NAMES
from ecoagent.mcp.adapter import McpAdapter
from ecoagent.mcp.server import McpToolDispatcher
from ecoagent.supervisor.history_buffer import HistoryBuffer
from ecoagent.supervisor.events import EventBus
from ecoagent.supervisor.supervisor import SupervisorInterface
from ecoagent.supervisor.tools import ToolRegistry

class MockCompletions:
    def create(self, **kwargs):
        # Dump exactly what was passed to the LLM
        with open("scratch/llm_payload.json", "w") as f:
            json.dump({
                "messages": kwargs.get("messages"),
                "tools": kwargs.get("tools")
            }, f, indent=2)
        # We don't actually need to return a valid response, we just want to intercept the request and exit.
        sys.exit(0)

class MockChat:
    completions = MockCompletions()

class MockClient:
    chat = MockChat()

# Setup same as loop uses
history = HistoryBuffer(max_size=96)
supervisor = SupervisorInterface()
event_bus = EventBus()
registry = ToolRegistry(history, supervisor, event_bus, history.latest)
adapter = McpAdapter(registry)
dispatcher = McpToolDispatcher(adapter)

zones = {n: ZoneSnapshot(n, 22.0, 22.0, 24.0, STATE_IDLE, False, 4, False, False, 'approved', 22.0, 24.0, 22.0, 24.0, True, True) for n in ZONE_NAMES}
zones['SPACE1-1'].temperature_c = 18.0 
snapshot = RuntimeSnapshot(1, (1, 1, 0, 15), 'RUNNING', 10.0, 0.0, zones)
history.append(snapshot)

logger = AgentTraceLogger(output_dir='logs/manual_test', run_id='dump')
config = {'model': 'qwen2.5:7b', 'temperature': 0.0}

loop = AgentLoop(adapter, logger, queue.Queue(), threading.Event(), config, dispatcher)
loop._get_client = lambda: MockClient()
loop._run_reasoning(snapshot)
