"""Context Builder — assembles LLM prompt context from McpAdapter.

Calls adapter read tools to build a context dict containing building
summary and selective zone trends for zones needing attention.
"""

from ecoagent.controller.constants import (
    ZONE_NAMES, COMFORT_TRIGGER_LOW, COMFORT_TRIGGER_HIGH,
)


class ContextBuilder:
    """Builds structured context for LLM prompts from adapter data."""

    def __init__(self, adapter):
        """
        Args:
            adapter: McpAdapter instance for reading building state.
        """
        self._adapter = adapter

    def build(self):
        """Build context dict for LLM consumption.

        Returns:
            dict with keys:
                - callback_number: int or None
                - building_summary: dict from adapter.get_building_summary()
                - zone_trends: dict mapping zone_name → trend dict or None
                - context_error: str or None
        """
        context_error = None

        # Get building summary (always)
        summary = self._adapter.get_building_summary()
        if isinstance(summary, dict) and "error" in summary:
            return {
                "callback_number": None,
                "building_summary": {},
                "zone_trends": {},
                "context_error": f"building_summary failed: {summary}",
            }

        callback_number = summary.get("callback_number")

        # Determine which zones need trends
        zone_trends = {}
        zones = summary.get("zones", {})
        for zone_name in ZONE_NAMES:
            zone_data = zones.get(zone_name)
            if zone_data is None:
                zone_trends[zone_name] = None
                continue

            temp = zone_data.get("temperature_c")
            state = zone_data.get("controller_state")

            needs_trend = False
            if state is not None and state != "IDLE":
                needs_trend = True
            if temp is not None and (temp < COMFORT_TRIGGER_LOW or temp > COMFORT_TRIGGER_HIGH):
                needs_trend = True

            if needs_trend:
                trend = self._adapter.get_zone_trend(zone_name, window=4)
                if isinstance(trend, dict) and "error" in trend:
                    zone_trends[zone_name] = None
                    context_error = f"trend failed for {zone_name}: {trend}"
                else:
                    zone_trends[zone_name] = trend
            else:
                zone_trends[zone_name] = None

        return {
            "callback_number": callback_number,
            "building_summary": summary,
            "zone_trends": zone_trends,
            "context_error": context_error,
        }
