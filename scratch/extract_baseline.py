"""Extract per-cycle latencies from pre-ReAct trace."""
import sys
import json
sys.stdout.reconfigure(line_buffering=True)

lines = open('logs/runs/run_20260726_180115/agent/trace.jsonl').readlines()
print(f'Pre-ReAct trace: run_20260726_180115')
print(f'Total cycles: {len(lines)}')
print()

header = f"{'Cycle':<6} {'Callback':<10} {'Latency':<10} {'P_Tok':<8} {'C_Tok':<8} {'T_Tok':<8} {'Tools':<25} {'Finish':<10}"
print(header)
print('-' * len(header))

for i, line in enumerate(lines):
    e = json.loads(line)
    m = e.get('metrics', {})
    lat = m.get('latency_seconds', '?')
    pt = m.get('prompt_tokens', '?')
    ct = m.get('completion_tokens', '?')
    tt = m.get('total_tokens', '?')
    cb = e.get('cycle_callback', '?')
    fr = e.get('llm_response', {}).get('finish_reason', '?')
    tools = [tc['name'] for tc in e.get('llm_response', {}).get('tool_calls', [])]
    tools_str = ','.join(tools) if tools else 'none'
    print(f'{i:<6} {cb:<10} {lat:<10} {pt:<8} {ct:<8} {tt:<8} {tools_str:<25} {fr:<10}')

latencies = [json.loads(l)['metrics']['latency_seconds'] for l in lines]
print()
print(f'Cold start (cycle 0):   {latencies[0]:.2f}s')
print(f'Warm avg (cycles 1-10): {sum(latencies[1:])/len(latencies[1:]):.2f}s')
print(f'Warm min:               {min(latencies[1:]):.2f}s')
print(f'Warm max:               {max(latencies[1:]):.2f}s')
print(f'Total LLM time:         {sum(latencies):.2f}s')

# Also check prompt token counts
prompt_tokens = [json.loads(l)['metrics']['prompt_tokens'] for l in lines]
compl_tokens = [json.loads(l)['metrics']['completion_tokens'] for l in lines]
print(f'Prompt tokens range:    {min(prompt_tokens)}-{max(prompt_tokens)}')
print(f'Completion tokens range:{min(compl_tokens)}-{max(compl_tokens)}')
print(f'Avg prompt tokens:      {sum(prompt_tokens)/len(prompt_tokens):.0f}')
print(f'Avg completion tokens:  {sum(compl_tokens)/len(compl_tokens):.0f}')
