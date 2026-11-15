from dataclasses import dataclass
from enum import StrEnum


class EntityType(StrEnum):
    PERSONA = "PERSONA"
    ORGANIZACION = "ORGANIZACION"
    UBICACION = "UBICACION"
    EMAIL = "EMAIL"
    TELEFONO = "TELEFONO"
    DNI_NIE = "DNI_NIE"
    IBAN = "IBAN"
    TARJETA = "TARJETA"
    URL = "URL"
    IP = "IP"
    SECRETO = "SECRETO"  # API keys, tokens, contraseñas dictadas
    GLOSARIO = "GLOSARIO"  # términos propios (clientes, proyectos, apodos)


@dataclass(frozen=True, slots=True)
class DetectedEntity:
    """Entidad sensible encontrada. Los offsets son de caracteres sobre el texto original."""

    type: EntityType
    start: int
    end: int
    text: str
    score: float  # 0..1
    source: str  # nombre del detector que la encontró

    @property
    def length(self) -> int:
        return self.end - self.start
