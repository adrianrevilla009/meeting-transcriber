"""Canary tests (lo más importante): valores únicos inyectados en transcripciones no pueden aparecer en lo que
SALDRÍA a Internet. Se captura el cuerpo HTTP exacto que enviaría el adaptador real de OpenAI."""

import httpx
import pytest
from fastapi.testclient import TestClient

from privacy_shield.adapters.inbound.api.app import create_app
from privacy_shield.adapters.outbound.llm.http import AllowlistTransport
from privacy_shield.adapters.outbound.llm.openai_adapter import OpenAIAdapter
from privacy_shield.application.runtime import Runtime
from privacy_shield.domain.entities import DetectedEntity
from tests.helpers import CANARY_NAME, make_runtime

AUTH = {"Authorization": "Bearer tok"}

TRANSCRIPTS = [
    f"Oye, ¿le pasaste el informe a {CANARY_NAME}? Su correo es canario.7f3a@example.org, escríbele.",
    "Apunta el teléfono: 612 345 678 y el IBAN ES91 2100 0418 4502 0005 1332.",
    "Mi DNI es 12345678Z y la web es https://canario.example.org/x para el formulario.",
    "Su correo es canario punto zeta arroba example punto org y el móvil seis uno dos, tres cuatro cinco, seis siete ocho.",
    f"{CANARY_NAME} dijo que sí. Más tarde {CANARY_NAME.lower()} confirmó. {CANARY_NAME.upper()} firmó el acta.",
    f"Reunión con Marta García (marta.garcia@example.org). {CANARY_NAME} llamará al +34 612 345 678.",
]
# Fragmentos que NO pueden aparecer en ningún cuerpo saliente (en minúsculas).
FORBIDDEN = [
    "zoltrabek",
    "quillfeather",
    "canario.7f3a",
    "canario punto zeta",
    "canario.example.org",
    "612 345 678",
    "612345678",
    "seis uno dos",
    "es91",
    "12345678z",
    "marta garcía",
    "marta.garcia@",
]


def shield(captured: list[str]) -> tuple[Runtime, TestClient]:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.content.decode("utf-8"))
        if b'"stream": true' in request.content or b'"stream":true' in request.content:
            body = 'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"model": "gpt-x", "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})

    client = httpx.AsyncClient(transport=AllowlistTransport(["api.openai.com"], httpx.MockTransport(handler)))
    adapter = OpenAIAdapter("sk-test", client=client)
    rt, _, _ = make_runtime(adapters=[adapter], default_provider="openai")
    return rt, TestClient(create_app(rt, api_token="tok"))


def assert_clean(captured: list[str]) -> None:
    for body in captured:
        lowered = body.lower()
        for fragment in FORBIDDEN:
            assert fragment not in lowered, f"Se filtró {fragment!r} en el cuerpo saliente"


@pytest.mark.parametrize("transcript", TRANSCRIPTS)
def test_no_canary_leaves_in_a_normal_request(transcript: str) -> None:
    captured: list[str] = []
    _, client = shield(captured)
    r = client.post("/v1/chat", json={"messages": [{"role": "user", "content": transcript}]}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert len(captured) == 1
    assert_clean(captured)


@pytest.mark.parametrize("transcript", TRANSCRIPTS)
def test_no_canary_leaves_when_streaming(transcript: str) -> None:
    captured: list[str] = []
    _, client = shield(captured)
    r = client.post("/v1/chat", json={"messages": [{"role": "user", "content": transcript}], "stream": True}, headers=AUTH)
    assert r.status_code == 200
    assert len(captured) == 1
    assert_clean(captured)


def test_the_outgoing_body_carries_tokens_instead() -> None:
    captured: list[str] = []
    _, client = shield(captured)
    client.post("/v1/chat", json={"messages": [{"role": "user", "content": TRANSCRIPTS[3]}]}, headers=AUTH)
    assert "[EMAIL_1]" in captured[0] and "[TELEFONO_1]" in captured[0]


def test_canaries_in_system_assistant_and_name_fields_are_covered() -> None:
    captured: list[str] = []
    _, client = shield(captured)
    body = {
        "messages": [
            {"role": "system", "content": f"El usuario se llama {CANARY_NAME}."},
            {"role": "assistant", "content": "Hola, canario.7f3a@example.org, ¿en qué te ayudo?"},
            {"role": "user", "name": CANARY_NAME, "content": "Llámame al 612 345 678"},
        ]
    }
    assert client.post("/v1/chat", json=body, headers=AUTH).status_code == 200
    assert_clean(captured)


def test_one_session_shares_tokens_across_calls_without_leaking() -> None:
    captured: list[str] = []
    _, client = shield(captured)
    first = client.post("/v1/chat", json={"messages": [{"role": "user", "content": TRANSCRIPTS[0]}]}, headers=AUTH).json()
    for transcript in TRANSCRIPTS[1:]:
        body = {"session_id": first["session_id"], "messages": [{"role": "user", "content": transcript}]}
        assert client.post("/v1/chat", json=body, headers=AUTH).status_code == 200
    assert len(captured) == len(TRANSCRIPTS)
    assert_clean(captured)


def test_fail_closed_when_the_detector_breaks() -> None:
    class Boom:
        def detect(self, text: str, *, language: str = "es") -> list[DetectedEntity]:
            raise RuntimeError("detector caído")

    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.content.decode("utf-8"))
        return httpx.Response(200, json={})

    client_http = httpx.AsyncClient(transport=AllowlistTransport(["api.openai.com"], httpx.MockTransport(handler)))
    rt, _, _ = make_runtime(adapters=[OpenAIAdapter("sk-test", client=client_http)], detector=Boom(), default_provider="openai")
    client = TestClient(create_app(rt, api_token="tok"))
    r = client.post("/v1/chat", json={"messages": [{"role": "user", "content": TRANSCRIPTS[0]}]}, headers=AUTH)
    assert r.status_code == 503
    assert captured == []  # no se hizo ninguna llamada saliente
