class AssistantError(Exception):
    """Base de los errores del dominio. Nunca incluyen texto de la reunión."""


class MeetingNotFound(AssistantError):
    pass


class QuestionNotFound(AssistantError):
    pass


class TranscriberUnavailable(AssistantError):
    """No se puede leer la transcripción del módulo 1 (caído, token incorrecto...)."""


class ClassifierUnavailable(AssistantError):
    """El LLM local no responde: se usan solo las reglas."""


class ShieldBlocked(AssistantError):
    """privacy-shield rechazó la consulta (fuga detectada, política...). `code` es su código de error."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(f"privacy-shield bloqueó la consulta: {code}")


class ShieldUnavailable(AssistantError):
    """privacy-shield no responde o falló. `code` identifica el motivo."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(f"privacy-shield no disponible: {code}")
