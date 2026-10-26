from unittest.mock import Mock

from go2.watchdog import MoveWatchdog


def test_failed_stop_retries_once_per_second():
    watchdog = MoveWatchdog(Mock(stop_if_stale=Mock(side_effect=RuntimeError("-1"))))
    waits = []
    watchdog._stop_event.wait = lambda delay: waits.append(delay) or len(waits) == 3

    watchdog._run()

    assert waits == [0.05, 1.0, 0.05]
    watchdog.controller.stop_if_stale.assert_called_once()
