import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


router = APIRouter()


@router.websocket("/ws/state")
async def state(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            state = websocket.app.state.state_reader.snapshot()
            state["patrol"] = websocket.app.state.patrol.snapshot()
            state["control"] = websocket.app.state.controller.status()
            await websocket.send_json(state)
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        pass
