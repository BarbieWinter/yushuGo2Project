import base64
import io
import json
import logging
import threading
import wave
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api.control import check_control_origin

MAX_AUDIO_BYTES = 2_000_000
MEGAPHONE_CHUNK_SIZE = 65536
router = APIRouter(prefix="/api/audio", dependencies=[Depends(check_control_origin)])
logger = logging.getLogger("go2.rpc")


class AudioHub:
    def __init__(self, client=None, storage: Optional[Path] = None, vui=None):
        self.client = client
        self.vui = vui
        self.storage = storage
        self.player = None
        self.stop_event = None
        self.lock = threading.Lock()
        self.rpc_lock = threading.Lock()

    def initialize(self):
        from unitree_sdk2py.rpc.client import Client
        from unitree_sdk2py.go2.vui.vui_client import VuiClient
        client = Client("audiohub")
        client.SetTimeout(4.0)
        client._SetApiVerson("1.0.0.1")
        for api in (1001, 1002, 1003, 1007, 4001, 4002, 4003):
            client._RegistApi(api, 0)
        self.client = client
        self.vui = VuiClient()
        self.vui.SetTimeout(3.0)
        self.vui.Init()

    def call(self, api, payload):
        if self.client is None:
            raise RuntimeError("AudioHub unavailable")
        with self.rpc_lock:
            code, data = self.client._Call(api, json.dumps(payload))
        if code != 0:
            raise RuntimeError(f"AudioHub API {api}: code {code}; execution unconfirmed, not retried")
        return json.loads(data) if data else {}

    def upload(self, data, name):
        try:
            with wave.open(io.BytesIO(data), "rb") as wav:
                frames = wav.getnframes()
                if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (1, 2, 16000, "NONE"):
                    raise ValueError("WAV must be mono 16-bit PCM, 16000 Hz")
                if not 0 < frames <= 60 * 16000 or len(wav.readframes(frames)) != frames * 2:
                    raise ValueError("WAV must contain complete audio of 0–60 seconds")
        except (wave.Error, EOFError, ValueError) as error:
            raise HTTPException(422, str(error) or "Invalid WAV")
        if self.storage is None:
            raise RuntimeError("Local audio storage unavailable")
        unique_id = uuid4()
        self.storage.mkdir(parents=True, exist_ok=True)
        target = self.storage / f"{unique_id}_{name}.wav"
        temporary = self.storage / f".{unique_id}.tmp"
        temporary.write_bytes(data)
        temporary.replace(target)
        return {"code": 0, "name": name, "unique_id": str(unique_id),
                "audio_list": self.audio_list()}

    def audio_list(self):
        if self.storage is None:
            return self.call(1001, {}).get("audio_list", [])
        self.storage.mkdir(parents=True, exist_ok=True)
        records = []
        for path in sorted(self.storage.glob("????????-????-????-????-????????????_*.wav"),
                           key=lambda item: item.stat().st_mtime, reverse=True):
            with wave.open(str(path), "rb") as wav:
                duration = wav.getnframes() / wav.getframerate()
            records.append({"UNIQUE_ID": path.name[:36], "CUSTOM_NAME": path.stem[37:],
                            "ADD_TIME": int(path.stat().st_mtime * 1000),
                            "DURATION": round(duration, 3), "SIZE": path.stat().st_size})
        return records

    def delete(self, unique_id):
        if self.storage is None:
            raise RuntimeError("Local audio storage unavailable")
        path = next(self.storage.glob(f"{unique_id}_*.wav"), None)
        if path is None:
            raise HTTPException(404, "Audio not found")
        path.unlink()

    def get_volume(self):
        if self.vui is None:
            raise RuntimeError("VUI unavailable")
        code, volume = self.vui.GetVolume()
        if code != 0:
            raise RuntimeError(f"GetVolume: SDK 返回错误码 {code}")
        return volume

    def set_volume(self, volume):
        if self.vui is None:
            raise RuntimeError("VUI unavailable")
        code = self.vui.SetVolume(volume)
        if code != 0:
            raise RuntimeError(f"SetVolume: SDK 返回错误码 {code}")

    def play(self, unique_id):
        if self.storage is not None:
            path = next(self.storage.glob(f"{unique_id}_*.wav"), None)
            if path is not None:
                self.stop_local()
                with wave.open(str(path), "rb") as wav:
                    duration = wav.getnframes() / wav.getframerate()
                data = base64.b64encode(path.read_bytes()).decode("ascii")
                chunks = [data[i:i + MEGAPHONE_CHUNK_SIZE]
                          for i in range(0, len(data), MEGAPHONE_CHUNK_SIZE)]
                self.call(4001, {})
                self.stop_event = threading.Event()
                self.player = threading.Thread(
                    target=self._play_megaphone,
                    args=(str(unique_id), chunks, duration, self.stop_event), daemon=True)
                self.player.start()
                return "megaphone"
        self.call(1007, {"play_mode": "no_cycle"})
        self.call(1002, {"unique_id": str(unique_id)})
        return "audiohub"

    def _play_megaphone(self, unique_id, chunks, duration, stop_event):
        logger.info("event=audio_start id=%s chunks=%d duration=%.3f", unique_id, len(chunks), duration)
        try:
            for index, chunk in enumerate(chunks, 1):
                if stop_event.is_set():
                    break
                self.call(4003, {
                    "current_block_size": len(chunk),
                    "block_content": chunk,
                    "current_block_index": index,
                    "total_block_number": len(chunks),
                })
                if stop_event.is_set():
                    break
            if not stop_event.is_set():
                logger.info("event=audio_uploaded id=%s", unique_id)
                stop_event.wait(duration + 0.5)
        except Exception:
            logger.exception("event=audio_failed id=%s", unique_id)
        finally:
            try:
                self.call(4002, {})
            except Exception:
                logger.exception("event=audio_exit_failed id=%s", unique_id)
            if self.player is threading.current_thread():
                self.player = None
                self.stop_event = None
            logger.info("event=audio_end id=%s stopped=%s", unique_id, stop_event.is_set())

    def stop_local(self):
        player = self.player
        if player is None or not player.is_alive():
            self.player = None
            self.stop_event = None
            return False
        self.stop_event.set()
        player.join(timeout=5)
        return True


class PlayAudio(BaseModel):
    unique_id: UUID


class SetVolume(BaseModel):
    volume: int = Field(ge=0, le=10)


@router.get("/list")
def audio_list(request: Request):
    hub = request.app.state.audio
    with hub.lock:
        return {"audio_list": hub.audio_list()}


@router.post("/upload")
async def audio_upload(request: Request, name: str = Query(min_length=1, max_length=64, pattern=r"^[\w-]+$")):
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "Audio exceeds 2 MB")
        data.extend(chunk)
    return await run_in_threadpool(request.app.state.audio.upload, bytes(data), name)


@router.post("/play")
def audio_play(command: PlayAudio, request: Request):
    hub = request.app.state.audio
    with hub.lock:
        backend = hub.play(command.unique_id)
    return {"code": 0, "status": "play_requested", "backend": backend}


@router.post("/pause")
def audio_pause(request: Request):
    hub = request.app.state.audio
    with hub.lock:
        if not hub.stop_local():
            hub.call(1003, {})
    return {"code": 0, "status": "pause_requested"}


@router.delete("/{unique_id}")
def audio_delete(unique_id: UUID, request: Request):
    hub = request.app.state.audio
    with hub.lock:
        hub.delete(unique_id)
    return {"code": 0, "status": "deleted"}


@router.get("/volume")
def audio_volume(request: Request):
    hub = request.app.state.audio
    with hub.lock:
        return {"volume": hub.get_volume()}


@router.post("/volume")
def audio_volume_set(command: SetVolume, request: Request):
    hub = request.app.state.audio
    with hub.lock:
        hub.set_volume(command.volume)
    return {"code": 0, "volume": command.volume}
