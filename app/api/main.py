import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Auth
from app.config import get_settings
from app.db import get_session, init_db, session_factory
from app.models import (
    AuditLog,
    Chunk,
    ChunkStatus,
    Meeting,
    MeetingStatus,
    Segment,
    utcnow,
)
from app.schemas import (
    ChunkOut,
    MeetingCreate,
    MeetingOut,
    MeetingProgress,
    SearchHit,
    SegmentOut,
    SystemInfo,
)
from app.services.export import render_markdown
from app.services.storage import chunk_path, delete_audio

log = logging.getLogger("api")
MAX_CHUNK_BYTES = 50 * 1024 * 1024


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Meeting Transcriber", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def audit(request: Request, call_next):
    response = await call_next(request)
    if request.url.path != "/health":
        try:
            with session_factory()() as s:
                s.add(
                    AuditLog(
                        method=request.method,
                        path=request.url.path[:300],
                        status=response.status_code,
                        client=request.client.host if request.client else "",
                    )
                )
                s.commit()
        except Exception:
            log.exception("No se pudo escribir el log de auditoría")
    return response


def _meeting(session: Session, meeting_id: int) -> Meeting:
    m = session.get(Meeting, meeting_id)
    if not m:
        raise HTTPException(404, "Reunión no encontrada")
    return m


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/system", response_model=SystemInfo, dependencies=[Auth])
def system_info(session: Session = Depends(get_session)):
    """Modelos configurados, estado de Ollama y cola de trozos pendientes (para el frontal)."""
    s = get_settings()
    reachable = installed = False
    if s.analyzer == "ollama":
        try:
            r = httpx.get(f"{s.ollama_url}/api/tags", timeout=3)
            r.raise_for_status()
            names = {m["name"] for m in r.json().get("models", [])}
            reachable = True
            installed = s.ollama_model in names or f"{s.ollama_model}:latest" in names
        except (httpx.HTTPError, ValueError, KeyError):
            pass
    queue = session.scalar(
        select(func.count()).select_from(Chunk).where(Chunk.status.in_([ChunkStatus.pending, ChunkStatus.processing]))
    )
    return SystemInfo(
        whisper_model=s.whisper_model,
        whisper_language=s.whisper_language,
        analyzer=s.analyzer,
        ollama_model=s.ollama_model,
        ollama_reachable=reachable,
        ollama_model_installed=installed,
        queue=queue or 0,
    )


@app.post("/meetings", response_model=MeetingOut, status_code=201, dependencies=[Auth])
def create_meeting(body: MeetingCreate, session: Session = Depends(get_session)):
    m = Meeting(title=body.title, project=body.project)
    session.add(m)
    session.commit()
    return m


@app.get("/meetings", response_model=list[MeetingOut], dependencies=[Auth])
def list_meetings(project: str | None = None, session: Session = Depends(get_session)):
    q = select(Meeting).order_by(Meeting.id.desc())
    if project:
        q = q.where(Meeting.project == project)
    return session.scalars(q).all()


@app.get("/meetings/{meeting_id}", response_model=MeetingOut, dependencies=[Auth])
def get_meeting(meeting_id: int, session: Session = Depends(get_session)):
    return _meeting(session, meeting_id)


@app.get("/meetings/{meeting_id}/progress", response_model=MeetingProgress, dependencies=[Auth])
def meeting_progress(meeting_id: int, session: Session = Depends(get_session)):
    _meeting(session, meeting_id)
    counts = {
        st.value: n
        for st, n in session.execute(
            select(Chunk.status, func.count()).where(Chunk.meeting_id == meeting_id).group_by(Chunk.status)
        ).all()
    }
    return MeetingProgress(
        chunks_total=sum(counts.values()),
        chunks_pending=counts.get("pending", 0),
        chunks_processing=counts.get("processing", 0),
        chunks_done=counts.get("done", 0),
        chunks_failed=counts.get("failed", 0),
        segments=session.scalar(select(func.count()).select_from(Segment).where(Segment.meeting_id == meeting_id)) or 0,
    )


@app.post("/meetings/{meeting_id}/chunks", response_model=ChunkOut, status_code=202, dependencies=[Auth])
async def upload_chunk(
    meeting_id: int,
    file: UploadFile = File(...),
    seq: int = Form(...),
    offset_seconds: float = Form(0.0),
    source: str = Form("mix"),
    session: Session = Depends(get_session),
):
    m = _meeting(session, meeting_id)
    if m.status != MeetingStatus.recording:
        raise HTTPException(409, "La reunión ya no admite audio")
    if source not in {"mic", "system", "mix"}:
        raise HTTPException(422, "source debe ser mic, system o mix")
    data = await file.read(MAX_CHUNK_BYTES + 1)
    if len(data) > MAX_CHUNK_BYTES:
        raise HTTPException(413, "Trozo demasiado grande")
    suffix = "." + (file.filename or "x.wav").rsplit(".", 1)[-1]
    path = chunk_path(meeting_id, seq, source, suffix)
    path.write_bytes(data)
    chunk = Chunk(meeting_id=meeting_id, seq=seq, source=source, offset_seconds=offset_seconds, path=str(path))
    session.add(chunk)
    session.commit()
    return chunk


@app.post("/meetings/{meeting_id}/finish", response_model=MeetingOut, dependencies=[Auth])
def finish_meeting(meeting_id: int, session: Session = Depends(get_session)):
    m = _meeting(session, meeting_id)
    if m.status == MeetingStatus.recording:
        m.status = MeetingStatus.finished
        m.finished_at = utcnow()
        session.commit()
    return m


@app.get("/meetings/{meeting_id}/transcript", dependencies=[Auth])
def transcript(
    meeting_id: int, format: str = Query("md", pattern="^(md|json)$"), session: Session = Depends(get_session)
):
    m = _meeting(session, meeting_id)
    if format == "md":
        return PlainTextResponse(render_markdown(session, m), media_type="text/markdown; charset=utf-8")
    segs = session.scalars(select(Segment).where(Segment.meeting_id == m.id).order_by(Segment.start)).all()
    return [SegmentOut.model_validate(s) for s in segs]


@app.post("/meetings/{meeting_id}/analyze", response_model=MeetingOut, status_code=202, dependencies=[Auth])
def reanalyze(meeting_id: int, session: Session = Depends(get_session)):
    """Encola un reanálisis: el worker lo recoge al volver a pasar la reunión por 'finished'."""
    m = _meeting(session, meeting_id)
    if m.status == MeetingStatus.recording:
        raise HTTPException(409, "La reunión sigue en curso")
    m.status = MeetingStatus.finished
    m.analysis_status = "pending"
    session.commit()
    return m


@app.delete("/meetings/{meeting_id}", status_code=204, dependencies=[Auth])
def delete_meeting(meeting_id: int, session: Session = Depends(get_session)):
    m = _meeting(session, meeting_id)
    for c in m.chunks:
        delete_audio(c.path)
    session.delete(m)
    session.commit()


@app.get("/search", response_model=list[SearchHit], dependencies=[Auth])
def search(q: str = Query(..., min_length=2), limit: int = Query(50, le=200), session: Session = Depends(get_session)):
    like = f"%{q}%"
    rows = session.scalars(
        select(Segment).where(Segment.text.ilike(like)).order_by(Segment.meeting_id.desc(), Segment.start).limit(limit)
    ).all()
    return [SearchHit(meeting_id=s.meeting_id, segment_id=s.id, start=s.start, text=s.text) for s in rows]
