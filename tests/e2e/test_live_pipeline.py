"""E2E contra el stack real (make start): audio de voz → Whisper → Ollama → Postgres → API.

    pytest -m e2e                       # usa http://127.0.0.1:8000 y el token de .env
    MT_E2E_API=http://host:8000 MT_API_TOKEN=... pytest -m e2e

El audio es voz sintética en español (tests/fixtures/speech_es.wav, generado con make_speech.ps1) y su
guion exacto está en speech_es.txt, así que se puede medir el WER real de Whisper.
"""

import os
import re
import time
import unicodedata
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
API = os.environ.get("MT_E2E_API", "http://127.0.0.1:8000")
MAX_WER = float(os.environ.get("MT_E2E_MAX_WER", "0.25"))
TIMEOUT_S = int(os.environ.get("MT_E2E_TIMEOUT", "420"))


def _token() -> str:
    if tok := os.environ.get("MT_API_TOKEN"):
        return tok
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("MT_API_TOKEN="):
                return line.split("=", 1)[1].strip()
    pytest.skip("Sin MT_API_TOKEN ni .env")


def normalize(text: str) -> str:
    """Minúsculas, sin tildes ni puntuación."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text)).strip()


def wer(reference: str, hypothesis: str) -> float:
    """Word Error Rate (distancia de edición por palabras / palabras de la referencia)."""
    r, h = normalize(reference).split(), normalize(hypothesis).split()
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hw in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw))
        prev = cur
    return prev[-1] / max(1, len(r))


@pytest.fixture(scope="module")
def api():
    try:
        httpx.get(f"{API}/health", timeout=3).raise_for_status()
    except httpx.HTTPError:
        pytest.skip(f"El stack no responde en {API} (make start)")
    with httpx.Client(base_url=API, headers={"Authorization": f"Bearer {_token()}"}, timeout=30) as c:
        yield c


@pytest.fixture(scope="module")
def processed(api):
    """Sube el audio como si fueran dos participantes y espera a que termine todo el pipeline."""
    info = api.get("/system").json()
    mid = api.post("/meetings", json={"title": "__e2e pytest__", "project": "__e2e__"}).json()["id"]
    try:
        wav = (FIXTURES / "speech_es.wav").read_bytes()
        for seq, (source, offset) in enumerate([("system", 0.0), ("mic", 20.0)]):
            r = api.post(
                f"/meetings/{mid}/chunks",
                files={"file": (f"{seq:06d}_{source}.wav", wav, "audio/wav")},
                data={"seq": 0, "offset_seconds": offset, "source": source},
            )
            assert r.status_code == 202, r.text
        api.post(f"/meetings/{mid}/finish").raise_for_status()

        t0 = time.monotonic()
        while time.monotonic() - t0 < TIMEOUT_S:
            m = api.get(f"/meetings/{mid}").json()
            if m["status"] == "done" and m["analysis_status"] != "pending":
                break
            time.sleep(3)
        else:
            pytest.fail(f"El pipeline no terminó en {TIMEOUT_S} s: {m}")
        yield {"id": mid, "meeting": m, "system": info, "elapsed": time.monotonic() - t0}
    finally:
        api.delete(f"/meetings/{mid}")


def test_system_is_healthy(api):
    info = api.get("/system").json()
    if info["analyzer"] == "ollama":
        assert info["ollama_reachable"], "La API no alcanza Ollama"
        assert info["ollama_model_installed"], f"Falta el modelo {info['ollama_model']} en Ollama"


def test_all_chunks_transcribed(api, processed):
    p = api.get(f"/meetings/{processed['id']}/progress").json()
    assert p["chunks_total"] == 2 and p["chunks_done"] == 2 and p["chunks_failed"] == 0
    assert processed["meeting"]["analysis_status"] in {"done", "skipped"}, processed["meeting"]["analysis_error"]


def test_whisper_accuracy_against_reference_script(api, processed):
    segs = api.get(f"/meetings/{processed['id']}/transcript", params={"format": "json"}).json()
    reference = (FIXTURES / "speech_es.txt").read_text(encoding="utf-8")
    for source in ("system", "mic"):
        text = " ".join(s["text"] for s in segs if s["source"] == source)
        # "quince" puede salir como "15": se normalizan los números del guion.
        score = min(wer(reference, text), wer(reference.replace("quince", "15"), text))
        assert score <= MAX_WER, f"WER {score:.0%} en {source}: {text!r}"
    assert not any(s["low_confidence"] for s in segs), "Voz limpia marcada como dudosa"


def test_offsets_and_speakers_are_preserved(api, processed):
    segs = api.get(f"/meetings/{processed['id']}/transcript", params={"format": "json"}).json()
    system = [s for s in segs if s["source"] == "system"]
    mic = [s for s in segs if s["source"] == "mic"]
    assert system and mic
    assert min(s["start"] for s in mic) >= 20.0 > max(s["start"] for s in system)
    assert [s["start"] for s in segs] == sorted(s["start"] for s in segs)


def test_llm_summary_covers_the_meeting(api, processed):
    if processed["meeting"]["analysis_status"] == "skipped":
        pytest.skip("Análisis desactivado")
    summary = api.get(f"/meetings/{processed['id']}").json()["summary"]
    assert summary and len(summary) >= 80, "El LLM no generó un resumen de un audio con contenido explícito"
    assert "tarjeta" in normalize(summary), f"El resumen omite un dato clave del audio: {summary!r}"


def test_search_reflects_the_meeting(api, processed):
    hits = api.get("/search", params={"q": "tarjeta"}).json()
    assert any(h["meeting_id"] == processed["id"] for h in hits)


def test_markdown_export(api, processed):
    md = api.get(f"/meetings/{processed['id']}/transcript").text
    assert md.startswith("# __e2e pytest__")
    assert "**Otros:**" in md and "**Yo:**" in md


def test_pipeline_speed(processed):
    # 2 × 15 s de audio en CPU: generoso para no ser frágil, pero detecta regresiones graves.
    assert processed["elapsed"] < TIMEOUT_S
    print(f"\nPipeline completo en {processed['elapsed']:.0f} s")
