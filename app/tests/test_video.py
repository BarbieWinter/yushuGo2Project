from go2.video import VideoStream


class FakeVideoClient:
    def __init__(self):
        self.calls = 0

    def GetImageSample(self):
        self.calls += 1
        return (0, b"jpeg") if self.calls == 1 else (3104, None)


def test_mjpeg_frame():
    client = FakeVideoClient()
    stream = VideoStream(client)
    stream.initialize()
    try:
        first = next(stream.frames())
        second = next(stream.frames())
        assert first == second == b"--frame\r\nContent-Type: image/jpeg\r\n\r\njpeg\r\n"
    finally:
        stream.stop()


def test_readiness_requires_a_recent_frame():
    from unittest.mock import patch
    stream = VideoStream()
    stream._running = True
    assert not stream.ready
    with patch("go2.video.time.monotonic", return_value=10):
        stream._last_frame_at = 10
        assert stream.ready
        stream._last_frame_at = 0
        assert not stream.ready
