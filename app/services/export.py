from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Meeting, RequirementEvent, Segment

LABELS = {"mic": "Yo", "system": "Otros"}
KIND_TITLES = {
    "new_requirement": "Requisitos nuevos",
    "changed_requirement": "Cambios de requisitos",
    "decision": "Decisiones",
    "open_question": "Dudas abiertas",
}


def fmt_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def render_markdown(session: Session, meeting: Meeting) -> str:
    segments = session.scalars(
        select(Segment).where(Segment.meeting_id == meeting.id).order_by(Segment.start, Segment.id)
    ).all()
    events = session.scalars(
        select(RequirementEvent).where(RequirementEvent.meeting_id == meeting.id).order_by(RequirementEvent.id)
    ).all()

    lines = [
        f"# {meeting.title or 'Reunión ' + str(meeting.id)}",
        "",
        f"- Proyecto: {meeting.project or '-'}",
        f"- Fecha: {meeting.created_at:%Y-%m-%d %H:%M}",
        f"- Segmentos marcados `[?]` (baja confianza): {sum(1 for s in segments if s.low_confidence)}",
        "",
    ]
    if events:
        lines += ["## Análisis (citas verificadas contra la transcripción)", ""]
        for kind, title in KIND_TITLES.items():
            group = [e for e in events if e.kind == kind]
            if not group:
                continue
            lines += [f"### {title}", ""]
            for e in group:
                name = f"**{e.requirement.title}** — " if e.requirement else ""
                lines.append(f"- {name}{e.summary} (`{fmt_ts(e.timestamp or 0)}`)")
                lines.append(f"  > {e.quote}")
            lines.append("")
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
