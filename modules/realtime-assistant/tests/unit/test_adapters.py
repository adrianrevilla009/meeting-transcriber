"""Adaptadores de salida con red simulada: transcriber, privacy-shield, clasificador local, almacén de eventos."""

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest

from realtime_assistant.adapters.outbound.answers.shield_client import ShieldAnswerGenerator
from realtime_assistant.adapters.outbound.classifier.ollama import OllamaQuestionClassifier
from realtime_assistant.adapters.outbound.events.memory import MemoryEventStore
from realtime_assistant.adapters.outbound.http_egress import AllowlistTransport
from realtime_assistant.adapters.outbound.source.http_source import HttpTranscriptSource
from realtime_assistant.domain.entities import TranscriptSegment, Verdict
from realtime_assistant.domain.errors import (
    ClassifierUnavailable,
    MeetingNotFound,
    ShieldBlocked,
    ShieldUnavailable,
    TranscriberUnavailable,
)

Handler = Callable[[httpx.Request], httpx.Response]


def client(host: str, handler: Handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=AllowlistTransport([host], httpx.MockTransport(handler)))


# ------------------------------------------------------------------ transcriber
def source(handler: Handler, base: str = "http://api:8000") -> HttpTranscriptSource:
    return HttpTranscriptSource(base, "tok", client=client("api", handler))


async def test_source_reads_new_segments_with_the_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/meetings/7/segments"
        assert dict(request.url.params) == {"after_id": "3", "limit": "200"}
        assert request.headers["authorization"] == "Bearer tok"
        body = [{"id": 4, "source": "system", "start": 1.0, "end": 2.5, "text": "hola", "low_confidence": False}]
        return httpx.Response(200, json=body)

    assert await source(handler).fetch_after(7, 3) == [TranscriptSegment(4, "system", 1.0, 2.5, "hola")]


async def test_source_maps_http_failures() -> None:
    with pytest.raises(MeetingNotFound):
        await source(lambda r: httpx.Response(404)).fetch_after(1, 0)
    for status in (401, 403, 500):
        with pytest.raises(TranscriberUnavailable):
            await source(lambda r, s=status: httpx.Response(s)).fetch_after(1, 0)
    with pytest.raises(TranscriberUnavailable):
        await source(lambda r: httpx.Response(200, json={"inesperado": True})).fetch_after(1, 0)


async def test_source_survives_network_errors_and_blocks_other_hosts() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red")

    with pytest.raises(TranscriberUnavailable):
        await source(boom).fetch_after(1, 0)
    with pytest.raises(TranscriberUnavailable):  # la URL apunta fuera de la allowlist
        await source(lambda r: httpx.Response(200, json=[]), base="http://evil.example").fetch_after(1, 0)


# ------------------------------------------------------------------ privacy-shield
SSE_OK = (
    'data: {"content": "Hola ", "finish_reason": null}\n\n'
    'data: {"content": "mundo", "finish_reason": null}\n\n'
    'data: {"content": "", "finish_reason": "stop"}\n\n'
    "data: [DONE]\n\n"
)


def shield(handler: Handler, **kwargs: str) -> ShieldAnswerGenerator:
    return ShieldAnswerGenerator("http://privacy-shield:8100", "shield-token", client=client("privacy-shield", handler), **kwargs)


async def collect(generator: ShieldAnswerGenerator) -> list[str]:
    return [c async for c in generator.stream_answer(5, "¿Qué opinas?", "Otros: hola")]


async def test_shield_streams_the_answer_through_chat() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat" and request.headers["authorization"] == "Bearer shield-token"
        body = json.loads(request.content)
        assert body["stream"] is True and body["session_id"] == "rta-5"
        assert body["messages"][0]["role"] == "system" and body["messages"][1]["role"] == "user"
        assert "Otros: hola" in body["messages"][1]["content"] and "¿Qué opinas?" in body["messages"][1]["content"]
        assert "provider" not in body and "model" not in body
        return httpx.Response(200, text=SSE_OK, headers={"content-type": "text/event-stream"})

    assert await collect(shield(handler)) == ["Hola ", "mundo"]


async def test_shield_passes_provider_model_and_profile() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["provider"] == "anthropic" and body["model"] == "claude-x"
        assert "Soy el CTO" in body["messages"][0]["content"]
        return httpx.Response(200, text=SSE_OK)

    generator = shield(handler, provider="anthropic", model="claude-x", profile="Soy el CTO")
    assert await collect(generator) == ["Hola ", "mundo"]


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (422, {"error": "leak_detected", "types": {"EMAIL": 1}}, ShieldBlocked),
        (422, {"error": "policy_blocked"}, ShieldBlocked),
        (403, {"error": "provider_not_allowed"}, ShieldBlocked),
        (503, {"error": "detector_unavailable"}, ShieldUnavailable),
        (502, {"error": "provider_error"}, ShieldUnavailable),
        (401, {"detail": "Token inválido"}, ShieldUnavailable),
    ],
)
async def test_shield_errors_become_codes(status: int, body: dict[str, object], expected: type[Exception]) -> None:
    with pytest.raises(expected) as err:
        await collect(shield(lambda r: httpx.Response(status, json=body)))
    assert "Token" not in str(err.value)  # los cuerpos no se reenvían
    if "error" in body:
        assert err.value.code == body["error"]  # type: ignore[attr-defined]
    else:
        assert err.value.code == "shield_unauthorized"  # type: ignore[attr-defined]


async def test_shield_http_errors_without_json_and_mid_stream_errors() -> None:
    with pytest.raises(ShieldUnavailable) as err:
        await collect(shield(lambda r: httpx.Response(500, text="boom")))
    assert err.value.code == "http_500"
    stream_error = 'event: error\ndata: {"error": "provider_error"}\n\n'
    with pytest.raises(ShieldUnavailable) as err:
        await collect(shield(lambda r: httpx.Response(200, text='data: {"content": "a"}\n\n' + stream_error)))
    assert err.value.code == "provider_error"


async def test_shield_network_failures_and_egress() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red")

    with pytest.raises(ShieldUnavailable) as err:
        await collect(shield(boom))
    assert err.value.code == "shield_unavailable"
    evil = ShieldAnswerGenerator("http://api.openai.com", "t", client=client("privacy-shield", lambda r: httpx.Response(200)))
    with pytest.raises(ShieldUnavailable):  # el asistente no puede hablar con ningún LLM directamente
        await collect(evil)


# ------------------------------------------------------------------ clasificador local
def classifier(handler: Handler, names: tuple[str, ...] = ()) -> OllamaQuestionClassifier:
    return OllamaQuestionClassifier("http://localhost:11434", "qwen-test", user_names=names, client=client("localhost", handler))


async def test_classifier_parses_the_verdict() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/api/chat" and body["format"] == "json" and body["stream"] is False
        assert body["model"] == "qwen-test" and body["options"]["temperature"] == 0
        user = body["messages"][1]["content"]
        assert "Adrián, Adri" in user and "FRASE: ¿Qué opinas?" in user and "Otros: hola" in user
        content = json.dumps({"is_question": True, "directed_at_me": False})
        return httpx.Response(200, json={"message": {"content": content}})

    verdict = await classifier(handler, ("Adrián", "Adri")).classify("¿Qué opinas?", "Otros: hola")
    assert verdict == Verdict(True, False)


async def test_classifier_defaults_to_directed_when_not_stated() -> None:
    content = json.dumps({"is_question": True})
    result = await classifier(lambda r: httpx.Response(200, json={"message": {"content": content}})).classify("x", "")
    assert result == Verdict(True, True)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"message": {"content": "no es json"}}),
        httpx.Response(200, json={"message": {"content": "{}"}}),
        httpx.Response(200, json={"otra": "cosa"}),
        httpx.Response(500),
    ],
)
async def test_classifier_failures_mean_unavailable(response: httpx.Response) -> None:
    with pytest.raises(ClassifierUnavailable):
        await classifier(lambda r: response).classify("x", "")


async def test_classifier_network_failure() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red")

    with pytest.raises(ClassifierUnavailable):
        await classifier(boom).classify("x", "")


# ------------------------------------------------------------------ almacén de eventos
def test_events_get_increasing_ids_per_meeting() -> None:
    store = MemoryEventStore()
    assert [store.append(1, "a", {}).id, store.append(1, "b", {}).id, store.append(2, "c", {}).id] == [1, 2, 1]
    assert [e.type for e in store.after(1, 1)] == ["b"] and store.after(3, 0) == []


def test_event_log_is_bounded_but_ids_keep_growing() -> None:
    store = MemoryEventStore(max_events=3)
    for i in range(5):
        store.append(1, "x", {"i": i})
    assert [e.id for e in store.after(1, 0)] == [3, 4, 5]


async def test_subscribe_replays_then_streams_live_events() -> None:
    store = MemoryEventStore()
    store.append(1, "antes", {})
    stream = store.subscribe(1, 0)
    assert (await anext(stream)).type == "antes"  # type: ignore[union-attr]

    async def later() -> None:
        await asyncio.sleep(0.01)
        store.append(1, "despues", {"k": 1})

    task = asyncio.create_task(later())
    event = await anext(stream)
    assert event is not None and event.type == "despues" and event.data == {"k": 1}
    await task
    await stream.aclose()


async def test_subscribe_after_an_id_skips_older_events_and_sends_heartbeats() -> None:
    store = MemoryEventStore()
    store.append(1, "a", {})
    store.append(1, "b", {})
    stream = store.subscribe(1, 1, heartbeat_seconds=0.01)
    assert (await anext(stream)).type == "b"  # type: ignore[union-attr]
    assert await anext(stream) is None  # latido
    await stream.aclose()
