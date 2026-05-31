"""SSE推送路由 — P2占位"""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import asyncio

router = APIRouter(tags=["stream"])


@router.get("/api/v1/stream")
async def stream():
    """SSE实时推送 — P2实现"""
    async def event_generator():
        while True:
            yield f"data: {{}}"
            await asyncio.sleep(30)
    return StreamingResponse(event_generator(), media_type="text/event-stream")
