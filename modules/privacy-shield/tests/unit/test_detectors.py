"""Detectores: regex, glosario, lista de nombres, compuesto (solapes) y NER (si está instalado)."""

import pytest

from privacy_shield.adapters.outbound.detectors.composite import resolve_overlaps
from privacy_shield.adapters.outbound.detectors.glossary import GlossaryDetector
from privacy_shield.adapters.outbound.detectors.names import NameListDetector
from privacy_shield.adapters.outbound.detectors.org_patterns import OrgPatternDetector
from privacy_shield.adapters.outbound.detectors.regex_es import RegexDetector
from privacy_shield.adapters.outbound.detectors.spacy_ner import SpacyNerDetector, recase
from privacy_shield.domain.entities import DetectedEntity, EntityType
from privacy_shield.domain.glossary import GlossaryTerm

regex = RegexDetector()


def found(text: str) -> dict[EntityType, list[str]]:
    out: dict[EntityType, list[str]] = {}
    for e in regex.detect(text):
        out.setdefault(e.type, []).append(e.text)
    return out


@pytest.mark.parametrize(
    ("text", "entity_type", "value"),
    [
        ("escríbeme a marta.garcia@gmail.com mañana", EntityType.EMAIL, "marta.garcia@gmail.com"),
        ("mira https://app.empresa.es/x?id=3, gracias", EntityType.URL, "https://app.empresa.es/x?id=3"),
        ("entra en www.ejemplo.com.", EntityType.URL, "www.ejemplo.com"),
        ("el servidor 192.168.1.10 no responde", EntityType.IP, "192.168.1.10"),
        ("llámame al 612 345 678 por favor", EntityType.TELEFONO, "612 345 678"),
        ("mi número es 612345678", EntityType.TELEFONO, "612345678"),
        ("mi número es +34 612 345 678.", EntityType.TELEFONO, "+34 612 345 678"),
        ("fijo 912 34 56 78", EntityType.TELEFONO, "912 34 56 78"),
        ("mi DNI es 12345678Z", EntityType.DNI_NIE, "12345678Z"),
        ("mi NIE es X1234567L", EntityType.DNI_NIE, "X1234567L"),
        ("el IBAN es ES91 2100 0418 4502 0005 1332 gracias", EntityType.IBAN, "ES91 2100 0418 4502 0005 1332"),
        ("el IBAN ES9121000418450200051332", EntityType.IBAN, "ES9121000418450200051332"),
        ("tarjeta 4111 1111 1111 1111 caduca", EntityType.TARJETA, "4111 1111 1111 1111"),
        ("la clave es sk-abcdefghijklmnopqrstuvwxyz0123456789ABCD", EntityType.SECRETO, "sk-abcdefghijklmnopqrstuvwxyz0123456789ABCD"),
        ("la contraseña es Tr0ub4dor&3 ok", EntityType.SECRETO, "Tr0ub4dor&3"),
    ],
)
def test_regex_detects_each_type(text: str, entity_type: EntityType, value: str) -> None:
    assert value in found(text).get(entity_type, [])


@pytest.mark.parametrize(
    "text",
    [
        "Hoy hay reunión a las diez y media.",
        "El presupuesto es de 1250 euros.",
        "La versión 2.5.1 ya está en producción.",
        "Nos vemos el 15 de diciembre.",
        "la clave es importante para el proyecto",  # sin valor dictado
    ],
)
def test_regex_ignores_plain_text(text: str) -> None:
    assert found(text) == {}


def test_invalid_dni_letter_scores_lower() -> None:
    valid = next(e for e in regex.detect("12345678Z") if e.type == EntityType.DNI_NIE)
    invalid = next(e for e in regex.detect("12345678A") if e.type == EntityType.DNI_NIE)
    assert valid.score > invalid.score


def test_iban_followed_by_short_words_keeps_only_the_iban() -> None:
    text = "ES91 2100 0418 4502 0005 1332 ok"
    iban = next(e for e in regex.detect(text) if e.type == EntityType.IBAN)
    assert iban.text == "ES91 2100 0418 4502 0005 1332"


def test_iban_digits_are_not_taken_for_a_card() -> None:
    assert EntityType.TARJETA not in found("el IBAN es ES91 2100 0418 4502 0005 1332")


def test_card_must_pass_luhn() -> None:
    assert EntityType.TARJETA not in found("pedido 4111 1111 1111 1112")


def test_glossary_ignores_case_and_accents() -> None:
    detector = GlossaryDetector([GlossaryTerm("Proyecto Quimera", aliases=("Quimera",)), GlossaryTerm("Zoltrabek")])
    entities = detector.detect("Hablamos del proyecto QUIMERA y de Zöltrabek con Quimera.")
    assert [e.text for e in entities].count("Quimera") == 1
    assert {e.text for e in entities} >= {"proyecto QUIMERA", "Zöltrabek", "Quimera"}


def test_glossary_respects_word_boundaries() -> None:
    detector = GlossaryDetector([GlossaryTerm("Atlas")])
    assert detector.detect("La palabra atlasada no cuenta") == []


def test_names_detects_first_name_and_known_surnames() -> None:
    names = NameListDetector()
    entities = names.detect("Ayer llamó Marta García López para confirmar.")
    assert [e.text for e in entities] == ["Marta García López"]
    assert all(e.type == EntityType.PERSONA for e in entities)


def test_ambiguous_names_need_context() -> None:
    names = NameListDetector()
    assert names.detect("Me gusta el color rosa para la portada") == []
    assert [e.text for e in names.detect("Hola, soy Rosa y vengo de parte de la empresa")] == ["Rosa"]


def test_lowercase_asr_name_needs_a_cue() -> None:
    names = NameListDetector()
    assert [e.text for e in names.detect("dile a todos que hable con marta mañana")] == ["marta"]
    assert names.detect("la marta es un animal") == []


def test_names_extends_to_an_unknown_surname() -> None:
    names = NameListDetector()
    assert [e.text for e in names.detect("Hey, send the report to Emilio Zabaleta tomorrow")] == ["Emilio Zabaleta"]
    assert [e.text for e in names.detect("Dile a Marta Gracias por todo")] == ["Marta"]  # 'Gracias' no es un apellido
    assert [e.text for e in names.detect("Habló ARTEMIO SEGOVIA ayer")] == ["ARTEMIO SEGOVIA"]


def test_names_do_not_swallow_the_next_sentence() -> None:
    assert [e.text for e in NameListDetector().detect("Hablé con Marta. Luego fui a casa")] == ["Marta"]


def test_org_patterns() -> None:
    orgs = OrgPatternDetector()
    text = "Trabaja en Industrias Navarro y colabora con la Fundación de la Esperanza; factura Gómez y Hermanos S.L. hoy."
    assert [e.text for e in orgs.detect(text)] == ["Industrias Navarro", "Fundación de la Esperanza", "Gómez y Hermanos S.L."]
    assert all(e.type == EntityType.ORGANIZACION for e in orgs.detect(text))
    assert orgs.detect("Buscamos soluciones técnicas y un grupo de trabajo") == []


def test_ner_recases_shouted_text_only() -> None:
    assert recase("LE DIJE A ARTEMIO SEGOVIA QUE VINIERA") == "LE Dije A Artemio Segovia Que Viniera"
    assert recase("Hablé con la ONU ayer por la tarde") == "Hablé con la ONU ayer por la tarde"


def _entity(entity_type: EntityType, start: int, end: int, score: float, source: str) -> DetectedEntity:
    return DetectedEntity(entity_type, start, end, "x" * (end - start), score, source)


def test_overlaps_longest_span_wins() -> None:
    long_ner = _entity(EntityType.ORGANIZACION, 0, 20, 0.7, "ner")
    short_regex = _entity(EntityType.EMAIL, 5, 10, 0.99, "regex")
    assert resolve_overlaps([short_regex, long_ner]) == [long_ner]


def test_overlaps_tie_goes_to_score_then_specificity() -> None:
    ner = _entity(EntityType.PERSONA, 0, 10, 0.8, "ner")
    glossary = _entity(EntityType.GLOSARIO, 0, 10, 0.97, "glossary")
    regex_ = _entity(EntityType.EMAIL, 0, 10, 0.97, "regex")
    assert resolve_overlaps([ner, glossary]) == [glossary]
    assert resolve_overlaps([glossary, regex_]) == [regex_]  # a igualdad de score, regex > glosario


def test_non_overlapping_spans_are_all_kept_in_order() -> None:
    a = _entity(EntityType.PERSONA, 10, 15, 0.8, "ner")
    b = _entity(EntityType.EMAIL, 0, 5, 0.99, "regex")
    assert resolve_overlaps([a, b]) == [b, a]


@pytest.mark.ner
def test_spacy_finds_people_and_places(ner_detector: SpacyNerDetector) -> None:
    entities = ner_detector.detect("Ayer María Fernández viajó desde Valladolid a Sevilla para ver a su familia.")
    by_type = {e.type for e in entities}
    assert EntityType.PERSONA in by_type
    assert EntityType.UBICACION in by_type
    assert any("Fernández" in e.text for e in entities if e.type == EntityType.PERSONA)
