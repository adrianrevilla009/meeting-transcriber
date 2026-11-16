from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Valor centinela: no es una credencial, marca que RTA_API_TOKEN no está configurado.
UNSET_TOKEN = "change-me"  # noqa: S105  # nosec B105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RTA_", env_file=".env", extra="ignore")

    # Seguridad: token Bearer (en el despliegue por defecto es el mismo MT_API_TOKEN del módulo 1).
    api_token: str = UNSET_TOKEN

    # Servicios con los que habla (y los únicos): el transcriber, privacy-shield y un Ollama local.
    transcriber_url: str = "http://api:8000"
    shield_url: str = "http://privacy-shield:8100"
    shield_token: str = ""
    shield_provider: str = ""  # vacío = el proveedor por defecto de privacy-shield
    shield_model: str = ""
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    classifier: str = "ollama"  # ollama | rules

    # Comportamiento
    poll_seconds: float = 1.5
    context_chars: int = 6000
    user_names: str = ""  # alias del usuario separados por comas: "Adrián, Adri"
    profile: str = ""  # contexto del usuario para las respuestas (va por privacy-shield)
    auto_answer: bool = True
    answer_cooldown_seconds: float = 15.0
    min_question_score: float = 0.55
    idle_timeout_seconds: float = 1800.0
    own_source: str = "mic"
    listen_sources: str = "system,mix"

    @property
    def user_name_list(self) -> tuple[str, ...]:
        return tuple(n.strip() for n in self.user_names.split(",") if n.strip())

    @property
    def listen_source_set(self) -> frozenset[str]:
        return frozenset(s.strip() for s in self.listen_sources.split(",") if s.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
