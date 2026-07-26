import json
from pathlib import Path
from collections import Counter
import pandas as pd
from datetime import datetime

run_dir = Path("logs/runs/run_20260726_180115")
trace_file = run_dir / "agent" / "trace.jsonl"
controller_file = run_dir / "controller" / "controller.jsonl"
csv_file = run_dir / "simulation" / "eplusout.csv"

# 1. Trace Analysis
traces = []
if trace_file.exists():
    with open(trace_file) as f:
        for line in f:
            traces.append(json.loads(line))

print(f"Total traces: {len(traces)}")
tool_counter = Counter()
latencies = []
errors = []

print("\n--- REASONING TIMELINE ---")
for t in traces:
    cb = t.get("cycle_callback")
    wall = t.get("wall_clock_iso")
    sim = t.get("simulated_timestamp")
    metrics = t.get("metrics", {})
    latency = metrics.get("latency_seconds", 0)
    latencies.append(latency)
    
    tools_called = [tc["name"] for tc in t.get("llm_response", {}).get("tool_calls", [])]
    for tc in tools_called:
        tool_counter[tc] += 1
        
    pol_ver = t.get("policy_state", {}).get("policy_version", 0)
    err = t.get("error")
    if err:
        errors.append(err)
        
    print(f"CB: {cb} | Wall: {wall} | Sim: {sim} | Latency: {latency:.2f}s | Tools: {tools_called} | Policy V: {pol_ver}")

print("\n--- POLICY EVOLUTION ---")
for t in traces:
    pol = t.get("policy_state", {})
    print(f"V{pol.get('policy_version')}: Active: {pol.get('active_zones')} | Released: {pol.get('released_zones')}")

print("\n--- TOOL USAGE ---")
for k, v in tool_counter.items():
    print(f"{k}: {v}")

# 2. Controller Analysis
events = []
if controller_file.exists():
    with open(controller_file) as f:
        for line in f:
            events.append(json.loads(line))

proposals = [e for e in events if e.get("type") == "proposal"]
states = [e for e in events if e.get("type") == "state_transition"]

print("\n--- PROPOSAL STATS ---")
print(f"Total Proposals: {len(proposals)}")
approved = [p for p in proposals if p.get("reason") == "approved"]
clamped = [p for p in proposals if p.get("reason") == "clamped"]
rejected = [p for p in proposals if p.get("reason") == "rejected"]

print(f"Approved: {len(approved)}")
print(f"Clamped (SafetyGuard): {len(clamped)}")
print(f"Rejected: {len(rejected)}")

zone_props = Counter([p.get("zone_name") for p in proposals])
print(f"Per-zone: {zone_props}")

# Check source of proposals (drift vs supervisor)
source_counter = Counter([p.get("source") for p in proposals])
print(f"Proposal Sources: {source_counter}")

print("\n--- CONTROLLER STATES ---")
state_counter = Counter([s.get("new_state") for s in states])
print(f"State counts: {state_counter}")

print("\n--- LLM BEHAVIOUR ---")
if latencies:
    print(f"Avg Latency: {sum(latencies)/len(latencies):.2f}s")
    print(f"Max Latency: {max(latencies):.2f}s")
print(f"Errors in trace: {len(errors)}")

# Read task log for timeouts
task_log = Path(".system_generated/tasks/task-1392.log")
timeouts = 0
retries = 0
if task_log.exists():
    text = task_log.read_text()
    timeouts = text.count("failed: Connection error") or text.count("timeout")
    retries = text.count("Retrying")

print(f"Timeouts/Connection Errors logged: {timeouts}")
print(f"Retries logged: {retries}")
