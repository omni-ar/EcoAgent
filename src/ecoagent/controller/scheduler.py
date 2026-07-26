from ecoagent.controller.constants import (
    STATUS_INITIALIZING, STATUS_RUNNING, STATUS_STOPPED, STATUS_DISABLED,
    INITIALIZING_TIMEOUT_CYCLES,
)


class Scheduler:
    def __init__(self, init_timeout=INITIALIZING_TIMEOUT_CYCLES, reminder_interval=96):
        self.callback_counter = 0
        self.warmup_active = False
        self.simulation_clock = (0, 0, 0, 0)
        self.simulation_status = STATUS_INITIALIZING
        self._init_counter = 0
        self._handles_resolved = False
        self.init_timeout = init_timeout
        self.reminder_interval = reminder_interval
        self.timeout_triggered = False
        self.should_log_reminder = False

    def notify_handles_resolved(self, all_zones_failed):
        self._handles_resolved = True
        if all_zones_failed:
            self.simulation_status = STATUS_DISABLED

    def tick(self, api, state):
        """Returns True if the controller should execute this cycle."""
        self.should_log_reminder = False

        if api.exchange.warmup_flag(state):
            self.warmup_active = True
            return False

        self.warmup_active = False
        self.callback_counter += 1

        self.simulation_clock = (
            api.exchange.month(state),
            api.exchange.day_of_month(state),
            api.exchange.hour(state),
            api.exchange.minutes(state),
        )

        if self.simulation_status == STATUS_DISABLED:
            if self.callback_counter % self.reminder_interval == 0:
                self.should_log_reminder = True
            return False

        if self.simulation_status == STATUS_STOPPED:
            return False

        if self.simulation_status == STATUS_INITIALIZING:
            self._init_counter += 1
            if self._handles_resolved:
                self.simulation_status = STATUS_RUNNING
            elif self._init_counter > self.init_timeout:
                self.simulation_status = STATUS_DISABLED
                self.timeout_triggered = True
                return False
            return True

        return self.simulation_status == STATUS_RUNNING

    def stop(self):
        self.simulation_status = STATUS_STOPPED
