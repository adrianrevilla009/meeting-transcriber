"""Export a Markdown, almacenamiento de audio, transcriptor falso y autenticación."""

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.api.deps import require_token
from app.models import Meeting, Segment
from app.services.export import fmt_ts, render_markdown
from app.services.storage import chunk_path, delete_audio
from app.services.transcriber import FakeTranscriber


@pytest.mark.parametrize(("secs", "out"), [(0, "00:00:00"), (59.9, "00:00:59"), (61, "00:01:01"), (3725, "01:02:05")])
def test_fmt_ts(secs, out):
    assert fmt_ts(secs) == out


def test_markdown_contains_summary_speakers_and_flags(session):
    m = Meeting(
        title="Kickoff",
        project="pagos",
        created_at=datetime(2026, 11, 13, 10, 30, tzinfo=UTC),
        summary="Se acordó pagar con Bizum.\n- Entrega el 15 de diciembre",
    )
    session.add(m)
    session.flush()
    session.add_all(
        [
            Segment(meeting_id=m.id, source="mic", start=0, end=4, text="Quiero pagar con Bizum."),
            Segment(meeting_id=m.id, source="system", start=65, end=70, text="Se oyó fatal.", low_confidence=True),
        ]
    )
    session.commit()

    md = render_markdown(session, m)
    assert md.startswith("# Kickoff")
    assert "- Proyecto: pagos" in md and "2026-11-13 10:30" in md
    assert "baja confianza): 1" in md
    assert "## Resumen\n\nSe acordó pagar con Bizum.\n- Entrega el 15 de diciembre" in md
    assert md.index("## Resumen") < md.index("## Transcripción")
    assert "`[00:00:00]` **Yo:** Quiero pagar con Bizum." in md
    assert "`[00:01:05]` **Otros:** Se oyó fatal. `[?]`" in md


def test_markdown_untitled_meeting_without_summary(session):
    m = Meeting(title="", project="")
    session.add(m)
    session.commit()
    md = render_markdown(session, m)
    assert md.startswith(f"# Reunión {m.id}")
    assert "## Resumen" not in md


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
