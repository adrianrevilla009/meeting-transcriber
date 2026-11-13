from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config import Settings, get_settings


@dataclass
class RawSegment:
    start: float
    end: float
    text: str
    avg_logprob: float | None = None
    no_speech_prob: float | None = None


class Transcriber(Protocol):
    def transcribe(self, path: Path) -> list[RawSegment]: ...


class FasterWhisperTranscriber:
    """Whisper local (CTranslate2). El modelo se carga una sola vez."""

    def __init__(self, settings: Settings):
        from faster_whisper import WhisperModel  # import perezoso: dependencia opcional

        self.s = settings
        settings.whisper_models_dir.mkdir(parents=True, exist_ok=True)
        self.model = WhisperModel(
            settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
            download_root=str(settings.whisper_models_dir),
        )
        self.prompt = (
            f"Reunión técnica de negocio. Términos: {settings.glossary}." if settings.glossary else None
        )

    def transcribe(self, path: Path) -> list[RawSegment]:
        segments, _info = self.model.transcribe(
            str(path),
            language=self.s.whisper_language,
            vad_filter=True,  # evita alucinaciones en silencios
            initial_prompt=self.prompt,
            condition_on_previous_text=False,  # evita bucles de repetición
        )
        return [
            RawSegment(s.start, s.end, s.text.strip(), s.avg_logprob, s.no_speech_prob)
            for s in segments
            if s.text.strip()
        ]


class FakeTranscriber:
    """Para tests y desarrollo sin modelo: devuelve el contenido del audio como texto si es .txt,
    o un segmento fijo."""

    def transcribe(self, path: Path) -> list[RawSegment]:
        try:
            text = path.read_text(encoding="utf-8").strip()
        except (UnicodeDecodeError, OSError):
            text = "texto de prueba"
        out, t = [], 0.0
        for line in [l for l in text.splitlines() if l.strip()]:
            lp = -0.2
            if line.startswith("?"):
                line, lp = line[1:].strip(), -1.5
            out.append(RawSegment(t, t + 5.0, line, lp, 0.01))
            t += 5.0
        return out


_instance: Transcriber | None = None


def get_transcriber() -> Transcriber:
    global _instance
    if _instance is None:
        s = get_settings()
        _instance = FakeTranscriber() if s.transcriber == "fake" else FasterWhisperTranscriber(s)
    return _instance


def reset_transcriber() -> None:
    global _instance
    _instance = None
