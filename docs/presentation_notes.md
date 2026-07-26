# EcoAgent — Presentation Notes

## Slide 1: Title
- **EcoAgent**: AI-Supervised Building Energy Optimization
- Team/individual name
- Honeywell Eco-Loop Building Agents Hackathon

## Slide 2: Problem
- Buildings consume 40% of global energy
- Traditional BMS uses rigid schedules
- No real-time adaptation to weather, occupancy, grid conditions
- Opportunity: LLMs can reason about building state and optimize dynamically

## Slide 3: Solution Overview
- EnergyPlus (physics-based simulation) + Qwen 2.5 7B (open-source LLM)
- Model Context Protocol (MCP) bridges the two
- Fully autonomous closed-loop: observe → reason → act → verify
- Zero cloud dependency — runs entirely on local hardware

## Slide 4: Architecture
[Use the architecture diagram from docs/architecture.md]
- 4 layers: Simulation → Controller → Supervisor → Agent
- Safety Guard ensures LLM cannot violate thermal bounds
- MCP tools give LLM structured access to building state

## Slide 5: MCP Tool-Calling
- 8 tools: 7 observation + 1 action
- OpenAI function-calling format
- ReAct pattern: Turn 0 (observe) → Turn 1 (act)
- Example: get_building_summary → propose_setpoint

## Slide 6: Safety Design
- Hard bounds: Heating [18,22]°C, Cooling [23,27]°C
- Deadband ≥ 1°C always enforced
- Dwell timer prevents oscillation
- Readback verification on every actuator write
- LLM proposals are ADVISORY — Safety Guard has final say

## Slide 7: Results
- 3 successful reasoning cycles per simulation
- 100% proposal submission rate
- Energy comparison: baseline vs agent (from dashboard)
- All proposals passed Safety Guard validation

## Slide 8: Latency Engineering
- Challenge: 7B model on CPU generates at ~7 tok/s
- Solution: max_tokens cap (200), conciseness prompt, model warmup
- Result: 12s per warm cycle (down from 59s), fits 3+ cycles in 70s sim

## Slide 9: Demo
- Show trace.jsonl with real proposals
- Show dashboard.html with energy comparison
- Show the closed-loop: EnergyPlus → Controller → Agent → EnergyPlus

## Slide 10: Future Work
- Larger model (13B+) for better reasoning
- GPU inference for 10x throughput
- Multi-zone parallel proposals
- Seasonal strategy adaptation
- Integration with real BMS systems
