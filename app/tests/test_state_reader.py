from types import SimpleNamespace

from go2.state_reader import Go2StateReader


def test_state_snapshot():
    now = [5.0]
    reader = Go2StateReader(clock=lambda: now[0])
    message = SimpleNamespace(
        mode=3,
        gait_type=1,
        position=[1, 2, 3],
        velocity=[0.1, 0.2, 0.3],
        yaw_speed=0.4,
        body_height=0.32,
        imu_state=SimpleNamespace(rpy=[0.01, 0.02, 0.03]),
        range_obstacle=[0.5, 1.0, 1.5, 2.0],
        foot_force=[10, 20, 30, 40],
    )

    reader._on_sport(message)
    state = reader.snapshot()
    assert state["connected"]
    assert state["position"] == {"x": 1.0, "y": 2.0, "z": 3.0}
    assert state["imu"]["yaw"] == 0.03
    assert state["range_obstacle"] == [0.5, 1.0, 1.5, 2.0]

    now[0] += 1.01
    assert not reader.snapshot()["connected"]


def test_subscriptions_do_not_include_point_cloud(monkeypatch):
    import sys
    subscribers = []
    class Subscriber:
        def __init__(self, name, message_type):
            self.name, self.closed = name, False
            subscribers.append(self)
        def Init(self, callback, queue):
            pass
        def Close(self):
            self.closed = True
    monkeypatch.setitem(sys.modules, "unitree_sdk2py.core.channel",
                        SimpleNamespace(ChannelSubscriber=Subscriber))
    monkeypatch.setitem(sys.modules, "unitree_sdk2py.idl.unitree_go.msg.dds_",
                        SimpleNamespace(LowState_=object, SportModeState_=object))
    reader = Go2StateReader()
    reader.start()
    assert [sub.name for sub in subscribers] == ["rt/sportmodestate", "rt/lowstate"]
    assert "lidar" not in reader.snapshot()
    reader.stop()
    assert all(sub.closed for sub in subscribers)
