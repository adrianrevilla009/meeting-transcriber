from collections.abc import Iterable

from realtime_assistant.domain.entities import TranscriptSegment


def format_context(segments: Iterable[TranscriptSegment], max_chars: int, own_source: str = "mic") -> str:
    """Las últimas líneas de la conversación (como máximo `max_chars` caracteres), con quién habla."""
    lines = [f"{'Yo' if s.source == own_source else 'Otros'}: {s.text.strip()}" for s in segments if s.text.strip()]
    kept: list[str] = []
    size = 0
    for line in reversed(lines):
        if kept and size + len(line) + 1 > max_chars:
            break
        kept.append(line)
        size += len(line) + 1
    return "\n".join(reversed(kept))
