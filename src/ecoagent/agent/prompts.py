"""Agent Prompt Templates — system prompt and user message builder.

The system prompt defines the agent's role, constraints, and available tools.
The user message builder formats building state into structured context.
"""

import json

SYSTEM_PROMPT = """\
You are an HVAC supervisory agent for a 5-zone commercial building simulated in EnergyPlus.

ROLE:
You observe real-time building performance data and propose setpoint adjustments to optimize energy efficiency while maintaining thermal comfort.

CONSTRAINTS:
- Your proposals are ADVISORY. Every proposal passes through a Safety Guard that enforces hard bounds and dwell timers. You cannot bypass it.
- Heating setpoint bounds: 18.0°C to 22.0°C
- Cooling setpoint bounds: 23.0°C to 27.0°C
- Minimum deadband: 1.0°C (cooling - heating >= 1.0)
- Comfort triggers: below 21.5°C or above 24.5°C
- The deterministic controller handles cycle-by-cycle control. You provide strategic setpoint optimization.

AVAILABLE TOOLS:
- get_runtime_state: Current state for all zones (temperatures, setpoints, controller states).
- get_zone(zone_name): Detailed state for one zone.
- get_scheduler_status: Simulation clock and scheduler lifecycle.
- get_history(offset, count): Historical snapshots for trend analysis.
- get_analytics_summary: Comfort percentage, safety triggers, energy metrics.
- propose_setpoint(zone_name, heating, cooling, source): Submit a setpoint proposal.
- get_zone_trend(zone_name, window): Temperature and setpoint trend for a zone.
- get_building_summary: Merged scheduler, zones, and analytics in one call.

STRATEGY:
1. OBSERVE: Read building state before acting. Use get_building_summary for overview.
2. ANALYZE: Identify zones where energy can be saved without compromising comfort.
3. ACT: Propose setpoint changes only when justified by thermal conditions.
4. DO NOT propose for zones already within comfort and operating efficiently.

ENERGY-SAVING STRATEGIES:
- Raise cooling setpoints when zones are well below the cooling trigger (24.5°C).
- Lower heating setpoints when zones are well above the heating trigger (21.5°C).
- Widen the deadband during mild outdoor conditions to reduce HVAC cycling.
- Avoid aggressive setpoint changes that cause oscillation.

ZONES: SPACE1-1, SPACE2-1, SPACE3-1, SPACE4-1, SPACE5-1

Respond with tool calls when you want to take action. If no action is needed, respond with a brief observation.
"""


def build_user_message(context):
    """Format building context dict into a structured user message.

    Args:
        context: dict from ContextBuilder.build() containing building_summary,
                 zone_trends, callback_number, and optional context_error.

    Returns:
        str: Formatted message for the LLM user role.
    """
    parts = []

    cb = context.get("callback_number", "?")
    parts.append(f"=== Building State at Callback {cb} ===\n")

    summary = context.get("building_summary", {})

    # Scheduler
    sched = summary.get("scheduler", {})
    ts = sched.get("simulated_timestamp", {})
    parts.append(
        f"Scheduler: {sched.get('status', '?')} | "
        f"Sim Time: Month {ts.get('month', '?')} Day {ts.get('day', '?')} "
        f"Hour {ts.get('hour', '?')}:{ts.get('minute', 0):02d}"
    )

    # Outdoor & chiller
    parts.append(
        f"Outdoor: {summary.get('outdoor_temp_c', '?')}°C | "
        f"Chiller: {summary.get('chiller_power_w', '?')} W"
    )

    # Zone states
    parts.append("\n--- Zone States ---")
    zones = summary.get("zones", {})
    for zname in sorted(zones.keys()):
        z = zones[zname]
        parts.append(
            f"  {zname}: {z.get('temperature_c', '?'):.1f}°C | "
            f"H={z.get('heating_setpoint', '?'):.1f} C={z.get('cooling_setpoint', '?'):.1f} | "
            f"State={z.get('controller_state', '?')}"
        )

    # Analytics
    analytics = summary.get("analytics", {})
    if analytics:
        parts.append(
            f"\nComfort: {analytics.get('comfort_percentage', '?'):.1f}% | "
            f"History Window: {analytics.get('history_window_size', '?')}"
        )
        energy = analytics.get("energy", {})
        if energy:
            parts.append(
                f"Chiller Mean: {energy.get('chiller_power_mean_w', 0):.0f} W | "
                f"Max: {energy.get('chiller_power_max_w', 0):.0f} W"
            )

    # Zone trends (only for zones the context builder flagged)
    trends = context.get("zone_trends", {})
    active_trends = {k: v for k, v in trends.items() if v is not None}
    if active_trends:
        parts.append("\n--- Zone Trends (Needing Attention) ---")
        for zname, trend in sorted(active_trends.items()):
            dps = trend.get("data_points", [])
            if dps:
                temps = [d.get("temperature_c", 0) for d in dps]
                parts.append(
                    f"  {zname}: {len(dps)} points | "
                    f"Temp range: {min(temps):.1f}–{max(temps):.1f}°C"
                )

    err = context.get("context_error")
    if err:
        parts.append(f"\n[Context Error: {err}]")

    return "\n".join(parts)
