"""Worker + base de datos: ciclo de vida de trozos y reuniones, fallos, retención y análisis."""

from datetime import timedelta

from sqlalchemy import select

from app.models import Chunk, Meeting, Requirement, RequirementEvent, Segment, utcnow
from app.services.analyzer import FakeAnalyzer, Item
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

    monkeypatch.setattr(FakeAnalyzer, "extract", explode)
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


def test_reanalysis_replaces_previous_events(client, session):
    mid = new_meeting(client, project="p")
    upload(client, mid, 0, "Decidimos usar Postgres para todo.")
    FakeAnalyzer.script = [Item(kind="decision", requirement="BD", summary="Postgres", quote="usar Postgres para todo")]
    client.post(f"/meetings/{mid}/finish")
    drain()
    assert len(client.get(f"/meetings/{mid}/events").json()) == 1

    FakeAnalyzer.script = [
        Item(kind="decision", requirement="BD", summary="Postgres", quote="usar Postgres para todo"),
        Item(kind="open_question", summary="¿Y MySQL?", quote="Decidimos usar Postgres"),
    ]
    assert client.post(f"/meetings/{mid}/analyze").json()["analysis_status"] == "pending"
    drain()
    events = client.get(f"/meetings/{mid}/events").json()
    assert sorted(e["kind"] for e in events) == ["decision", "open_question"]
    assert session.query(RequirementEvent).count() == 2


class TestAnalysisRules:
    """Reglas de aceptación del análisis aplicadas sobre la BD."""

    def _run(self, client, text, items, project="p"):
        mid = new_meeting(client, project=project)
        upload(client, mid, 0, text)
        FakeAnalyzer.script = items
        client.post(f"/meetings/{mid}/finish")
        drain()
        return mid, client.get(f"/meetings/{mid}/events").json()

    def test_unknown_kind_is_rejected(self, client):
        _, events = self._run(
            client,
            "Hay que migrar la base de datos.",
            [Item(kind="chiste", summary="x", quote="migrar la base de datos")],
        )
        assert events == []

    def test_duplicates_from_overlapping_windows_are_collapsed(self, client):
        item = Item(kind="decision", requirement="Migración", summary="Migrar la BD", quote="migrar la base de datos")
        _, events = self._run(client, "Hay que migrar la base de datos.", [item, item])
        assert len(events) == 1

    def test_event_points_to_the_segment_and_time_of_the_quote(self, client):
        text = "Buenos días.\nRepaso rápido.\nHay que migrar la base de datos."
        _, events = self._run(client, text, [Item(kind="decision", summary="Migrar", quote="migrar la base de datos")])
        assert events[0]["timestamp"] == 10.0  # tercer segmento (FakeTranscriber: 5 s por línea)

    def test_open_questions_do_not_create_requirements(self, client, session):
        self._run(
            client,
            "¿Necesitamos soporte para dólares?",
            [Item(kind="open_question", requirement="Divisas", summary="Dólares", quote="soporte para dólares")],
        )
        assert session.query(Requirement).count() == 0

    def test_similar_requirement_names_merge_within_project_only(self, client, session):
        t = "Queremos pagar con tarjeta."
        self._run(
            client,
            t,
            [Item(kind="new_requirement", requirement="Método de pago", summary="a", quote="pagar con tarjeta")],
            project="pagos",
        )
        self._run(
            client,
            t,
            [Item(kind="changed_requirement", requirement="metodo de pago", summary="b", quote="pagar con tarjeta")],
            project="pagos",
        )
        self._run(
            client,
            t,
            [Item(kind="new_requirement", requirement="Método de pago", summary="c", quote="pagar con tarjeta")],
            project="otro",
        )
        reqs = session.scalars(select(Requirement).order_by(Requirement.id)).all()
        assert [(r.project, len(r.events)) for r in reqs] == [("pagos", 2), ("otro", 1)]

    def test_different_requirements_stay_separate(self, client, session):
        text = "Queremos pagar con tarjeta.\nY un modo oscuro en la web."
        self._run(
            client,
            text,
            [
                Item(kind="new_requirement", requirement="Método de pago", summary="a", quote="pagar con tarjeta"),
                Item(kind="new_requirement", requirement="Modo oscuro", summary="b", quote="un modo oscuro en la web"),
            ],
        )
        assert session.query(Requirement).count() == 2


def test_long_meeting_is_analyzed_in_several_windows(client, set_env, monkeypatch):
    set_env("MT_ANALYSIS_WINDOW_CHARS", "60")
    seen = []
    monkeypatch.setattr(FakeAnalyzer, "extract", lambda self, w: seen.append(w) or [])
    mid = new_meeting(client)
    upload(client, mid, 0, "\n".join(f"frase número {i} de la reunión" for i in range(10)))
    client.post(f"/meetings/{mid}/finish")
    drain()
    assert len(seen) > 2


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

    monkeypatch.setattr(FakeAnalyzer, "extract", delete_then_fail)
    mid = new_meeting(client)
    upload(client, mid, 0, "hola")
    client.post(f"/meetings/{mid}/finish")
    drain()  # no debe lanzar
    assert client.get(f"/meetings/{mid}").status_code == 404
