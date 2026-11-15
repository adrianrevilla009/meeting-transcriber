"""Puertos: lo que el núcleo necesita del exterior. Los adaptadores los implementan."""

from collections.abc import AsyncIterator, Iterable
from datetime import datetime
from typing import Protocol

from privacy_shield.domain.audit import AuditEvent
from privacy_shield.domain.entities import DetectedEntity, EntityType
from privacy_shield.domain.messages import ChatChunk, ChatRequest, ChatResponse
from privacy_shield.domain.session import SessionId


class DetectorPort(Protocol):
    def detect(self, text: str, *, language: str = "es") -> list[DetectedEntity]: ...


class VaultPort(Protocol):
    def ensure_session(self, session: SessionId) -> None: ...

    def session_exists(self, session: SessionId) -> bool: ...

    def find_token(self, session: SessionId, type: EntityType, value: str) -> str | None: ...

    def get_or_create_token(self, session: SessionId, type: EntityType, value: str) -> str: ...

    def resolve(self, session: SessionId, token: str) -> str | None: ...

    def known_values(self, session: SessionId) -> Iterable[tuple[EntityType, str]]: ...

    def add_alias(self, session: SessionId, token: str, alias: str) -> None: ...

    def delete_session(self, session: SessionId) -> None: ...


class LLMPort(Protocol):
    name: str
    leaves_machine: bool

    def is_configured(self) -> bool: ...

    async def complete(self, req: ChatRequest) -> ChatResponse: ...

    def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]: ...


class ProviderRegistryPort(Protocol):
    def get(self, name: str) -> LLMPort: ...  # lanza ProviderNotFound

    def names(self) -> list[str]: ...


class AuditPort(Protocol):
    def record(self, event: AuditEvent) -> None: ...


class ClockPort(Protocol):
    def now(self) -> datetime: ...

    def perf_ms(self) -> float: ...
