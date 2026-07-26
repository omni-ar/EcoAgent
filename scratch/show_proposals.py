import json, sys
sys.stdout.reconfigure(line_buffering=True)
lines = open('logs/runs/run_20260726_192042/agent/trace.jsonl').readlines()
for i, line in enumerate(lines):
    e = json.loads(line)
    turns = e.get('turns', [])
    for t_idx, turn in enumerate(turns):
        for tc in turn.get('tool_calls', []):
            if tc['name'] == 'propose_setpoint':
                print(f'Cycle {i} Turn {t_idx}: propose_setpoint({tc["arguments"]})')
        for tr in turn.get('tool_results', []):
            if tr.get('tool') == 'propose_setpoint':
                print(f'  Result: {tr["result"]}')
