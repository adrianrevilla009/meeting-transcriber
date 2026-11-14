"""Contrato HTTP de la API: validaciones, códigos de estado, auditoría y endpoints del frontal."""

import httpx
import pytest
from sqlalchemy import select

from app.api import main
from app.models import AuditLog, Chunk
from app.services.analyzer import FakeAnalyzer
from tests.helpers import drain, new_meeting, upload

PROTECTED = [
    ("get", "/meetings"),
    ("post", "/meetings"),
    ("get", "/meetings/1"),
    ("get", "/meetings/1/progress"),
    ("post", "/meetings/1/finish"),
    ("get", "/meetings/1/transcript"),
    ("post", "/meetings/1/analyze"),
    ("delete", "/meetings/1"),
    ("get", "/search?q=hola"),
    ("get", "/system"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_every_endpoint_requires_token(anon, method, path):
    assert getattr(anon, method)(path).status_code == 401


def test_health_is_public(anon):
    assert anon.get("/health").json() == {"status": "ok"}


def test_create_and_list_meetings_newest_first_with_project_filter(client):
    a = new_meeting(client, "A", "pagos")
    b = new_meeting(client, "B", "web")
    c = new_meeting(client, "C", "pagos")
    assert [m["id"] for m in client.get("/meetings").json()] == [c, b, a]
    assert [m["id"] for m in client.get("/meetings", params={"project": "pagos"}).json()] == [c, a]
    m = client.get(f"/meetings/{a}").json()
    assert m["status"] == "recording" and m["analysis_status"] == "pending" and m["finished_at"] is None


@pytest.mark.parametrize(
    "path",
    [
        "/meetings/999",
        "/meetings/999/progress",
        "/meetings/999/transcript",
    ],
)
def test_unknown_ids_are_404(client, path):
    assert client.get(path).status_code == 404


def test_upload_rejects_invalid_source(client):
    mid = new_meeting(client)
    assert upload(client, mid, 0, "x", source="webcam").status_code == 422


def test_upload_rejects_oversized_chunk(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_CHUNK_BYTES", 10)
    mid = new_meeting(client)
    assert upload(client, mid, 0, "x" * 11).status_code == 413
    assert upload(client, mid, 0, "x" * 10).status_code == 202


def test_upload_requires_seq(client):
    mid = new_meeting(client)
    r = client.post(f"/meetings/{mid}/chunks", files={"file": ("a.wav", b"x")})
    assert r.status_code == 422


def test_uploaded_file_stays_inside_audio_dir(client, env, session):
    mid = new_meeting(client)
    r = client.post(
        f"/meetings/{mid}/chunks",
        files={"file": ("../../../evil.sh", b"x")},
        data={"seq": 0, "source": "mic"},
    )
    assert r.status_code == 202
    path = session.scalars(select(Chunk.path)).one()
    from pathlib import Path

    assert Path(path).resolve().is_relative_to((env / "audio").resolve())


def test_finish_is_idempotent_and_sets_finished_at(client):
    mid = new_meeting(client)
    first = client.post(f"/meetings/{mid}/finish").json()
    second = client.post(f"/meetings/{mid}/finish").json()
    assert first["status"] == "finished" and first["finished_at"]
    # SQLite pierde la zona horaria al releer (Postgres no): se compara el instante sin el sufijo.
    assert second["finished_at"].rstrip("Z") == first["finished_at"].rstrip("Z")


def test_reanalyze_rejected_while_recording(client):
    mid = new_meeting(client)
    assert client.post(f"/meetings/{mid}/analyze").status_code == 409


def test_transcript_json_and_markdown(client):
    mid = new_meeting(client, "Demo")
    upload(client, mid, 0, "hola\n?ruido", source="mic")
    client.post(f"/meetings/{mid}/finish")
    drain()
    segs = client.get(f"/meetings/{mid}/transcript", params={"format": "json"}).json()
    assert [(s["text"], s["source"], s["low_confidence"]) for s in segs] == [
        ("hola", "mic", False),
        ("ruido", "mic", True),
    ]
    md = client.get(f"/meetings/{mid}/transcript")
    assert md.headers["content-type"].startswith("text/markdown")
    assert "# Demo" in md.text and "**Yo:** hola" in md.text
    assert client.get(f"/meetings/{mid}/transcript", params={"format": "pdf"}).status_code == 422


def test_search_is_case_insensitive_limited_and_validated(client):
    mid = new_meeting(client)
    upload(client, mid, 0, "\n".join(f"Bizum número {i}" for i in range(5)))
    client.post(f"/meetings/{mid}/finish")
    drain()
    assert len(client.get("/search", params={"q": "BIZUM"}).json()) == 5
    assert len(client.get("/search", params={"q": "bizum", "limit": 2}).json()) == 2
    assert client.get("/search", params={"q": "b"}).status_code == 422
    assert client.get("/search", params={"q": "bizum", "limit": 500}).status_code == 422
    assert client.get("/search", params={"q": "inexistente"}).json() == []


def test_delete_removes_audio_and_all_rows(client, env):
    mid = new_meeting(client)
    upload(client, mid, 0, "hola")
    assert any((env / "audio").rglob("*"))
    assert client.delete(f"/meetings/{mid}").status_code == 204
    assert not any(p.is_file() for p in (env / "audio").rglob("*"))
    assert client.get(f"/meetings/{mid}/progress").status_code == 404
    assert client.get("/search", params={"q": "hola"}).json() == []


def test_summary_is_exposed_on_the_meeting(client):
    mid = new_meeting(client, project="pagos")
    assert client.get(f"/meetings/{mid}").json()["summary"] is None
    upload(client, mid, 0, "Queremos pagar con tarjeta sí o sí.")
    FakeAnalyzer.script = "El cliente exige pago con tarjeta."
    client.post(f"/meetings/{mid}/finish")
    drain()
    m = client.get(f"/meetings/{mid}").json()
    assert m["analysis_status"] == "done" and m["summary"] == "El cliente exige pago con tarjeta."
    assert client.get("/meetings", params={"project": "pagos"}).json()[0]["summary"] == m["summary"]


def test_progress_counts_by_status(client, session):
    mid = new_meeting(client)
    for i in range(3):
        upload(client, mid, i, f"frase {i}", offset=i * 45)
    chunk = session.scalars(select(Chunk).order_by(Chunk.id)).first()
    chunk.status = "failed"
    session.commit()
    p = client.get(f"/meetings/{mid}/progress").json()
    assert p == {
        "chunks_total": 3,
        "chunks_pending": 2,
        "chunks_processing": 0,
        "chunks_done": 0,
        "chunks_failed": 1,
        "segments": 0,
    }


def test_audit_log_records_requests_but_not_health(client, anon, session):
    client.get("/meetings")
    anon.get("/meetings")
    anon.get("/health")
    rows = session.scalars(select(AuditLog).order_by(AuditLog.id)).all()
    assert [(r.method, r.path, r.status) for r in rows] == [("GET", "/meetings", 200), ("GET", "/meetings", 401)]


class TestSystem:
    def test_reports_models_and_queue(self, client):
        mid = new_meeting(client)
        upload(client, mid, 0, "hola")
        info = client.get("/system").json()
        assert info == {
            "whisper_model": "small",
            "whisper_language": "es",
            "analyzer": "fake",
            "ollama_model": "qwen2.5:7b",
            "ollama_reachable": False,
            "ollama_model_installed": False,
            "queue": 1,
        }

    @pytest.mark.parametrize(("names", "installed"), [(["qwen2.5:7b"], True), (["llama3.2:latest"], False)])
    def test_ollama_model_detection(self, client, set_env, monkeypatch, names, installed):
        set_env("MT_ANALYZER", "ollama")
        req = httpx.Request("GET", "http://ollama/api/tags")
        monkeypatch.setattr(
            main.httpx,
            "get",
            lambda url, timeout: httpx.Response(200, json={"models": [{"name": n} for n in names]}, request=req),
        )
        info = client.get("/system").json()
        assert info["ollama_reachable"] is True and info["ollama_model_installed"] is installed

    def test_untagged_model_matches_latest(self, client, set_env, monkeypatch):
        set_env("MT_ANALYZER", "ollama")
        set_env("MT_OLLAMA_MODEL", "llama3.2")
        req = httpx.Request("GET", "http://ollama/api/tags")
        monkeypatch.setattr(
            main.httpx,
            "get",
            lambda url, timeout: httpx.Response(200, json={"models": [{"name": "llama3.2:latest"}]}, request=req),
        )
        assert client.get("/system").json()["ollama_model_installed"] is True

    def test_ollama_down(self, client, set_env, monkeypatch):
        set_env("MT_ANALYZER", "ollama")

        def boom(url, timeout):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(main.httpx, "get", boom)
        info = client.get("/system").json()
        assert info["ollama_reachable"] is False and info["ollama_model_installed"] is False
