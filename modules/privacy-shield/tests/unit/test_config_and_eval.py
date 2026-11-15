"""Carga de política/glosario, composición (bootstrap), generador de corpus y evaluador."""

import json
from pathlib import Path

import pytest

from eval.generator.generate import GLOSSARY_TERMS, CorpusGenerator, load_corpus, write_corpus
from eval.run_eval import evaluate, leaked, render_markdown
from privacy_shield.adapters.outbound.files.loaders import load_glossary, load_policy
from privacy_shield.bootstrap import build_runtime
from privacy_shield.config import Settings
from privacy_shield.domain.entities import EntityType
from privacy_shield.domain.policy import Policy, Strategy

CONFIG = Path(__file__).resolve().parents[2] / "config"


# ------------------------------------------------------------------ política y glosario
def test_shipped_policy_matches_the_documented_defaults() -> None:
    policy = load_policy(CONFIG / "policy.yaml")
    assert policy.strategy_for(EntityType.PERSONA) == Strategy.PSEUDONYMIZE
    assert policy.strategy_for(EntityType.IBAN) == Strategy.MASK
    assert policy.strategy_for(EntityType.TARJETA) == Strategy.BLOCK
    assert policy.min_score_for(EntityType.UBICACION) == 0.6
    assert policy.min_score_for(EntityType.PERSONA) == policy.default_min_score == 0.5
    assert policy.local_only is False


def test_missing_policy_file_means_defaults() -> None:
    assert load_policy(None) == Policy()
    assert load_policy(Path("no-existe.yaml")) == Policy()


def test_invalid_policy_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text("strategies:\n  PERSONA: explotar\n", encoding="utf-8")
    with pytest.raises(ValueError, match="explotar"):
        load_policy(path)


def test_policy_overrides(tmp_path: Path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text("local_only: true\nstrategies:\n  email: allow\nmin_scores:\n  persona: 0.9\n", encoding="utf-8")
    policy = load_policy(path)
    assert policy.local_only and policy.strategy_for(EntityType.EMAIL) == Strategy.ALLOW
    assert policy.min_score_for(EntityType.PERSONA) == 0.9


def test_glossary_example_loads() -> None:
    terms = load_glossary(CONFIG / "glossary.example.yaml")
    assert [t.text for t in terms] == ["Proyecto Quimera", "Zoltrabek", "Cliente Atlas"]
    assert terms[0].aliases == ("Quimera",) and terms[0].entity_type == EntityType.GLOSARIO


def test_glossary_edge_cases(tmp_path: Path) -> None:
    assert load_glossary(None) == [] and load_glossary(tmp_path / "no.yaml") == []
    bad = tmp_path / "bad.yaml"
    bad.write_text("terms:\n  - foo: 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="glosario"):
        load_glossary(bad)


def test_settings_read_the_anon_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANON_VAULT", "sqlite")
    monkeypatch.setenv("ANON_VAULT_TTL_MINUTES", "30")
    settings = Settings()
    assert settings.vault == "sqlite" and settings.vault_ttl_minutes == 30
    assert settings.bind == "127.0.0.1"  # por defecto solo en local


# ------------------------------------------------------------------ bootstrap
def test_build_runtime_wires_everything(tmp_path: Path) -> None:
    settings = Settings(
        ner_enabled=False,
        glossary_path=None,
        policy_path=None,
        audit_path=tmp_path / "audit.jsonl",
        vault="sqlite",
        vault_sqlite_path=tmp_path / "vault.sqlite3",
    )
    rt = build_runtime(settings)
    out = rt.anonymize.execute("Escribe a ana@example.org")
    assert out.text == "Escribe a [EMAIL_1]"
    assert rt.deanonymize.execute(out.session_id, out.text) == "Escribe a ana@example.org"
    assert rt.registry.names() == ["anthropic", "ollama", "openai"]
    assert rt.health()["vault"] == "sqlite"
    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and "ana@example.org" not in "".join(lines)


# ------------------------------------------------------------------ generador de corpus
def test_corpus_generation_is_deterministic_and_labels_are_exact() -> None:
    first = CorpusGenerator(7).generate(3)
    second = CorpusGenerator(7).generate(3)
    assert first == second
    assert CorpusGenerator(8).generate(3) != first
    for sample in first:
        for label in sample.entities:
            assert sample.text[label.start : label.end] == label.value, sample.id


def test_corpus_covers_every_kind_and_scenario() -> None:
    samples = CorpusGenerator(7).generate(2)
    assert {s.kind for s in samples} == {"normal", "adversarial", "trap"}
    assert len({s.scenario for s in samples}) >= 15
    assert all(not s.entities for s in samples if s.kind == "trap")
    types = {label.type for s in samples for label in s.entities}
    assert types >= {"PERSONA", "ORGANIZACION", "UBICACION", "EMAIL", "TELEFONO", "DNI_NIE", "IBAN", "TARJETA", "SECRETO", "URL", "IP"}
    assert GLOSSARY_TERMS


def test_corpus_round_trips_through_jsonl(tmp_path: Path) -> None:
    samples = CorpusGenerator(7).generate(2)
    write_corpus(samples, tmp_path)
    loaded = load_corpus(tmp_path)
    assert sorted(loaded, key=lambda s: s.id) == sorted(samples, key=lambda s: s.id)


# ------------------------------------------------------------------ evaluador
def test_leak_detection_rules() -> None:
    from eval.generator.generate import Labeled

    person = Labeled("PERSONA", 0, 12, "Marta García")
    assert leaked(person, "Hablé con García ayer") and not leaked(person, "Hablé con [PERSONA_1] ayer")
    email = Labeled("EMAIL", 0, 15, "ana@example.org")
    assert leaked(email, "escribe a ana@example.org") and not leaked(email, "escribe a [EMAIL_1]")


def test_evaluator_runs_without_ner_and_reports_sensible_numbers(tmp_path: Path) -> None:
    samples = CorpusGenerator(7).generate(2)
    report = evaluate(samples, ner=False)
    assert report["samples"] == len(samples) and report["totals"]["labeled"] > 0
    assert 0.0 <= report["leak_rate"] < 0.6  # umbral muy holgado: solo detecta un pipeline roto
    assert report["per_type"]["EMAIL"]["labeled"] > 0
    assert report["latency_ms"]["p95"] >= report["latency_ms"]["p50"] >= 0
    markdown = render_markdown(report)
    assert "Leak rate" in markdown and "## Por tipo" in markdown and "## Fallos concretos" in markdown
    json.dumps(report)  # serializable


def test_leak_rate_does_not_regress_against_the_baseline() -> None:
    baseline_path = Path(__file__).resolve().parents[2] / "eval" / "baseline.json"
    if not baseline_path.exists():
        pytest.skip("Sin baseline.json: se fija con `python -m eval.run_eval --write-baseline`")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if baseline["ner"]:
        pytest.importorskip("spacy")
    report = evaluate(CorpusGenerator(7).generate(10), ner=bool(baseline["ner"]))
    assert report["leak_rate"] <= baseline["leak_rate"] + 0.01
