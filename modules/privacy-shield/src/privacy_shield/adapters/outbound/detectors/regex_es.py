"""Detector determinista y rápido de datos con formato: email, teléfono, DNI/NIE, IBAN, tarjeta, IP, URL, secretos."""

import re

from privacy_shield.domain.entities import DetectedEntity, EntityType

SOURCE = "regex"

_EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"'\[\]]+", re.IGNORECASE)
_IPV4 = re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?!\d)")
_PHONE = re.compile(
    r"(?<![\w+])(?:(?:\+|00)34[ .-]?)?[6-9]\d{2}(?:[ .-]?\d{3}[ .-]?\d{3}|[ .-]?\d{2}[ .-]?\d{2}[ .-]?\d{2})(?!\d)"
)
_DNI = re.compile(r"(?<![A-Za-z0-9])(?P<num>\d{8})[ -]?(?P<letter>[A-Za-z])(?![A-Za-z0-9])")
_NIE = re.compile(r"(?<![A-Za-z0-9])(?P<prefix>[XYZxyz])(?P<num>\d{7})[ -]?(?P<letter>[A-Za-z])(?![A-Za-z0-9])")
_IBAN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2}\d{2}(?: ?[A-Za-z0-9]{4}){2,7}(?: ?[A-Za-z0-9]{1,4})?(?![A-Za-z0-9])")
# Formatos habituales: 13-19 dígitos seguidos, grupos de 4 (Visa/MC) o 4-6-5 (Amex). Evita falsos positivos con IBAN.
_CARD = re.compile(
    r"(?<![\d-])(?:\d{13,19}|\d{4}(?:[ -]\d{4}){2,3}(?:[ -]\d{1,4})?|\d{4}[ -]\d{6}[ -]\d{4,5})(?![\d-])"
)
_API_KEY = re.compile(
    r"(?<![A-Za-z0-9_-])(?:sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})(?![A-Za-z0-9_-])"
)
_DICTATED_SECRET = re.compile(
    r"\b(?:contraseña|clave|password|passwd|token|pin)\s*(?:es|:|=)\s*(?P<secret>\S{4,})", re.IGNORECASE
)

_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
_NIE_PREFIX = {"X": "0", "Y": "1", "Z": "2"}
_URL_TRAILING = ".,;:!?)"
# Longitud exacta de los IBAN más comunes: evita que un IBAN seguido de una palabra pase mod 97 por azar.
_IBAN_LENGTHS = {
    "ES": 24, "FR": 27, "DE": 22, "IT": 27, "PT": 25, "GB": 22,
    "NL": 18, "BE": 16, "AT": 20, "CH": 21, "IE": 22, "LU": 20,
}  # fmt: skip


class RegexDetector:
    def detect(self, text: str, *, language: str = "es") -> list[DetectedEntity]:
        out: list[DetectedEntity] = []
        out += self._email(text)
        out += self._url(text)
        out += self._ip(text)
        out += self._phone(text)
        out += self._dni_nie(text)
        out += self._iban(text)
        out += self._card(text)
        out += self._secrets(text)
        return out

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _entity(text: str, entity_type: EntityType, start: int, end: int, score: float) -> DetectedEntity:
        return DetectedEntity(entity_type, start, end, text[start:end], score, SOURCE)

    def _email(self, text: str) -> list[DetectedEntity]:
        return [self._entity(text, EntityType.EMAIL, m.start(), m.end(), 0.99) for m in _EMAIL.finditer(text)]

    def _url(self, text: str) -> list[DetectedEntity]:
        out = []
        for m in _URL.finditer(text):
            end = m.end()
            while end > m.start() and text[end - 1] in _URL_TRAILING:
                end -= 1
            if end - m.start() > 4:
                out.append(self._entity(text, EntityType.URL, m.start(), end, 0.95))
        return out

    def _ip(self, text: str) -> list[DetectedEntity]:
        return [self._entity(text, EntityType.IP, m.start(), m.end(), 0.9) for m in _IPV4.finditer(text)]

    def _phone(self, text: str) -> list[DetectedEntity]:
        return [
            self._entity(text, EntityType.TELEFONO, m.start(), m.end(), 0.9 if m.group(0)[0] in "+0" else 0.85)
            for m in _PHONE.finditer(text)
        ]

    def _dni_nie(self, text: str) -> list[DetectedEntity]:
        out = []
        for m in _DNI.finditer(text):
            valid = _DNI_LETTERS[int(m["num"]) % 23] == m["letter"].upper()
            out.append(self._entity(text, EntityType.DNI_NIE, m.start(), m.end(), 0.95 if valid else 0.6))
        for m in _NIE.finditer(text):
            number = int(_NIE_PREFIX[m["prefix"].upper()] + m["num"])
            valid = _DNI_LETTERS[number % 23] == m["letter"].upper()
            out.append(self._entity(text, EntityType.DNI_NIE, m.start(), m.end(), 0.95 if valid else 0.6))
        return out

    def _iban(self, text: str) -> list[DetectedEntity]:
        out = []
        for m in _IBAN.finditer(text):
            chunks = m.group(0).split(" ")
            found = False
            for k in range(len(chunks), 0, -1):  # puede ir seguido de palabras cortas: se prueba el prefijo válido
                if _iban_valid("".join(chunks[:k])):
                    end = m.start() + len(" ".join(chunks[:k]))
                    out.append(self._entity(text, EntityType.IBAN, m.start(), end, 0.98))
                    found = True
                    break
            compact = m.group(0).replace(" ", "")
            if not found and compact[:2].upper() == "ES" and len(compact) == 24:
                out.append(self._entity(text, EntityType.IBAN, m.start(), m.end(), 0.7))
        return out

    def _card(self, text: str) -> list[DetectedEntity]:
        out = []
        for m in _CARD.finditer(text):
            digits = re.sub(r"\D", "", m.group(0))
            if 13 <= len(digits) <= 19 and _luhn(digits):
                out.append(self._entity(text, EntityType.TARJETA, m.start(), m.end(), 0.95))
        return out

    def _secrets(self, text: str) -> list[DetectedEntity]:
        out = [self._entity(text, EntityType.SECRETO, m.start(), m.end(), 0.95) for m in _API_KEY.finditer(text)]
        for m in _DICTATED_SECRET.finditer(text):
            secret = m.group("secret").rstrip(".,;")
            if len(secret) >= 4 and (any(c.isdigit() for c in secret) or not secret.isalnum()):
                start = m.start("secret")
                out.append(self._entity(text, EntityType.SECRETO, start, start + len(secret), 0.8))
        return out


def _iban_valid(compact: str) -> bool:
    compact = compact.upper()
    if not 15 <= len(compact) <= 34 or not compact[:2].isalpha() or not compact[2:4].isdigit():
        return False
    if len(compact) != _IBAN_LENGTHS.get(compact[:2], len(compact)):
        return False
    rearranged = compact[4:] + compact[:4]
    try:
        number = "".join(str(int(c, 36)) for c in rearranged)
    except ValueError:
        return False
    return int(number) % 97 == 1


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0
