from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Meeting, Segment

LABELS = {"mic": "Yo", "system": "Otros"}


def fmt_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def render_markdown(session: Session, meeting: Meeting) -> str:
    segments = session.scalars(
        select(Segment).where(Segment.meeting_id == meeting.id).order_by(Segment.start, Segment.id)
    ).all()
    lines = [
        f"# {meeting.title or 'Reunión ' + str(meeting.id)}",
        "",
        f"- Proyecto: {meeting.project or '-'}",
        f"- Fecha: {meeting.created_at:%Y-%m-%d %H:%M}",
        f"- Segmentos marcados `[?]` (baja confianza): {sum(1 for s in segments if s.low_confidence)}",
        "",
    ]
    if meeting.summary:
        lines += ["## Resumen", "", meeting.summary, ""]
    lines += ["## Transcripción", ""]
    for seg in segments:
        who = LABELS.get(seg.source, "")
        who = f"**{who}:** " if who else ""
        flag = " `[?]`" if seg.low_confidence else ""
        lines.append(f"`[{fmt_ts(seg.start)}]` {who}{seg.text}{flag}")
        lines.append("")
    return "\n".join(lines)


def export_meeting(session: Session, meeting: Meeting) -> Path:
    s = get_settings()
    s.export_dir.mkdir(parents=True, exist_ok=True)
    path = s.export_dir / f"meeting_{meeting.id}.md"
    path.write_text(render_markdown(session, meeting), encoding="utf-8")
    return path
