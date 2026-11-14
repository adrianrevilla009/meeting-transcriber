"""Dependencias ya cableadas que reciben los casos de uso y los adaptadores de entrada.

Se construye en `transcriber.bootstrap` (único sitio que conoce los adaptadores concretos).
Los transcriptores y analizadores son funciones para instanciarlos solo cuando hacen falta
(cargar Whisper es caro y la API no lo necesita).
"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from transcriber.application.ports import AnalyzerPort, AudioStorePort, LlmStatus, TranscriberPort


@dataclass
class Runtime:
    session: Callable[[], Session]
    init_db: Callable[[], None]
    audio: AudioStorePort
    transcriber: Callable[[], TranscriberPort]
    analyzer: Callable[[], AnalyzerPort | None]
    llm_status: Callable[[], LlmStatus]
