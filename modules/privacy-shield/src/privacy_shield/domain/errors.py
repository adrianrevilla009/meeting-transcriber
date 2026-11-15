from collections.abc import Iterable

from privacy_shield.domain.entities import EntityType


class PrivacyShieldError(Exception):
    """Base de los errores del dominio. Nunca incluyen texto del usuario."""


class LeakDetected(PrivacyShieldError):
    def __init__(self, counts: dict[EntityType, int]):
        self.counts = counts
        super().__init__(f"Fuga detectada antes de salir: {_fmt(counts)}")


class BlockedByPolicy(PrivacyShieldError):
    def __init__(self, types: Iterable[EntityType]):
        self.types = tuple(sorted(set(types)))
        super().__init__("La política bloquea la petición: " + ", ".join(t.value for t in self.types))


class DetectorUnavailable(PrivacyShieldError):
    """Un detector falló: se bloquea la petición (fail closed)."""


class SessionNotFound(PrivacyShieldError):
    pass


class ProviderNotFound(PrivacyShieldError):
    pass


class ProviderNotConfigured(PrivacyShieldError):
    pass


class ProviderNotAllowed(PrivacyShieldError):
    """La política (local_only) no permite este proveedor."""


class ProviderError(PrivacyShieldError):
    pass


def _fmt(counts: dict[EntityType, int]) -> str:
    return ", ".join(f"{t.value}={n}" for t, n in sorted(counts.items()))
