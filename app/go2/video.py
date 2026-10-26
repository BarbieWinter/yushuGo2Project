import logging
import threading
import time

from config import VIDEO_FPS, VIDEO_RPC_TIMEOUT


log = logging.getLogger(__name__)


class VideoStream:
    def __init__(self, client=None):
        self._client = client
        self._condition = threading.Condition()
        self._stop_event = threading.Event()
        self._thread = None
        self._frame = None
        self._version = 0
        self._error_code = None
        self._running = False
        self._last_frame_at = float("-inf")

    @property
    def ready(self):
        return self._running and time.monotonic() - self._last_frame_at < VIDEO_RPC_TIMEOUT + 1.0

    def initialize(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        if self._client is None:
            from unitree_sdk2py.go2.video.video_client import VideoClient

            self._client = VideoClient()
            self._client.SetTimeout(VIDEO_RPC_TIMEOUT)
            self._client.Init()
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._capture, name="go2-video", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread:
            self._thread.join(timeout=VIDEO_RPC_TIMEOUT + 0.5)
        self._thread = None

    def frames(self):
        version = -1
        while self._running:
            with self._condition:
                self._condition.wait_for(
                    lambda: self._version != version or not self._running,
                    timeout=VIDEO_RPC_TIMEOUT + 1.0,
                )
                if not self._running:
                    return
                frame = self._frame
                version = self._version
            if frame is None:
                continue
            if not self.ready:
                return
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"

    def _capture(self) -> None:
        interval = 1.0 / VIDEO_FPS
        while not self._stop_event.is_set():
            started = time.monotonic()
            try:
                code, data = self._client.GetImageSample()
            except Exception:
                log.exception("GetImageSample failed")
                code, data = -1, None
            if code == 0 and data:
                with self._condition:
                    self._last_frame_at = time.monotonic()
                    self._frame = bytes(data)
                    self._version += 1
                    self._error_code = None
                    self._condition.notify_all()
                self._stop_event.wait(max(0.0, interval - (time.monotonic() - started)))
                continue
            if code != self._error_code:
                log.warning("GetImageSample failed: %s", code)
                self._error_code = code
            self._stop_event.wait(0.2)
