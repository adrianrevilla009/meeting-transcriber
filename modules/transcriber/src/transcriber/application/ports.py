"""Puertos: lo que el núcleo necesita del mundo exterior. Los adaptadores los implementan."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from transcriber.domain.transcription import RawSegment


class TranscriberPort(Protocol):
    def transcribe(self, path: Path) -> list[RawSegment]: ...


class AnalyzerPort(Protocol):
    def summarize(self, transcript_window: str) -> str: ...

    def merge(self, partial_summaries: list[str]) -> str: ...


class AudioStorePort(Protocol):
    def path_for(self, meeting_id: int, seq: int, source: str, suffix: str) -> Path: ...

    def delete(self, path: str | None) -> None: ...


@dataclass(frozen=True)
class LlmStatus:
    reachable: bool
    model_installed: bool
