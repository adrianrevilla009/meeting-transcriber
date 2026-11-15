from dataclasses import dataclass, field
from enum import StrEnum

from privacy_shield.domain.entities import EntityType


class Strategy(StrEnum):
    PSEUDONYMIZE = "pseudonymize"  # token reversible: [PERSONA_1]
    MASK = "mask"  # token no reversible: [IBAN]
    BLOCK = "block"  # rechaza toda la petición
    ALLOW = "allow"  # no se toca


def _default_strategies() -> dict[EntityType, Strategy]:
    strategies = dict.fromkeys(EntityType, Strategy.PSEUDONYMIZE)
    strategies[EntityType.DNI_NIE] = Strategy.MASK
    strategies[EntityType.IBAN] = Strategy.MASK
    strategies[EntityType.TARJETA] = Strategy.BLOCK
    strategies[EntityType.SECRETO] = Strategy.BLOCK
    return strategies


@dataclass(frozen=True)
class Policy:
    """Qué hacer con cada tipo de entidad y con qué confianza mínima."""

    strategies: dict[EntityType, Strategy] = field(default_factory=_default_strategies)
    min_scores: dict[EntityType, float] = field(default_factory=dict)
    default_min_score: float = 0.5
    local_only: bool = False  # si es True, solo se admiten proveedores que no salen de la máquina

    def strategy_for(self, entity_type: EntityType) -> Strategy:
        return self.strategies.get(entity_type, Strategy.PSEUDONYMIZE)

    def min_score_for(self, entity_type: EntityType) -> float:
        return self.min_scores.get(entity_type, self.default_min_score)
