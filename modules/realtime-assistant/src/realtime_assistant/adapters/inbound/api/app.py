"""Adaptador de entrada HTTP (FastAPI). Traduce HTTP <-> casos de uso; recibe un `Runtime` ya cableado."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from realtime_assistant.adapters.inbound.api.deps import Auth, get_runtime
from realtime_assistant.adapters.inbound.api.schemas import AskIn, FollowOut, QuestionOut, StatusOut
from realtime_assistant.application.runtime import Runtime
from realtime_assistant.domain.errors import MeetingNotFound, QuestionNotFound, TranscriberUnavailable
from realtime_assistant.domain.events import AssistantEvent

router = APIRouter()
HEARTBEAT_SECONDS = 15.0


@router.get("/health")
def health(rt: Runtime = Depends(get_runtime)) -> dict[str, object]:
    return rt.health()


@router.post("/v1/meetings/{meeting_id}/follow", response_model=FollowOut, dependencies=[Auth])
async def follow(meeting_id: int, rt: Runtime = Depends(get_runtime)) -> FollowOut:
    await rt.assistant.follow(meeting_id)
    return FollowOut(meeting_id=meeting_id, following=True)


@router.delete("/v1/meetings/{meeting_id}/follow", status_code=204, dependencies=[Auth])
async def unfollow(meeting_id: int, rt: Runtime = Depends(get_runtime)) -> None:
    await rt.assistant.unfollow(meeting_id)


@router.get("/v1/meetings/{meeting_id}/status", response_model=StatusOut, dependencies=[Auth])
def status(meeting_id: int, rt: Runtime = Depends(get_runtime)) -> StatusOut:
    s = rt.assistant.status(meeting_id)
    return StatusOut(following=bool(s["following"]), questions=int(str(s["questions"])), answers=int(str(s["answers"])))


@router.post("/v1/meetings/{meeting_id}/ask", response_model=QuestionOut, status_code=202, dependencies=[Auth])
async def ask(meeting_id: int, body: AskIn, rt: Runtime = Depends(get_runtime)) -> QuestionOut:
    return QuestionOut(question_id=await rt.assistant.ask(meeting_id, body.text))


@router.post("/v1/meetings/{meeting_id}/questions/{question_id}/answer", status_code=202, dependencies=[Auth])
async def answer(meeting_id: int, question_id: str, rt: Runtime = Depends(get_runtime)) -> QuestionOut:
    await rt.assistant.answer(meeting_id, question_id)
    return QuestionOut(question_id=question_id)


@router.get("/v1/meetings/{meeting_id}/events", dependencies=[Auth])
async def events(
    meeting_id: int,
    after: int = Query(0, ge=0),
    once: bool = Query(False, description="Solo el histórico posterior a `after`, sin quedarse a la escucha"),
    rt: Runtime = Depends(get_runtime),
) -> StreamingResponse:
    return StreamingResponse(
        sse(rt, meeting_id, after, once),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def frame(event: AssistantEvent) -> str:
    payload = json.dumps({**event.data, "id": event.id, "type": event.type}, ensure_ascii=False)
    return f"data: {payload}\n\n"


async def sse(rt: Runtime, meeting_id: int, after: int, once: bool) -> AsyncIterator[str]:
    if once:
        for event in rt.store.after(meeting_id, after):
            yield frame(event)
        return
    async for item in rt.store.subscribe(meeting_id, after, HEARTBEAT_SECONDS):
        yield ": keepalive\n\n" if item is None else frame(item)


def _error(status_code: int, code: str) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status_code)  # nunca incluye texto de la reunión


def create_app(rt: Runtime, *, api_token: str) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await rt.assistant.shutdown()

    app = FastAPI(title="realtime-assistant", version="0.1.0", lifespan=lifespan)
    app.state.runtime = rt
    app.state.api_token = api_token
    app.include_router(router)

    @app.exception_handler(MeetingNotFound)
    async def _meeting(_: Request, exc: MeetingNotFound) -> JSONResponse:
        return _error(404, "meeting_not_found")

    @app.exception_handler(QuestionNotFound)
    async def _question(_: Request, exc: QuestionNotFound) -> JSONResponse:
        return _error(404, "question_not_found")

    @app.exception_handler(TranscriberUnavailable)
    async def _transcriber(_: Request, exc: TranscriberUnavailable) -> JSONResponse:
        return _error(503, "transcriber_unavailable")

    return app
