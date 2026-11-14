"""Adaptador de transcripción local: faster-whisper (CTranslate2). El modelo se carga una sola vez."""

from pathlib import Path

from transcriber.config import Settings
from transcriber.domain.transcription import RawSegment


class FasterWhisperTranscriber:
    def __init__(self, settings: Settings):
        from faster_whisper import WhisperModel  # import perezoso: dependencia opcional

        self.s = settings
        settings.whisper_models_dir.mkdir(parents=True, exist_ok=True)
        self.model = WhisperModel(
            settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
            download_root=str(settings.whisper_models_dir),
            local_files_only=True,  # el modelo se descarga aparte (make models); nunca en caliente
        )
        self.prompt = f"Reunión técnica de negocio. Términos: {settings.glossary}." if settings.glossary else None

    def transcribe(self, path: Path) -> list[RawSegment]:
        segments, _info = self.model.transcribe(
            str(path),
            language=self.s.whisper_language,
            vad_filter=True,  # evita alucinaciones en silencios
            beam_size=self.s.whisper_beam_size,
            initial_prompt=self.prompt,
            condition_on_previous_text=False,  # evita bucles de repetición
        )
        return [
            RawSegment(s.start, s.end, s.text.strip(), s.avg_logprob, s.no_speech_prob)
            for s in segments
            if s.text.strip()
        ]
