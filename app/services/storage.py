import re
from datetime import UTC, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Chunk, ChunkStatus, utcnow

_SAFE = re.compile(r"[^a-zA-Z0-9_.-]")


def chunk_path(meeting_id: int, seq: int, source: str, suffix: str) -> Path:
    s = get_settings()
    safe_suffix = _SAFE.sub("", suffix) or ".wav"
    d = s.audio_dir / f"meeting_{meeting_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{seq:06d}_{_SAFE.sub('', source)}{safe_suffix}"


def delete_audio(path: str | None) -> None:
    if not path:
        return
    p = Path(path)
    try:
        p.unlink(missing_ok=True)
        # Borra la carpeta de la reunión si queda vacía.
        if p.parent.exists() and not any(p.parent.iterdir()):
            p.parent.rmdir()
    except OSError:
        pass


def purge_expired_audio(session: Session) -> int:
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
            delete_audio(c.path)
            c.path = None
            n += 1
    session.commit()
    return n
