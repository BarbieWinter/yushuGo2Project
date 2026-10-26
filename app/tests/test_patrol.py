import json
import math
import tempfile
import threading
from pathlib import Path
import pytest

from go2.patrol import PATROL_JOIN_TIMEOUT, PatrolController


class FakeController:
    def set_straight_reference(self, heading):
        pass

    def move(self, *_args, **_kwargs):
        return None

    def stop(self):
        return None


class ClearStateReader:
    def snapshot(self):
        return {
            "connected": True,
            "range_obstacle": [0, 0, 0, 0],
            "position": {"x": 0, "y": 0},
            "imu": {"yaw": 0},
            "yaw_speed": 0,
        }


class RadarStateReader(ClearStateReader):
    def snapshot(self):
        state = super().snapshot()
        state["range_obstacle"] = [1.5, 1.5, 1.5, 1.5]
        return state


@pytest.mark.parametrize("ranges", [None, [0, 0, 0, 0], [0.01, 0.01], [float("nan")]])
@pytest.mark.parametrize("action", ["forward", "backward_distance", "left", "turn_left"])
def test_patrol_does_not_require_or_use_obstacle_data(ranges, action):
    moved = threading.Event()
    class Reader(ClearStateReader):
        def snapshot(self):
            state = super().snapshot()
            state.pop("range_obstacle")
            if ranges is not None:
                state["range_obstacle"] = ranges
            return state
    class Controller(FakeController):
        def move(self, *_args):
            moved.set()
            patrol._stop_event.set()
    patrol = PatrolController(Controller(), Reader())
    assert patrol.set_path([{"action": action, "duration": 1, "distance": 1}])[0]
    assert patrol.start()[0]
    try:
        assert moved.wait(1)
    finally:
        patrol.stop()


def test_patrol_still_stops_when_robot_state_is_lost():
    stopped = threading.Event()
    class Reader(ClearStateReader):
        connected = True
        def snapshot(self):
            return dict(super().snapshot(), connected=self.connected)
    reader = Reader()
    class Controller(FakeController):
        def move(self, *_args):
            reader.connected = False
        def stop(self):
            stopped.set()
    patrol = PatrolController(Controller(), reader)
    assert patrol.start()[0]
    try:
        assert stopped.wait(1)
        assert patrol.snapshot() == {"status": "blocked", "reason": "机器人状态丢失"}
    finally:
        patrol.stop()
    assert not patrol.start()[0]


def test_path_validation():
    patrol = PatrolController(None, None)
    ok, _ = patrol.set_path([
        {"action": "forward", "duration": 2},
        {"action": "turn_right", "duration": 1.5},
    ])
    assert ok
    assert patrol.path()[1] == {"action": "turn_right", "duration": 1.5}
    assert patrol.set_path([{"action": "turn_left_90", "duration": 2.2}])[0]
    assert patrol.path()[0]["duration"] == 2.2
    assert patrol.set_path([{"action": "turn_right_180", "duration": 3.9}])[0]
    assert patrol.path()[0]["action"] == "turn_right_180"
    assert not patrol.set_path([{"action": "turn_left_90", "duration": 20}])[0]
    assert patrol.set_path([{"action": "wait", "duration": 1}])[0]
    assert patrol.set_path([{"action": "forward_distance", "distance": 1.25}])[0]
    assert patrol.path()[0] == {"action": "forward_distance", "distance": 1.25}
    assert not patrol.set_path([{"action": "backward_distance", "distance": 0.01}])[0]
    assert round(PatrolController._traveled({"x": 1, "y": 1}, {"x": 1.3, "y": 1.4}), 6) == 0.5
    assert round(PatrolController._angle_delta(-3.1, 3.1), 3) == 0.083
    progress = PatrolController._turn_step(0, 0.1, 0)
    assert round(PatrolController._turn_step(progress, 0.05, 0.1), 3) == 0.05
    assert PatrolController._turn_step(0, -0.1, 0) < 0
    assert not patrol.set_path([{"action": "jump", "duration": 1}])[0]
    assert not patrol.set_path([{}])[0]
    assert not patrol.set_path("not-a-list")[0]

    with tempfile.TemporaryDirectory() as directory:
        path_file = Path(directory) / "patrol_path.json"
        saved = PatrolController(None, None, path_file)
        assert saved.set_path([{"action": "left", "duration": 3}])[0]
        assert json.loads(path_file.read_text(encoding="utf-8"))[0]["action"] == "left"
        assert PatrolController(None, None, path_file).path()[0]["duration"] == 3.0
        path_file.write_text('[{"duration": 1}]', encoding="utf-8")
        assert PatrolController(None, None, path_file).path()[0]["action"] == "forward"


def test_stop_does_not_wait_forever_for_sdk_thread():
    class StuckThread:
        timeout = None

        def is_alive(self):
            return True

        def join(self, timeout=None):
            self.timeout = timeout

    patrol = PatrolController(FakeController(), RadarStateReader())
    patrol._thread = StuckThread()
    assert patrol.stop()
    assert patrol._thread.timeout == PATROL_JOIN_TIMEOUT
    assert patrol.snapshot()["status"] == "stopping"


def test_patrol_uses_manual_forward_and_turn_speed():
    turned = threading.Event()

    class RecordingController(FakeController):
        def __init__(self):
            self.calls = []

        def move(self, vx, vy, vyaw, **kwargs):
            self.calls.append((vx, vy, vyaw, kwargs))
            if vyaw:
                turned.set()

        def stop(self):
            return None

    controller = RecordingController()
    patrol = PatrolController(controller, RadarStateReader())
    assert patrol.set_path([
        {"action": "forward", "duration": 0.1},
        {"action": "turn_left", "duration": 0.1},
    ])[0]
    assert patrol.start(0.7, 2.3)[0]
    assert turned.wait(1)
    patrol.stop()
    assert (0.5, 0.0, 0.0, {}) in controller.calls
    assert (0.0, 0.0, 1.0, {}) in controller.calls


def test_fixed_turn_reverses_after_overshoot():
    import math
    class Reader(RadarStateReader):
        yaw = 0
        def snapshot(self):
            state = super().snapshot()
            state["imu"]["yaw"] = self.yaw
            return state
    reader = Reader()
    reversed_turn = threading.Event()
    class Controller:
        def move(self, vx, vy, vyaw):
            if vyaw > 0:
                reader.yaw = math.pi / 2 + 0.1
            elif vyaw < 0:
                reversed_turn.set()
                patrol._stop_event.set()
        def stop(self):
            return 0
    patrol = PatrolController(Controller(), reader)
    assert patrol.set_path([{"action": "turn_left_90", "duration": 1}])[0]
    assert patrol.start()[0]
    try:
        assert reversed_turn.wait(1)
    finally:
        patrol.stop()
