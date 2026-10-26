import threading
from functools import wraps

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, FiniteFloat

from config import GO2_IFACE, MAX_VX, MAX_VY, MAX_VYAW
from go2.controller import Go2Controller


def check_control_origin(request: Request):
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if (
        (origin is not None and origin != str(request.base_url).rstrip("/"))
        or request.headers.get("sec-fetch-site") == "cross-site"
        or content_type in {"application/x-www-form-urlencoded", "multipart/form-data", "text/plain"}
    ):
        raise HTTPException(status_code=403, detail="拒绝跨来源或表单控制请求")


router = APIRouter(prefix="/api", dependencies=[Depends(check_control_origin)])
# ponytail: one robot per process; use per-robot locks only for multi-robot support.
_command_lock = threading.RLock()


def serialized(action):
    @wraps(action)
    def call(*args, **kwargs):
        with _command_lock:
            request = kwargs.get("request")
            if request is not None and request.url.path not in {
                "/api/stop", "/api/patrol/stop", "/api/handstand/exit",
            }:
                controller = request.app.state.controller
                if isinstance(controller, Go2Controller):
                    controller.require_transition_complete()
            return action(*args, **kwargs)
    return call


def stop_patrol(request):
    request.app.state.patrol.stop()
    if request.app.state.patrol.running():
        raise HTTPException(status_code=409, detail="巡逻仍在停止，请稍后重试")


class MoveCommand(BaseModel):
    vx: FiniteFloat = 0.0
    vy: FiniteFloat = 0.0
    vyaw: FiniteFloat = 0.0
    client_id: str = Field(min_length=1, max_length=64)
    sequence: int = Field(ge=1)


class StopCommand(BaseModel):
    client_id: str = Field(min_length=1, max_length=64)
    sequence: int = Field(ge=1)


class PatrolStep(BaseModel):
    action: str
    duration: float = 0.0
    distance: float = 0.0


class PatrolPath(BaseModel):
    steps: List[PatrolStep]


class PatrolSpeed(BaseModel):
    vx: FiniteFloat = Field(gt=0)
    vyaw: FiniteFloat = Field(gt=0)


def get_controller(request: Request) -> Go2Controller:
    controller = request.app.state.controller
    if not controller.ready:
        raise HTTPException(status_code=503, detail="Go2 controller unavailable")
    return controller


def run_action(request: Request, command: str, method: str) -> dict:
    stop_patrol(request)
    controller = get_controller(request)
    controller.stop_if_active()
    return {"command": command, "code": getattr(controller, method)()}


@router.get("/health")
def health(request: Request, response: Response) -> dict:
    controller = request.app.state.controller
    robot = request.app.state.state_reader.snapshot()
    control_status = controller.status() if isinstance(controller, Go2Controller) else {}
    ok = controller.ready and robot["connected"] and not control_status.get("stop_pending", False)
    response.status_code = status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "ok": ok,
        "interface": GO2_IFACE,
        "control": control_status,
        "limits": {"vx": MAX_VX, "vy": MAX_VY, "vyaw": MAX_VYAW},
        "telemetry": {
            "battery": robot.get("battery"),
            "motor_temperature": robot.get("motor_temperature", []),
            "body_height": robot.get("body_height"),
            "velocity": robot.get("velocity", {"vx": 0.0, "vy": 0.0, "vz": 0.0}),
        },
        "components": {
            "controller": controller.ready,
            "robot_state": robot["connected"],
            "front_camera": request.app.state.video.ready,
        },
    }


@router.post("/move")
@serialized
def move(cmd: MoveCommand, request: Request) -> dict:
    controller = get_controller(request)
    if not controller.move_sequence_valid(cmd.client_id, cmd.sequence):
        return {"command": "move", "code": None, "accepted": False}
    if request.app.state.patrol.running():
        stop_patrol(request)
    vx, vy, vyaw, code, accepted = controller.move(
        cmd.vx, cmd.vy, cmd.vyaw, cmd.client_id, cmd.sequence
    )
    return {
        "command": "move", "vx": vx, "vy": vy, "vyaw": vyaw,
        "code": code, "accepted": accepted,
    }


@router.post("/stop")
@serialized
def stop(request: Request, cmd: Optional[StopCommand] = None) -> dict:
    request.app.state.patrol.stop()
    controller = get_controller(request)
    code = controller.stop(cmd.client_id, cmd.sequence) if cmd else controller.stop()
    return {"command": "stop", "code": code}


@router.post("/stand")
@serialized
def stand(request: Request) -> dict:
    stop_patrol(request)
    return {"command": "stand", "code": get_controller(request).stand()}


@router.post("/stand_down")
@serialized
def stand_down(request: Request) -> dict:
    return run_action(request, "stand_down", "stand_down")


@router.post("/balance_stand")
@serialized
def balance_stand(request: Request) -> dict:
    return run_action(request, "balance_stand", "balance_stand")


@router.post("/recovery")
@serialized
def recovery(request: Request) -> dict:
    return run_action(request, "recovery", "recovery")


@router.post("/sit")
@serialized
def sit(request: Request) -> dict:
    return run_action(request, "sit", "sit")


@router.post("/rise_sit")
@serialized
def rise_sit(request: Request) -> dict:
    return run_action(request, "rise_sit", "rise_sit")


@router.post("/hello")
@serialized
def hello(request: Request) -> dict:
    return run_action(request, "hello", "hello")


@router.post("/stretch")
@serialized
def stretch(request: Request) -> dict:
    return run_action(request, "stretch", "stretch")


@router.post("/heart")
@serialized
def heart(request: Request) -> dict:
    return run_action(request, "heart", "heart")


@router.post("/handstand")
@serialized
def handstand(request: Request) -> dict:
    stop_patrol(request)
    return {"command": "handstand", "code": get_controller(request).handstand()}


@router.post("/scrape")
@serialized
def scrape(request: Request) -> dict:
    return run_action(request, "scrape", "scrape")


@router.post("/handstand/exit")
@serialized
def handstand_exit(request: Request) -> dict:
    return {"command": "handstand_exit", "code": get_controller(request).exit_handstand()}


@router.post("/front_jump")
@serialized
def front_jump(request: Request) -> dict:
    return run_action(request, "front_jump", "front_jump")


@router.post("/cross_step")
@serialized
def cross_step(request: Request) -> dict:
    stop_patrol(request)
    controller = get_controller(request)
    controller.stop_if_active()
    audio = request.app.state.audio
    with audio.lock:
        audio.set_volume(0)
    start_code, stop_code = controller.cross_step(2.0)
    return {"command": "cross_step", "code": start_code, "finish_code": stop_code}


@router.post("/patrol/start")
@serialized
def patrol_start(request: Request, speed: Optional[PatrolSpeed] = None) -> dict:
    if not request.app.state.patrol.running():
        get_controller(request).stop()
    ok, message = request.app.state.patrol.start(
        speed.vx if speed else MAX_VX,
        speed.vyaw if speed else MAX_VYAW,
    )
    if not ok:
        raise HTTPException(status_code=409, detail=message)
    return {"command": "patrol_start", "code": 0}


@router.get("/patrol/path")
def patrol_path(request: Request) -> dict:
    return {"steps": request.app.state.patrol.path()}


@router.post("/patrol/path")
@serialized
def patrol_path_save(path: PatrolPath, request: Request) -> dict:
    steps = []
    for step in path.steps:
        steps.append({"action": step.action, "duration": step.duration, "distance": step.distance})
    ok, message = request.app.state.patrol.set_path(steps)
    if not ok:
        raise HTTPException(status_code=409, detail=message)
    return {"command": "patrol_path", "code": 0, "steps": request.app.state.patrol.path()}


@router.post("/patrol/stop")
@serialized
def patrol_stop(request: Request) -> dict:
    request.app.state.patrol.stop()
    return {"command": "patrol_stop", "code": get_controller(request).stop()}
