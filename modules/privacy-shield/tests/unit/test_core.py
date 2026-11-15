"""Núcleo: pseudonimizador, desanonimizador (también en streaming), leak guard, normalizador de ASR y política."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from privacy_shield.adapters.outbound.detectors.regex_es import RegexDetector
from privacy_shield.application.deanonymizer import Deanonymizer, StreamingDeanonymizer
from privacy_shield.application.leak_guard import LeakGuard, contains_value, within_one_edit
from privacy_shield.application.normalizer import NormalizingDetector, normalize
from privacy_shield.application.ports import VaultPort
from privacy_shield.application.pseudonymizer import Pseudonymizer
from privacy_shield.application.use_cases import Anonymizer
from privacy_shield.domain.entities import DetectedEntity, EntityType
from privacy_shield.domain.errors import BlockedByPolicy, DetectorUnavailable, LeakDetected
from privacy_shield.domain.policy import Policy, Strategy
from privacy_shield.domain.session import SessionId
from tests.helpers import make_detector


def anonymizer(vault: VaultPort, policy: Policy | None = None) -> Anonymizer:
    return Anonymizer(make_detector(), Pseudonymizer(vault, policy or Policy()))


# ------------------------------------------------------------------ pseudonymizer
def test_same_value_gets_the_same_token(vault: VaultPort, session: SessionId) -> None:
    out = anonymizer(vault).anonymize(session, "Marta García escribió. Luego Marta García llamó.")
    assert out.text == "[PERSONA_1] escribió. Luego [PERSONA_1] llamó."
    assert [r.token for r in out.replacements] == ["[PERSONA_1]", "[PERSONA_1]"]


def test_same_value_with_other_format_gets_the_same_token(vault: VaultPort, session: SessionId) -> None:
    out = anonymizer(vault).anonymize(session, "Llama al 612 345 678 o al +34 612345678.")
    assert out.text == "Llama al [TELEFONO_1] o al [TELEFONO_1]."


def test_first_name_reuses_the_full_name_token(vault: VaultPort, session: SessionId) -> None:
    out = anonymizer(vault).anonymize(session, "Marta García llamó. Después, Marta dijo que sí.")
    assert out.text == "[PERSONA_1] llamó. Después, [PERSONA_1] dijo que sí."
    assert vault.find_token(session, EntityType.PERSONA, "marta") == "[PERSONA_1]"


def test_ambiguous_first_name_gets_its_own_token(vault: VaultPort, session: SessionId) -> None:
    out = anonymizer(vault).anonymize(session, "Marta García y Marta López hablaron. Luego Marta llamó.")
    assert out.text == "[PERSONA_1] y [PERSONA_2] hablaron. Luego [PERSONA_3] llamó."


def test_full_name_after_first_name_reuses_the_token(vault: VaultPort, session: SessionId) -> None:
    out = anonymizer(vault).anonymize(session, "Hable con Marta. Más tarde llegó Marta García.")
    assert out.text == "Hable con [PERSONA_1]. Más tarde llegó [PERSONA_1]."


def test_known_values_missed_by_the_detector_are_swept(vault: VaultPort, session: SessionId) -> None:
    pseudo = Pseudonymizer(vault, Policy())
    first = pseudo.apply(session, "Contacto: ana@example.org", RegexDetector().detect("Contacto: ana@example.org"))
    assert first.text == "Contacto: [EMAIL_1]"
    # La segunda vez el detector no marca nada, pero el vault ya conoce el valor.
    second = pseudo.apply(session, "Reenvía a ANA@example.org y confirma", [])
    assert second.text == "Reenvía a [EMAIL_1] y confirma"


def test_mask_is_not_reversible(vault: VaultPort, session: SessionId) -> None:
    out = anonymizer(vault).anonymize(session, "Mi IBAN es ES91 2100 0418 4502 0005 1332 ok")
    assert out.text == "Mi IBAN es [IBAN] ok"
    assert vault.resolve(session, "[IBAN]") is None


def test_block_strategy_rejects_the_whole_text(vault: VaultPort, session: SessionId) -> None:
    with pytest.raises(BlockedByPolicy) as err:
        anonymizer(vault).anonymize(session, "Mi tarjeta es 4111 1111 1111 1111")
    assert EntityType.TARJETA in err.value.types


def test_allow_strategy_leaves_the_text_untouched(vault: VaultPort, session: SessionId) -> None:
    policy = Policy(strategies={**Policy().strategies, EntityType.EMAIL: Strategy.ALLOW})
    out = anonymizer(vault, policy).anonymize(session, "Escribe a ana@example.org")
    assert out.text == "Escribe a ana@example.org"


def test_entities_below_min_score_are_ignored(vault: VaultPort, session: SessionId) -> None:
    low = DetectedEntity(EntityType.PERSONA, 0, 5, "Marta", 0.3, "test")
    assert Pseudonymizer(vault, Policy()).apply(session, "Marta dijo", [low]).text == "Marta dijo"
    strict = Policy(min_scores={EntityType.PERSONA: 0.2})
    assert Pseudonymizer(vault, strict).apply(session, "Marta dijo", [low]).text == "[PERSONA_1] dijo"


def test_detector_failure_fails_closed(vault: VaultPort, session: SessionId) -> None:
    class Boom:
        def detect(self, text: str, *, language: str = "es") -> list[DetectedEntity]:
            raise RuntimeError("modelo caído")

    with pytest.raises(DetectorUnavailable):
        Anonymizer(Boom(), Pseudonymizer(vault, Policy())).anonymize(session, "texto cualquiera")


# ------------------------------------------------------------------ deanonymizer
@pytest.mark.parametrize(
    "variant", ["[PERSONA_1]", "[persona 1]", "[Persona_1]", "PERSONA_1", "[ PERSONA_1 ]", "[PERSONA 1]"]
)
def test_deanonymize_is_tolerant(vault: VaultPort, session: SessionId, variant: str) -> None:
    vault.get_or_create_token(session, EntityType.PERSONA, "Marta García")
    assert Deanonymizer(vault).deanonymize(session, f"Hola {variant}, adiós").text == "Hola Marta García, adiós"


def test_deanonymize_accepts_accented_type(vault: VaultPort, session: SessionId) -> None:
    vault.get_or_create_token(session, EntityType.ORGANIZACION, "Acme")
    assert Deanonymizer(vault).deanonymize(session, "Trabaja en [ORGANIZACIÓN_1]").text == "Trabaja en Acme"


def test_unknown_tokens_are_left_and_counted(vault: VaultPort, session: SessionId) -> None:
    result = Deanonymizer(vault).deanonymize(session, "Hola [PERSONA_9] y [EMAIL_3]")
    assert result.text == "Hola [PERSONA_9] y [EMAIL_3]"
    assert result.unknown_tokens == 2


def test_deanonymize_ignores_masked_tokens_and_plain_text(vault: VaultPort, session: SessionId) -> None:
    result = Deanonymizer(vault).deanonymize(session, "Tu IBAN es [IBAN] y el índice [1] y [no es token]")
    assert result.text == "Tu IBAN es [IBAN] y el índice [1] y [no es token]"
    assert result.unknown_tokens == 0


STREAM_TEXT = (
    "Hola [PERSONA_1], te escribo de [ORGANIZACION_1]. PERSONA_1 dijo [PERSONA_9] y [no es token] "
    "luego [persona 1] y EMAIL_1 [EMAIL_1] fin [ sin cerrar"
)


def _stream(vault: VaultPort, session: SessionId, cuts: list[int]) -> tuple[str, int]:
    streaming = StreamingDeanonymizer(Deanonymizer(vault), session)
    points = sorted({0, len(STREAM_TEXT), *(c for c in cuts if 0 <= c <= len(STREAM_TEXT))})
    out = "".join(streaming.feed(STREAM_TEXT[a:b]) for a, b in zip(points, points[1:], strict=False))
    return out + streaming.flush(), streaming.unknown_tokens


@settings(max_examples=250, deadline=None)
@given(cuts=st.lists(st.integers(min_value=0, max_value=len(STREAM_TEXT)), max_size=25))
def test_streaming_matches_non_streaming_for_any_split(cuts: list[int]) -> None:
    from privacy_shield.adapters.outbound.vault.memory import MemoryVault
    from tests.helpers import FakeClock

    vault = MemoryVault(FakeClock())
    session = SessionId("s")
    vault.get_or_create_token(session, EntityType.PERSONA, "Marta García")
    vault.get_or_create_token(session, EntityType.ORGANIZACION, "Acme")
    vault.get_or_create_token(session, EntityType.EMAIL, "a@b.es")
    expected = Deanonymizer(vault).deanonymize(session, STREAM_TEXT)
    out, unknown = _stream(vault, session, cuts)
    assert out == expected.text
    assert unknown == expected.unknown_tokens


def test_streaming_token_split_in_every_position(vault: VaultPort, session: SessionId) -> None:
    vault.get_or_create_token(session, EntityType.PERSONA, "Marta García")
    text = "Dile a [PERSONA_1] y a PERSONA_1 que sí."
    expected = Deanonymizer(vault).deanonymize(session, text).text
    for cut in range(len(text) + 1):
        s = StreamingDeanonymizer(Deanonymizer(vault), session)
        assert s.feed(text[:cut]) + s.feed(text[cut:]) + s.flush() == expected


# ------------------------------------------------------------------ leak guard
def _guard(vault: VaultPort) -> LeakGuard:
    return LeakGuard(vault, RegexDetector())


def test_guard_passes_clean_payload(vault: VaultPort, session: SessionId) -> None:
    vault.get_or_create_token(session, EntityType.PERSONA, "Zoltrabek Quillfeather")
    _guard(vault).check(session, ["[PERSONA_1] aprobó el presupuesto", "sin datos"])


def test_guard_blocks_a_real_value_that_survived(vault: VaultPort, session: SessionId) -> None:
    vault.get_or_create_token(session, EntityType.PERSONA, "Zoltrabek Quillfeather")
    with pytest.raises(LeakDetected) as err:
        _guard(vault).check(session, ["Que apruebe Zoltrabek Quillfeather el presupuesto"])
    assert err.value.counts == {EntityType.PERSONA: 1}


def test_guard_is_fuzzy_for_long_values(vault: VaultPort, session: SessionId) -> None:
    vault.get_or_create_token(session, EntityType.PERSONA, "Zoltrabek Quillfeather")
    with pytest.raises(LeakDetected):
        _guard(vault).check(session, ["Habló con zoltrabek quillfether ayer"])  # falta una letra


def test_guard_respects_word_boundaries(vault: VaultPort, session: SessionId) -> None:
    vault.get_or_create_token(session, EntityType.PERSONA, "Rosa")
    _guard(vault).check(session, ["Es pura prosa, sin nombres"])
    with pytest.raises(LeakDetected):
        _guard(vault).check(session, ["Llamó Rosa"])


def test_guard_runs_the_regex_detector_again(vault: VaultPort, session: SessionId) -> None:
    with pytest.raises(LeakDetected) as err:
        _guard(vault).check(session, ["escribe a ana@example.org o llama al 612 345 678"])
    assert set(err.value.counts) == {EntityType.EMAIL, EntityType.TELEFONO}


def test_guard_ignores_tokens(vault: VaultPort, session: SessionId) -> None:
    _guard(vault).check(session, ["Hola [PERSONA_1], tu IBAN [IBAN] y [EMAIL_2]"])


def test_edit_distance_helpers() -> None:
    assert within_one_edit("casa", "casa") and within_one_edit("casa", "casas") and within_one_edit("casa", "cosa")
    assert within_one_edit("casas", "casa") and not within_one_edit("casa", "cosas") and not within_one_edit("ab", "ba")
    assert contains_value("hola marta garcia ok", "marta garcia")
    assert not contains_value("hola marta", "marta garcia")


# ------------------------------------------------------------------ normalizador de ASR
def test_spoken_digits_become_digits() -> None:
    view = normalize("mi número es seis cuatro cinco, treinta y dos, diez, once gracias")
    assert view.text == "mi número es 645321011 gracias"


def test_few_number_words_are_left_alone() -> None:
    text = "tengo dos o tres reuniones y cuatro cafés"
    assert normalize(text).text == text


def test_spoken_email_becomes_an_email() -> None:
    view = normalize("mi correo es marta punto garcia arroba gmail punto com gracias")
    assert view.text == "mi correo es marta.garcia@gmail.com gracias"


def test_spoken_url_and_symbols() -> None:
    assert normalize("entra en www punto ejemplo punto com").text == "entra en www.ejemplo.com"
    assert normalize("es ana guion bajo ruiz arroba empresa punto es").text == "es ana_ruiz@empresa.es"


def test_normalizing_detector_projects_spans_to_the_original() -> None:
    text = "mi correo es marta punto garcia arroba gmail punto com gracias"
    detector = NormalizingDetector(RegexDetector())
    [email] = [e for e in detector.detect(text) if e.type == EntityType.EMAIL]
    assert email.text == "marta punto garcia arroba gmail punto com"
    assert text[email.start : email.end] == email.text


def test_spoken_phone_is_detected_and_covered_entirely() -> None:
    text = "apunta: seis uno dos, tres cuatro cinco, seis siete ocho. Gracias"
    detector = NormalizingDetector(RegexDetector())
    [phone] = [e for e in detector.detect(text) if e.type == EntityType.TELEFONO]
    assert phone.text == "seis uno dos, tres cuatro cinco, seis siete ocho"


def test_text_without_asr_forms_is_passed_through() -> None:
    text = "escribe a ana@example.org"
    assert normalize(text).text == text
    assert [e.text for e in NormalizingDetector(RegexDetector()).detect(text)] == ["ana@example.org"]


# ------------------------------------------------------------------ propiedad de ida y vuelta
_WORDS = ["hola", "reunión", "mañana", "proyecto", "el", "la", "y", "revisa", "esto", "por", "favor"]
_VALUES = [
    "ana@example.org",
    "https://app.empresa.es/x",
    "192.168.1.10",
    "612 345 678",
    "marta.ruiz@correo.es",
]


@settings(max_examples=150, deadline=None)
@given(
    words=st.lists(st.sampled_from(_WORDS), min_size=1, max_size=12),
    values=st.lists(st.sampled_from(_VALUES), min_size=1, max_size=6),
)
def test_round_trip(words: list[str], values: list[str]) -> None:
    from privacy_shield.adapters.outbound.vault.memory import MemoryVault
    from tests.helpers import FakeClock

    vault = MemoryVault(FakeClock())
    session = SessionId("rt")
    vault.ensure_session(session)
    parts: list[str] = []
    for i, value in enumerate(values):
        parts.append(words[i % len(words)])
        parts.append(value)
    parts.extend(words)
    text = " ".join(parts)
    anonymized = Anonymizer(make_detector(), Pseudonymizer(vault, Policy())).anonymize(session, text)
    assert all(v not in anonymized.text for v in values)
    assert Deanonymizer(vault).deanonymize(session, anonymized.text).text == text
