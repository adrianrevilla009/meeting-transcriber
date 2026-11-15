"""Generador determinista (semilla) de transcripciones de reunión con etiquetas de verdad.

Cada muestra trae el texto y las entidades sensibles con sus offsets, para medir fugas y sobre-redacción.
Modos: `normal` (frases habituales), `adversarial` (errores típicos de ASR, nombres ambiguos, datos dictados...)
y `trap` (frases sin datos sensibles pero con palabras tramposas, para medir sobre-redacción).
"""

import json
import random
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from faker import Faker

from privacy_shield.application.textnorm import fold
from privacy_shield.domain.entities import EntityType
from privacy_shield.domain.glossary import GlossaryTerm

GLOSSARY_TERMS = [
    GlossaryTerm("Proyecto Quimera", EntityType.GLOSARIO, ("Quimera",)),
    GlossaryTerm("Cliente Atlas", EntityType.GLOSARIO),
    GlossaryTerm("Zoltrabek", EntityType.GLOSARIO),
]
_GLOSSARY_SURFACES = ["Proyecto Quimera", "Quimera", "Cliente Atlas", "Zoltrabek"]

_CITIES = [
    "Valladolid", "Zaragoza", "Sevilla", "Bilbao", "Málaga", "Valencia", "Granada", "Salamanca", "Pamplona",
    "Santander", "Vigo", "Córdoba", "Alicante", "Murcia", "Toledo", "Burgos", "León", "Gijón", "Almería", "Cádiz",
]  # fmt: skip
_ORG_PREFIX = ["Grupo", "Industrias", "Consultora", "Talleres", "Soluciones", "Logística", "Editorial", "Clínica"]
GENERIC_ORG_WORDS = {fold(p) for p in _ORG_PREFIX}  # palabras genéricas: no cuentan como fuga
_FALLBACK_FIRST = ["Marta", "Javier", "Lucía", "Andrés", "Elena", "Pablo", "Nuria", "Sergio", "Irene", "Raúl"]
_AMBIGUOUS_FIRST = ["Rosa", "Salvador", "Pilar", "Amparo", "Consuelo", "Dolores"]
_DIGITS = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve"]
_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
_SPOKEN_DOMAINS = [("gmail", "com"), ("hotmail", "com"), ("outlook", "es"), ("empresa", "es")]


@dataclass
class Labeled:
    type: str
    start: int
    end: int
    value: str


@dataclass
class Sample:
    id: str
    scenario: str
    kind: str  # normal | adversarial | trap
    text: str
    entities: list[Labeled] = field(default_factory=list)


# ------------------------------------------------------------------ escenarios
NORMAL: dict[str, list[str]] = {
    "trabajo": [
        "Oye, ¿le pasaste a {persona:a} el contrato de {org:x}?",
        "Sí, se lo mandé ayer a {email}. {first:a} dijo que lo revisaría con {persona:b}.",
        "Perfecto. Recuerda que la reunión con {org:x} es en {city}, el viernes.",
    ],
    "medico": [
        "Buenos días, soy {persona:a}, mi DNI es {dni}.",
        "Dígame, {first:a}, ¿qué le pasa? Apunto su teléfono: {tel}.",
        "Vivo en {city}. Mi correo es {email}.",
    ],
    "familia": [
        "Mamá, dile a {first:a} que me llame al {tel}.",
        "Vale, ¿y {persona:b} viene el domingo a {city}?",
        "Creo que sí, {first:b} me dijo que sí.",
    ],
    "finanzas": [
        "Para la transferencia, el IBAN es {iban}.",
        "Perfecto, ¿a nombre de {persona:a}? El pago es para {org:x}.",
        "Sí, y avisa a {email} cuando llegue.",
    ],
    "pagos_tarjeta": [
        "Quiero pagar con mi tarjeta, {persona:a}.",
        "Claro. Dígame el número: {card}.",
    ],
    "soporte": [
        "Hola, soy {persona:a}. Mi servidor {ip} no responde.",
        "¿Puede abrir {url} y decirme qué ve, {first:a}?",
        "Mi correo para el ticket: {emailhab}.",
    ],
    "rrhh": [
        "Vamos a revisar la nómina de {persona:a}, que entró en {org:x}.",
        "Su DNI es {dni} y su IBAN {iban}.",
        "{first:a} vive en {city}, ¿no?",
    ],
    "proyecto": [
        "El {glos:g} va retrasado. {persona:a} habló con {glos:h}.",
        "Habrá que avisar a {persona:b} antes del lunes.",
        "Llámame al {telhab} si hay novedades.",
    ],
    "secretos": [
        "La clave de la API es {secret}, no la compartas.",
        "Y la contraseña es {passw}, apúntala.",
    ],
    "ventas": [
        "Llámame al {tel} o escribe a {email}, {first:a}.",
        "Se lo digo a {persona:a} de {org:x}. Estamos en {city}.",
    ],
}

ADVERSARIAL: dict[str, list[str]] = {
    "asr_minusculas": [
        "oye le pasaste a {persona:a|asr} el contrato de {org:x|asr}",
        "si se lo mande a {email} {first:a|asr} dijo que lo revisaba con {persona:b|asr}",
    ],
    "mayusculas": [
        "LE DIJE A {persona:a|upper} QUE LLAMARA AL {tel}.",
        "{first:a|upper} VIVE EN {city|upper}.",
    ],
    "numeros_dictados": [
        "mi numero es {telhab} apuntalo por favor",
        "el de mi socio es {telhab} y el correo {emailhab}",
    ],
    "nombres_ambiguos": [
        "Hola, soy {amb:a}, ¿hablo con {persona:b}?",
        "Dile a {first:a} que {first:b} la espera.",
    ],
    "mezcla_idiomas": [
        "Hey, can you send the report to {persona:a}? Su email es {email}.",
        "We need to call {first:a} about the {glos:g} tomorrow.",
    ],
    "apodos_glosario": [
        "¿Cómo va {glos:g}? {glos:h} necesita novedades.",
        "Se lo comenté a {first:a}, que lleva {glos:g}.",
    ],
}

TRAPS = [
    "Me gusta el color rosa y el verde para la portada.",
    "Hoy me comí una manzana y luego probé la tarta de Apple Pie.",
    "El 15 de diciembre tenemos la entrega del informe.",
    "Son las diez y media de la mañana, no hay prisa.",
    "Tengo tres o cuatro reuniones esta semana, nada más.",
    "El precio es ciento veinte euros con cincuenta céntimos.",
    "En Python usamos pandas para limpiar los datos.",
    "Mañana hay que revisar el presupuesto y cerrar el sprint.",
    "Dice que el salvador de la reunión fue el café.",
    "La sala tiene capacidad para doce personas y proyector.",
    "El informe tiene cuarenta y dos páginas y tres anexos.",
    "Subí la versión dos punto cinco al repositorio ayer.",
]

_PLACEHOLDER = re.compile(r"\{(\w+)(?::(\w+))?(?:\|(\w+))?\}")


class CorpusGenerator:
    def __init__(self, seed: int = 7):
        self._rng = random.Random(seed)
        self._fake = Faker("es_ES")
        self._fake.seed_instance(seed)
        self._counter = 0

    # ------------------------------------------------------------------ valores
    def _first_name(self) -> str:
        name = str(self._fake.first_name()).split()[0]
        return name if len(name) >= 3 and "." not in name else self._rng.choice(_FALLBACK_FIRST)

    def _persona(self, ambiguous: bool = False) -> str:
        first = self._rng.choice(_AMBIGUOUS_FIRST) if ambiguous else self._first_name()
        return f"{first} {self._fake.last_name()}"

    def _digits(self, n: int) -> str:
        return "".join(str(self._rng.randint(0, 9)) for _ in range(n))

    def _phone(self) -> str:
        d = self._rng.choice("6789") + self._digits(8)
        style = self._rng.choice(["plain", "groups3", "groups2", "prefix"])
        if style == "groups3":
            return f"{d[:3]} {d[3:6]} {d[6:]}"
        if style == "groups2":
            return f"{d[:3]} {d[3:5]} {d[5:7]} {d[7:]}"
        if style == "prefix":
            return f"+34 {d[:3]} {d[3:6]} {d[6:]}"
        return d

    def _phone_spoken(self) -> str:
        d = self._rng.choice("67") + self._digits(8)
        groups = [d[:3], d[3:6], d[6:]]
        return ", ".join(" ".join(_DIGITS[int(c)] for c in g) for g in groups)

    def _dni(self) -> str:
        n = self._rng.randint(10_000_000, 99_999_999)
        return f"{n}{_DNI_LETTERS[n % 23]}"

    def _iban(self) -> str:
        bban = self._digits(20)
        check = 98 - (int(bban + "142800") % 97)
        iban = f"ES{check:02d}{bban}"
        return " ".join(iban[i : i + 4] for i in range(0, len(iban), 4))

    def _card(self) -> str:
        body = [self._rng.randint(0, 9) for _ in range(15)]
        body[0] = 4
        total = 0
        for i, d in enumerate(reversed(body)):
            x = d * 2 if i % 2 == 0 else d
            total += x - 9 if x > 9 else x
        digits = "".join(map(str, body)) + str((10 - total % 10) % 10)
        return " ".join(digits[i : i + 4] for i in range(0, 16, 4))

    def _email_for(self, persona: str) -> str:
        first, last = _ascii(persona).lower().split()[0], _ascii(persona).lower().split()[-1]
        domain = self._rng.choice(["gmail.com", "hotmail.com", "empresa.es", "correo.org"])
        return f"{first}.{last}@{domain}"

    def _email_spoken(self, persona: str) -> str:
        first, last = _ascii(persona).lower().split()[0], _ascii(persona).lower().split()[-1]
        name, tld = self._rng.choice(_SPOKEN_DOMAINS)
        return f"{first} punto {last} arroba {name} punto {tld}"

    def _secret(self) -> str:
        alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        return "sk-" + "".join(self._rng.choice(alphabet) for _ in range(40))

    def _password(self) -> str:
        return "".join(self._rng.choice("abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789#$%") for _ in range(10)) + "7#"

    def _ip(self) -> str:
        return ".".join(str(self._rng.randint(1, 254)) for _ in range(4))

    # ------------------------------------------------------------------ plantillas
    def _render(self, turns: list[str], scenario: str, kind: str) -> Sample:
        self._counter += 1
        vars_: dict[str, str] = {}

        def persona(key: str, ambiguous: bool = False) -> str:
            return vars_.setdefault(f"persona:{key}", self._persona(ambiguous))

        out: list[str] = []
        labels: list[Labeled] = []
        pos = 0
        text = "\n".join(turns)
        for m in _PLACEHOLDER.finditer(text):
            kind_name, key, mode = m.group(1), m.group(2) or "_", m.group(3)
            value, label_type = self._value(kind_name, key, persona, vars_)
            value = _apply_mode(value, mode)
            out.append(text[pos : m.start()])
            start = sum(len(s) for s in out)
            out.append(value)
            if label_type:
                labels.append(Labeled(label_type.value, start, start + len(value), value))
            pos = m.end()
        out.append(text[pos:])
        return Sample(f"{scenario}-{self._counter:04d}", scenario, kind, "".join(out), labels)

    def _value(
        self, name: str, key: str, persona: Callable[..., str], vars_: dict[str, str]
    ) -> tuple[str, EntityType | None]:
        if name == "persona":
            return persona(key), EntityType.PERSONA
        if name == "amb":
            return persona(key, ambiguous=True).split()[0], EntityType.PERSONA
        if name == "first":
            return persona(key).split()[0], EntityType.PERSONA
        if name == "org":
            org = vars_.setdefault(f"org:{key}", f"{self._rng.choice(_ORG_PREFIX)} {self._fake.last_name()}")
            return org, EntityType.ORGANIZACION
        if name == "city":
            return self._rng.choice(_CITIES), EntityType.UBICACION
        if name == "email":
            return self._email_for(persona("email")), EntityType.EMAIL
        if name == "emailhab":
            return self._email_spoken(persona("emailhab")), EntityType.EMAIL
        if name == "tel":
            return self._phone(), EntityType.TELEFONO
        if name == "telhab":
            return self._phone_spoken(), EntityType.TELEFONO
        if name == "dni":
            return self._dni(), EntityType.DNI_NIE
        if name == "iban":
            return self._iban(), EntityType.IBAN
        if name == "card":
            return self._card(), EntityType.TARJETA
        if name == "secret":
            return self._secret(), EntityType.SECRETO
        if name == "passw":
            return self._password(), EntityType.SECRETO
        if name == "ip":
            return self._ip(), EntityType.IP
        if name == "url":
            return f"https://app.{self._rng.choice(['atlas', 'nube', 'taller'])}.es/{self._digits(4)}", EntityType.URL
        if name == "glos":
            return vars_.setdefault(f"glos:{key}", self._rng.choice(_GLOSSARY_SURFACES)), EntityType.GLOSARIO
        raise ValueError(f"Marcador desconocido en la plantilla: {name}")

    # ------------------------------------------------------------------ API
    def generate(self, per_scenario: int = 10) -> list[Sample]:
        samples: list[Sample] = []
        for scenario, turns in NORMAL.items():
            samples += [self._render(turns, scenario, "normal") for _ in range(per_scenario)]
        for scenario, turns in ADVERSARIAL.items():
            samples += [self._render(turns, scenario, "adversarial") for _ in range(max(1, per_scenario // 2))]
        samples += self._repeated_person()
        samples += [self._trap(t) for t in TRAPS]
        return samples

    def _repeated_person(self) -> list[Sample]:
        """Una misma persona repetida 20 veces con formas distintas (completa, nombre de pila, sin tildes)."""
        full = self._persona()
        first = full.split()[0]
        forms = [full, first, _ascii(full), _ascii(first).lower()]
        parts: list[str] = []
        labels: list[Labeled] = []
        pos = 0
        for i in range(20):
            form = forms[i % len(forms)]
            prefix = f"Punto {i + 1}: hablar con "
            start = pos + len(prefix)
            parts.append(prefix + form + ".")
            labels.append(Labeled(EntityType.PERSONA.value, start, start + len(form), form))
            pos += len(parts[-1]) + 1
        self._counter += 1
        return [Sample(f"repeticion-{self._counter:04d}", "repeticion", "adversarial", "\n".join(parts), labels)]

    def _trap(self, text: str) -> Sample:
        self._counter += 1
        return Sample(f"trampa-{self._counter:04d}", "trampas", "trap", text, [])


# ------------------------------------------------------------------ utilidades
def _ascii(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _apply_mode(value: str, mode: str | None) -> str:
    if mode == "asr":  # minúsculas, sin tildes y a veces letras intercambiadas (error típico de Whisper)
        value = _ascii(value).lower()
        words = value.split()
        if len(words) > 1 and len(words[-1]) > 4:
            w = words[-1]
            words[-1] = w[:2] + w[3] + w[2] + w[4:]
        return " ".join(words)
    if mode == "upper":
        return value.upper()
    return value


def write_corpus(samples: Iterable[Sample], out_dir: Path) -> list[Path]:
    """Un .jsonl por escenario."""
    out_dir.mkdir(parents=True, exist_ok=True)
    by_scenario: dict[str, list[Sample]] = {}
    for s in samples:
        by_scenario.setdefault(s.scenario, []).append(s)
    paths = []
    for scenario, items in by_scenario.items():
        path = out_dir / f"{scenario}.jsonl"
        path.write_text("\n".join(json.dumps(asdict(s), ensure_ascii=False) for s in items) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def load_corpus(directory: Path) -> list[Sample]:
    samples: list[Sample] = []
    for path in sorted(directory.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                data = json.loads(line)
                samples.append(Sample(**{**data, "entities": [Labeled(**e) for e in data["entities"]]}))
    return samples
