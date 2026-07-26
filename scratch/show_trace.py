import json, sys
sys.stdout.reconfigure(line_buffering=True)
run_id = 'run_20260726_194902'
lines = open(f'logs/runs/{run_id}/agent/trace.jsonl').readlines()
print(f'Trace entries: {len(lines)}')
for i, line in enumerate(lines):
    e = json.loads(line)
    m = e.get('metrics', {})
    turns = e.get('turns', [])
    policy = e.get('policy_snapshot', {})
    cb = e.get('cycle_callback')
    lat = m.get('latency_seconds', '?')
    tc = m.get('turn_count', '?')
    pt = m.get('prompt_tokens')
    ct = m.get('completion_tokens')
    ps = e.get('proposal_submitted')
    pv = policy.get('version')
    az = list(policy.get('active_zones', {}).keys())
    print(f'\nCycle {i}:')
    print(f'  Callback: {cb}')
    print(f'  Latency: {lat}s')
    print(f'  Prompt tokens: {pt}')
    print(f'  Completion tokens: {ct}')
    print(f'  Proposal submitted: {ps}')
    print(f'  Policy version: {pv}')
    print(f'  Policy zones: {az}')
    for t_idx, turn in enumerate(turns):
        tools = [tc2['name'] for tc2 in turn.get('tool_calls', [])]
        content = (turn.get('content', '') or '')[:200]
        print(f'  Turn {t_idx}: tools={tools} content={repr(content)}')
        for tc2 in turn.get('tool_calls', []):
            if tc2['name'] == 'propose_setpoint':
                print(f'    -> propose_setpoint({tc2["arguments"]})')
        for tr in turn.get('tool_results', []):
            print(f'    result({tr.get("tool","?")}): status={tr.get("result",{}).get("status","?")} ({len(json.dumps(tr.get("result",{})))} chars)')
