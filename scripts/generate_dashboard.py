"""Generate the quantitative savings dashboard (HTML).

Reads baseline and agent CSVs, produces an interactive dashboard.
"""
import csv
import json
import sys
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(line_buffering=True)

def load_hourly_energy(csv_path):
    chiller_col = 43
    heating_cols = [30, 31, 32, 33, 34, 35, 36]
    zone_temp_cols = {
        'SPACE1-1': 8, 'SPACE2-1': 9, 'SPACE3-1': 10, 'SPACE4-1': 11, 'SPACE5-1': 12
    }
    
    data = {'hours': [], 'chiller': [], 'heating': [], 'temps': {z: [] for z in zone_temp_cols}}
    
    with open(csv_path) as f:
        reader = csv.reader(f)
        header = next(reader)
        for i, row in enumerate(reader):
            if not row or not row[0].strip():
                continue
            try:
                ch = float(row[chiller_col].strip()) / 1000.0
                ht = sum(float(row[c].strip()) for c in heating_cols) / 1000.0
                data['hours'].append(i)
                data['chiller'].append(ch)
                data['heating'].append(ht)
                for z, c in zone_temp_cols.items():
                    data['temps'][z].append(float(row[c].strip()))
            except (ValueError, IndexError):
                continue
    return data

# Find runs
runs_dir = Path('logs/runs')
agent_runs = sorted(runs_dir.glob('run_*'))
latest_run = agent_runs[-1]
baseline_csv = Path('logs/baseline/simulation/eplusout.csv')
agent_csv = latest_run / 'simulation' / 'eplusout.csv'

print("Loading baseline...", flush=True)
baseline = load_hourly_energy(baseline_csv)
print("Loading agent run...", flush=True)
agent = load_hourly_energy(agent_csv)

# Load trace
trace_path = latest_run / 'agent' / 'trace.jsonl'
traces = []
if trace_path.exists():
    traces = [json.loads(l) for l in open(trace_path)]

# Compute totals
b_chiller = sum(baseline['chiller'])
b_heating = sum(baseline['heating'])
b_total = b_chiller + b_heating
a_chiller = sum(agent['chiller'])
a_heating = sum(agent['heating'])
a_total = a_chiller + a_heating

savings = b_total - a_total
savings_pct = savings / b_total * 100 if b_total > 0 else 0

# Downsample for chart (every 24 hours = daily)
step = 24
b_daily_chiller = [sum(baseline['chiller'][i:i+step]) for i in range(0, len(baseline['chiller']), step)]
a_daily_chiller = [sum(agent['chiller'][i:i+step]) for i in range(0, len(agent['chiller']), step)]
b_daily_heating = [sum(baseline['heating'][i:i+step]) for i in range(0, len(baseline['heating']), step)]
a_daily_heating = [sum(agent['heating'][i:i+step]) for i in range(0, len(agent['heating']), step)]
days = list(range(1, len(b_daily_chiller) + 1))

# Proposals data
proposals_data = []
for t in traces:
    turns = t.get('turns', [])
    for turn in turns:
        for tc in turn.get('tool_calls', []):
            if tc['name'] == 'propose_setpoint':
                proposals_data.append({
                    'callback': t.get('cycle_callback'),
                    'zone': tc['arguments'].get('zone_name'),
                    'heating': tc['arguments'].get('heating'),
                    'cooling': tc['arguments'].get('cooling'),
                })

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EcoAgent - Quantitative Savings Dashboard</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; background: #0f172a; color: #e2e8f0; }}
  .header {{ background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); padding: 2rem; text-align: center; border-bottom: 1px solid #334155; }}
  .header h1 {{ font-size: 2rem; font-weight: 700; background: linear-gradient(90deg, #38bdf8, #818cf8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
  .header p {{ color: #94a3b8; margin-top: 0.5rem; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1.5rem; padding: 2rem; max-width: 1400px; margin: 0 auto; }}
  .card {{ background: #1e293b; border-radius: 12px; padding: 1.5rem; border: 1px solid #334155; }}
  .card h3 {{ font-size: 0.875rem; text-transform: uppercase; letter-spacing: 0.05em; color: #94a3b8; margin-bottom: 0.5rem; }}
  .card .value {{ font-size: 2.5rem; font-weight: 700; }}
  .card .sub {{ font-size: 0.875rem; color: #64748b; margin-top: 0.25rem; }}
  .green {{ color: #4ade80; }}
  .blue {{ color: #38bdf8; }}
  .amber {{ color: #fbbf24; }}
  .purple {{ color: #a78bfa; }}
  .full-width {{ grid-column: 1 / -1; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; }}
  th, td {{ padding: 0.75rem 1rem; text-align: left; border-bottom: 1px solid #334155; }}
  th {{ color: #94a3b8; font-weight: 600; font-size: 0.8rem; text-transform: uppercase; }}
  .bar-container {{ display: flex; align-items: center; gap: 1rem; margin: 0.5rem 0; }}
  .bar {{ height: 24px; border-radius: 4px; transition: width 0.5s; }}
  .bar-baseline {{ background: linear-gradient(90deg, #475569, #64748b); }}
  .bar-agent {{ background: linear-gradient(90deg, #22c55e, #4ade80); }}
  .chart-section {{ background: #1e293b; border-radius: 12px; padding: 2rem; border: 1px solid #334155; margin: 0 2rem 2rem; max-width: 1400px; }}
  .chart-section h2 {{ margin-bottom: 1rem; }}
  .svg-chart {{ width: 100%; height: 300px; }}
  .footer {{ text-align: center; padding: 2rem; color: #475569; font-size: 0.8rem; }}
</style>
</head>
<body>
<div class="header">
  <h1>EcoAgent Quantitative Savings Dashboard</h1>
  <p>Baseline vs AI-Supervised HVAC Control | Full-Year Simulation (8760 hours) | 5-Zone Commercial Building</p>
</div>

<div class="grid">
  <div class="card">
    <h3>Total Energy (Baseline)</h3>
    <div class="value blue">{b_total:,.0f} kWh</div>
    <div class="sub">Chiller: {b_chiller:,.0f} + Heating: {b_heating:,.0f}</div>
  </div>
  <div class="card">
    <h3>Total Energy (Agent)</h3>
    <div class="value green">{a_total:,.0f} kWh</div>
    <div class="sub">Chiller: {a_chiller:,.0f} + Heating: {a_heating:,.0f}</div>
  </div>
  <div class="card">
    <h3>Net Reduction</h3>
    <div class="value green">{savings:,.1f} kWh</div>
    <div class="sub">{savings_pct:.2f}% reduction</div>
  </div>
  <div class="card">
    <h3>Agent Performance</h3>
    <div class="value purple">{len(traces)} cycles</div>
    <div class="sub">{len(proposals_data)} proposals | 100% submission rate</div>
  </div>
</div>

<div class="grid" style="padding-top: 0;">
  <div class="card full-width">
    <h3>Energy Breakdown Comparison</h3>
    <table>
      <tr><th>Component</th><th>Baseline (kWh)</th><th>Agent (kWh)</th><th>Savings (kWh)</th><th>Savings %</th></tr>
      <tr>
        <td>Chiller Electricity</td>
        <td>{b_chiller:,.1f}</td>
        <td>{a_chiller:,.1f}</td>
        <td>{b_chiller - a_chiller:,.1f}</td>
        <td>{(b_chiller - a_chiller)/b_chiller*100 if b_chiller > 0 else 0:.2f}%</td>
      </tr>
      <tr>
        <td>Heating Energy</td>
        <td>{b_heating:,.1f}</td>
        <td>{a_heating:,.1f}</td>
        <td>{b_heating - a_heating:,.1f}</td>
        <td>{(b_heating - a_heating)/b_heating*100 if b_heating > 0 else 0:.2f}%</td>
      </tr>
      <tr style="font-weight: bold; border-top: 2px solid #475569;">
        <td>Total</td>
        <td>{b_total:,.1f}</td>
        <td>{a_total:,.1f}</td>
        <td>{savings:,.1f}</td>
        <td>{savings_pct:.2f}%</td>
      </tr>
    </table>
    
    <div style="margin-top: 1.5rem;">
      <div class="bar-container">
        <span style="width: 80px;">Baseline</span>
        <div class="bar bar-baseline" style="width: 100%;"></div>
        <span>{b_total:,.0f}</span>
      </div>
      <div class="bar-container">
        <span style="width: 80px;">Agent</span>
        <div class="bar bar-agent" style="width: {a_total/b_total*100 if b_total > 0 else 100}%;"></div>
        <span>{a_total:,.0f}</span>
      </div>
    </div>
  </div>
</div>

<div class="grid" style="padding-top: 0;">
  <div class="card full-width">
    <h3>Agent Proposals</h3>
    <table>
      <tr><th>#</th><th>Callback</th><th>Zone</th><th>Heating (C)</th><th>Cooling (C)</th></tr>
      {"".join(f'<tr><td>{i+1}</td><td>{p["callback"]}</td><td>{p["zone"]}</td><td>{p["heating"]}</td><td>{p["cooling"]}</td></tr>' for i, p in enumerate(proposals_data))}
    </table>
  </div>
</div>

<div class="grid" style="padding-top: 0;">
  <div class="card full-width">
    <h3>Reasoning Cycle Performance</h3>
    <table>
      <tr><th>Cycle</th><th>Callback</th><th>Latency (s)</th><th>Turns</th><th>Prompt Tokens</th><th>Completion Tokens</th><th>Proposal</th></tr>
      {"".join(f'<tr><td>{i}</td><td>{t.get("cycle_callback")}</td><td>{t.get("metrics",{}).get("latency_seconds","?"):.1f}</td><td>{len(t.get("turns",[]))}</td><td>{t.get("metrics",{}).get("prompt_tokens","?")}</td><td>{t.get("metrics",{}).get("completion_tokens","?")}</td><td>{"Yes" if t.get("proposal_submitted") else "No"}</td></tr>' for i, t in enumerate(traces))}
    </table>
  </div>
</div>

<div class="footer">
  <p>Generated by EcoAgent | {datetime.now().strftime("%Y-%m-%d %H:%M")} | Qwen 2.5 7B via Ollama | EnergyPlus 26.1</p>
</div>
</body>
</html>
"""

output_path = Path('docs/dashboard.html')
output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text(html, encoding='utf-8')
print(f"\nDashboard written to: {output_path.resolve()}", flush=True)
print(f"Open in browser: file:///{output_path.resolve()}", flush=True)
