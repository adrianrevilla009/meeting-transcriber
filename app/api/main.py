import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Auth
from app.config import get_settings
from app.db import get_session, init_db, session_factory
from app.models import (
    AuditLog,
    Chunk,
    Meeting,
    MeetingStatus,
    Requirement,
    RequirementEvent,
    Segment,
    utcnow,
)
from app.schemas import (
    ChunkOut,
    EventOut,
    MeetingCreate,
    MeetingOut,
    RequirementHistory,
    RequirementOut,
    SearchHit,
    SegmentOut,
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
        except Exception:  # noqa: BLE001 - la auditoría nunca debe tumbar la petición
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
def transcript(meeting_id: int, format: str = Query("md", pattern="^(md|json)$"), session: Session = Depends(get_session)):
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


@app.get("/meetings/{meeting_id}/events", response_model=list[EventOut], dependencies=[Auth])
def meeting_events(meeting_id: int, session: Session = Depends(get_session)):
    _meeting(session, meeting_id)
    return session.scalars(
        select(RequirementEvent).where(RequirementEvent.meeting_id == meeting_id).order_by(RequirementEvent.id)
    ).all()


@app.delete("/meetings/{meeting_id}", status_code=204, dependencies=[Auth])
def delete_meeting(meeting_id: int, session: Session = Depends(get_session)):
    m = _meeting(session, meeting_id)
    for c in m.chunks:
        delete_audio(c.path)
    session.delete(m)
    session.commit()


@app.get("/requirements", response_model=list[RequirementOut], dependencies=[Auth])
def list_requirements(project: str | None = None, session: Session = Depends(get_session)):
    q = select(Requirement).order_by(Requirement.id)
    if project:
        q = q.where(Requirement.project == project)
    return session.scalars(q).all()


@app.get("/requirements/{req_id}/history", response_model=RequirementHistory, dependencies=[Auth])
def requirement_history(req_id: int, session: Session = Depends(get_session)):
    r = session.get(Requirement, req_id)
    if not r:
        raise HTTPException(404, "Requisito no encontrado")
    return RequirementHistory(requirement=r, events=[EventOut.model_validate(e) for e in r.events])


@app.get("/search", response_model=list[SearchHit], dependencies=[Auth])
def search(q: str = Query(..., min_length=2), limit: int = Query(50, le=200), session: Session = Depends(get_session)):
    like = f"%{q}%"
    rows = session.scalars(
        select(Segment).where(Segment.text.ilike(like)).order_by(Segment.meeting_id.desc(), Segment.start).limit(limit)
    ).all()
    return [SearchHit(meeting_id=s.meeting_id, segment_id=s.id, start=s.start, text=s.text) for s in rows]
