from go2.controller import Go2Controller
from unittest.mock import patch


class FakeClient:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args):
            self.calls.append((name, args))
            return 0
        return call


def test_normal_handstand_exit_and_emergency_override():
    import pytest
    from config import HANDSTAND_EXIT_SECONDS
    now = [10.0]
    sdk = FakeClient()
    c = Go2Controller('test', client=sdk, clock=lambda: now[0])
    c.handstand()
    assert c.exit_handstand() == 0
    assert c.exit_handstand() == 0
    assert not c.stop_if_stale()
    for action in (lambda: c.move(.1, 0, 0), c.stand, c.handstand, c.sit, c.cross_step):
        with pytest.raises(RuntimeError, match='退出等待中'):
            action()
    assert sdk.calls == [('HandStand', (True,)), ('HandStand', (False,))]
    now[0] += HANDSTAND_EXIT_SECONDS
    c.stand()
    c.handstand()
    c.exit_handstand()
    c.stop()
    assert sdk.calls[-1] == ('StopMove', ())
    assert not c.status()['handstand_exiting']


def test_normal_handstand_exit_failure_remains_pending():
    import pytest
    c = Go2Controller('test', client=FakeClient())
    c.handstand()
    with patch.object(c._client, 'HandStand', return_value=-1):
        with pytest.raises(RuntimeError):
            c.exit_handstand()
    assert c.status()['stop_pending'] and c.status()['handstand_active']
    assert c.stop_if_stale()


def test_limits_and_watchdog():
    now = [10.0]
    client = FakeClient()
    controller = Go2Controller("test", client=client, clock=lambda: now[0])

    assert controller.move(10, -10, 10)[:3] == (0.5, -0.4, 1.0)
    now[0] += 0.41
    assert controller.stop_if_stale()
    assert client.calls == [
        ("Move", (0.5, -0.4, 1.0)),
        ("StopMove", ()),
    ]

    assert controller.move(float("nan"), float("inf"), float("-inf"))[:3] == (0.0, 0.0, 0.0)



def test_cross_step_stops_after_two_seconds():
    client = FakeClient()
    controller = Go2Controller("test", client=client)
    with patch("go2.controller.threading.Timer") as timer:
        assert controller.cross_step() == (0, None)
        assert timer.call_args.args[0] == 2.0
        timer.return_value.start.assert_called_once()
        timer.call_args.args[1]()
    assert client.calls == [("CrossStep", (True,)), ("CrossStep", (False,)), ("StopMove", ())]


def test_extra_actions_use_official_sdk_calls():
    client = FakeClient()
    controller = Go2Controller("test", client=client)
    controller.stand_down()
    controller.balance_stand()
    controller.hello()
    controller.stretch()
    controller.heart()
    assert client.calls == [
        ("StandDown", ()),
        ("BalanceStand", ()),
        ("Hello", ()),
        ("Stretch", ()),
        ("Heart", ()),
    ]


def test_stale_move_cannot_restart_after_stop():
    client = FakeClient()
    controller = Go2Controller("test", client=client)

    assert controller.move(0.2, 0, 0, "browser", 1)[-1]
    controller.stop("browser", 2)
    assert not controller.move(0.2, 0, 0, "browser", 1)[-1]
    assert client.calls == [
        ("Move", (0.2, 0, 0)),
        ("StopMove", ()),
    ]


def test_straight_move_holds_initial_heading():
    from config import PATROL_FORWARD_YAW_TRIM
    yaw = [1.0]
    client = FakeClient()
    controller = Go2Controller("test", client=client, heading=lambda: yaw[0])

    assert controller.move(0.5, 0, 0)[2] == PATROL_FORWARD_YAW_TRIM
    yaw[0] = 1.1
    assert controller.move(0.5, 0, 0)[2] < 0
    controller.stop()
    yaw[0] = 2.0
    assert controller.move(0.5, 0, 0)[2] == PATROL_FORWARD_YAW_TRIM


def test_straight_move_uses_odom_lateral_error():
    from config import PATROL_FORWARD_YAW_TRIM
    pose = [[0.0, 0.0, 1.0]]
    client = FakeClient()
    controller = Go2Controller(
        "test", client=client, heading=lambda: pose[0][2], pose=lambda: tuple(pose[0])
    )
    assert controller.move(0.5, 0, 0)[2] == PATROL_FORWARD_YAW_TRIM
    pose[0][1] = 0.2
    assert controller.move(0.5, 0, 0)[2] < 0


def test_stop_cancels_timer_without_stopping_later_motion():
    client = FakeClient()
    controller = Go2Controller("test", client=client)
    with patch("go2.controller.threading.Timer") as timer:
        controller.cross_step()
        controller.stop()
        timer.return_value.cancel.assert_called_once()
        controller.move(0.1, 0, 0)
        count = len(client.calls)
        timer.call_args.args[1]()
        assert len(client.calls) == count


def test_failed_stop_is_retried_and_blocks_motion():
    import pytest
    for failure in (7, RuntimeError("offline")):
        client = FakeClient()
        controller = Go2Controller("test", client=client)
        with patch.object(client, "StopMove", side_effect=[failure, 0]) as stop:
            with pytest.raises(RuntimeError):
                controller.stop()
            with pytest.raises(RuntimeError):
                controller.move(0.1, 0, 0)
            assert controller.stop_if_stale()
            assert stop.call_count == 2
            assert not controller.stop_if_stale()


def test_cross_step_failure_still_sends_stopmove():
    import pytest
    client = FakeClient()
    controller = Go2Controller("test", client=client)
    controller._cross_step_active = True
    with patch.object(client, "CrossStep", return_value=8):
        with pytest.raises(RuntimeError):
            controller.stop()
    assert ("StopMove", ()) in client.calls
    assert controller.stop_if_stale()


def test_move_owner_is_released_by_stop():
    controller = Go2Controller("test", client=FakeClient())
    assert controller.move(0.1, 0, 0, "first", 1)[-1]
    assert not controller.move(0.1, 0, 0, "second", 1)[-1]
    controller.stop()
    assert controller.move(0.1, 0, 0, "second", 1)[-1]


def test_stop_timeout_retries_once_and_accepts_acknowledgement():
    client = FakeClient()
    controller = Go2Controller("test", client=client)
    with patch.object(client, "StopMove", side_effect=[3104, 0]) as stop:
        assert controller.stop() == 0
        assert stop.call_count == 2
        assert client.calls == [("Move", (0.0, 0.0, 0.0))]
        assert not controller.status()["stop_pending"]
        assert not controller.stop_if_stale()


def test_stop_timeout_sends_zero_but_does_not_claim_success():
    import pytest
    client = FakeClient()
    controller = Go2Controller("test", client=client)
    with patch.object(client, "StopMove", side_effect=[3104, 3104, 0]) as stop:
        with pytest.raises(RuntimeError, match="StopMove.*3104"):
            controller.stop()
        assert stop.call_count == 2
        assert client.calls == [("Move", (0.0, 0.0, 0.0))]
        assert controller.status()["stop_pending"]
        assert "StopMove" in controller.status()["last_error"]
        with pytest.raises(RuntimeError, match="停止尚未确认"):
            controller.move(0.1, 0, 0)
        assert controller.stop_if_stale()
        assert stop.call_count == 3
        assert not controller.status()["stop_pending"]


def test_action_timeout_is_named_and_not_replayed():
    import pytest
    client = FakeClient()
    controller = Go2Controller("test", client=client)
    with patch.object(client, "StandUp", return_value=3104) as stand:
        with pytest.raises(RuntimeError, match="StandUp.*3104"):
            controller.stand()
        assert controller.stop_if_stale()
        stand.assert_called_once()


def test_handstand_exit_failure_keeps_stop_pending():
    import pytest
    client = FakeClient()
    controller = Go2Controller("test", client=client)
    assert controller.handstand() == 0
    assert not controller.move(0.1, 0, 0)[-1]
    with patch.object(client, "HandStand", side_effect=[3104, 0]) as handstand:
        with pytest.raises(RuntimeError, match="HandStand.*3104"):
            controller.stop()
        assert controller.status()["stop_pending"]
        assert client.calls[-1] == ("StopMove", ())
        assert controller.stop_if_stale()
        assert handstand.call_args_list == [((False,),), ((False,),)]
    assert not controller.status()["stop_pending"]
    assert controller.move(0.1, 0, 0)[-1]


def test_handstand_entry_timeout_still_exits_without_replaying_entry():
    import pytest
    client = FakeClient()
    controller = Go2Controller("test", client=client)
    with patch.object(client, "HandStand", side_effect=[3104, 0]) as handstand:
        with pytest.raises(RuntimeError, match="HandStand.*3104"):
            controller.handstand()
        assert controller.stop_if_stale()
        assert handstand.call_args_list == [((True,),), ((False,),)]


def test_stand_preserves_stop_protection():
    import pytest
    for flag in ("_moving", "_cross_step_active", "_handstand_active", "_stop_pending"):
        client = FakeClient()
        controller = Go2Controller("test", client=client)
        setattr(controller, flag, True)
        with patch.object(client, "StopMove", return_value=-1):
            with pytest.raises(RuntimeError, match="StopMove.*-1"):
                controller.stand()
        assert ("StandUp", ()) not in client.calls
        assert controller.status()["stop_pending"]
        assert controller.stand() == 0
        assert client.calls[-2:] == [("StopMove", ()), ("StandUp", ())]

def test_handstand_does_not_bypass_failed_stop():
    import pytest
    for flag in ("_moving", "_cross_step_active", "_handstand_active", "_stop_pending"):
        client = FakeClient()
        controller = Go2Controller("test", client=client)
        setattr(controller, flag, True)
        with patch.object(client, "StopMove", return_value=-1):
            with pytest.raises(RuntimeError, match="StopMove.*-1"):
                controller.handstand()
        assert ("HandStand", (True,)) not in client.calls
        assert controller.status()["stop_pending"]


def test_disconnected_motion_and_watchdog():
    import pytest
    connected = [True]
    sdk = FakeClient()
    controller = Go2Controller("test", client=sdk, connected=lambda: connected[0])
    controller.move(0.2, 0, 0)
    connected[0] = False
    assert controller.stop_if_stale()
    assert sdk.calls[-1] == ("StopMove", ())
    with pytest.raises(RuntimeError, match="机器人状态丢失"):
        controller.move(0.2, 0, 0)
    assert controller.stop() == 0
    connected[0] = True
    controller.move(0.2, 0, 0)
    connected[0] = False
    with pytest.raises(RuntimeError, match="机器人状态丢失"):
        controller.move(0.2, 0, 0)
    assert sdk.calls[-1] == ("StopMove", ())


def test_sequence_capacity_preserves_stop_watermarks():
    import pytest
    controller = Go2Controller("test", client=FakeClient())
    controller.stop("original", 10)
    for i in range(200):
        controller.stop(str(i), 1)
    assert len(controller._sequences) == 128
    assert not controller.move(0.2, 0, 0, "original", 9)[-1]
    with pytest.raises(RuntimeError, match="控制会话已满"):
        controller.move(0.2, 0, 0, "new", 1)
    assert controller.move(0.2, 0, 0, "original", 11)[-1]
    assert controller.stop("new", 2) == 0
    assert len(controller._sequences) == 128


def test_idle_action_switch_skips_stop_and_rejection_does_not_latch():
    import pytest
    client = FakeClient()
    controller = Go2Controller("test", client=client)

    controller.stand_down()
    assert not controller.stop_if_active()
    with patch.object(client, "Heart", return_value=-1):
        with pytest.raises(RuntimeError, match="Heart.*-1"):
            controller.heart()
    assert not controller.status()["stop_pending"]
    assert controller.stand() == 0
    assert client.calls == [("StandDown", ()), ("StandUp", ())]


def test_nonwalking_posture_rejects_move_and_does_not_call_stopmove():
    import pytest
    walking_ready = [False]
    client = FakeClient()
    controller = Go2Controller(
        "test", client=client, walking_ready=lambda: walking_ready[0]
    )

    with pytest.raises(RuntimeError, match="姿态.*起立"):
        controller.move(0.5, 0, 0)
    assert controller.stop() == 0
    assert not client.calls

    controller._stop_pending = True
    assert controller.stand() == 0
    assert client.calls == [("StandUp", ())]
    walking_ready[0] = True
    assert controller.move(0.5, 0, 0)[-1]
