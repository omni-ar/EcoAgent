import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ecoagent.controller.constants import STATUS_INITIALIZING, STATUS_DISABLED
from ecoagent.controller.orchestrator import Orchestrator


class MockAPI:
    class MockExchange:
        def warmup_flag(self, s): return False
        def month(self, s): return 1
        def day_of_month(self, s): return 1
        def hour(self, s): return 12
        def minutes(self, s): return 0
        def get_variable_value(self, s, h): return 20.0
    
    def __init__(self):
        self.exchange = self.MockExchange()


def test_initialization_timeout():
    print("=" * 60)
    print("Automated Test: Initialization Timeout & Periodic Reminders")
    print("=" * 60)

    orchestrator = Orchestrator(log_dir="logs/test_output/test_timeout")
    # Mark actuator manager resolved so resolve_handles block is skipped, leaving handles_resolved=False
    orchestrator.actuator_manager._resolved = True

    orchestrator.scheduler.reminder_interval = 5
    callback = orchestrator.create_callback()

    api = MockAPI()
    mock_state = "MOCK_STATE"

    # Callbacks 1..10 (INITIALIZING state)
    for i in range(1, 11):
        callback(api, mock_state)
        print(f"Callback #{i}: Scheduler Status = {orchestrator.scheduler.simulation_status}")
        assert orchestrator.scheduler.simulation_status == STATUS_INITIALIZING, f"Expected INITIALIZING at step {i}"

    # Callback 11 (Timeout threshold reached: 11 > 10)
    callback(api, mock_state)
    print(f"Callback #11: Scheduler Status = {orchestrator.scheduler.simulation_status}")
    assert orchestrator.scheduler.simulation_status == STATUS_DISABLED, "Expected STATUS_DISABLED at step 11"

    # Callbacks 12..25 (Check periodic reminders logged at multiples of reminder_interval=5)
    for i in range(12, 26):
        callback(api, mock_state)

    orchestrator.finalize()

    # Read log file and verify events
    log_path = Path(orchestrator.logger.log_path)
    lines = log_path.read_text().strip().split("\n")
    events = [json.loads(line) for line in lines if "event" in json.loads(line)]

    timeout_events = [e for e in events if e["event"] == "CRITICAL_INITIALIZATION_TIMEOUT"]
    reminder_events = [e for e in events if e["event"] == "CONTROLLER_DISABLED_REMINDER"]

    print("\n--- EVENT VERIFICATION ---")
    print(f"CRITICAL_INITIALIZATION_TIMEOUT events logged: {len(timeout_events)}")
    print(f"CONTROLLER_DISABLED_REMINDER events logged: {len(reminder_events)}")

    assert len(timeout_events) == 1, "Expected exactly 1 CRITICAL_INITIALIZATION_TIMEOUT event"
    assert timeout_events[0]["callback_number"] == 11, "Expected timeout event at callback #11"
    assert len(reminder_events) >= 2, "Expected periodic reminder events when disabled"

    print("\n" + "=" * 60)
    print("AUTOMATED INITIALIZATION TIMEOUT TEST: PASS")
    print("=" * 60)


if __name__ == "__main__":
    test_initialization_timeout()
