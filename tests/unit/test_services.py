"""Export a Markdown, almacenamiento de audio, transcriptor falso y autenticación."""

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.api.deps import require_token
from app.models import Meeting, Requirement, RequirementEvent, Segment
from app.services.export import fmt_ts, render_markdown
from app.services.storage import chunk_path, delete_audio
from app.services.transcriber import FakeTranscriber


@pytest.mark.parametrize(("secs", "out"), [(0, "00:00:00"), (59.9, "00:00:59"), (61, "00:01:01"), (3725, "01:02:05")])
def test_fmt_ts(secs, out):
    assert fmt_ts(secs) == out


def test_markdown_contains_analysis_speakers_and_flags(session):
    m = Meeting(title="Kickoff", project="pagos", created_at=datetime(2026, 11, 13, 10, 30, tzinfo=UTC))
    session.add(m)
    session.flush()
    s1 = Segment(meeting_id=m.id, source="mic", start=0, end=4, text="Quiero pagar con Bizum.")
    s2 = Segment(meeting_id=m.id, source="system", start=65, end=70, text="Se oyó fatal.", low_confidence=True)
    req = Requirement(project="pagos", title="Método de pago")
    session.add_all([s1, s2, req])
    session.flush()
    session.add(
        RequirementEvent(
            meeting_id=m.id,
            requirement_id=req.id,
            segment_id=s1.id,
            kind="new_requirement",
            summary="Pago con Bizum",
            quote="pagar con Bizum",
            timestamp=0,
        )
    )
    session.add(
        RequirementEvent(
            meeting_id=m.id,
            segment_id=s2.id,
            kind="open_question",
            summary="¿Qué se dijo?",
            quote="se oyó fatal",
            timestamp=65,
        )
    )
    session.commit()

    md = render_markdown(session, m)
    assert md.startswith("# Kickoff")
    assert "- Proyecto: pagos" in md and "2026-11-13 10:30" in md
    assert "baja confianza): 1" in md
    assert "### Requisitos nuevos" in md and "**Método de pago** — Pago con Bizum (`00:00:00`)" in md
    assert "### Dudas abiertas" in md and "> se oyó fatal" in md
    assert "### Decisiones" not in md  # las secciones vacías no aparecen
    assert "`[00:00:00]` **Yo:** Quiero pagar con Bizum." in md
    assert "`[00:01:05]` **Otros:** Se oyó fatal. `[?]`" in md


def test_markdown_untitled_meeting_without_analysis(session):
    m = Meeting(title="", project="")
    session.add(m)
    session.commit()
    md = render_markdown(session, m)
    assert md.startswith(f"# Reunión {m.id}")
    assert "## Análisis" not in md


def test_chunk_path_is_sanitized_and_contained(env):
    p = chunk_path(7, 3, "../../etc", "./../x.wav;rm")
    audio_root = (env / "audio").resolve()
    assert p.resolve().is_relative_to(audio_root)
    assert p.parent.name == "meeting_7"
    assert p.name.startswith("000003_")
    assert "/" not in p.name and ";" not in p.name


def test_delete_audio_removes_file_and_empty_folder(env):
    p = chunk_path(1, 0, "mic", ".wav")
    p.write_bytes(b"x")
    delete_audio(str(p))
    assert not p.exists() and not p.parent.exists()
    delete_audio(None)  # no falla
    delete_audio(str(p))  # idempotente


def test_fake_transcriber_lines_and_confidence(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hola\n\n?mal oído\nadiós", encoding="utf-8")
    out = FakeTranscriber().transcribe(f)
    assert [s.text for s in out] == ["hola", "mal oído", "adiós"]
    assert [s.start for s in out] == [0, 5, 10]
    assert out[1].avg_logprob < out[0].avg_logprob


@pytest.mark.parametrize("header", ["", "Bearer", "Bearer mal", "Basic tok", "tok"])
def test_require_token_rejects(env, header):
    with pytest.raises(HTTPException) as e:
        require_token(header)
    assert e.value.status_code == 401


@pytest.mark.parametrize("header", ["Bearer tok", "bearer tok"])
def test_require_token_accepts(env, header):
    assert require_token(header) is None


@pytest.mark.parametrize("configured", ["", "change-me"])
def test_unconfigured_token_fails_closed(env, set_env, configured):
    set_env("MT_API_TOKEN", configured)
    with pytest.raises(HTTPException) as e:
        require_token("Bearer change-me")
    assert e.value.status_code == 503
