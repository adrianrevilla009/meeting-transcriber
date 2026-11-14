import enum
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from transcriber.domain.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class MeetingStatus(str, enum.Enum):
    recording = "recording"
    finished = "finished"  # el agente avisó del fin; quedan trozos por procesar
    done = "done"  # todos los trozos transcritos


class ChunkStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    project: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[MeetingStatus] = mapped_column(Enum(MeetingStatus), default=MeetingStatus.recording)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    analysis_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|done|failed|skipped
    analysis_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="meeting", cascade="all, delete-orphan")
    segments: Mapped[list["Segment"]] = relationship(back_populates="meeting", cascade="all, delete-orphan")


class Chunk(Base):
    """Trozo de audio subido por el agente. El audio se borra tras transcribir."""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20), default="mix")  # mic | system | mix
    offset_seconds: Mapped[float] = mapped_column(Float, default=0.0)  # inicio dentro de la reunión
    path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[ChunkStatus] = mapped_column(Enum(ChunkStatus), default=ChunkStatus.pending, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    meeting: Mapped[Meeting] = relationship(back_populates="chunks")


class Segment(Base):
    """Transcripción cruda. Inmutable: es la fuente de verdad."""

    __tablename__ = "segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), index=True)
    chunk_id: Mapped[int | None] = mapped_column(ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="mix")
    start: Mapped[float] = mapped_column(Float)  # segundos desde el inicio de la reunión
    end: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text)
    avg_logprob: Mapped[float | None] = mapped_column(Float, nullable=True)
    no_speech_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_confidence: Mapped[bool] = mapped_column(default=False)

    meeting: Mapped[Meeting] = relationship(back_populates="segments")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(300))
    status: Mapped[int] = mapped_column(Integer)
    client: Mapped[str] = mapped_column(String(100), default="")
