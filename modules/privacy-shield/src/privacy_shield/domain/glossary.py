from dataclasses import dataclass

from privacy_shield.domain.entities import EntityType


@dataclass(frozen=True)
class GlossaryTerm:
    """Término propio a proteger (cliente, proyecto, apodo) y sus variantes."""

    text: str
    entity_type: EntityType = EntityType.GLOSARIO
    aliases: tuple[str, ...] = ()
