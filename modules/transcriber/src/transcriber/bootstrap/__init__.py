"""Raíz de composición: el ÚNICO sitio que conoce los adaptadores concretos y los cablea.

Cambiar de proveedor (otro LLM, otro transcriptor, otro almacén) = escribir un adaptador y tocar aquí.
"""

from transcriber.adapters.outbound.analysis.fake import FakeAnalyzer
from transcriber.adapters.outbound.analysis.ollama import OllamaAnalyzer, ollama_status
from transcriber.adapters.outbound.persistence import database
from transcriber.adapters.outbound.storage.audio_fs import FsAudioStore
from transcriber.adapters.outbound.transcription.fake import FakeTranscriber
from transcriber.adapters.outbound.transcription.faster_whisper import FasterWhisperTranscriber
from transcriber.application.ports import AnalyzerPort, LlmStatus, TranscriberPort
from transcriber.application.runtime import Runtime
from transcriber.config import get_settings

_transcriber: TranscriberPort | None = None
_runtime: Runtime | None = None


def get_transcriber() -> TranscriberPort:
    """Una sola instancia: cargar el modelo Whisper es caro."""
    global _transcriber
    if _transcriber is None:
        s = get_settings()
        _transcriber = FakeTranscriber() if s.transcriber == "fake" else FasterWhisperTranscriber(s)
    return _transcriber


def get_analyzer() -> AnalyzerPort | None:
    name = get_settings().analyzer
    if name == "ollama":
        return OllamaAnalyzer()
    if name == "fake":
        return FakeAnalyzer()
    return None


def get_llm_status() -> LlmStatus:
    if get_settings().analyzer == "ollama":
        return ollama_status()
    return LlmStatus(reachable=False, model_installed=False)


def get_runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        _runtime = Runtime(
            session=database.new_session,
            init_db=database.init_db,
            audio=FsAudioStore(),
            transcriber=get_transcriber,
            analyzer=get_analyzer,
            llm_status=get_llm_status,
        )
    return _runtime


def reset() -> None:
    """Solo para tests: descarta instancias en caché."""
    global _transcriber, _runtime
    _transcriber = None
    _runtime = None
    database.reset_engine()
