"""Cliente de Ollama y troceado de la transcripción (sin LLM real)."""
import httpx
import pytest

from app.models import Segment
from app.services import analyzer
from app.services.analyzer import Item, OllamaAnalyzer, _windows, get_analyzer


class FakeResponse:
    def __init__(self, content: str, status: int = 200):
        self._content, self.status_code = content, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=httpx.Request("POST", "http://x"), response=httpx.Response(self.status_code))

    def json(self):
        return {"message": {"content": self._content}}


@pytest.fixture
def ollama(env, set_env, monkeypatch):
    set_env("MT_ANALYZER", "ollama")
    set_env("MT_OLLAMA_MODEL", "qwen-test")
    calls = []

    def respond(content: str, status: int = 200):
        def fake_post(url, json, timeout):
            calls.append({"url": url, "json": json, "timeout": timeout})
            return FakeResponse(content, status)

        monkeypatch.setattr(analyzer.httpx, "post", fake_post)

    return respond, calls


def test_ollama_request_is_deterministic_json_with_system_prompt(ollama):
    respond, calls = ollama
    respond('{"items": []}')
    OllamaAnalyzer().extract("Transcripción de prueba")
    req = calls[0]
    assert req["url"].endswith("/api/chat")
    body = req["json"]
    assert body["model"] == "qwen-test"
    assert body["format"] == "json" and body["stream"] is False
    assert body["options"]["temperature"] == 0
    assert body["messages"][0]["role"] == "system" and "LITERAL" in body["messages"][0]["content"]
    assert "Transcripción de prueba" in body["messages"][1]["content"]


def test_ollama_items_are_parsed(ollama):
    respond, _ = ollama
    respond(
        '{"items":[{"kind":"decision","requirement":"Entrega","summary":"Se entrega en diciembre",'
        '"quote":"se entregará el quince de diciembre"}]}'
    )
    items = OllamaAnalyzer().extract("x")
    assert items == [Item(kind="decision", requirement="Entrega", summary="Se entrega en diciembre", quote="se entregará el quince de diciembre")]


@pytest.mark.parametrize(
    "content",
    [
        "esto no es json",
        '{"items": [{"kind": "decision"}]}',  # faltan campos obligatorios
        '{"items": "no es una lista"}',
        "[]",
    ],
)
def test_malformed_llm_output_is_discarded(ollama, content):
    respond, _ = ollama
    respond(content)
    assert OllamaAnalyzer().extract("x") == []


def test_one_malformed_item_does_not_discard_the_valid_ones(ollama):
    respond, _ = ollama
    respond('{"items":[{"kind":"decision","summary":"ok","quote":"cita válida larga"},{"summary":"sin tipo ni cita"},"basura"]}')
    assert [i.summary for i in OllamaAnalyzer().extract("x")] == ["ok"]


def test_kind_written_as_key_is_repaired(ollama):
    # Respuesta real de qwen2.5:7b capturada en el e2e.
    respond, _ = ollama
    respond(
        '{"items":[{"kind":"new_requirement","requirement":"","summary":"Pago","quote":"pagar con tarjeta"},'
        '{"decision":"delivery_date","requirement":"","summary":"Fecha de entrega","quote":"se entregará el 15 de diciembre"},'
        '{"open_question":"currency_support","requirement":"","summary":"Divisas","quote":"soporte para pagos en dólares"}]}'
    )
    assert [i.kind for i in OllamaAnalyzer().extract("x")] == ["new_requirement", "decision", "open_question"]


def test_http_errors_propagate_so_the_worker_marks_failure(ollama):
    respond, _ = ollama
    respond("{}", status=500)
    with pytest.raises(httpx.HTTPStatusError):
        OllamaAnalyzer().extract("x")


@pytest.mark.parametrize(("name", "cls"), [("ollama", OllamaAnalyzer), ("fake", analyzer.FakeAnalyzer), ("none", type(None))])
def test_get_analyzer_by_config(env, set_env, name, cls):
    set_env("MT_ANALYZER", name)
    assert isinstance(get_analyzer(), cls)


def _segs(texts):
    return [Segment(id=i, meeting_id=1, start=i, end=i + 1, text=t) for i, t in enumerate(texts)]


def test_windows_fit_in_budget_and_overlap_two_segments():
    texts = [f"frase número {i:02d} " + "x" * 30 for i in range(20)]
    windows = _windows(_segs(texts), max_chars=200)
    assert len(windows) > 1
    for w in windows:
        assert len(w.replace("\n", "")) <= 200 + 50  # un segmento puede desbordar el último hueco
    for a, b in zip(windows, windows[1:]):
        assert a.splitlines()[-2:] == b.splitlines()[:2]  # solape para no cortar citas
    joined = "\n".join(windows)
    assert all(t in joined for t in texts)  # no se pierde nada


def test_windows_small_transcript_is_single_window():
    assert _windows(_segs(["hola", "adiós"]), 6000) == ["hola\nadiós"]


def test_windows_empty():
    assert _windows([], 6000) == []
