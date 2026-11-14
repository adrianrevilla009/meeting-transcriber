from dataclasses import dataclass


@dataclass
class RawSegment:
    """Fragmento devuelto por un transcriptor, con tiempos relativos al inicio del trozo de audio."""

    start: float
    end: float
    text: str
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
