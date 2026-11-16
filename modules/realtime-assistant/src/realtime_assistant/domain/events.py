from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AssistantEvent:
    """Evento para la interfaz. `type`: question | answer_start | answer_chunk | answer_done | error | status."""

    id: int
    type: str
    data: Mapping[str, object]
