"""EcoAgent Savings Comparison — Baseline vs Agent Run.

Computes total energy (kWh) from chiller electricity and heating coil rates.
Produces comparison report and simple chart.
"""
import csv
import sys
import os
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

def load_energy(csv_path):
    """Extract hourly chiller electricity and heating rates."""
    chiller_col = 43  # CENTRAL CHILLER:Chiller Electricity Rate [W](Hourly)
    heating_cols = [30, 31, 32, 33, 34, 35, 36]  # Zone + OA + Main heating coils
    
    chiller_kwh = 0.0
    heating_kwh = 0.0
    rows = 0
    
    with open(csv_path) as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            if not row or not row[0].strip():
                continue
            try:
                chiller_w = float(row[chiller_col].strip())
                chiller_kwh += chiller_w / 1000.0  # W*hr -> Wh, but since hourly, this is Wh per hour = W avg
                
                h_total = 0
                for c in heating_cols:
                    h_total += float(row[c].strip())
                heating_kwh += h_total / 1000.0
                rows += 1
            except (ValueError, IndexError):
                continue
    
    return {
        'chiller_kwh': chiller_kwh,
        'heating_kwh': heating_kwh,
        'total_kwh': chiller_kwh + heating_kwh,
        'rows': rows,
    }

# Find the latest agent run
runs_dir = Path('logs/runs')
agent_runs = sorted(runs_dir.glob('run_*'))
latest_run = agent_runs[-1] if agent_runs else None

baseline_csv = Path('logs/baseline/simulation/eplusout.csv')
agent_csv = latest_run / 'simulation' / 'eplusout.csv' if latest_run else None

print("=" * 60)
print("EcoAgent Energy Savings Comparison")
print("=" * 60)

if not baseline_csv.exists():
    print("ERROR: Baseline CSV not found")
    sys.exit(1)
if not agent_csv or not agent_csv.exists():
    print("ERROR: Agent CSV not found")
    sys.exit(1)

print(f"\nBaseline: {baseline_csv}")
print(f"Agent:    {agent_csv}")
print(f"Agent run: {latest_run.name}")

baseline = load_energy(baseline_csv)
agent = load_energy(agent_csv)

print(f"\n{'Metric':<30} {'Baseline':>12} {'Agent':>12} {'Savings':>12} {'%':>8}")
print("-" * 74)

for label, key in [('Chiller Electricity (kWh)', 'chiller_kwh'),
                   ('Heating Energy (kWh)', 'heating_kwh'),
                   ('Total Energy (kWh)', 'total_kwh')]:
    b = baseline[key]
    a = agent[key]
    s = b - a
    pct = (s / b * 100) if b > 0 else 0
    print(f"{label:<30} {b:>12.1f} {a:>12.1f} {s:>12.1f} {pct:>7.1f}%")

print(f"\n{'Data points (hourly)':<30} {baseline['rows']:>12} {agent['rows']:>12}")

# Also check trace entries
trace_path = latest_run / 'agent' / 'trace.jsonl'
if trace_path.exists():
    import json
    traces = [json.loads(l) for l in open(trace_path)]
    proposals = sum(1 for t in traces if t.get('proposal_submitted'))
    print(f"\n{'Agent reasoning cycles':<30} {len(traces):>12}")
    print(f"{'Proposals submitted':<30} {proposals:>12}")
    print(f"{'Proposal rate':<30} {proposals/len(traces)*100 if traces else 0:>11.0f}%")

# Generate simple text-based chart
total_b = baseline['total_kwh']
total_a = agent['total_kwh']
bar_width = 40
b_bar = '#' * bar_width
a_bar = '#' * int(bar_width * total_a / total_b) if total_b > 0 else ''
print(f"\nTotal Energy Comparison:")
print(f"  Baseline: [{b_bar}] {total_b:.0f} kWh")
print(f"  Agent:    [{a_bar}] {total_a:.0f} kWh")

savings_pct = (total_b - total_a) / total_b * 100 if total_b > 0 else 0
print(f"\n  Net Reduction: {total_b - total_a:.0f} kWh ({savings_pct:.1f}%)")
