import logging
import threading

from config import WATCHDOG_TIMEOUT
from go2.controller import Go2Controller


log = logging.getLogger(__name__)


class MoveWatchdog:
    def __init__(self, controller: Go2Controller, timeout: float = WATCHDOG_TIMEOUT):
        self.controller = controller
        self.timeout = timeout
        self._stop_event = threading.Event()
        self._thread = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="go2-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        last_error = ""
        while not self._stop_event.wait(0.05):
            try:
                if self.controller.stop_if_stale(self.timeout):
                    log.warning("Move command timed out; StopMove() sent")
                if last_error:
                    log.info("Move watchdog recovered")
                last_error = ""
            except Exception as error:
                if str(error) != last_error:
                    log.exception("Move watchdog failed; retrying in 1 second")
                last_error = str(error)
                self._stop_event.wait(1.0)
