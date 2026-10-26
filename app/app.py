import logging
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.control import router as control_router
from api.websocket import router as websocket_router
from api.video import router as video_router
from api.audio import AudioHub, router as audio_router
from config import GO2_IFACE, MIN_WALK_BODY_HEIGHT
from go2.controller import Go2Controller
from go2.patrol import PatrolController
from go2.state_reader import Go2StateReader
from go2.video import VideoStream
from go2.watchdog import MoveWatchdog


BASE_DIR = Path(__file__).resolve().parent

state_reader = Go2StateReader()


def current_yaw():
    state = state_reader.snapshot()
    return state["imu"]["yaw"] if state["connected"] else None


def current_pose():
    state = state_reader.snapshot()
    if not state["connected"]:
        return None
    return state["position"]["x"], state["position"]["y"], state["imu"]["yaw"]


def walking_ready():
    state = state_reader.snapshot()
    return state["body_height"] >= MIN_WALK_BODY_HEIGHT if state["connected"] else None


controller = Go2Controller(
    GO2_IFACE, heading=current_yaw, pose=current_pose, walking_ready=walking_ready,
    connected=lambda: state_reader.snapshot()["connected"],
)
watchdog = MoveWatchdog(controller)
video = VideoStream()
audio = AudioHub(storage=BASE_DIR / "audio" / "uploads")
patrol = PatrolController(controller, state_reader, BASE_DIR / "patrol_path.json")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    rpc_log = logging.getLogger("go2.rpc")
    handler = RotatingFileHandler(str(log_dir / "rpc.log"), maxBytes=5_000_000,
                                  backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    rpc_log.addHandler(handler)
    rpc_log.setLevel(logging.INFO)
    rpc_log.propagate = False
    rpc_log.info("event=session_start interface=%s", GO2_IFACE)
    try:
        controller.initialize()
    except Exception:
        logging.getLogger(__name__).exception("Go2 controller initialization failed")
    watchdog.start()
    for name, start in (
        ("Front camera", video.initialize),
        ("DDS state reader", state_reader.start),
        ("AudioHub", audio.initialize),
    ):
        try:
            start()
        except Exception:
            logging.getLogger(__name__).exception("%s initialization failed", name)
    try:
        yield
    finally:
        for name, stop in (
            ("patrol", patrol.stop),
            ("front camera", video.stop),
            ("state reader", state_reader.stop),
            ("watchdog", watchdog.stop),
            ("audio", audio.stop_local),
            ("controller", controller.stop),
        ):
            try:
                if name != "controller" or controller.ready:
                    stop()
            except Exception:
                logging.getLogger(__name__).exception("%s shutdown failed", name)
        rpc_log.info("event=session_end")
        rpc_log.removeHandler(handler)
        handler.close()


app = FastAPI(title="Go2 Web Control API", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(control_router)
app.include_router(video_router)
app.include_router(websocket_router)
app.include_router(audio_router)
app.state.controller = controller
app.state.video = video
app.state.state_reader = state_reader
app.state.patrol = patrol
app.state.audio = audio


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(str(BASE_DIR / "templates" / "index.html"))


@app.get("/patrol", include_in_schema=False)
def patrol_page() -> FileResponse:
    return FileResponse(str(BASE_DIR / "templates" / "index.html"))


@app.get("/settings", include_in_schema=False)
def settings_page() -> FileResponse:
    return FileResponse(str(BASE_DIR / "templates" / "index.html"))


@app.exception_handler(RuntimeError)
async def controller_error(_request, error):
    return JSONResponse(status_code=503, content={"detail": str(error)})
