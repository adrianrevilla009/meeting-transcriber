"""Reglas de detección de preguntas en español."""

import pytest

from realtime_assistant.application.context import format_context
from realtime_assistant.application.question_rules import RuleQuestionDetector
from realtime_assistant.domain.entities import TranscriptSegment
from tests.helpers import seg

detector = RuleQuestionDetector(("Adrián", "Adri"))


def questions(*segments: TranscriptSegment) -> list[str]:
    return [c.text for c in detector.detect(list(segments))]


@pytest.mark.parametrize(
    "text",
    [
        "¿Tú qué opinas del plazo de entrega?",
        "Oye, ¿puedes enviarme el informe mañana?",
        "¿Cuándo entregamos el informe?",
        "¿Qué hora es?",
        "¿El plazo termina el lunes?",
        "Gracias, ¿puedes repetirlo?",
        "Adrián, ¿cómo lo ves?",
        "Adri, ¿tienes un minuto?",
    ],
)
def test_detects_questions(text: str) -> None:
    assert questions(seg(1, text)) == [text]


@pytest.mark.parametrize(
    "text",
    [
        "El plazo termina el lunes.",
        "Cuándo entregamos el informe",  # sin signos: demasiado débil
        "Yo creo que sí, ¿verdad?",
        "Eso es todo, ¿no?",
        "Gracias a todos.",
        "¿Sí?",
        "Vale, perfecto, lo reviso mañana",
    ],
)
def test_ignores_statements_and_tag_questions(text: str) -> None:
    assert questions(seg(1, text)) == []


def test_question_ending_in_no_is_not_a_tag_question() -> None:
    assert questions(seg(1, "¿Puedes decirme si es así o no?")) == ["¿Puedes decirme si es así o no?"]


@pytest.mark.parametrize(
    "text",
    [
        "¿Puedes enviar el contrato a Marta García (marta@empresa.es) esta semana?",
        "¿Cuánto cuesta la versión 2.5 del plan en www.empresa.es/precios?",
    ],
)
def test_dots_inside_emails_urls_and_numbers_do_not_split_the_question(text: str) -> None:
    assert questions(seg(1, text)) == [text]


def test_only_listens_to_others() -> None:
    assert questions(seg(1, "¿Tú qué opinas del plazo?", source="mic")) == []
    assert questions(seg(1, "¿Tú qué opinas del plazo?", source="system")) == ["¿Tú qué opinas del plazo?"]
    assert questions(seg(1, "¿Tú qué opinas del plazo?", source="mix")) == ["¿Tú qué opinas del plazo?"]


def test_joins_segments_of_the_same_speaker_with_short_pauses() -> None:
    first = seg(1, "¿Cuándo podemos", start=0.0)
    second = seg(2, "tener el informe?", start=4.5)  # 0.5 s de pausa
    assert questions(first, second) == ["¿Cuándo podemos tener el informe?"]


def test_does_not_join_across_long_pauses_or_speakers() -> None:
    assert questions(seg(1, "¿Cuándo podemos", start=0.0), seg(2, "tener el informe?", start=20.0)) == []
    assert questions(seg(1, "¿Cuándo podemos", start=0.0), seg(2, "tener el informe?", source="mic", start=4.5)) == []


def test_several_questions_in_one_turn() -> None:
    found = questions(seg(1, "¿Qué hora es? ¿Dónde es la reunión?"))
    assert found == ["¿Qué hora es?", "¿Dónde es la reunión?"]


def test_candidates_carry_time_and_score() -> None:
    [candidate] = detector.detect([seg(3, "¿Cuándo entregamos el informe?")])
    assert candidate.ts == 15.0 and candidate.source == "system" and 0.55 <= candidate.score <= 1.0


def test_threshold_is_configurable() -> None:
    strict = RuleQuestionDetector(threshold=0.9)
    assert strict.detect([seg(1, "¿El plazo termina el lunes?")]) == []
    assert strict.detect([seg(1, "Oye, ¿puedes enviarme el informe mañana?")]) != []


def test_context_keeps_the_latest_lines_with_speakers() -> None:
    segments = [seg(1, "hola", "system"), seg(2, "buenas", "mic"), seg(3, "¿qué tal?", "system")]
    assert format_context(segments, 1000) == "Otros: hola\nYo: buenas\nOtros: ¿qué tal?"
    assert format_context(segments, 30) == "Yo: buenas\nOtros: ¿qué tal?"
    assert format_context([], 100) == ""
