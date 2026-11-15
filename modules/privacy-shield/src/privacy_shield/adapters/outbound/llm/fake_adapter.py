"""Proveedor falso para tests y desarrollo: no usa red y CAPTURA lo que "saldría" hacia el proveedor."""

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict

from privacy_shield.domain.messages import ChatChunk, ChatRequest, ChatResponse


def echo_last_user(req: ChatRequest) -> str:
    """Respuesta por defecto: repite el último mensaje del usuario (con sus tokens), para probar la reversión."""
    last = next((m.content for m in reversed(req.messages) if m.role == "user"), "")
    return f"Entendido: {last}"


class FakeLLMAdapter:
    def __init__(
        self,
        responder: Callable[[ChatRequest], str] = echo_last_user,
        *,
        name: str = "fake",
        leaves_machine: bool = True,
        configured: bool = True,
        chunk_size: int = 7,
        fail_with: Exception | None = None,
    ):
        self.name = name
        self.leaves_machine = leaves_machine
        self._responder = responder
        self._configured = configured
        self._chunk_size = max(1, chunk_size)
        self._fail_with = fail_with
        self.calls: list[ChatRequest] = []

    def is_configured(self) -> bool:
        return self._configured

    def captured_payloads(self) -> list[str]:
        """El cuerpo exacto (JSON) de cada llamada saliente: es lo que un tercero vería."""
        return [json.dumps(asdict(c), ensure_ascii=False) for c in self.calls]

    async def complete(self, req: ChatRequest) -> ChatResponse:
        self.calls.append(req)
        if self._fail_with:
            raise self._fail_with
        return ChatResponse(self._responder(req), req.model or "fake-model", "stop")

    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        self.calls.append(req)
        if self._fail_with:
            raise self._fail_with
        text = self._responder(req)
        for i in range(0, len(text), self._chunk_size):
            yield ChatChunk(text[i : i + self._chunk_size])
        yield ChatChunk("", "stop")
