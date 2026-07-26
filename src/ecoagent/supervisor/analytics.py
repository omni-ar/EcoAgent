from ecoagent.controller.constants import STATE_IDLE, STATE_HEATING, STATE_COOLING
from ecoagent.supervisor.constants import STATE_SUPERVISOR


def compute_comfort_percentage(history):
    snapshots = history.get_range(0, history.size())
    if not snapshots:
        return 0.0
    comfortable = 0
    total = 0
    for snapshot in snapshots:
        has_supervisor = False
        all_idle = True
        for zone in snapshot.zones.values():
            if zone.controller_state == STATE_SUPERVISOR:
                has_supervisor = True
                break
            if zone.controller_state != STATE_IDLE:
                all_idle = False
        if has_supervisor:
            continue
        if all_idle:
            comfortable += 1
        total += 1
    if total == 0:
        return 0.0
    return (comfortable / total) * 100.0


def compute_safety_summary(history):
    snapshots = history.get_range(0, history.size())
    counts = {}
    for snapshot in snapshots:
        for zone in snapshot.zones.values():
            reason = zone.safety_guard_reason
            if reason and reason != "approved":
                counts[reason] = counts.get(reason, 0) + 1
    return counts


def compute_oscillation_count(history, zone_name, window=8):
    snapshots = history.get_range(0, min(window, history.size()))
    transitions = 0
    prev_state = None
    for snapshot in snapshots:
        zone = snapshot.zones.get(zone_name)
        if zone is None:
            continue
        state = zone.controller_state
        if state == STATE_SUPERVISOR:
            continue
        if prev_state is not None and state != prev_state:
            if (prev_state == STATE_HEATING and state == STATE_COOLING) or \
               (prev_state == STATE_COOLING and state == STATE_HEATING):
                transitions += 1
        if state in (STATE_HEATING, STATE_COOLING):
            prev_state = state
    return transitions


def compute_saturation_summary(history):
    snapshot = history.latest()
    if snapshot is None:
        return {}
    result = {}
    for zone_name, zone in snapshot.zones.items():
        result[zone_name] = {
            "saturation_flag": zone.saturation_flag,
        }
    return result


def compute_energy_summary(history):
    snapshots = history.get_range(0, history.size())
    if not snapshots:
        return {"chiller_power_mean_w": 0.0, "chiller_power_max_w": 0.0, "chiller_power_min_w": 0.0}
    values = [s.chiller_power_w for s in snapshots]
    return {
        "chiller_power_mean_w": sum(values) / len(values),
        "chiller_power_max_w": max(values),
        "chiller_power_min_w": min(values),
    }


def compute_zone_summary(history, zone_name):
    snapshot = history.latest()
    if snapshot is None:
        return {}
    zone = snapshot.zones.get(zone_name)
    if zone is None:
        return {}
    return zone.to_dict()


def compute_full_summary(history):
    return {
        "comfort_percentage": compute_comfort_percentage(history),
        "safety_triggers": compute_safety_summary(history),
        "oscillation_counts": {
            zone_name: compute_oscillation_count(history, zone_name)
            for zone_name in _zone_names_from_history(history)
        },
        "saturation_summary": compute_saturation_summary(history),
        "energy": compute_energy_summary(history),
        "history_window_size": history.size(),
    }


def _zone_names_from_history(history):
    snapshot = history.latest()
    if snapshot is None:
        return []
    return list(snapshot.zones.keys())
