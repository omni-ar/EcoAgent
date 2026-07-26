import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

import queue
import threading
import json
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

print('Setting up environment...')
history = HistoryBuffer(max_size=96)
supervisor = SupervisorInterface()
event_bus = EventBus()
registry = ToolRegistry(history, supervisor, event_bus, history.latest)
adapter = McpAdapter(registry)
dispatcher = McpToolDispatcher(adapter)

# Create a scenario where SPACE1-1 is too cold (18.0C)
zones = {n: ZoneSnapshot(n, 22.0, 22.0, 24.0, STATE_IDLE, False, 4, False, False, 'approved', 22.0, 24.0, 22.0, 24.0, True, True) for n in ZONE_NAMES}
zones['SPACE1-1'].temperature_c = 18.0 
snapshot = RuntimeSnapshot(1, (1, 1, 0, 15), 'RUNNING', 10.0, 0.0, zones)
history.append(snapshot)

logger = AgentTraceLogger(output_dir='logs/manual_test', run_id='manual')
config = {'model': 'qwen2.5:7b', 'base_url': 'http://localhost:11434/v1', 'api_key': 'ollama', 'temperature': 0.0}

print('Sending building state to local Ollama (qwen2.5:7b)... please wait.')
loop = AgentLoop(adapter, logger, queue.Queue(), threading.Event(), config, dispatcher)
loop._run_reasoning(snapshot)

print('\n=== LLM FINISHED ===')
print('Active Policy:', loop.current_policy)
pending = supervisor.get_all_pending()
for zone, prop in pending.items():
    print(f'Proposal for {zone}: Heating={prop.heating_setpoint}, Cooling={prop.cooling_setpoint}')

print('\nCheck the trace log at: logs/manual_test/agent/trace.jsonl')
