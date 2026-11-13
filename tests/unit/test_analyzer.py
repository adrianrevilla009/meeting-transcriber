"""Resumen con Ollama y troceado de la transcripción (sin LLM real)."""

import itertools

import httpx
import pytest

from app.models import Segment
from app.services import analyzer
from app.services.analyzer import OllamaAnalyzer, _windows, get_analyzer


class FakeResponse:
    def __init__(self, content: str, status: int = 200):
        self._content, self.status_code = content, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "boom", request=httpx.Request("POST", "http://x"), response=httpx.Response(self.status_code)
            )

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


def test_summarize_request_is_deterministic_with_system_prompt(ollama):
    respond, calls = ollama
    respond("Se acordó migrar a Postgres.")
    assert OllamaAnalyzer().summarize("Transcripción de prueba") == "Se acordó migrar a Postgres."
    req = calls[0]
    assert req["url"].endswith("/api/chat")
    body = req["json"]
    assert body["model"] == "qwen-test" and body["stream"] is False
    assert body["options"]["temperature"] == 0
    assert body["messages"][0]["role"] == "system" and "TODO lo relevante" in body["messages"][0]["content"]
    assert "Transcripción de prueba" in body["messages"][1]["content"]


def test_summary_is_stripped(ollama):
    respond, _ = ollama
    respond("  \nResumen con espacios.\n\n")
    assert OllamaAnalyzer().summarize("x") == "Resumen con espacios."


def test_merge_sends_every_partial_summary(ollama):
    respond, calls = ollama
    respond("Resumen final")
    assert OllamaAnalyzer().merge(["Parte A", "Parte B"]) == "Resumen final"
    user = calls[0]["json"]["messages"][1]["content"]
    assert "Parte A" in user and "Parte B" in user


def test_http_errors_propagate_so_the_worker_marks_failure(ollama):
    respond, _ = ollama
    respond("{}", status=500)
    with pytest.raises(httpx.HTTPStatusError):
        OllamaAnalyzer().summarize("x")


@pytest.mark.parametrize(
    ("name", "cls"), [("ollama", OllamaAnalyzer), ("fake", analyzer.FakeAnalyzer), ("none", type(None))]
)
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
    for a, b in itertools.pairwise(windows):
        assert a.splitlines()[-2:] == b.splitlines()[:2]  # solape para no cortar frases
    joined = "\n".join(windows)
    assert all(t in joined for t in texts)  # no se pierde nada


def test_windows_small_transcript_is_single_window():
    assert _windows(_segs(["hola", "adiós"]), 6000) == ["hola\nadiós"]


def test_windows_empty():
    assert _windows([], 6000) == []
