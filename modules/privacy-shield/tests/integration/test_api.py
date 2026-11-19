"""API + FakeLLM: el caso de uso principal de extremo a extremo, errores, auth, streaming y auditoría."""

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from privacy_shield.adapters.inbound.api.app import create_app
from privacy_shield.adapters.outbound.audit.jsonl import JsonlAuditAdapter
from privacy_shield.adapters.outbound.llm.fake_adapter import FakeLLMAdapter
from privacy_shield.application.ports import DetectorPort
from privacy_shield.application.runtime import Runtime
from privacy_shield.domain.audit import AuditEvent
from privacy_shield.domain.entities import DetectedEntity
from privacy_shield.domain.errors import ProviderError
from privacy_shield.domain.policy import Policy
from tests.helpers import make_runtime

AUTH = {"Authorization": "Bearer tok"}
TEXT = "Hola, soy Marta García y mi correo es marta@example.org"
EXPECTED_OUT = "Hola, soy [PERSONA_1] y mi correo es [EMAIL_1]"


def client_for(rt: Runtime, *, bearer: str = "tok", debug: bool = False) -> TestClient:
    return TestClient(create_app(rt, api_token=bearer, debug_mapping=debug))


def chat_body(text: str = TEXT, **extra: object) -> dict[str, object]:
    return {"messages": [{"role": "user", "content": text}], **extra}


# ------------------------------------------------------------------ auth
def test_health_is_public() -> None:
    rt, _, _ = make_runtime()
    body = client_for(rt).get("/health").json()
    assert body["status"] == "ok" and body["providers"] == ["fake"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/v1/anonymize"),
        ("post", "/v1/deanonymize"),
        ("post", "/v1/chat"),
        ("get", "/v1/providers"),
        ("delete", "/v1/sessions/x"),
        ("get", "/v1/sessions/x/mapping"),
    ],
)
def test_endpoints_require_the_token(method: str, path: str) -> None:
    rt, _, _ = make_runtime()
    c = client_for(rt)
    assert getattr(c, method)(path).status_code == 401
    assert getattr(c, method)(path, headers={"Authorization": "Bearer mal"}).status_code == 401


@pytest.mark.parametrize("token", ["", "change-me"])
def test_unconfigured_token_fails_closed(token: str) -> None:
    rt, _, _ = make_runtime()
    assert client_for(rt, bearer=token).get("/v1/providers", headers={"Authorization": f"Bearer {token}"}).status_code == 503


# ------------------------------------------------------------------ anonymize / deanonymize
def test_anonymize_then_deanonymize_round_trip() -> None:
    rt, _, _ = make_runtime()
    c = client_for(rt)
    out = c.post("/v1/anonymize", json={"text": TEXT}, headers=AUTH).json()
    assert out["text"] == EXPECTED_OUT
    assert [(e["type"], e["token"], e["strategy"]) for e in out["entities"]] == [
        ("PERSONA", "[PERSONA_1]", "pseudonymize"),
        ("EMAIL", "[EMAIL_1]", "pseudonymize"),
    ]
    assert "Marta" not in json.dumps(out) and "marta@example.org" not in json.dumps(out)  # sin valores reales
    back = c.post("/v1/deanonymize", json={"session_id": out["session_id"], "text": "Para " + out["text"]}, headers=AUTH)
    assert back.json() == {"text": "Para " + TEXT}


def test_same_session_keeps_the_same_tokens() -> None:
    rt, _, _ = make_runtime()
    c = client_for(rt)
    first = c.post("/v1/anonymize", json={"text": "Escribe a ana@example.org"}, headers=AUTH).json()
    second = c.post(
        "/v1/anonymize", json={"session_id": first["session_id"], "text": "Otra vez ana@example.org y luis@example.org"}, headers=AUTH
    ).json()
    assert second["text"] == "Otra vez [EMAIL_1] y [EMAIL_2]"


def test_card_numbers_are_blocked() -> None:
    rt, _, _ = make_runtime()
    r = client_for(rt).post("/v1/anonymize", json={"text": "Pago con 4111 1111 1111 1111"}, headers=AUTH)
    assert r.status_code == 422 and r.json() == {"error": "policy_blocked", "types": ["TARJETA"]}


def test_deanonymize_unknown_session_is_404() -> None:
    rt, _, _ = make_runtime()
    r = client_for(rt).post("/v1/deanonymize", json={"session_id": "nope", "text": "x"}, headers=AUTH)
    assert r.status_code == 404 and r.json() == {"error": "session_not_found"}


def test_delete_session_forgets_everything() -> None:
    rt, _, _ = make_runtime()
    c = client_for(rt)
    sid = c.post("/v1/anonymize", json={"text": TEXT}, headers=AUTH).json()["session_id"]
    assert c.delete(f"/v1/sessions/{sid}", headers=AUTH).status_code == 204
    assert c.post("/v1/deanonymize", json={"session_id": sid, "text": "x"}, headers=AUTH).status_code == 404


def test_mapping_endpoint_is_disabled_by_default() -> None:
    rt, _, _ = make_runtime()
    c = client_for(rt)
    sid = c.post("/v1/anonymize", json={"text": TEXT}, headers=AUTH).json()["session_id"]
    assert c.get(f"/v1/sessions/{sid}/mapping", headers=AUTH).status_code == 404


def test_mapping_endpoint_when_debugging() -> None:
    rt, _, _ = make_runtime()
    c = client_for(rt, debug=True)
    sid = c.post("/v1/anonymize", json={"text": TEXT}, headers=AUTH).json()["session_id"]
    mapping = c.get(f"/v1/sessions/{sid}/mapping", headers=AUTH).json()["mapping"]
    assert mapping == {"[PERSONA_1]": "Marta García", "[EMAIL_1]": "marta@example.org"}


# ------------------------------------------------------------------ chat
def test_chat_sends_only_tokens_and_returns_the_real_values() -> None:
    fake = FakeLLMAdapter()
    rt, _, _ = make_runtime(adapters=[fake])
    r = client_for(rt).post("/v1/chat", json=chat_body(), headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["message"]["content"] == f"Entendido: {TEXT}"  # el eco del LLM, ya revertido
    assert body["provider"] == "fake" and body["entities"] == {"PERSONA": 1, "EMAIL": 1} and body["unknown_tokens"] == 0
    [call] = fake.calls
    assert call.messages[0].content == EXPECTED_OUT
    outgoing = fake.captured_payloads()[0]
    assert "Marta" not in outgoing and "marta@example.org" not in outgoing


def test_chat_pseudonymizes_every_message_and_keeps_the_session() -> None:
    fake = FakeLLMAdapter()
    rt, _, _ = make_runtime(adapters=[fake])
    c = client_for(rt)
    first = c.post("/v1/chat", json=chat_body(), headers=AUTH).json()
    body = {
        "session_id": first["session_id"],
        "messages": [
            {"role": "system", "content": "Eres el asistente de Marta García."},
            {"role": "assistant", "content": "Claro, Marta."},
            {"role": "user", "content": "Avisa a luis@example.org"},
        ],
    }
    c.post("/v1/chat", json=body, headers=AUTH)
    assert [m.content for m in fake.calls[1].messages] == [
        "Eres el asistente de [PERSONA_1].",
        "Claro, [PERSONA_1].",
        "Avisa a [EMAIL_2]",
    ]


def test_chat_streaming_equals_non_streaming() -> None:
    fake = FakeLLMAdapter(chunk_size=5)  # trozos pequeños: parten los tokens
    rt, _, _ = make_runtime(adapters=[fake])
    c = client_for(rt)
    plain = c.post("/v1/chat", json=chat_body(), headers=AUTH).json()["message"]["content"]
    response = c.post("/v1/chat", json=chat_body(stream=True), headers=AUTH)
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    events = [b[6:] for b in response.text.split("\n\n") if b.startswith("data: ")]
    assert events[-1] == "[DONE]"
    chunks = [json.loads(e) for e in events[:-1]]
    assert "".join(ch["content"] for ch in chunks) == plain
    assert chunks[-1]["finish_reason"] == "stop"
    assert "marta@example.org" not in fake.captured_payloads()[1]


def test_a_value_found_in_a_later_message_is_swept_from_the_earlier_ones() -> None:
    fake = FakeLLMAdapter()
    rt, _, _ = make_runtime(adapters=[fake])
    body = {
        "messages": [
            {"role": "system", "content": "No olvides a marta en la lista."},  # sin pista: no se detecta aquí
            {"role": "user", "content": "Habla con Marta mañana."},  # aquí sí ("con" es una pista)
        ]
    }
    r = client_for(rt).post("/v1/chat", json=body, headers=AUTH)
    assert r.status_code == 200, r.text
    [call] = fake.calls
    assert [m.content for m in call.messages] == [
        "No olvides a [PERSONA_1] en la lista.",
        "Habla con [PERSONA_1] mañana.",
    ]
    assert "arta" not in fake.captured_payloads()[0]


def test_leak_guard_blocks_what_the_detector_missed() -> None:
    class Blind:
        def detect(self, text: str, *, language: str = "es") -> list[DetectedEntity]:
            return []

    fake = FakeLLMAdapter()
    detector: DetectorPort = Blind()
    rt, audit, _ = make_runtime(adapters=[fake], detector=detector)
    r = client_for(rt).post("/v1/chat", json=chat_body("Escríbeme a ana.ruiz@example.org"), headers=AUTH)
    assert r.status_code == 422 and r.json() == {"error": "leak_detected", "types": {"EMAIL": 1}}
    assert fake.calls == []  # no salió nada
    assert audit.events[-1].leak_blocked and audit.events[-1].outcome == "leak_blocked"


def test_detector_failure_means_nothing_leaves() -> None:
    class Boom:
        def detect(self, text: str, *, language: str = "es") -> list[DetectedEntity]:
            raise RuntimeError("modelo caído")

    fake = FakeLLMAdapter()
    detector: DetectorPort = Boom()
    rt, audit, _ = make_runtime(adapters=[fake], detector=detector)
    r = client_for(rt).post("/v1/chat", json=chat_body(), headers=AUTH)
    assert r.status_code == 503 and r.json() == {"error": "detector_unavailable"}
    assert fake.calls == [] and audit.events[-1].outcome == "detector_unavailable"


def test_policy_block_means_nothing_leaves() -> None:
    fake = FakeLLMAdapter()
    rt, _, _ = make_runtime(adapters=[fake])
    r = client_for(rt).post("/v1/chat", json=chat_body("Mi tarjeta es 4111 1111 1111 1111"), headers=AUTH)
    assert r.status_code == 422 and r.json()["error"] == "policy_blocked"
    assert fake.calls == []


def test_unknown_and_unconfigured_providers() -> None:
    rt, _, _ = make_runtime(adapters=[FakeLLMAdapter(), FakeLLMAdapter(name="sin_clave", configured=False)])
    c = client_for(rt)
    assert c.post("/v1/chat", json=chat_body(provider="otro"), headers=AUTH).json() == {"error": "provider_not_found"}
    r = c.post("/v1/chat", json=chat_body(provider="sin_clave"), headers=AUTH)
    assert r.status_code == 503 and r.json() == {"error": "provider_not_configured"}


def test_provider_failures_are_502_and_never_echo_content() -> None:
    fake = FakeLLMAdapter(fail_with=ProviderError("openai respondió con HTTP 500"))
    rt, audit, _ = make_runtime(adapters=[fake])
    r = client_for(rt).post("/v1/chat", json=chat_body(), headers=AUTH)
    assert r.status_code == 502 and r.json() == {"error": "provider_error"}
    assert audit.events[-1].outcome == "provider_error"


def test_unknown_tokens_from_the_llm_are_left_and_counted() -> None:
    fake = FakeLLMAdapter(lambda req: "Hablé con [PERSONA_9] y con [EMAIL_1]")
    rt, audit, _ = make_runtime(adapters=[fake])
    body = client_for(rt).post("/v1/chat", json=chat_body(), headers=AUTH).json()
    assert body["message"]["content"] == "Hablé con [PERSONA_9] y con marta@example.org"
    assert body["unknown_tokens"] == 1 and audit.events[-1].unknown_tokens == 1


def test_local_providers_skip_pseudonymization_by_default() -> None:
    local = FakeLLMAdapter(name="local", leaves_machine=False)
    rt, audit, _ = make_runtime(adapters=[local], default_provider="local")
    body = client_for(rt).post("/v1/chat", json=chat_body(), headers=AUTH).json()
    assert local.calls[0].messages[0].content == TEXT  # sin tocar: no sale de la máquina
    assert body["message"]["content"] == f"Entendido: {TEXT}" and audit.events[-1].skipped_local


def test_local_providers_can_be_forced_through_the_shield() -> None:
    local = FakeLLMAdapter(name="local", leaves_machine=False)
    rt, _, _ = make_runtime(adapters=[local], default_provider="local", skip_local=False)
    client_for(rt).post("/v1/chat", json=chat_body(), headers=AUTH)
    assert local.calls[0].messages[0].content == EXPECTED_OUT


def test_local_only_policy_rejects_cloud_providers() -> None:
    fake = FakeLLMAdapter()
    rt, _, _ = make_runtime(adapters=[fake], policy=Policy(local_only=True))
    r = client_for(rt).post("/v1/chat", json=chat_body(), headers=AUTH)
    assert r.status_code == 403 and r.json() == {"error": "provider_not_allowed"}
    assert fake.calls == []


def test_providers_listing_never_shows_keys() -> None:
    rt, _, _ = make_runtime(adapters=[FakeLLMAdapter(), FakeLLMAdapter(name="local", leaves_machine=False, configured=False)])
    listing = client_for(rt).get("/v1/providers", headers=AUTH).json()
    assert listing == [
        {"name": "fake", "configured": True, "leaves_machine": True},
        {"name": "local", "configured": False, "leaves_machine": False},
    ]


def test_request_validation() -> None:
    rt, _, _ = make_runtime()
    c = client_for(rt)
    assert c.post("/v1/chat", json={"messages": []}, headers=AUTH).status_code == 422
    assert c.post("/v1/chat", json={"messages": [{"role": "robot", "content": "x"}]}, headers=AUTH).status_code == 422


# ------------------------------------------------------------------ auditoría
def test_audit_has_counts_and_latencies_but_no_plaintext() -> None:
    rt, audit, _ = make_runtime()
    client_for(rt).post("/v1/chat", json=chat_body(), headers=AUTH)
    [event] = audit.events
    assert event.operation == "chat" and event.provider == "fake" and event.outcome == "ok"
    assert event.entity_counts == {"PERSONA": 1, "EMAIL": 1} and event.strategy_counts == {"pseudonymize": 2}
    assert len(event.session_hash) == 12 and event.total_ms >= event.provider_ms >= 0
    dumped = json.dumps(asdict(event), default=str)
    assert "Marta" not in dumped and "example.org" not in dumped


def test_jsonl_audit_adapter_writes_one_line_per_event(tmp_path: Path) -> None:
    path = tmp_path / "audit" / "events.jsonl"
    JsonlAuditAdapter(path).record(AuditEvent(datetime(2026, 1, 1, tzinfo=UTC), "chat", "abc123abc123"))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["operation"] == "chat"
