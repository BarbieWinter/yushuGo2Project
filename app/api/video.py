from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse


router = APIRouter(prefix="/api")


@router.get("/video", include_in_schema=False)
def video(request: Request) -> StreamingResponse:
    stream = request.app.state.video
    if not stream.ready:
        raise HTTPException(status_code=503, detail="Front camera unavailable")
    return StreamingResponse(
        stream.frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"},
    )

