"""Verificación de citas: la barrera contra las alucinaciones del LLM."""
import pytest

from app.models import Segment
from app.services.verifier import locate_quote, normalize


def segs(*texts: str) -> list[Segment]:
    return [Segment(id=i + 1, meeting_id=1, start=i * 5.0, end=i * 5.0 + 5, text=t) for i, t in enumerate(texts)]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Hola, ¿Qué TAL?", "hola que tal"),
        ("Pagos   en\tdólares", "pagos en dolares"),
        ("¡Ñandú! añadir", "nandu anadir"),
        ("", ""),
    ],
)
def test_normalize_strips_case_accents_and_punctuation(raw, expected):
    assert normalize(raw) == expected


def test_exact_quote_is_located():
    s = segs("Buenos días.", "El cliente quiere pagar con tarjeta.")
    assert locate_quote("quiere pagar con tarjeta", s, 92).id == 2


def test_quote_ignores_accents_case_and_punctuation():
    s = segs("Todavía no sabemos si hace falta soporte para pagos en dólares.")
    assert locate_quote("TODAVIA no sabemos, si hace falta soporte", s, 92).id == 1


def test_quote_spanning_two_segments_points_to_first():
    s = segs("Hemos decidido que la primera versión", "se entregará el quince de diciembre.")
    assert locate_quote("la primera versión se entregará el quince", s, 92).id == 1


def test_small_transcription_error_still_accepted_by_fuzzy_match():
    s = segs("El cliente quiere que la aplicación permita pagar con Bisum.")
    assert locate_quote("la aplicación permita pagar con Bizum", s, 90) is not None


def test_invented_quote_is_rejected():
    s = segs("Buenos días a todos.", "El cliente quiere pagar con tarjeta.")
    assert locate_quote("esta frase nunca se dijo en la reunión", s, 92) is None


def test_too_short_quote_is_rejected():
    s = segs("sí, vale, perfecto")
    assert locate_quote("sí", s, 92) is None


def test_threshold_controls_fuzzy_acceptance():
    s = segs("el pago se hará mediante transferencia bancaria")
    quote = "el pago se hará mediante transferencia urgente"
    assert locate_quote(quote, s, 99) is None
    assert locate_quote(quote, s, 70) is not None


def test_empty_transcript():
    assert locate_quote("cualquier cosa larga", [], 92) is None
