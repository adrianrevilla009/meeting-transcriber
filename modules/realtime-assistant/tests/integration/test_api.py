"""API HTTP + piezas falsas: auth, seguimiento, preguntas manuales, eventos SSE y configuración."""

import json
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from realtime_assistant.adapters.inbound.api.app import create_app, sse
from realtime_assistant.application.runtime import Runtime
from realtime_assistant.bootstrap import build_runtime
from realtime_assistant.config import Settings
from realtime_assistant.domain.errors import MeetingNotFound, ShieldBlocked, TranscriberUnavailable
from tests.helpers import FakeGenerator, FakeSource, make_runtime, seg

AUTH = {"Authorization": "Bearer tok"}
Env = tuple[TestClient, Runtime, FakeSource, FakeGenerator]


@pytest.fixture
def env() -> Iterator[Env]:
    rt, source, generator, _ = make_runtime()
    with TestClient(create_app(rt, api_token="tok")) as client:  # el 'with' mantiene vivo el bucle de eventos
        yield client, rt, source, generator


def read_events(client: TestClient, after: int = 0, meeting_id: int = 1) -> list[dict[str, object]]:
    response = client.get(f"/v1/meetings/{meeting_id}/events", params={"after": after, "once": True}, headers=AUTH)
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    frames = [f for f in response.text.split("\n\n") if f]
    assert all(f.startswith("data: ") for f in frames)
    return [json.loads(f[6:]) for f in frames]


def wait_for(client: TestClient, event_type: str, timeout: float = 3.0) -> list[dict[str, object]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        events = read_events(client)
        if any(e["type"] == event_type for e in events):
            return events
        time.sleep(0.02)
    raise AssertionError(f"No llegó '{event_type}': {read_events(client)}")


# ------------------------------------------------------------------ auth
def test_health_is_public(env: Env) -> None:
    client, *_ = env
    assert client.get("/health").json() == {"status": "ok", "classifier": "rules", "auto_answer": True}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/v1/meetings/1/follow"),
        ("delete", "/v1/meetings/1/follow"),
        ("get", "/v1/meetings/1/status"),
        ("post", "/v1/meetings/1/ask"),
        ("post", "/v1/meetings/1/questions/q1/answer"),
        ("get", "/v1/meetings/1/events"),
    ],
)
def test_endpoints_require_the_token(env: Env, method: str, path: str) -> None:
    client, *_ = env
    assert getattr(client, method)(path).status_code == 401
    assert getattr(client, method)(path, headers={"Authorization": "Bearer mal"}).status_code == 401


@pytest.mark.parametrize("token", ["", "change-me"])
def test_unconfigured_token_fails_closed(token: str) -> None:
    rt, *_ = make_runtime()
    with TestClient(create_app(rt, api_token=token)) as client:
        assert client.get("/v1/meetings/1/status", headers={"Authorization": f"Bearer {token}"}).status_code == 503


# ------------------------------------------------------------------ seguimiento
def test_follow_status_and_unfollow(env: Env) -> None:
    client, *_ = env
    assert client.get("/v1/meetings/1/status", headers=AUTH).json() == {"following": False, "questions": 0, "answers": 0}
    assert client.post("/v1/meetings/1/follow", headers=AUTH).json() == {"meeting_id": 1, "following": True}
    assert client.post("/v1/meetings/1/follow", headers=AUTH).status_code == 200  # idempotente
    assert client.get("/v1/meetings/1/status", headers=AUTH).json()["following"] is True
    assert client.delete("/v1/meetings/1/follow", headers=AUTH).status_code == 204
    assert client.get("/v1/meetings/1/status", headers=AUTH).json()["following"] is False
    assert client.delete("/v1/meetings/99/follow", headers=AUTH).status_code == 204  # sin efecto


def test_follow_errors(env: Env) -> None:
    client, _, source, _ = env
    source.error = MeetingNotFound("1")
    assert client.post("/v1/meetings/1/follow", headers=AUTH).json() == {"error": "meeting_not_found"}
    source.error = TranscriberUnavailable("caído")
    r = client.post("/v1/meetings/1/follow", headers=AUTH)
    assert r.status_code == 503 and r.json() == {"error": "transcriber_unavailable"}


def test_following_detects_questions_from_the_transcript(env: Env) -> None:
    client, _, source, generator = env
    client.post("/v1/meetings/1/follow", headers=AUTH)
    source.add(seg(1, "Buenos días.", start=0.0), seg(2, "¿Cuándo podemos tener el informe?", start=4.5))
    events = wait_for(client, "answer_done")
    assert [e["type"] for e in events][:2] == ["status", "question"]
    question = events[1]
    assert question["text"] == "¿Cuándo podemos tener el informe?" and question["origin"] == "detected"
    assert generator.calls and generator.calls[0][1] == "¿Cuándo podemos tener el informe?"
    client.delete("/v1/meetings/1/follow", headers=AUTH)


# ------------------------------------------------------------------ preguntas y eventos
def test_manual_question_streams_an_answer(env: Env) -> None:
    client, _, _, generator = env
    r = client.post("/v1/meetings/1/ask", json={"text": "¿Qué opinas del plan?"}, headers=AUTH)
    assert r.status_code == 202 and r.json() == {"question_id": "q1"}
    events = wait_for(client, "answer_done")
    assert [e["type"] for e in events] == ["question", "answer_start", "answer_chunk", "answer_chunk", "answer_done"]
    assert events[0] == {"id": 1, "type": "question", "question_id": "q1", "text": "¿Qué opinas del plan?",
                         "ts": 0.0, "origin": "manual", "score": 1.0}  # fmt: skip
    assert events[-1]["content"] == "Respuesta corta." and events[-1]["question_id"] == "q1"
    assert [e["id"] for e in events] == [1, 2, 3, 4, 5]
    assert generator.calls[0][:2] == (1, "¿Qué opinas del plan?")


def test_events_after_an_id_only_return_newer_ones(env: Env) -> None:
    client, *_ = env
    client.post("/v1/meetings/1/ask", json={"text": "¿Qué opinas del plan?"}, headers=AUTH)
    wait_for(client, "answer_done")
    assert [e["id"] for e in read_events(client, after=3)] == [4, 5]
    assert read_events(client, after=5) == []
    assert read_events(client, meeting_id=2) == []
    assert client.get("/v1/meetings/1/events", params={"after": -1}, headers=AUTH).status_code == 422


def test_ask_validates_its_body(env: Env) -> None:
    client, *_ = env
    assert client.post("/v1/meetings/1/ask", json={"text": ""}, headers=AUTH).status_code == 422
    assert client.post("/v1/meetings/1/ask", json={}, headers=AUTH).status_code == 422
    assert client.post("/v1/meetings/1/ask", json={"text": "x" * 2001}, headers=AUTH).status_code == 422


def test_answer_endpoint(env: Env) -> None:
    client, *_ = env
    r = client.post("/v1/meetings/1/questions/q9/answer", headers=AUTH)
    assert r.status_code == 404 and r.json() == {"error": "question_not_found"}


def test_failed_answers_report_a_code_and_can_be_retried() -> None:
    generator = FakeGenerator(error=ShieldBlocked("leak_detected"))
    rt, *_ = make_runtime(generator=generator)
    with TestClient(create_app(rt, api_token="tok")) as client:
        client.post("/v1/meetings/1/ask", json={"text": "¿Qué opinas del plan?"}, headers=AUTH)
        events = wait_for(client, "error")
        assert events[-1] == {"id": 3, "type": "error", "question_id": "q1", "error": "leak_detected"}
        generator.error = None
        assert client.post("/v1/meetings/1/questions/q1/answer", headers=AUTH).status_code == 202
        assert wait_for(client, "answer_done")[-1]["content"] == "Respuesta corta."


async def test_live_stream_replays_and_follows_new_events() -> None:
    rt, *_ = make_runtime()
    stream = sse(rt, 1, 0, False)
    await rt.assistant.ask(1, "¿Qué opinas del plan?")
    first = await anext(stream)
    assert first.startswith("data: ") and json.loads(first[6:])["type"] == "question"
    types = [json.loads((await anext(stream))[6:])["type"] for _ in range(4)]
    assert types == ["answer_start", "answer_chunk", "answer_chunk", "answer_done"]
    await stream.aclose()
    await rt.assistant.shutdown()


# ------------------------------------------------------------------ configuración y composición
def test_settings_parse_lists_and_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RTA_USER_NAMES", "Adrián,  Adri , ")
    monkeypatch.setenv("RTA_LISTEN_SOURCES", "system")
    settings = Settings()
    assert settings.user_name_list == ("Adrián", "Adri") and settings.listen_source_set == frozenset({"system"})
    assert settings.transcriber_url == "http://api:8000" and settings.shield_url == "http://privacy-shield:8100"
    assert settings.classifier == "ollama" and settings.auto_answer is True


def test_default_wiring_uses_the_local_classifier_unless_rules_only() -> None:
    assert build_runtime(Settings(api_token="tok")).health()["classifier"] == "ollama"
    assert build_runtime(Settings(api_token="tok", classifier="rules")).health()["classifier"] == "rules"
    assert build_runtime(Settings(api_token="tok"), rules_only=True).health()["classifier"] == "rules"
