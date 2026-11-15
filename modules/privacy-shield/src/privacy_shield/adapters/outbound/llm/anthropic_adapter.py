"""Adaptador de Anthropic (Messages API). Traduce ChatRequest <-> API; el núcleo no ve este formato."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from privacy_shield.adapters.outbound.llm.http import check_status, make_client
from privacy_shield.domain.errors import ProviderError, ProviderNotConfigured
from privacy_shield.domain.messages import ChatChunk, ChatRequest, ChatResponse

_API_VERSION = "2023-06-01"
_DEFAULT_MAX_TOKENS = 1024


class AnthropicAdapter:
    name = "anthropic"
    leaves_machine = True

    def __init__(
        self,
        api_key: str = "",
        *,
        base_url: str = "https://api.anthropic.com",
        default_model: str = "claude-sonnet-5-5",
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
            raise ProviderNotConfigured("Falta ANON_ANTHROPIC_API_KEY")
        system = "\n\n".join(m.content for m in req.messages if m.role == "system")
        messages = [{"role": m.role, "content": m.content} for m in req.messages if m.role != "system"]
        body: dict[str, Any] = {
            "model": req.model or self._default_model,
            "max_tokens": req.max_tokens or _DEFAULT_MAX_TOKENS,
            "messages": messages,
            "stream": stream,
        }
        if system:
            body["system"] = system
        if req.temperature is not None:
            body["temperature"] = req.temperature
        headers = {"x-api-key": self._api_key, "anthropic-version": _API_VERSION, "content-type": "application/json"}
        return f"{self._base_url}/v1/messages", headers, body

    async def complete(self, req: ChatRequest) -> ChatResponse:
        url, headers, body = self._prepare(req, stream=False)
        try:
            response = await self._client.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise ProviderError(f"anthropic no disponible ({type(exc).__name__})") from exc
        check_status(response, "anthropic")
        try:
            data = response.json()
            text = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
            return ChatResponse(text, data.get("model", body["model"]), data.get("stop_reason"))
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise ProviderError("Respuesta de anthropic con formato inesperado") from exc

    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        url, headers, body = self._prepare(req, stream=True)
        try:
            async with self._client.stream("POST", url, headers=headers, json=body) as response:
                check_status(response, "anthropic")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[5:].strip())
                        kind = event.get("type")
                        if kind == "content_block_delta" and event["delta"].get("type") == "text_delta":
                            yield ChatChunk(event["delta"].get("text", ""))
                        elif kind == "message_delta" and event["delta"].get("stop_reason"):
                            yield ChatChunk("", event["delta"]["stop_reason"])
                    except (KeyError, ValueError, TypeError, AttributeError) as exc:
                        raise ProviderError("Evento de anthropic con formato inesperado") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"anthropic no disponible ({type(exc).__name__})") from exc
