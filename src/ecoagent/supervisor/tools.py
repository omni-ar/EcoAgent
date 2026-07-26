from ecoagent.controller.constants import ZONE_NAMES
from ecoagent.supervisor.supervisor import SetpointProposal
from ecoagent.supervisor import analytics as _analytics


class ToolRegistry:
    def __init__(self, history, supervisor, event_bus, get_latest_snapshot):
        self._history = history
        self._supervisor = supervisor
        self._event_bus = event_bus
        self._get_latest_snapshot = get_latest_snapshot

    def get_runtime_state(self):
        try:
            snapshot = self._get_latest_snapshot()
            if snapshot is None:
                return {"error": "no_data", "message": "No callback cycles completed yet."}
            return snapshot.to_dict()
        except Exception as e:
            return {"error": "internal", "message": str(e)}

    def get_zone(self, zone_name):
        try:
            if zone_name not in ZONE_NAMES:
                return {"error": "unknown_zone", "message": f"Zone '{zone_name}' not found."}
            snapshot = self._get_latest_snapshot()
            if snapshot is None:
                return {"error": "no_data", "message": "No callback cycles completed yet."}
            zone = snapshot.zones.get(zone_name)
            if zone is None:
                return {"error": "unknown_zone", "message": f"Zone '{zone_name}' not in snapshot."}
            return zone.to_dict()
        except Exception as e:
            return {"error": "internal", "message": str(e)}

    def get_scheduler_status(self):
        try:
            snapshot = self._get_latest_snapshot()
            if snapshot is None:
                return {"error": "no_data", "message": "No callback cycles completed yet."}
            return {
                "status": snapshot.scheduler_status,
                "callback_number": snapshot.callback_number,
                "simulated_timestamp": {
                    "month": snapshot.simulated_timestamp[0],
                    "day": snapshot.simulated_timestamp[1],
                    "hour": snapshot.simulated_timestamp[2],
                    "minute": snapshot.simulated_timestamp[3],
                },
            }
        except Exception as e:
            return {"error": "internal", "message": str(e)}

    def get_history(self, offset=0, count=10):
        try:
            snapshots = self._history.get_range(offset, count)
            return [s.to_dict() for s in snapshots]
        except Exception as e:
            return {"error": "internal", "message": str(e)}

    def get_analytics_summary(self):
        try:
            return _analytics.compute_full_summary(self._history)
        except Exception as e:
            return {"error": "internal", "message": str(e)}

    def propose_setpoint(self, zone_name, heating, cooling, source="external"):
        try:
            if zone_name not in ZONE_NAMES:
                return {"error": "unknown_zone", "message": f"Zone '{zone_name}' not found."}
            if self._supervisor is None:
                return {"error": "supervisor_disabled", "message": "Supervisor interface is not enabled."}
            proposal = SetpointProposal(zone_name, heating, cooling, source=source)
            accepted = self._supervisor.submit_proposal(proposal)
            if not accepted:
                return {"error": "invalid_proposal", "message": "Proposal rejected by pre-validation."}
            return {"status": "pending", "zone": zone_name}
        except Exception as e:
            return {"error": "internal", "message": str(e)}

    def list_tools(self):
        return [
            {
                "name": "get_runtime_state",
                "description": "Current controller state for all zones.",
                "arguments": [],
            },
            {
                "name": "get_zone",
                "description": "Current state for a specific zone.",
                "arguments": [{"name": "zone_name", "type": "string", "required": True}],
            },
            {
                "name": "get_scheduler_status",
                "description": "Scheduler lifecycle status and simulation clock.",
                "arguments": [],
            },
            {
                "name": "get_history",
                "description": "Historical snapshots by offset and count.",
                "arguments": [
                    {"name": "offset", "type": "integer", "required": False, "default": 0},
                    {"name": "count", "type": "integer", "required": False, "default": 10},
                ],
            },
            {
                "name": "get_analytics_summary",
                "description": "Comfort, safety, oscillation, and energy metrics.",
                "arguments": [],
            },
            {
                "name": "propose_setpoint",
                "description": "Submit advisory setpoint proposal for a zone.",
                "arguments": [
                    {"name": "zone_name", "type": "string", "required": True},
                    {"name": "heating", "type": "float", "required": True},
                    {"name": "cooling", "type": "float", "required": True},
                    {"name": "source", "type": "string", "required": False, "default": "external"},
                ],
            },
        ]
