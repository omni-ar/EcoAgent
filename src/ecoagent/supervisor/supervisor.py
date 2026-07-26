import math
import time
from ecoagent.controller.constants import ZONE_NAMES


class SetpointProposal:
    def __init__(self, zone_name, heating_setpoint, cooling_setpoint,
                 source="external", ttl_cycles=1):
        self.zone_name = zone_name
        self.heating_setpoint = heating_setpoint
        self.cooling_setpoint = cooling_setpoint
        self.source = source
        self.timestamp = time.time()
        self.ttl_cycles = ttl_cycles
        self.submitted_at_callback = -1
        self.status = "NEW"


class SupervisorInterface:
    def __init__(self):
        self._proposals = {}

    def submit_proposal(self, proposal, current_callback=-1):
        if proposal.zone_name not in ZONE_NAMES:
            return False
        if not isinstance(proposal.heating_setpoint, (int, float)):
            return False
        if not isinstance(proposal.cooling_setpoint, (int, float)):
            return False
        if math.isnan(proposal.heating_setpoint) or math.isinf(proposal.heating_setpoint):
            return False
        if math.isnan(proposal.cooling_setpoint) or math.isinf(proposal.cooling_setpoint):
            return False

        if current_callback >= 0:
            proposal.submitted_at_callback = current_callback

        proposal.status = "PENDING"
        self._proposals[proposal.zone_name] = proposal
        return True

    def get_pending_proposal(self, zone_name):
        proposal = self._proposals.get(zone_name)
        if proposal is not None and proposal.status == "PENDING":
            proposal.status = "SELECTED"
            return proposal
        return None

    def consume_proposal(self, zone_name):
        proposal = self._proposals.pop(zone_name, None)
        if proposal is not None:
            proposal.status = "CONSUMED"

    def clear_expired(self, current_callback):
        expired = []
        for zone_name, proposal in list(self._proposals.items()):
            if proposal.status != "PENDING":
                continue
            if proposal.submitted_at_callback < 0:
                proposal.submitted_at_callback = current_callback
            if current_callback - proposal.submitted_at_callback >= proposal.ttl_cycles:
                expired.append(zone_name)

        for zone_name in expired:
            proposal = self._proposals.pop(zone_name)
            proposal.status = "EXPIRED"

    def get_all_pending(self):
        return {k: v for k, v in self._proposals.items() if v.status == "PENDING"}

    def clear_all(self):
        self._proposals.clear()
