"""Adaptador de OpenAI (Chat Completions). Traduce ChatRequest <-> API; el núcleo no ve este formato."""

import json
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from privacy_shield.adapters.outbound.llm.http import check_status, make_client
from privacy_shield.domain.errors import ProviderError, ProviderNotConfigured
from privacy_shield.domain.messages import ChatChunk, ChatRequest, ChatResponse


def _safe_name(name: str) -> str:
    """OpenAI solo admite [A-Za-z0-9_-] en `name`: los tokens como [PERSONA_1] se adaptan."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", name).strip("_") or "user"


class OpenAIAdapter:
    name = "openai"
    leaves_machine = True

    def __init__(
        self,
        api_key: str = "",
        *,
        base_url: str = "https://api.openai.com",
        default_model: str = "gpt-4o-mini",
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._client = make_client(self._base_url, client, timeout)

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _prepare(self, req: ChatRequest, *, stream: bool) -> tuple[str, dict[str, str], dict[str, Any]]:
        if not self._api_key:
            raise ProviderNotConfigured("Falta ANON_OPENAI_API_KEY")
        messages = [
            {"role": m.role, "content": m.content, **({"name": _safe_name(m.name)} if m.name else {})}
            for m in req.messages
        ]
        body: dict[str, Any] = {"model": req.model or self._default_model, "messages": messages, "stream": stream}
        if req.temperature is not None:
            body["temperature"] = req.temperature
        if req.max_tokens is not None:
            body["max_tokens"] = req.max_tokens
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        return f"{self._base_url}/v1/chat/completions", headers, body

    async def complete(self, req: ChatRequest) -> ChatResponse:
        url, headers, body = self._prepare(req, stream=False)
        try:
            response = await self._client.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise ProviderError(f"openai no disponible ({type(exc).__name__})") from exc
        check_status(response, "openai")
        try:
            data = response.json()
            choice = data["choices"][0]
            content = choice["message"]["content"] or ""
            return ChatResponse(content, data.get("model", body["model"]), choice.get("finish_reason"))
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise ProviderError("Respuesta de openai con formato inesperado") from exc

    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        url, headers, body = self._prepare(req, stream=True)
        try:
            async with self._client.stream("POST", url, headers=headers, json=body) as response:
                check_status(response, "openai")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        choice = json.loads(payload)["choices"][0]
                        delta = (choice.get("delta") or {}).get("content") or ""
                        finish = choice.get("finish_reason")
                    except (KeyError, IndexError, ValueError, TypeError) as exc:
                        raise ProviderError("Evento de openai con formato inesperado") from exc
                    if delta or finish:
                        yield ChatChunk(delta, finish)
        except httpx.HTTPError as exc:
            raise ProviderError(f"openai no disponible ({type(exc).__name__})") from exc
