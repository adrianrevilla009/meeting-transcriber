"""Worker + base de datos: ciclo de vida de trozos y reuniones, fallos, retención y análisis."""

from datetime import timedelta

from sqlalchemy import select

from app.models import Chunk, Meeting, Segment, utcnow
from app.services.analyzer import FakeAnalyzer
from app.workers import worker
from app.workers.worker import run_once
from tests.helpers import drain, new_meeting, upload


def test_meeting_waits_until_all_chunks_are_transcribed(client, session):
    mid = new_meeting(client)
    upload(client, mid, 0, "uno")
    upload(client, mid, 1, "dos", offset=45)
    client.post(f"/meetings/{mid}/finish")

    assert run_once(session)  # procesa solo el primer trozo
    assert client.get(f"/meetings/{mid}").json()["status"] == "finished"
    drain()
    assert client.get(f"/meetings/{mid}").json()["status"] == "done"


def test_recording_meeting_is_never_finalized(client):
    mid = new_meeting(client)
    upload(client, mid, 0, "hola")
    drain()
    m = client.get(f"/meetings/{mid}").json()
    assert m["status"] == "recording"  # el trozo se transcribe, pero la reunión sigue abierta
    assert client.get(f"/meetings/{mid}/progress").json()["segments"] == 1


def test_mic_and_system_are_interleaved_by_time(client):
    mid = new_meeting(client)
    upload(client, mid, 0, "otros 1\notros 2", source="system")  # 0 s y 5 s
    upload(client, mid, 0, "yo 1", source="mic", offset=2.5)
    client.post(f"/meetings/{mid}/finish")
    drain()
    segs = client.get(f"/meetings/{mid}/transcript", params={"format": "json"}).json()
    assert [(s["source"], s["text"]) for s in segs] == [("system", "otros 1"), ("mic", "yo 1"), ("system", "otros 2")]


def test_failed_transcription_keeps_audio_and_does_not_block_meeting(client, env, monkeypatch, session):
    class Broken:
        def transcribe(self, path):
            raise RuntimeError("GPU en llamas")

    monkeypatch.setattr(worker, "get_transcriber", lambda: Broken())
    mid = new_meeting(client)
    upload(client, mid, 0, "hola")
    client.post(f"/meetings/{mid}/finish")
    drain()

    chunk = session.scalars(select(Chunk)).one()
    assert chunk.status == "failed" and "GPU en llamas" in chunk.error
    assert chunk.path and (env / "audio").rglob("*.txt")  # el audio se conserva para reintentar
    assert client.get(f"/meetings/{mid}").json()["status"] == "done"
    assert client.get(f"/meetings/{mid}/progress").json()["chunks_failed"] == 1


def test_analysis_failure_marks_meeting_but_keeps_transcript(client, env, monkeypatch):
    def explode(self, window):
        raise RuntimeError("Ollama caído")

    monkeypatch.setattr(FakeAnalyzer, "summarize", explode)
    mid = new_meeting(client)
    upload(client, mid, 0, "hola a todos")
    client.post(f"/meetings/{mid}/finish")
    drain()

    m = client.get(f"/meetings/{mid}").json()
    assert m["status"] == "done" and m["analysis_status"] == "failed" and "Ollama caído" in m["analysis_error"]
    assert "hola a todos" in (env / "exports" / f"meeting_{mid}.md").read_text(encoding="utf-8")


def test_analysis_disabled_is_skipped(client, set_env):
    set_env("MT_ANALYZER", "none")
    mid = new_meeting(client)
    upload(client, mid, 0, "hola")
    client.post(f"/meetings/{mid}/finish")
    drain()
    assert client.get(f"/meetings/{mid}").json()["analysis_status"] == "skipped"


def test_retention_keeps_audio_then_purges_it(client, env, set_env, session):
    set_env("MT_AUDIO_RETENTION_DAYS", "7")
    mid = new_meeting(client)
    upload(client, mid, 0, "hola")
    client.post(f"/meetings/{mid}/finish")
    drain()
    chunk = session.scalars(select(Chunk)).one()
    assert chunk.path and any((env / "audio").rglob("*.txt"))  # aún dentro del plazo

    chunk.processed_at = utcnow() - timedelta(days=8)
    session.commit()
    run_once(session)
    session.refresh(chunk)
    assert chunk.path is None and not any((env / "audio").rglob("*.txt"))


def test_reanalysis_replaces_previous_summary(client):
    mid = new_meeting(client, project="p")
    upload(client, mid, 0, "Decidimos usar Postgres para todo.")
    FakeAnalyzer.script = "Se decide usar Postgres."
    client.post(f"/meetings/{mid}/finish")
    drain()
    assert client.get(f"/meetings/{mid}").json()["summary"] == "Se decide usar Postgres."

    FakeAnalyzer.script = "Se decide usar Postgres y se descarta MySQL."
    assert client.post(f"/meetings/{mid}/analyze").json()["analysis_status"] == "pending"
    drain()
    m = client.get(f"/meetings/{mid}").json()
    assert m["analysis_status"] == "done" and m["summary"] == "Se decide usar Postgres y se descarta MySQL."


def test_empty_transcript_gives_done_without_summary(client):
    mid = new_meeting(client)
    client.post(f"/meetings/{mid}/finish")
    drain()
    m = client.get(f"/meetings/{mid}").json()
    assert m["analysis_status"] == "done" and m["summary"] is None


def test_long_meeting_is_summarized_by_windows_and_merged(client, set_env, monkeypatch):
    set_env("MT_ANALYSIS_WINDOW_CHARS", "60")
    seen = []
    monkeypatch.setattr(FakeAnalyzer, "summarize", lambda self, w: seen.append(w) or f"parte {len(seen)}")
    mid = new_meeting(client)
    upload(client, mid, 0, "\n".join(f"frase número {i} de la reunión" for i in range(10)))
    client.post(f"/meetings/{mid}/finish")
    drain()
    assert len(seen) > 2
    summary = client.get(f"/meetings/{mid}").json()["summary"]
    assert all(f"parte {i}" in summary for i in range(1, len(seen) + 1))  # el resumen final reúne todas las partes


def test_segments_store_confidence_metrics(client, session):
    mid = new_meeting(client)
    upload(client, mid, 0, "clara\n?dudosa")
    drain()
    segs = session.scalars(select(Segment).order_by(Segment.start)).all()
    assert [s.low_confidence for s in segs] == [False, True]
    assert all(s.avg_logprob is not None and s.no_speech_prob is not None for s in segs)
    assert session.get(Meeting, mid).status == "recording"


def test_chunk_whose_audio_was_already_deleted_fails_cleanly(client, session):
    mid = new_meeting(client)
    upload(client, mid, 0, "hola")
    chunk = session.scalars(select(Chunk)).one()
    chunk.path = None
    session.commit()
    client.post(f"/meetings/{mid}/finish")
    drain()
    session.refresh(chunk)
    assert chunk.status == "failed" and "ya no existe" in chunk.error
    assert client.get(f"/meetings/{mid}").json()["status"] == "done"


def test_meeting_deleted_while_analysis_fails_does_not_crash_worker(client, monkeypatch):
    def delete_then_fail(self, window):
        from app.db import session_factory

        with session_factory()() as s:
            s.delete(s.get(Meeting, mid))
            s.commit()
        raise RuntimeError("Ollama caído")

    monkeypatch.setattr(FakeAnalyzer, "summarize", delete_then_fail)
    mid = new_meeting(client)
    upload(client, mid, 0, "hola")
    client.post(f"/meetings/{mid}/finish")
    drain()  # no debe lanzar
    assert client.get(f"/meetings/{mid}").status_code == 404
