from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Valor centinela: no es una credencial, marca que MT_API_TOKEN no está configurado.
UNSET_TOKEN = "change-me"  # noqa: S105  # nosec B105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MT_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/mt.db"
    audio_dir: Path = Path("./data/audio")
    export_dir: Path = Path("./data/exports")

    # Seguridad: token simple para API y agente.
    api_token: str = UNSET_TOKEN  # sin MT_API_TOKEN la API rechaza todas las peticiones

    # Transcripción
    transcriber: str = "faster-whisper"  # "faster-whisper" | "fake"
    whisper_model: str = "small"  # small/medium en CPU; large-v3 si hay GPU
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_language: str = "es"
    whisper_models_dir: Path = Path("./data/models")
    glossary: str = ""  # términos separados por coma; va al initial_prompt

    # Umbrales de fiabilidad: por debajo se marca el segmento con [?]
    min_avg_logprob: float = -0.8
    max_no_speech_prob: float = 0.6

    # Retención del audio tras transcribir: 0 = borrar al instante
    audio_retention_days: int = 0

    worker_poll_seconds: float = 2.0

    # Análisis con LLM local (Ollama). "none" desactiva el análisis.
    analyzer: str = "ollama"  # "ollama" | "fake" | "none"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_timeout: float = 900.0
    analysis_window_chars: int = 6000
    quote_min_score: float = 92.0  # similitud mínima (0-100) para aceptar una cita
    requirement_match_score: float = 85.0  # similitud para unir un requisito a uno existente


@lru_cache
def get_settings() -> Settings:
    return Settings()
