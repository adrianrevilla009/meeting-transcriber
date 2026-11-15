"""Carga de política y glosario desde YAML (config/policy.yaml, config/glossary.yaml)."""

from pathlib import Path
from typing import Any

import yaml

from privacy_shield.domain.entities import EntityType
from privacy_shield.domain.glossary import GlossaryTerm
from privacy_shield.domain.policy import Policy, Strategy


def _read(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: se esperaba un mapa YAML")
    return data


def load_policy(path: Path | None) -> Policy:
    """Sin fichero devuelve la política por defecto."""
    if path is None or not path.exists():
        return Policy()
    data = _read(path)
    base = Policy()
    strategies = dict(base.strategies)
    for name, value in (data.get("strategies") or {}).items():
        strategies[EntityType(str(name).upper())] = Strategy(str(value).lower())
    min_scores = {EntityType(str(k).upper()): float(v) for k, v in (data.get("min_scores") or {}).items()}
    return Policy(
        strategies=strategies,
        min_scores=min_scores,
        default_min_score=float(data.get("default_min_score", base.default_min_score)),
        local_only=bool(data.get("local_only", False)),
    )


def load_glossary(path: Path | None) -> list[GlossaryTerm]:
    """Sin fichero devuelve un glosario vacío."""
    if path is None or not path.exists():
        return []
    terms: list[GlossaryTerm] = []
    for item in _read(path).get("terms") or []:
        if isinstance(item, str):
            terms.append(GlossaryTerm(item))
        elif isinstance(item, dict) and item.get("text"):
            entity_type = EntityType(str(item.get("type", "GLOSARIO")).upper())
            terms.append(GlossaryTerm(str(item["text"]), entity_type, tuple(str(a) for a in item.get("aliases") or ())))
        else:
            raise ValueError(f"{path}: término de glosario no válido: {item!r}")
    return terms
