class CycleCompleted:
    def __init__(self, snapshot):
        self.snapshot = snapshot


class SafetyTriggered:
    def __init__(self, zone_name, reason, callback_number):
        self.zone_name = zone_name
        self.reason = reason
        self.callback_number = callback_number


class ReadbackFailure:
    def __init__(self, zone_name, callback_number, written_h, readback_h, written_c, readback_c):
        self.zone_name = zone_name
        self.callback_number = callback_number
        self.written_h = written_h
        self.readback_h = readback_h
        self.written_c = written_c
        self.readback_c = readback_c


class ZoneDegraded:
    def __init__(self, zone_name, reason, callback_number):
        self.zone_name = zone_name
        self.reason = reason
        self.callback_number = callback_number


class SupervisorProposalAccepted:
    def __init__(self, zone_name, heating, cooling, callback_number):
        self.zone_name = zone_name
        self.heating = heating
        self.cooling = cooling
        self.callback_number = callback_number


class SupervisorProposalModified:
    def __init__(self, zone_name, requested_heating, requested_cooling,
                 actual_heating, actual_cooling, reason, callback_number):
        self.zone_name = zone_name
        self.requested_heating = requested_heating
        self.requested_cooling = requested_cooling
        self.actual_heating = actual_heating
        self.actual_cooling = actual_cooling
        self.reason = reason
        self.callback_number = callback_number


class SupervisorProposalRejected:
    def __init__(self, zone_name, reason, callback_number):
        self.zone_name = zone_name
        self.reason = reason
        self.callback_number = callback_number


class SchedulerDisabled:
    def __init__(self, reason, callback_number):
        self.reason = reason
        self.callback_number = callback_number


class SimulationStarted:
    def __init__(self, callback_number):
        self.callback_number = callback_number


class EventBus:
    def __init__(self):
        self._listeners = {}
        self.listener_error_count = 0
        self.last_listener_error = None

    def subscribe(self, event_type, listener):
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        self._listeners[event_type].append(listener)

    def emit(self, event):
        listeners = self._listeners.get(type(event), [])
        for listener in listeners:
            try:
                listener(event)
            except Exception as e:
                self.listener_error_count += 1
                listener_name = getattr(listener, "__name__", str(listener))
                self.last_listener_error = {
                    "event_type": type(event).__name__,
                    "listener": listener_name,
                    "error_message": str(e),
                    "exception_type": type(e).__name__,
                }

    def clear(self):
        self._listeners.clear()
        self.listener_error_count = 0
        self.last_listener_error = None
