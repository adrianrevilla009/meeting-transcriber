from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ChatMessage:
    role: str  # system | user | assistant
    content: str
    name: str | None = None


@dataclass(frozen=True)
class ChatRequest:
    messages: tuple[ChatMessage, ...]
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatResponse:
    content: str
    model: str
    finish_reason: str | None = None


@dataclass(frozen=True)
class ChatChunk:
    content: str
    finish_reason: str | None = None
