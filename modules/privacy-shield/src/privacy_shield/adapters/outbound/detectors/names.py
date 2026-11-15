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
    celia angela esther susana veronica belen estela maite nerea sonia virginia
    ariel moises pascual celestino amelia febe aroa ovidio artemio prudencio julio aitor iker unai xavier jordi
    oriol marc joan josep carles ferran arnau guillem ander gorka imanol mikel jon koldo borja cesar agustin
    alfonso amadeo arturo bruno benjamin bernardo cayetano clemente damian domingo efrain elias ernesto eugenio
    fabian federico fermin gerardo german gregorio horacio isaac jaime jeronimo lazaro leandro leonardo
    leopoldo marcelo matias mauricio maximo nestor nicanor octavio omar orlando patricio sosimo venceslas
    carlota emma martina valeria triana adriana aitana lourdes asuncion montserrat merce rosario ramona josefa
    francisca antonia manuela juana mariana gema tamara sheila ruth jessica anunciacion bernarda agata pascuala
    ainara alejandra cecilia debora diana edurne fatima flora gabriela graciela helena hortensia iratxi leticia
    lola magdalena margarita matilde milagros nieves nora norma obdulia petra purificacion regina remedios
    rebeca renata roberta salome socorro soledad ursula violeta zaira""".split()
)
_AMBIGUOUS = {
    "rosa", "salvador", "pilar", "mar", "sol", "luz", "paz", "angel", "amparo", "consuelo", "dolores", "esperanza",
    "victoria", "gloria", "modesto", "santiago", "martin", "lorenzo", "cruz", "leon", "vega",
    "gala", "vera", "candela", "paloma", "aurora", "estrella", "ona", "noa", "pau",
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

# Palabras que, tras un nombre de pila, NO son un apellido (inicio de frase, conectores...).
_NOT_SURNAME = {
    "buenos", "buenas", "hola", "gracias", "saludos", "manana", "hoy", "ayer", "luego", "pero", "para", "por",
    "con", "que", "como", "cuando", "donde", "dijo", "dice", "llamo", "llama", "vive", "trabaja", "tiene", "esta",
    "quiere", "puede", "debe", "viene", "hemos", "estamos", "sobre", "desde", "hasta", "entre", "segun",
}  # fmt: skip

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
            if end_index == i and not ambiguous and capitalized and score >= 0.5 and i + 1 < len(words):
                nxt = words[i + 1]
                if _looks_like_surname(word, nxt.group(0)) and _adjacent(text, words[i], nxt):
                    end_index = i + 1  # apellido que no está en la lista: "Emilio Zabaleta"
            if score >= 0.5 or end_index > i:
                score = max(score, 0.7) if end_index > i else score
                start, end = words[i].start(), words[end_index].end()
                out.append(DetectedEntity(EntityType.PERSONA, start, end, text[start:end], score, SOURCE))
            i = end_index + 1
        return out


def _looks_like_surname(first: str, candidate: str) -> bool:
    """¿Parece un apellido la palabra que sigue a un nombre de pila? Mismo formato y no un conector."""
    if len(candidate) < 3 or fold(candidate) in _NOT_SURNAME:
        return False
    if first.isupper() and len(first) >= 3:
        return candidate.isupper()
    return candidate[0].isupper() and candidate[1:].islower()


def _adjacent(text: str, a: re.Match[str], b: re.Match[str]) -> bool:
    return text[a.end() : b.start()].strip(" ") == "" and b.start() - a.end() <= 2


def _score(capitalized: bool, ambiguous: bool, cue: bool, *, anti: bool) -> float:
    if ambiguous:
        return 0.7 if cue and capitalized else 0.4
    if capitalized:
        return 0.45 if anti and not cue else 0.7
    return 0.55 if cue else 0.3
