"""MCP Adapter — wraps frozen ToolRegistry and adds composite tools.

Single backend for both the in-process agent and the standalone MCP server.
All results are plain dicts (JSON-serializable).
"""

from ecoagent.controller.constants import ZONE_NAMES


class McpAdapter:
    """Wraps ToolRegistry with composite read tools for LLM consumption."""

    def __init__(self, tool_registry):
        self._registry = tool_registry

    # ── Direct passthroughs (6 tools) ────────────────────────────

    def get_runtime_state(self):
        """Current controller state for all zones."""
        return self._registry.get_runtime_state()

    def get_zone(self, zone_name):
        """Current state for a specific zone."""
        return self._registry.get_zone(zone_name)

    def get_scheduler_status(self):
        """Scheduler lifecycle status and simulation clock."""
        return self._registry.get_scheduler_status()

    def get_history(self, offset=0, count=10):
        """Historical snapshots by offset and count."""
        return self._registry.get_history(offset, count)

    def get_analytics_summary(self):
        """Comfort, safety, oscillation, and energy metrics."""
        return self._registry.get_analytics_summary()

    def propose_setpoint(self, zone_name, heating, cooling, source="mcp_agent"):
        """Submit advisory setpoint proposal for a zone."""
        return self._registry.propose_setpoint(zone_name, heating, cooling, source)

    # ── Composite tools (2 tools) ────────────────────────────────

    def get_zone_trend(self, zone_name, window=8):
        """Extract per-zone time series from history.

        Returns temperature, setpoints, and controller state for a single
        zone across the most recent ``window`` snapshots.
        """
        if zone_name not in ZONE_NAMES:
            return {"error": "unknown_zone", "message": f"Zone '{zone_name}' not found."}
        if not (1 <= window <= 96):
            return {"error": "invalid_window", "message": "window must be between 1 and 96."}

        history = self._registry.get_history(0, window)
        if isinstance(history, dict) and "error" in history:
            return {"error": "composition_failed", "detail": history}
        if not history:
            return {"error": "no_data", "message": "No history available."}

        callback_number = history[0].get("callback_number") if history else None

        data_points = []
        for snap in history:
            zone_data = snap.get("zones", {}).get(zone_name)
            if zone_data is None:
                continue
            data_points.append({
                "callback_number": snap.get("callback_number"),
                "simulated_timestamp": snap.get("simulated_timestamp"),
                "temperature_c": zone_data.get("temperature_c"),
                "heating_setpoint": zone_data.get("heating_setpoint"),
                "cooling_setpoint": zone_data.get("cooling_setpoint"),
                "controller_state": zone_data.get("controller_state"),
                "outdoor_temp_c": snap.get("outdoor_temp_c"),
            })

        return {
            "zone_name": zone_name,
            "window": window,
            "callback_number": callback_number,
            "data_points": data_points,
        }

    def get_building_summary(self):
        """Merge scheduler status, runtime state, and analytics into one dict.

        Includes ``callback_number`` at top level for staleness detection.
        """
        scheduler = self.get_scheduler_status()
        if isinstance(scheduler, dict) and "error" in scheduler:
            return {"error": "composition_failed", "detail": scheduler}

        state = self.get_runtime_state()
        if isinstance(state, dict) and "error" in state:
            return {"error": "composition_failed", "detail": state}

        analytics = self.get_analytics_summary()
        if isinstance(analytics, dict) and "error" in analytics:
            return {"error": "composition_failed", "detail": analytics}

        return {
            "callback_number": state.get("callback_number"),
            "scheduler": scheduler,
            "zones": state.get("zones", {}),
            "outdoor_temp_c": state.get("outdoor_temp_c"),
            "chiller_power_w": state.get("chiller_power_w"),
            "analytics": analytics,
        }

    # ── Tool manifest ────────────────────────────────────────────

    def list_tools(self):
        """Return 8-tool manifest with OpenAI function-calling schema."""
        base_tools = self._registry.list_tools()
        composite_tools = [
            {
                "name": "get_zone_trend",
                "description": "Temperature and setpoint trend for a zone over recent history.",
                "arguments": [
                    {"name": "zone_name", "type": "string", "required": True},
                    {"name": "window", "type": "integer", "required": False, "default": 8},
                ],
            },
            {
                "name": "get_building_summary",
                "description": "Merged scheduler, zone states, and analytics in one call.",
                "arguments": [],
            },
        ]
        return base_tools + composite_tools
