"""Casos de uso del procesamiento: transcribir trozos pendientes, finalizar reuniones, resumir y exportar .md.
Los adaptadores de entrada (worker, API) los invocan pasándoles el `Runtime`."""

import logging
from datetime import UTC, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from transcriber.application.analysis import analyze_meeting
from transcriber.application.export import export_meeting
from transcriber.application.ports import AudioStorePort
from transcriber.application.runtime import Runtime
from transcriber.config import get_settings
from transcriber.domain.models import Chunk, ChunkStatus, Meeting, MeetingStatus, Segment, utcnow

log = logging.getLogger("pipeline")


def claim_chunk(session: Session) -> Chunk | None:
    # SKIP LOCKED: varios workers pueden convivir sin pisarse (Postgres). SQLite lo ignora.
    chunk = session.scalars(
        select(Chunk)
        .where(Chunk.status == ChunkStatus.pending)
        .order_by(Chunk.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if chunk:
        chunk.status = ChunkStatus.processing
        session.commit()
    return chunk


def process_chunk(session: Session, chunk: Chunk, rt: Runtime) -> None:
    s = get_settings()
    try:
        if chunk.path is None:
            raise RuntimeError("El audio del trozo ya no existe")
        segs = rt.transcriber().transcribe(Path(chunk.path))
        for r in segs:
            low = (r.avg_logprob is not None and r.avg_logprob < s.min_avg_logprob) or (
                r.no_speech_prob is not None and r.no_speech_prob > s.max_no_speech_prob
            )
            session.add(
                Segment(
                    meeting_id=chunk.meeting_id,
                    chunk_id=chunk.id,
                    source=chunk.source,
                    start=chunk.offset_seconds + r.start,
                    end=chunk.offset_seconds + r.end,
                    text=r.text,
                    avg_logprob=r.avg_logprob,
                    no_speech_prob=r.no_speech_prob,
                    low_confidence=bool(low),
                )
            )
        chunk.status = ChunkStatus.done
        chunk.processed_at = utcnow()
        if s.audio_retention_days <= 0:
            rt.audio.delete(chunk.path)
            chunk.path = None
    except Exception as exc:
        log.exception("Fallo transcribiendo trozo %s", chunk.id)
        chunk.status = ChunkStatus.failed
        chunk.error = str(exc)[:500]
    session.commit()


def finalize_ready_meetings(session: Session, rt: Runtime) -> int:
    """Reuniones terminadas sin trozos abiertos: marca done, analiza y exporta."""
    n = 0
    for m in session.scalars(select(Meeting).where(Meeting.status == MeetingStatus.finished)).all():
        open_chunks = session.scalar(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.meeting_id == m.id, Chunk.status.in_([ChunkStatus.pending, ChunkStatus.processing]))
        )
        if open_chunks:
            continue
        m.status = MeetingStatus.done
        session.commit()
        export_meeting(session, m)  # transcripción disponible aunque falle el LLM
        meeting_id = m.id  # tras un rollback, leer m.id recarga la fila (y falla si se borró)
        try:
            analyze_meeting(session, m, rt.analyzer())
        except Exception as exc:
            log.exception("Fallo en el análisis de la reunión %s", meeting_id)
            session.rollback()
            fresh = session.get(Meeting, meeting_id)
            if fresh is None:  # se borró la reunión mientras se analizaba
                continue
            m = fresh
            m.analysis_status = "failed"
            m.analysis_error = str(exc)[:500]
            session.commit()
        export_meeting(session, m)
        n += 1
    return n


def purge_expired_audio(session: Session, audio: AudioStorePort) -> int:
    """Borra el audio ya transcrito cuando supera la retención configurada."""
    days = get_settings().audio_retention_days
    if days <= 0:
        return 0  # con retención 0 el worker ya borra al transcribir
    limit = utcnow() - timedelta(days=days)
    rows = session.scalars(select(Chunk).where(Chunk.status == ChunkStatus.done, Chunk.path.is_not(None))).all()
    n = 0
    for c in rows:
        processed = c.processed_at
        if processed is not None and processed.tzinfo is None:
            processed = processed.replace(tzinfo=UTC)
        if processed and processed < limit:
            audio.delete(c.path)
            c.path = None
            n += 1
    session.commit()
    return n


def run_once(session: Session, rt: Runtime) -> bool:
    chunk = claim_chunk(session)
    if chunk:
        process_chunk(session, chunk, rt)
        return True
    did = finalize_ready_meetings(session, rt)
    purge_expired_audio(session, rt.audio)
    return bool(did)
