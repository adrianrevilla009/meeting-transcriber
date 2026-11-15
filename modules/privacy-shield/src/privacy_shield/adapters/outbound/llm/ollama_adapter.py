"""Adaptador de Ollama (LLM local). No sale de la máquina: el caso de uso puede omitir la pseudonimización."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from privacy_shield.adapters.outbound.llm.http import check_status, make_client
from privacy_shield.domain.errors import ProviderError
from privacy_shield.domain.messages import ChatChunk, ChatRequest, ChatResponse


class OllamaAdapter:
    name = "ollama"
    leaves_machine = False

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        *,
        default_model: str = "qwen2.5:7b",
        client: httpx.AsyncClient | None = None,
        timeout: float = 300.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._client = make_client(self._base_url, client, timeout)

    def is_configured(self) -> bool:
        return True

    def _body(self, req: ChatRequest, *, stream: bool) -> dict[str, Any]:
        options: dict[str, Any] = {}
        if req.temperature is not None:
            options["temperature"] = req.temperature
        if req.max_tokens is not None:
            options["num_predict"] = req.max_tokens
        return {
            "model": req.model or self._default_model,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
            "stream": stream,
            "options": options,
        }

    async def complete(self, req: ChatRequest) -> ChatResponse:
        body = self._body(req, stream=False)
        try:
            response = await self._client.post(f"{self._base_url}/api/chat", json=body)
        except httpx.HTTPError as exc:
            raise ProviderError(f"ollama no disponible ({type(exc).__name__})") from exc
        check_status(response, "ollama")
        try:
            data = response.json()
            return ChatResponse(data["message"]["content"], data.get("model", body["model"]), data.get("done_reason"))
        except (KeyError, ValueError, TypeError) as exc:
            raise ProviderError("Respuesta de ollama con formato inesperado") from exc

    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        body = self._body(req, stream=True)
        try:
            async with self._client.stream("POST", f"{self._base_url}/api/chat", json=body) as response:
                check_status(response, "ollama")
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        content = data.get("message", {}).get("content", "")
                        finish = data.get("done_reason") if data.get("done") else None
                    except (ValueError, TypeError, AttributeError) as exc:
                        raise ProviderError("Evento de ollama con formato inesperado") from exc
                    if content or finish:
                        yield ChatChunk(content, finish)
        except httpx.HTTPError as exc:
            raise ProviderError(f"ollama no disponible ({type(exc).__name__})") from exc
