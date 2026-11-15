"""Nombres de pila y apellidos comunes en español. Complementa al NER, que falla con nombres sueltos,
en minúsculas o sin contexto. Los nombres que también son palabras (Rosa, Salvador...) solo puntúan alto con una pista
de contexto ("me llamo", "hola", "con", "señor"...); sin ella quedan por debajo del umbral y no se tocan."""

import re

from privacy_shield.application.textnorm import fold
from privacy_shield.domain.entities import DetectedEntity, EntityType

SOURCE = "names"

_FIRST_NAMES = set(
    """maria jose antonio manuel francisco juan david javier daniel carlos miguel rafael pedro alejandro fernando luis
    sergio pablo jorge alberto adrian alvaro diego ivan ruben oscar raul enrique andres victor gonzalo hugo marcos mario
    eduardo ramon joaquin ignacio tomas guillermo roberto jesus rodrigo gabriel lucas mateo samuel nicolas cristian
    emilio ricardo gustavo hector felipe ismael marta laura carmen ana isabel lucia paula elena sara cristina patricia
    andrea raquel beatriz sandra silvia monica irene nuria alicia teresa natalia eva julia claudia noelia rocio marina
    inmaculada mercedes concepcion sofia carla alba lorena vanesa yolanda olga ines miriam ainhoa leire begona lidia
    celia angela esther susana veronica belen estela maite nerea sonia virginia""".split()
)
_AMBIGUOUS = {
    "rosa", "salvador", "pilar", "mar", "sol", "luz", "paz", "angel", "amparo", "consuelo", "dolores", "esperanza",
    "victoria", "gloria", "modesto", "santiago", "martin", "lorenzo", "cruz", "leon", "vega",
}  # fmt: skip
_SURNAMES = set(
    """garcia fernandez gonzalez rodriguez lopez martinez sanchez perez gomez jimenez ruiz hernandez diaz moreno alvarez
    munoz romero alonso gutierrez navarro torres dominguez vazquez ramos gil ramirez serrano blanco molina morales
    suarez ortega delgado castro ortiz rubio marin sanz nunez iglesias medina garrido cortes castillo santos lozano
    guerrero cano prieto mendez calvo gallego vidal marquez herrera pena flores cabrera campos fuentes carrasco
    caballero reyes nieto aguilar pascual santana herrero hidalgo gimenez ibanez ferrer duran benitez mora vicente
    vargas arias carmona crespo roman pastor soto saez velasco moya soler parra esteban bravo gallardo rojas""".split()
)
# Palabras que, justo antes, indican que viene una persona.
_CUES = {
    "llamo", "llama", "soy", "hola", "señor", "senor", "señora", "senora", "don", "doña", "dona", "sr", "sra",
    "con", "para", "dile", "pregunta", "habla", "habló", "hablo", "gracias", "dijo", "dice",
}  # fmt: skip
# Palabras que, justo antes, indican que NO es una persona (color de rosa, el salvador...).
_ANTI_CUES = {"color", "tono", "flor", "un", "una", "el", "la", "los", "las"}

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


class NameListDetector:
    def detect(self, text: str, *, language: str = "es") -> list[DetectedEntity]:
        words = list(_WORD.finditer(text))
        out: list[DetectedEntity] = []
        i = 0
        while i < len(words):
            word = words[i].group(0)
            key = fold(word)
            if key not in _FIRST_NAMES and key not in _AMBIGUOUS:
                i += 1
                continue
            prev = fold(words[i - 1].group(0)) if i > 0 else ""
            cue = prev in _CUES
            capitalized = word[0].isupper()
            ambiguous = key in _AMBIGUOUS
            score = _score(capitalized, ambiguous, cue, anti=prev in _ANTI_CUES)
            end_index = i
            # Apellidos conocidos pegados al nombre: "Marta García López"
            while end_index + 1 < len(words) and end_index - i < 2:
                nxt = words[end_index + 1]
                is_surname = fold(nxt.group(0)) in _SURNAMES and nxt.group(0)[0].isupper()
                if is_surname and _adjacent(text, words[end_index], nxt):
                    end_index += 1
                else:
                    break
            if score >= 0.5 or end_index > i:
                score = max(score, 0.7) if end_index > i else score
                start, end = words[i].start(), words[end_index].end()
                out.append(DetectedEntity(EntityType.PERSONA, start, end, text[start:end], score, SOURCE))
            i = end_index + 1
        return out


def _adjacent(text: str, a: re.Match[str], b: re.Match[str]) -> bool:
    return text[a.end() : b.start()].strip(" ") == "" and b.start() - a.end() <= 2


def _score(capitalized: bool, ambiguous: bool, cue: bool, *, anti: bool) -> float:
    if ambiguous:
        return 0.7 if cue and capitalized else 0.4
    if capitalized:
        return 0.45 if anti and not cue else 0.7
    return 0.55 if cue else 0.3
