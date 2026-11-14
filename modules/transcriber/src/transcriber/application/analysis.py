"""Caso de uso: resumir una reunión (por ventanas si es larga). El LLM NUNCA reescribe la transcripción:
solo genera un resumen aparte; los segmentos originales no se tocan."""

import logging
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from transcriber.application.ports import AnalyzerPort
from transcriber.config import get_settings
from transcriber.domain.models import Meeting, Segment

log = logging.getLogger(__name__)


def windows(segments: Sequence[Segment], max_chars: int) -> list[str]:
    out: list[str] = []
    cur: list[str] = []
    size = 0
    for s in segments:
        line = s.text
        if size + len(line) > max_chars and cur:
            out.append("\n".join(cur))
            cur, size = cur[-2:], sum(len(x) for x in cur[-2:])  # solape de 2 segmentos
        cur.append(line)
        size += len(line)
    if cur:
        out.append("\n".join(cur))
    return out


def analyze_meeting(session: Session, meeting: Meeting, analyzer: AnalyzerPort | None) -> None:
    """Genera el resumen de la reunión y lo guarda. Sin analizador (desactivado) la marca como `skipped`."""
    if analyzer is None:
        meeting.analysis_status = "skipped"
        session.commit()
        return

    s = get_settings()
    segments = session.scalars(select(Segment).where(Segment.meeting_id == meeting.id).order_by(Segment.start)).all()
    parts = windows(segments, s.analysis_window_chars)
    partials = [p for w in parts if (p := analyzer.summarize(w).strip())]
    summary = partials[0] if len(partials) == 1 else analyzer.merge(partials) if partials else ""
    meeting.summary = summary.strip() or None
    meeting.analysis_status = "done"
    meeting.analysis_error = None
    session.commit()
    log.info("Resumen de la reunión %s generado (%s ventanas)", meeting.id, len(parts))
