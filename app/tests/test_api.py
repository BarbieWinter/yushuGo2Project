from types import SimpleNamespace

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from api.control import health, router
from app import app
from go2.controller import Go2Controller


class Snapshot:
    def __init__(self, value):
        self.value = value

    def snapshot(self):
        return self.value


def test_front_jump_uses_sdk_and_preserves_stop_protection(monkeypatch):
    from tests.test_controller import FakeClient
    from unittest.mock import patch
    sdk = FakeClient()
    controller = Go2Controller('test', client=sdk)
    monkeypatch.setattr(app.state, 'controller', controller)
    monkeypatch.setattr(app.state, 'patrol', SimpleNamespace(stop=lambda: None, running=lambda: False))
    client = TestClient(app)
    assert 'data-action="/api/front_jump">前跳' in client.get('/').text
    assert client.post('/api/front_jump').json() == {'command': 'front_jump', 'code': 0}
    assert sdk.calls == [('FrontJump', ())]
    sdk.calls.clear()
    controller._moving = True
    with patch.object(sdk, 'StopMove', return_value=-1):
        assert client.post('/api/front_jump').status_code == 503
    assert not sdk.calls
    assert controller.status()['stop_pending']


def test_handstand_exit_blocks_following_actions(monkeypatch):
    from tests.test_controller import FakeClient
    sdk = FakeClient()
    controller = Go2Controller('test', client=sdk)
    controller.handstand()
    monkeypatch.setattr(app.state, 'controller', controller)
    client = TestClient(app)
    assert client.post('/api/handstand/exit').status_code == 200
    for path in ('/api/sit', '/api/stand', '/api/patrol/start', '/api/cross_step'):
        assert client.post(path).status_code == 503
    assert sdk.calls == [('HandStand', (True,)), ('HandStand', (False,))]
    assert client.post('/api/stop').status_code == 200
    assert sdk.calls[-1] == ('StopMove', ())


def test_cross_step_mutes_without_restoring_volume(monkeypatch):
    from unittest.mock import Mock, call

    controller = SimpleNamespace(
        ready=True, stop=Mock(return_value=0), stop_if_active=Mock(return_value=False),
        cross_step=Mock(return_value=(0, None)),
    )
    audio = SimpleNamespace(
        lock=__import__('threading').Lock(),
        set_volume=Mock(),
    )
    monkeypatch.setattr(app.state, 'controller', controller)
    monkeypatch.setattr(app.state, 'audio', audio)
    monkeypatch.setattr(app.state, 'patrol', SimpleNamespace(stop=lambda: None, running=lambda: False))

    response = TestClient(app).post('/api/cross_step')

    assert response.json() == {'command': 'cross_step', 'code': 0, 'finish_code': None}
    audio.set_volume.assert_called_once_with(0)
    controller.cross_step.assert_called_once_with(2.0)

    audio.set_volume.reset_mock()
    controller.cross_step.side_effect = RuntimeError('failed')
    assert TestClient(app).post('/api/cross_step').status_code == 503
    assert audio.set_volume.call_args_list == [call(0)]


def request_with(controller_ready=False, robot_connected=False):
    state = SimpleNamespace(
        controller=SimpleNamespace(ready=controller_ready),
        state_reader=Snapshot({
            "connected": robot_connected,
            "battery": 76,
            "motor_temperature": [42, 44],
            "body_height": 0.31,
            "velocity": {"vx": 0.2, "vy": -0.1, "vz": 0.0},
        }),
        video=SimpleNamespace(ready=False),
    )
    return SimpleNamespace(app=SimpleNamespace(state=state))


def test_health_is_a_readiness_check():
    response = Response()
    data = health(request_with(), response)
    assert response.status_code == 503
    assert not data["ok"]

    response = Response()
    data = health(request_with(True, True), response)
    assert response.status_code == 200
    assert data["ok"]
    assert data["telemetry"] == {
        "battery": 76,
        "motor_temperature": [42, 44],
        "body_height": 0.31,
        "velocity": {"vx": 0.2, "vy": -0.1, "vz": 0.0},
    }


def test_health_is_unavailable_until_stop_acknowledged():
    request = request_with(True, True)
    controller = Go2Controller("test", client=object())
    controller._stop_pending = True
    request.app.state.controller = controller
    response = Response()
    assert not health(request, response)["ok"]
    assert response.status_code == 503


def test_fastapi_uses_lifespan_not_deprecated_event_lists():
    assert not app.router.on_startup
    assert not app.router.on_shutdown


def test_control_api_rejects_a_move_older_than_stop():
    class Client:
        def __init__(self):
            self.calls = []

        def Move(self, *args):
            self.calls.append(("Move", args))
            return 0

        def StopMove(self):
            self.calls.append(("StopMove", ()))
            return 0

    class Patrol:
        def running(self):
            return False

        def stop(self):
            return False

    sdk = Client()
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.controller = Go2Controller("test", client=sdk)
    test_app.state.patrol = Patrol()
    test_app.state.state_reader = Snapshot({"connected": True})
    test_app.state.video = SimpleNamespace(ready=False)

    with TestClient(test_app) as client:
        assert client.post("/api/move", json={
            "vx": 10, "client_id": "browser", "sequence": 1,
        }).json()["accepted"]
        assert client.post("/api/stop", json={
            "client_id": "browser", "sequence": 2,
        }).status_code == 200
        stale = client.post("/api/move", json={
            "vx": 0.2, "client_id": "browser", "sequence": 1,
        })
        assert stale.status_code == 200
        assert not stale.json()["accepted"]

    assert sdk.calls == [("Move", (0.5, 0.0, 0.0)), ("StopMove", ())]


def test_patrol_start_uses_manual_speed():
    class Patrol:
        speed = None

        def running(self):
            return False

        def start(self, vx, vyaw):
            self.speed = (vx, vyaw)
            return True, "ok"

    patrol = Patrol()
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.patrol = patrol
    test_app.state.controller = SimpleNamespace(ready=True, stop=lambda: 0)

    with TestClient(test_app) as client:
        response = client.post("/api/patrol/start", json={"vx": 0.7, "vyaw": 2.3})

    assert response.status_code == 200
    assert patrol.speed == (0.7, 2.3)


def test_removed_routes_and_pages():
    # Do not enter lifespan: hardware must not be initialized in this test.
    client = TestClient(app)
    for path in ("/api/slam/map", "/api/d435i/color", "/api/d435i/depth"):
        assert client.get(path).status_code == 404
    for path in ("/", "/patrol", "/settings"):
        page = client.get(path)
        assert page.status_code == 200
        assert "D435i" not in page.text and "slam-map" not in page.text


def test_api_rejects_nonfinite_move_and_nonpositive_patrol_speed():
    client = TestClient(app)
    assert client.post("/api/move", json={
        "vx": "Infinity", "client_id": "test", "sequence": 1,
    }).status_code == 422
    for speed in (0, -1, "Infinity"):
        assert client.post("/api/patrol/start", json={"vx": speed, "vyaw": 1}).status_code == 422


def test_stop_sdk_failure_returns_503_and_remains_pending(monkeypatch):
    class Client:
        def StopMove(self):
            return 7
    controller = Go2Controller("test", client=Client())
    monkeypatch.setattr(app.state, "controller", controller)
    response = TestClient(app).post("/api/stop")
    assert response.status_code == 503
    assert controller._stop_pending


def test_websocket_only_reports_retained_components():
    with TestClient(app).websocket_connect("/ws/state") as socket:
        state = socket.receive_json()
        assert "patrol" in state
        assert "slam" not in state and "d435i" not in state and "lidar" not in state


def test_move_waits_for_patrol_exit(monkeypatch):
    from tests.test_controller import FakeClient
    monkeypatch.setattr(app.state, "controller", Go2Controller("test", client=FakeClient()))
    monkeypatch.setattr(app.state, "patrol", SimpleNamespace(stop=lambda: None, running=lambda: True))
    response = TestClient(app).post("/api/move", json={
        "vx": 0.1, "client_id": "test", "sequence": 1,
    })
    assert response.status_code == 409


def test_new_action_buttons_and_sdk_calls():
    from tests.test_controller import FakeClient
    sdk = FakeClient()
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.controller = Go2Controller("test", client=sdk)
    test_app.state.patrol = SimpleNamespace(stop=lambda: None, running=lambda: False)
    with TestClient(test_app) as client:
        for action in ("handstand", "scrape"):
            response = client.post("/api/" + action)
            assert response.status_code == 200
            assert response.json() == {"command": action, "code": 0}
    assert sdk.calls == [
        ("HandStand", (True,)),
        ("HandStand", (False,)), ("StopMove", ()), ("Scrape", ()),
    ]
    page = TestClient(app).get("/").text
    assert 'class="brand"' not in page
    assert 'id="handstand-toggle" type="button" aria-pressed="false">倒立' in page
    assert 'data-action="/api/scrape">拜年' in page


def test_idle_stand_does_not_require_stopmove():
    from unittest.mock import Mock
    sdk = Mock()
    sdk.StopMove.return_value = -1
    sdk.StandUp.return_value = 0
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.controller = Go2Controller("test", client=sdk)
    test_app.state.patrol = SimpleNamespace(stop=lambda: None, running=lambda: False)
    with TestClient(test_app) as client:
        response = client.post("/api/stand")
    assert response.status_code == 200
    sdk.StopMove.assert_not_called()
    sdk.StandUp.assert_called_once()
    assert not test_app.state.controller.stop_if_stale()

def test_idle_handstand_does_not_require_stopmove():
    from unittest.mock import Mock
    sdk = Mock()
    sdk.StopMove.return_value = -1
    sdk.HandStand.return_value = 0
    test_app = FastAPI()
    test_app.include_router(router)
    controller = Go2Controller("test", client=sdk)
    test_app.state.controller = controller
    test_app.state.patrol = SimpleNamespace(stop=lambda: None, running=lambda: False)
    with TestClient(test_app) as client:
        assert client.post("/api/handstand").status_code == 200
    sdk.StopMove.assert_not_called()
    sdk.HandStand.assert_called_once_with(True)
    assert not controller.stop_if_stale()


def test_control_origin_blocks_actions_before_side_effects():
    from tests.test_controller import FakeClient
    sdk = FakeClient()
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.controller = Go2Controller("test", client=sdk)
    test_app.state.patrol = SimpleNamespace(stop=lambda: None, running=lambda: False)
    client = TestClient(test_app)
    for headers in (
        {"Origin": "https://untrusted.example"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Content-Type": "application/x-www-form-urlencoded"},
        {"Content-Type": "text/plain"},
    ):
        for path in ("/api/handstand", "/api/stand", "/api/stop", "/api/patrol/start"):
            assert client.post(path, headers=headers).status_code == 403
    assert not sdk.calls
    assert client.post("/api/handstand", headers={"Origin": "http://testserver"}).status_code == 200
    assert client.post("/api/stop", json={"client_id": "browser", "sequence": 1}).status_code == 200


def test_stale_move_does_not_stop_patrol():
    from unittest.mock import Mock
    from tests.test_controller import FakeClient
    sdk = FakeClient()
    controller = Go2Controller("test", client=sdk)
    controller.stop("browser", 2)
    patrol = SimpleNamespace(stop=Mock(), running=lambda: True)
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.controller = controller
    test_app.state.patrol = patrol
    result = TestClient(test_app).post("/api/move", json={
        "vx": 0.2, "client_id": "browser", "sequence": 1,
    })
    assert result.status_code == 200 and not result.json()["accepted"]
    patrol.stop.assert_not_called()
    assert sdk.calls == [("StopMove", ())]


def test_idle_actions_do_not_send_stopmove_between_modes():
    from tests.test_controller import FakeClient
    sdk = FakeClient()
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.controller = Go2Controller("test", client=sdk)
    test_app.state.patrol = SimpleNamespace(stop=lambda: None, running=lambda: False)

    with TestClient(test_app) as client:
        assert client.post("/api/stand_down").status_code == 200
        assert client.post("/api/recovery").status_code == 200

    assert sdk.calls == [("StandDown", ()), ("RecoveryStand", ())]
