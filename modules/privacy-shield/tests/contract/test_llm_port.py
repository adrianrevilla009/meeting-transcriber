"""Contrato de LLMPort: todos los adaptadores devuelven lo mismo con la misma conversación (red simulada)."""

import json
from collections.abc import Callable

import httpx
import pytest

from privacy_shield.adapters.outbound.llm.anthropic_adapter import AnthropicAdapter
from privacy_shield.adapters.outbound.llm.fake_adapter import FakeLLMAdapter
from privacy_shield.adapters.outbound.llm.http import AllowlistTransport
from privacy_shield.adapters.outbound.llm.ollama_adapter import OllamaAdapter
from privacy_shield.adapters.outbound.llm.openai_adapter import OpenAIAdapter
from privacy_shield.adapters.outbound.llm.registry import ProviderRegistry
from privacy_shield.application.ports import LLMPort
from privacy_shield.domain.errors import ProviderError, ProviderNotConfigured, ProviderNotFound
from privacy_shield.domain.messages import ChatMessage, ChatRequest

REQUEST = ChatRequest(
    (ChatMessage("system", "Sé breve."), ChatMessage("user", "Saluda.")), model="m", temperature=0.2, max_tokens=50
)
Handler = Callable[[httpx.Request], httpx.Response]


def _client(host: str, handler: Handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=AllowlistTransport([host], httpx.MockTransport(handler)))


def _sse(events: list[dict[str, object]], *, named: bool = False) -> httpx.Response:
    lines = []
    for e in events:
        if named:
            lines.append(f"event: {e['type']}")
        lines.append(f"data: {json.dumps(e)}\n")
    return httpx.Response(200, text="\n".join(lines) + "\n", headers={"content-type": "text/event-stream"})


def openai_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    assert request.headers["authorization"] == "Bearer sk-test"
    assert body["messages"][0] == {"role": "system", "content": "Sé breve."}
    if body["stream"]:
        events = [
            {"choices": [{"delta": {"content": "Hola "}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "mundo"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ]
        text = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
        return httpx.Response(200, text=text, headers={"content-type": "text/event-stream"})
    return httpx.Response(
        200, json={"model": "gpt-x", "choices": [{"message": {"content": "Hola mundo"}, "finish_reason": "stop"}]}
    )


def anthropic_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    assert request.headers["x-api-key"] == "ak-test" and request.headers["anthropic-version"]
    assert body["system"] == "Sé breve." and body["messages"] == [{"role": "user", "content": "Saluda."}]
    if body["stream"]:
        return _sse(
            [
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hola "}},
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "mundo"}},
                {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
            ],
            named=True,
        )
    return httpx.Response(
        200, json={"model": "claude-x", "content": [{"type": "text", "text": "Hola mundo"}], "stop_reason": "end_turn"}
    )


def ollama_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    if body["stream"]:
        lines = [
            {"message": {"content": "Hola "}, "done": False},
            {"message": {"content": "mundo"}, "done": False},
            {"message": {"content": ""}, "done": True, "done_reason": "stop"},
        ]
        return httpx.Response(200, text="\n".join(json.dumps(x) for x in lines) + "\n")
    return httpx.Response(200, json={"model": "m", "message": {"content": "Hola mundo"}, "done_reason": "stop"})


def make_openai(handler: Handler = openai_handler) -> LLMPort:
    return OpenAIAdapter("sk-test", client=_client("api.openai.com", handler))


def make_anthropic(handler: Handler = anthropic_handler) -> LLMPort:
    return AnthropicAdapter("ak-test", client=_client("api.anthropic.com", handler))


def make_ollama(handler: Handler = ollama_handler) -> LLMPort:
    return OllamaAdapter("http://localhost:11434", client=_client("localhost", handler))


def make_fake() -> LLMPort:
    return FakeLLMAdapter(lambda _: "Hola mundo")


FACTORIES = {"openai": make_openai, "anthropic": make_anthropic, "ollama": make_ollama, "fake": make_fake}


@pytest.fixture(params=list(FACTORIES))
def adapter(request: pytest.FixtureRequest) -> LLMPort:
    return FACTORIES[request.param]()


async def test_complete(adapter: LLMPort) -> None:
    response = await adapter.complete(REQUEST)
    assert response.content == "Hola mundo"
    assert response.model


async def test_stream_joins_to_the_same_text(adapter: LLMPort) -> None:
    chunks = [c async for c in adapter.stream(REQUEST)]
    assert "".join(c.content for c in chunks) == "Hola mundo"
    assert any(c.finish_reason for c in chunks)


def test_declares_name_and_locality() -> None:
    assert {a().name for a in FACTORIES.values()} == {"openai", "anthropic", "ollama", "fake"}
    assert make_ollama().leaves_machine is False
    assert make_openai().leaves_machine and make_anthropic().leaves_machine


@pytest.mark.parametrize("make", [make_openai, make_anthropic, make_ollama], ids=["openai", "anthropic", "ollama"])
async def test_http_errors_become_provider_errors_without_the_body(make: Callable[..., LLMPort]) -> None:
    adapter = make(lambda request: httpx.Response(500, text="secreto: ana@example.org"))
    with pytest.raises(ProviderError) as err:
        await adapter.complete(REQUEST)
    assert "ana@example.org" not in str(err.value)
    with pytest.raises(ProviderError):
        _ = [c async for c in adapter.stream(REQUEST)]


@pytest.mark.parametrize("make", [make_openai, make_anthropic, make_ollama], ids=["openai", "anthropic", "ollama"])
async def test_malformed_responses_are_provider_errors(make: Callable[..., LLMPort]) -> None:
    adapter = make(lambda request: httpx.Response(200, json={"inesperado": True}))
    with pytest.raises(ProviderError):
        await adapter.complete(REQUEST)


async def test_missing_key_means_not_configured() -> None:
    adapters: list[LLMPort] = [OpenAIAdapter(""), AnthropicAdapter("")]
    for adapter in adapters:
        assert not adapter.is_configured()
        with pytest.raises(ProviderNotConfigured):
            await adapter.complete(REQUEST)


async def test_egress_allowlist_blocks_other_hosts() -> None:
    client = _client("api.openai.com", openai_handler)
    adapter = OpenAIAdapter("sk-test", base_url="https://evil.example.com", client=client)
    with pytest.raises(ProviderError, match="allowlist"):
        await adapter.complete(REQUEST)


async def test_allowlist_transport_lets_the_allowed_host_through() -> None:
    transport = AllowlistTransport(["api.openai.com"], httpx.MockTransport(lambda r: httpx.Response(204)))
    async with httpx.AsyncClient(transport=transport) as client:
        assert (await client.get("https://api.openai.com/v1/x")).status_code == 204


def test_registry_lookup() -> None:
    registry = ProviderRegistry([make_fake(), make_ollama()])
    assert registry.names() == ["fake", "ollama"]
    assert registry.get("fake").name == "fake"
    with pytest.raises(ProviderNotFound):
        registry.get("otro")
