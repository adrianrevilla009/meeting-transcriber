"""E2E del módulo 2 (privacy-shield): lo que llega al LLM no contiene datos personales y la respuesta se restaura."""

import json

import httpx
import pytest
from helpers import SHIELD, captured

TEXT = "Hola, soy Marta García, mi correo es marta@empresa.es y mi teléfono es 612 345 678."
SECRETS = ["Marta", "García", "marta@empresa.es", "612 345 678", "612345678"]


def chat(shield: httpx.Client, text: str, **extra: object) -> httpx.Response:
    return shield.post("/v1/chat", json={"messages": [{"role": "user", "content": text}], **extra})


def assert_clean(stub: httpx.Client, secrets: list[str] = SECRETS) -> list[dict[str, object]]:
    sent = captured(stub, "chat")
    assert sent, "El LLM no recibió nada: el E2E no está probando lo que cree"
    dump = json.dumps(sent, ensure_ascii=False)
    for secret in secrets:
        assert secret not in dump, f"Se filtró {secret!r} hacia el LLM"
    return sent


def test_health_and_providers(shield: httpx.Client) -> None:
    assert shield.get("/health").json()["status"] == "ok"
    providers = {p["name"]: p for p in shield.get("/v1/providers").json()}
    assert providers["ollama"]["configured"] is True and providers["ollama"]["leaves_machine"] is False
    assert providers["openai"]["configured"] is False and providers["anthropic"]["configured"] is False


def test_anonymize_and_deanonymize_round_trip(shield: httpx.Client) -> None:
    out = shield.post("/v1/anonymize", json={"text": TEXT}).json()
    for secret in SECRETS:
        assert secret not in out["text"]
    assert "[PERSONA_1]" in out["text"] and "[EMAIL_1]" in out["text"] and "[TELEFONO_1]" in out["text"]
    assert {e["type"] for e in out["entities"]} >= {"PERSONA", "EMAIL", "TELEFONO"}
    back = shield.post("/v1/deanonymize", json={"session_id": out["session_id"], "text": "Para " + out["text"]}).json()
    assert back["text"] == "Para " + TEXT


def test_chat_sends_only_tokens_and_returns_the_real_values(shield: httpx.Client, stub: httpx.Client) -> None:
    r = chat(shield, TEXT + " ¿Puedes resumirlo?")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "ollama" and all(body["entities"][k] >= 1 for k in ("PERSONA", "EMAIL", "TELEFONO"))
    assert body["message"]["content"] == "ECO-STUB: " + TEXT + " ¿Puedes resumirlo?"  # el eco, ya restaurado
    [call] = assert_clean(stub)
    sent = call["body"]["messages"][0]["content"]  # type: ignore[index]
    assert "[PERSONA_1]" in sent and "[EMAIL_1]" in sent and "[TELEFONO_1]" in sent


def test_the_same_session_keeps_the_same_tokens(shield: httpx.Client, stub: httpx.Client) -> None:
    first = chat(shield, "Escribe a marta@empresa.es").json()
    chat(shield, "Y avisa también a luis@empresa.es y a marta@empresa.es", session_id=first["session_id"])
    sent = [c["body"]["messages"][0]["content"] for c in assert_clean(stub, ["marta@empresa.es", "luis@empresa.es"])]  # type: ignore[index]
    assert sent[0] == "Escribe a [EMAIL_1]" and sent[1] == "Y avisa también a [EMAIL_2] y a [EMAIL_1]"


def test_streaming_matches_the_plain_answer_and_is_also_clean(shield: httpx.Client, stub: httpx.Client) -> None:
    plain = chat(shield, TEXT).json()["message"]["content"]
    stub.delete("/_captured")
    with shield.stream("POST", "/v1/chat", json={"messages": [{"role": "user", "content": TEXT}], "stream": True}) as r:
        assert r.status_code == 200
        lines = [line for line in r.iter_lines() if line.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    streamed = "".join(json.loads(line[6:])["content"] for line in lines[:-1])
    assert streamed == plain
    assert_clean(stub)


def test_dictated_emails_and_phones_do_not_leave(shield: httpx.Client, stub: httpx.Client) -> None:
    spoken = "Mi correo es marta punto garcia arroba gmail punto com y mi móvil seis uno dos, tres cuatro cinco, seis siete ocho."
    r = chat(shield, spoken)
    assert r.status_code == 200 and r.json()["message"]["content"] == "ECO-STUB: " + spoken
    assert_clean(stub, ["marta punto garcia", "seis uno dos", "gmail punto com"])


@pytest.mark.parametrize(
    ("text", "blocked"),
    [
        ("Cobra con la tarjeta 4111 1111 1111 1111 por favor", "TARJETA"),
        ("La clave de la API es sk-abcdefghijklmnopqrstuvwxyz0123456789ABCD", "SECRETO"),
    ],
)
def test_cards_and_secrets_block_the_request_and_nothing_leaves(
    shield: httpx.Client, stub: httpx.Client, text: str, blocked: str
) -> None:
    r = chat(shield, text)
    assert r.status_code == 422 and r.json() == {"error": "policy_blocked", "types": [blocked]}
    assert captured(stub, "chat") == []


def test_iban_and_dni_are_masked_not_reversible(shield: httpx.Client, stub: httpx.Client) -> None:
    text = "Mi DNI es 12345678Z y mi IBAN es ES91 2100 0418 4502 0005 1332."
    body = chat(shield, text).json()
    assert "[DNI_NIE]" in body["message"]["content"] and "[IBAN]" in body["message"]["content"]
    assert "12345678Z" not in body["message"]["content"]
    assert_clean(stub, ["12345678Z", "ES91", "2100 0418"])


def test_unknown_provider_and_bad_requests(shield: httpx.Client, stub: httpx.Client) -> None:
    assert chat(shield, "hola", provider="no-existe").json() == {"error": "provider_not_found"}
    anthropic = chat(shield, "hola", provider="anthropic")  # sin clave configurada
    assert anthropic.status_code == 503 and anthropic.json() == {"error": "provider_not_configured"}
    assert shield.post("/v1/chat", json={"messages": []}).status_code == 422
    assert captured(stub, "chat") == []


def test_shield_requires_its_token() -> None:
    with httpx.Client(base_url=SHIELD, timeout=10) as client:
        assert client.post("/v1/chat", json={"messages": [{"role": "user", "content": "x"}]}).status_code == 401
        assert client.get("/v1/providers", headers={"Authorization": "Bearer mal"}).status_code == 401
        assert client.get("/health").status_code == 200
