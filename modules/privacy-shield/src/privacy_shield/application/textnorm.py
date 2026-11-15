"""Normalización de valores para compararlos (mismo valor = mismo token) y plegado de texto."""

import re
import unicodedata

from privacy_shield.domain.entities import EntityType

_SPACES = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^0-9A-Za-z]")


def fold(text: str) -> str:
    """Minúsculas y sin tildes, conservando la longitud (cada carácter produce exactamente uno)."""
    out: list[str] = []
    for ch in text:
        base = unicodedata.normalize("NFD", ch)[:1].lower()
        out.append(base if len(base) == 1 else ch)
    return "".join(out)


def normalize_value(entity_type: EntityType, value: str) -> str:
    """Clave canónica de un valor: variantes de formato del mismo dato dan la misma clave."""
    if entity_type in (EntityType.IBAN, EntityType.DNI_NIE, EntityType.TARJETA):
        return _NON_ALNUM.sub("", value).upper()
    if entity_type == EntityType.TELEFONO:
        digits = _NON_ALNUM.sub("", value)
        for prefix in ("0034", "34"):
            if digits.startswith(prefix) and len(digits) > 9:
                return digits[len(prefix) :]
        return digits
    if entity_type == EntityType.EMAIL:
        return value.strip().lower()
    if entity_type in (EntityType.URL, EntityType.IP):
        return value.strip().lower().rstrip("/")
    return _SPACES.sub(" ", fold(value)).strip()
