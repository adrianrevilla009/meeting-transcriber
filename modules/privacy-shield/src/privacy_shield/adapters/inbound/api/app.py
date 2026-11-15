"""Adaptador de entrada HTTP (FastAPI). Traduce HTTP <-> casos de uso; recibe un `Runtime` ya cableado."""

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from privacy_shield.adapters.inbound.api.deps import Auth, get_runtime
from privacy_shield.adapters.inbound.api.schemas import (
    AnonymizeIn,
    AnonymizeOut,
    ChatIn,
    ChatOut,
    DeanonymizeIn,
    DeanonymizeOut,
    EntityOut,
    MessageOut,
    ProviderOut,
)
from privacy_shield.application.runtime import Runtime
from privacy_shield.application.use_cases import ChatResult, PreparedChat
from privacy_shield.domain.errors import (
    BlockedByPolicy,
    DetectorUnavailable,
    LeakDetected,
    PrivacyShieldError,
    ProviderError,
    ProviderNotAllowed,
    ProviderNotConfigured,
    ProviderNotFound,
    SessionNotFound,
)
from privacy_shield.domain.messages import ChatChunk, ChatMessage, ChatRequest
from privacy_shield.domain.session import SessionId

router = APIRouter()


@router.get("/health")
def health(rt: Runtime = Depends(get_runtime)) -> dict[str, object]:
    return rt.health()


@router.post("/v1/anonymize", response_model=AnonymizeOut, dependencies=[Auth])
def anonymize(body: AnonymizeIn, rt: Runtime = Depends(get_runtime)) -> AnonymizeOut:
    session = SessionId(body.session_id) if body.session_id else None
    result = rt.anonymize.execute(body.text, session)
    return AnonymizeOut(
        session_id=result.session_id,
        text=result.text,
        entities=[EntityOut(type=r.type.value, token=r.token, strategy=r.strategy.value) for r in result.replacements],
    )


@router.post("/v1/deanonymize", response_model=DeanonymizeOut, dependencies=[Auth])
def deanonymize(body: DeanonymizeIn, rt: Runtime = Depends(get_runtime)) -> DeanonymizeOut:
    return DeanonymizeOut(text=rt.deanonymize.execute(SessionId(body.session_id), body.text))


@router.post("/v1/chat", response_model=ChatOut, dependencies=[Auth])
async def chat(body: ChatIn, rt: Runtime = Depends(get_runtime)) -> ChatOut | StreamingResponse:
    request = ChatRequest(
        messages=tuple(ChatMessage(m.role, m.content, m.name) for m in body.messages),
        model=body.model,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
    )
    session = SessionId(body.session_id) if body.session_id else None
    # Los errores salen aquí, antes de abrir el stream.
    prepared = await rt.chat.prepare(request, session, body.provider)
    if body.stream:
        return StreamingResponse(
            _sse(rt, prepared),
            media_type="text/event-stream",
            headers={"X-Session-Id": prepared.session_id, "Cache-Control": "no-cache"},
        )
    return _chat_out(await rt.chat.complete(prepared))


def _chat_out(result: ChatResult) -> ChatOut:
    counts: dict[str, int] = {}
    for r in result.replacements:
        counts[r.type.value] = counts.get(r.type.value, 0) + 1
    return ChatOut(
        session_id=result.session_id,
        provider=result.provider,
        model=result.response.model,
        message=MessageOut(content=result.response.content),
        finish_reason=result.response.finish_reason,
        entities=counts,
        unknown_tokens=result.unknown_tokens,
    )


async def _sse(rt: Runtime, prepared: PreparedChat) -> AsyncIterator[str]:
    try:
        async for chunk in rt.chat.stream(prepared):
            yield _event(chunk)
    except PrivacyShieldError:
        yield 'event: error\ndata: {"error": "provider_error"}\n\n'
        return
    yield "data: [DONE]\n\n"


def _event(chunk: ChatChunk) -> str:
    payload = json.dumps({"content": chunk.content, "finish_reason": chunk.finish_reason}, ensure_ascii=False)
    return f"data: {payload}\n\n"


@router.get("/v1/providers", response_model=list[ProviderOut], dependencies=[Auth])
def providers(rt: Runtime = Depends(get_runtime)) -> list[ProviderOut]:
    out = []
    for name in rt.registry.names():
        adapter = rt.registry.get(name)
        out.append(ProviderOut(name=name, configured=adapter.is_configured(), leaves_machine=adapter.leaves_machine))
    return out


@router.delete("/v1/sessions/{session_id}", status_code=204, dependencies=[Auth])
def delete_session(session_id: str, rt: Runtime = Depends(get_runtime)) -> None:
    rt.vault.delete_session(SessionId(session_id))


@router.get("/v1/sessions/{session_id}/mapping", dependencies=[Auth])
def mapping(session_id: str, request: Request, rt: Runtime = Depends(get_runtime)) -> JSONResponse:
    if not request.app.state.debug_mapping:
        detail = "Activa ANON_DEBUG_MAPPING solo para depurar en local"
        return JSONResponse({"error": "disabled", "detail": detail}, 404)
    session = SessionId(session_id)
    if not rt.vault.session_exists(session):
        return JSONResponse({"error": "session_not_found"}, 404)
    tokens: dict[str, str] = {}
    for entity_type, value in rt.vault.known_values(session):
        token = rt.vault.find_token(session, entity_type, value)
        if token:
            tokens.setdefault(token, value)
    return JSONResponse({"session_id": session_id, "mapping": tokens})


def _error(status: int, code: str, **extra: object) -> JSONResponse:
    return JSONResponse({"error": code, **extra}, status_code=status)  # nunca incluye texto del usuario


def create_app(rt: Runtime, *, api_token: str, debug_mapping: bool = False) -> FastAPI:
    app = FastAPI(title="privacy-shield", version="0.1.0")
    app.state.runtime = rt
    app.state.api_token = api_token
    app.state.debug_mapping = debug_mapping
    app.include_router(router)

    @app.exception_handler(LeakDetected)
    async def _leak(_: Request, exc: LeakDetected) -> JSONResponse:
        return _error(422, "leak_detected", types={t.value: n for t, n in exc.counts.items()})

    @app.exception_handler(BlockedByPolicy)
    async def _blocked(_: Request, exc: BlockedByPolicy) -> JSONResponse:
        return _error(422, "policy_blocked", types=[t.value for t in exc.types])

    @app.exception_handler(DetectorUnavailable)
    async def _detector(_: Request, exc: DetectorUnavailable) -> JSONResponse:
        return _error(503, "detector_unavailable")

    @app.exception_handler(SessionNotFound)
    async def _session(_: Request, exc: SessionNotFound) -> JSONResponse:
        return _error(404, "session_not_found")

    @app.exception_handler(ProviderNotFound)
    async def _no_provider(_: Request, exc: ProviderNotFound) -> JSONResponse:
        return _error(404, "provider_not_found")

    @app.exception_handler(ProviderNotConfigured)
    async def _not_configured(_: Request, exc: ProviderNotConfigured) -> JSONResponse:
        return _error(503, "provider_not_configured")

    @app.exception_handler(ProviderNotAllowed)
    async def _not_allowed(_: Request, exc: ProviderNotAllowed) -> JSONResponse:
        return _error(403, "provider_not_allowed")

    @app.exception_handler(ProviderError)
    async def _provider(_: Request, exc: ProviderError) -> JSONResponse:
        return _error(502, "provider_error")

    return app
