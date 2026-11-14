"""Worker: transcribe trozos pendientes, finaliza reuniones, analiza y exporta .md."""

import logging
import time
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import init_db, session_factory
from app.models import Chunk, ChunkStatus, Meeting, MeetingStatus, Segment, utcnow
from app.services.analyzer import analyze_meeting
from app.services.export import export_meeting
from app.services.storage import delete_audio, purge_expired_audio
from app.services.transcriber import get_transcriber

log = logging.getLogger("worker")


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


def process_chunk(session: Session, chunk: Chunk) -> None:
    s = get_settings()
    try:
        if chunk.path is None:
            raise RuntimeError("El audio del trozo ya no existe")
        segs = get_transcriber().transcribe(Path(chunk.path))
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
            delete_audio(chunk.path)
            chunk.path = None
    except Exception as exc:
        log.exception("Fallo transcribiendo trozo %s", chunk.id)
        chunk.status = ChunkStatus.failed
        chunk.error = str(exc)[:500]
    session.commit()


def finalize_ready_meetings(session: Session) -> int:
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
            analyze_meeting(session, m)
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


def run_once(session: Session) -> bool:
    chunk = claim_chunk(session)
    if chunk:
        process_chunk(session, chunk)
        return True
    did = finalize_ready_meetings(session)
    purge_expired_audio(session)
    return bool(did)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    init_db()
    s = get_settings()
    log.info("Worker iniciado (transcriber=%s, modelo=%s)", s.transcriber, s.whisper_model)
    while True:
        with session_factory()() as session:
            busy = run_once(session)
        if not busy:
            time.sleep(s.worker_poll_seconds)


if __name__ == "__main__":
    main()
