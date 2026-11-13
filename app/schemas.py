from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MeetingCreate(BaseModel):
    title: str = ""
    project: str = ""


class MeetingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    project: str
    status: str
    analysis_status: str
    analysis_error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class MeetingProgress(BaseModel):
    chunks_total: int
    chunks_pending: int
    chunks_processing: int
    chunks_done: int
    chunks_failed: int
    segments: int
    events: int


class SystemInfo(BaseModel):
    whisper_model: str
    whisper_language: str
    analyzer: str
    ollama_model: str
    ollama_reachable: bool
    ollama_model_installed: bool
    queue: int


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    meeting_id: int
    seq: int
    source: str
    status: str


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    start: float
    end: float
    text: str
    avg_logprob: float | None
    low_confidence: bool


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    requirement_id: int | None
    meeting_id: int
    segment_id: int | None
    kind: str
    summary: str
    quote: str
    timestamp: float | None
    created_at: datetime


class RequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project: str
    title: str
    created_at: datetime


class RequirementHistory(BaseModel):
    requirement: RequirementOut
    events: list[EventOut]


class SearchHit(BaseModel):
    meeting_id: int
    segment_id: int
    start: float
    text: str
