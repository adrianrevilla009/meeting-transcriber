"""Adaptador de entrada HTTP (FastAPI). Solo traduce HTTP <-> casos de uso; no conoce adaptadores de salida:
recibe un `Runtime` ya cableado (ver transcriber.bootstrap)."""

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from transcriber.adapters.inbound.api.deps import Auth, get_runtime, get_session
from transcriber.adapters.inbound.api.schemas import (
    ChunkOut,
    MeetingCreate,
    MeetingOut,
    MeetingProgress,
    SearchHit,
    SegmentOut,
    SystemInfo,
)
from transcriber.application.export import render_markdown
from transcriber.application.runtime import Runtime
from transcriber.config import get_settings
from transcriber.domain.models import (
    AuditLog,
    Chunk,
    ChunkStatus,
    Meeting,
    MeetingStatus,
    Segment,
    utcnow,
)

log = logging.getLogger("api")
MAX_CHUNK_BYTES = 50 * 1024 * 1024

router = APIRouter()


def create_app(rt: Runtime) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        rt.init_db()
        yield

    app = FastAPI(title="Meeting Transcriber", version="0.1.0", lifespan=lifespan)
    app.state.runtime = rt

    @app.middleware("http")
    async def audit(request: Request, call_next):
        response = await call_next(request)
        if request.url.path != "/health":
            try:
                with rt.session() as s:
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

    app.include_router(router)
    return app


def _meeting(session: Session, meeting_id: int) -> Meeting:
    m = session.get(Meeting, meeting_id)
    if not m:
        raise HTTPException(404, "Reunión no encontrada")
    return m


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/system", response_model=SystemInfo, dependencies=[Auth])
def system_info(session: Session = Depends(get_session), rt: Runtime = Depends(get_runtime)):
    """Modelos configurados, estado de Ollama y cola de trozos pendientes (para el frontal)."""
    s = get_settings()
    llm = rt.llm_status()
    queue = session.scalar(
        select(func.count()).select_from(Chunk).where(Chunk.status.in_([ChunkStatus.pending, ChunkStatus.processing]))
    )
    return SystemInfo(
        whisper_model=s.whisper_model,
        whisper_language=s.whisper_language,
        analyzer=s.analyzer,
        ollama_model=s.ollama_model,
        ollama_reachable=llm.reachable,
        ollama_model_installed=llm.model_installed,
        queue=queue or 0,
    )


@router.post("/meetings", response_model=MeetingOut, status_code=201, dependencies=[Auth])
def create_meeting(body: MeetingCreate, session: Session = Depends(get_session)):
    m = Meeting(title=body.title, project=body.project)
    session.add(m)
    session.commit()
    return m


@router.get("/meetings", response_model=list[MeetingOut], dependencies=[Auth])
def list_meetings(project: str | None = None, session: Session = Depends(get_session)):
    q = select(Meeting).order_by(Meeting.id.desc())
    if project:
        q = q.where(Meeting.project == project)
    return session.scalars(q).all()


@router.get("/meetings/{meeting_id}", response_model=MeetingOut, dependencies=[Auth])
def get_meeting(meeting_id: int, session: Session = Depends(get_session)):
    return _meeting(session, meeting_id)


@router.get("/meetings/{meeting_id}/progress", response_model=MeetingProgress, dependencies=[Auth])
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


@router.post("/meetings/{meeting_id}/chunks", response_model=ChunkOut, status_code=202, dependencies=[Auth])
async def upload_chunk(
    meeting_id: int,
    file: UploadFile = File(...),
    seq: int = Form(...),
    offset_seconds: float = Form(0.0),
    source: str = Form("mix"),
    session: Session = Depends(get_session),
    rt: Runtime = Depends(get_runtime),
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
    path = rt.audio.path_for(meeting_id, seq, source, suffix)
    path.write_bytes(data)
    chunk = Chunk(meeting_id=meeting_id, seq=seq, source=source, offset_seconds=offset_seconds, path=str(path))
    session.add(chunk)
    session.commit()
    return chunk


@router.post("/meetings/{meeting_id}/finish", response_model=MeetingOut, dependencies=[Auth])
def finish_meeting(meeting_id: int, session: Session = Depends(get_session)):
    m = _meeting(session, meeting_id)
    if m.status == MeetingStatus.recording:
        m.status = MeetingStatus.finished
        m.finished_at = utcnow()
        session.commit()
    return m


@router.get("/meetings/{meeting_id}/transcript", dependencies=[Auth])
def transcript(
    meeting_id: int, format: str = Query("md", pattern="^(md|json)$"), session: Session = Depends(get_session)
):
    m = _meeting(session, meeting_id)
    if format == "md":
        return PlainTextResponse(render_markdown(session, m), media_type="text/markdown; charset=utf-8")
    segs = session.scalars(select(Segment).where(Segment.meeting_id == m.id).order_by(Segment.start)).all()
    return [SegmentOut.model_validate(s) for s in segs]


@router.post("/meetings/{meeting_id}/analyze", response_model=MeetingOut, status_code=202, dependencies=[Auth])
def reanalyze(meeting_id: int, session: Session = Depends(get_session)):
    """Encola un reanálisis: el worker lo recoge al volver a pasar la reunión por 'finished'."""
    m = _meeting(session, meeting_id)
    if m.status == MeetingStatus.recording:
        raise HTTPException(409, "La reunión sigue en curso")
    m.status = MeetingStatus.finished
    m.analysis_status = "pending"
    session.commit()
    return m


@router.delete("/meetings/{meeting_id}", status_code=204, dependencies=[Auth])
def delete_meeting(meeting_id: int, session: Session = Depends(get_session), rt: Runtime = Depends(get_runtime)):
    m = _meeting(session, meeting_id)
    for c in m.chunks:
        rt.audio.delete(c.path)
    session.delete(m)
    session.commit()


@router.get("/search", response_model=list[SearchHit], dependencies=[Auth])
def search(q: str = Query(..., min_length=2), limit: int = Query(50, le=200), session: Session = Depends(get_session)):
    like = f"%{q}%"
    rows = session.scalars(
        select(Segment).where(Segment.text.ilike(like)).order_by(Segment.meeting_id.desc(), Segment.start).limit(limit)
    ).all()
    return [SearchHit(meeting_id=s.meeting_id, segment_id=s.id, start=s.start, text=s.text) for s in rows]
