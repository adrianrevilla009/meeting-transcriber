"""Evaluador: ejecuta el pipeline sobre el corpus y mide fugas, recall/precisión, sobre-redacción y latencia.

    python -m eval.run_eval                     # genera el corpus en memoria (semilla 7) y evalúa
    python -m eval.run_eval --no-ner            # sin spaCy
    python -m eval.run_eval --write-baseline    # fija eval/baseline.json con el resultado actual

Lo importante es el LEAK RATE: qué fracción de los valores reales etiquetados sigue apareciendo en lo que saldría.
"""

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

from eval.generator.generate import (
    GENERIC_ORG_WORDS,
    GLOSSARY_TERMS,
    CorpusGenerator,
    Labeled,
    Sample,
    load_corpus,
    write_corpus,
)
from privacy_shield.adapters.outbound.audit.memory import NullAuditAdapter
from privacy_shield.adapters.outbound.files.loaders import load_policy
from privacy_shield.application.leak_guard import contains_value
from privacy_shield.application.ports import DetectorPort
from privacy_shield.application.textnorm import fold
from privacy_shield.bootstrap import build_detector, build_runtime
from privacy_shield.config import Settings
from privacy_shield.domain.entities import DetectedEntity, EntityType
from privacy_shield.domain.errors import BlockedByPolicy, PrivacyShieldError
from privacy_shield.domain.policy import Policy, Strategy

ROOT = Path(__file__).resolve().parent
BASELINE = ROOT / "baseline.json"
_WORD_TYPES = {EntityType.PERSONA.value, EntityType.ORGANIZACION.value, EntityType.UBICACION.value, EntityType.GLOSARIO.value}
_BLOCKING = {EntityType.TARJETA.value, EntityType.SECRETO.value}


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def leaked(label: Labeled, anonymized: str) -> bool:
    """¿Sigue visible el valor real? Para nombres basta con que quede una palabra significativa."""
    haystack = " ".join(fold(anonymized).split())
    if label.type in _WORD_TYPES:
        words = [w for w in fold(label.value).replace(".", " ").split() if len(w) >= 4 and w not in GENERIC_ORG_WORDS]
        return any(contains_value(haystack, w) for w in words)
    return contains_value(haystack, " ".join(fold(label.value).split()))


def _effective(entities: list[DetectedEntity], policy: Policy) -> list[DetectedEntity]:
    return [e for e in entities if e.score >= policy.min_score_for(e.type) and policy.strategy_for(e.type) != Strategy.ALLOW]


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1) + 0.5))]


def evaluate(samples: list[Sample], *, ner: bool = True) -> dict[str, Any]:
    settings = Settings(ner_enabled=ner, glossary_path=None, policy_path=Path("config/policy.yaml"))
    policy = load_policy(settings.policy_path)
    detector: DetectorPort = build_detector(settings, GLOSSARY_TERMS)
    rt = build_runtime(settings, detector=detector, audit=NullAuditAdapter(), policy=policy)

    per_type: dict[str, dict[str, int]] = {}
    per_scenario: dict[str, dict[str, int]] = {}
    failures: list[dict[str, str]] = []
    over: list[dict[str, str]] = []
    latencies: list[float] = []
    totals = {"labeled": 0, "leaked": 0, "detections": 0, "over_redacted": 0, "blocked": 0, "unexpected_blocks": 0}
    round_trip = {"eligible": 0, "ok": 0}

    def bump(table: dict[str, dict[str, int]], key: str, field: str, n: int = 1) -> None:
        table.setdefault(key, {}).setdefault(field, 0)
        table[key][field] += n

    for sample in samples:
        t0 = time.perf_counter()
        status, anonymized, replacements, session = "ok", None, (), None
        try:
            result = rt.anonymize.execute(sample.text)
            anonymized, replacements, session = result.text, result.replacements, result.session_id
        except BlockedByPolicy:
            status = "blocked"
        except PrivacyShieldError:
            status = "error"
        latencies.append((time.perf_counter() - t0) * 1000)

        labels_all = [(lab.start, lab.end) for lab in sample.entities]
        detections = _effective(detector.detect(sample.text), policy)
        for d in detections:
            totals["detections"] += 1
            bump(per_type, d.type.value, "detections")
            same_type = any(_overlap((d.start, d.end), (lab.start, lab.end)) > 0 for lab in sample.entities if lab.type == d.type.value)
            if not same_type:
                bump(per_type, d.type.value, "false_positives")
            if not any(_overlap((d.start, d.end), span) > 0 for span in labels_all):
                totals["over_redacted"] += 1
                over.append({"scenario": sample.scenario, "type": d.type.value, "text": d.text})

        if status == "blocked":
            totals["blocked"] += 1
            if not any(lab.type in _BLOCKING for lab in sample.entities):
                totals["unexpected_blocks"] += 1
                failures.append({"scenario": sample.scenario, "kind": sample.kind, "type": "-", "value": "", "reason": "bloqueo inesperado"})

        for label in sample.entities:
            totals["labeled"] += 1
            bump(per_type, label.type, "labeled")
            bump(per_scenario, sample.scenario, "labeled")
            covered = any(
                d.type.value == label.type and _overlap((d.start, d.end), (label.start, label.end)) * 2 >= (label.end - label.start)
                for d in detections
            )
            bump(per_type, label.type, "detected" if covered else "missed")
            is_leak = status != "blocked" and anonymized is not None and leaked(label, anonymized)
            if status == "error":
                is_leak = True  # sin resultado no se puede afirmar que no haya fuga (en producción se bloquea)
            if is_leak:
                totals["leaked"] += 1
                bump(per_type, label.type, "leaked")
                bump(per_scenario, sample.scenario, "leaked")
                failures.append({"scenario": sample.scenario, "kind": sample.kind, "type": label.type, "value": label.value, "reason": "fuga"})

        if status == "ok" and anonymized is not None and session is not None and replacements:
            if all(r.strategy == Strategy.PSEUDONYMIZE for r in replacements):
                round_trip["eligible"] += 1
                if rt.deanonymize.execute(session, anonymized) == sample.text:
                    round_trip["ok"] += 1

    labeled = totals["labeled"] or 1
    return {
        "date": date.today().isoformat(),
        "ner": ner,
        "samples": len(samples),
        "leak_rate": totals["leaked"] / labeled,
        "over_redaction_rate": totals["over_redacted"] / (totals["detections"] or 1),
        "round_trip_ok": round_trip["ok"] / (round_trip["eligible"] or 1),
        "latency_ms": {"p50": percentile(latencies, 0.5), "p95": percentile(latencies, 0.95)},
        "totals": totals,
        "round_trip": round_trip,
        "per_type": per_type,
        "per_scenario": per_scenario,
        "failures": failures[:60],
        "over_redactions": over[:30],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lat = report["latency_ms"]
    t = report["totals"]
    lines = [
        f"# Informe de evaluación — {report['date']}",
        "",
        f"- Muestras: {report['samples']} · NER: {'sí' if report['ner'] else 'no'}",
        f"- **Leak rate: {report['leak_rate']:.1%}** ({t['leaked']} de {t['labeled']} valores etiquetados siguen visibles)",
        f"- Sobre-redacción: {report['over_redaction_rate']:.1%} ({t['over_redacted']} de {t['detections']} detecciones)",
        f"- Ida y vuelta correcta: {report['round_trip_ok']:.1%} ({report['round_trip']['ok']}/{report['round_trip']['eligible']})",
        f"- Peticiones bloqueadas por política: {t['blocked']} (inesperadas: {t['unexpected_blocks']})",
        f"- Latencia de anonimización: p50 {lat['p50']:.0f} ms · p95 {lat['p95']:.0f} ms (objetivo < 150 ms en ~500 caracteres)",
        "",
        "## Por tipo",
        "",
        "| Tipo | Etiquetados | Detectados | Fallados | Fugas | Recall | Falsos positivos |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in sorted(report["per_type"].items()):
        labeled = row.get("labeled", 0)
        recall = f"{row.get('detected', 0) / labeled:.0%}" if labeled else "-"
        lines.append(
            f"| {name} | {labeled} | {row.get('detected', 0)} | {row.get('missed', 0)} | {row.get('leaked', 0)} | {recall} | {row.get('false_positives', 0)} |"
        )
    lines += ["", "## Por escenario", "", "| Escenario | Etiquetados | Fugas |", "|---|---:|---:|"]
    for name, row in sorted(report["per_scenario"].items()):
        lines.append(f"| {name} | {row.get('labeled', 0)} | {row.get('leaked', 0)} |")
    lines += ["", "## Fallos concretos (para ajustar glosario y reglas)", ""]
    lines += [f"- [{f['scenario']}/{f['kind']}] {f['reason']} {f['type']}: `{f['value']}`" for f in report["failures"]] or ["- ninguno"]
    lines += ["", "## Sobre-redacción (detecciones que no eran sensibles)", ""]
    lines += [f"- [{o['scenario']}] {o['type']}: `{o['text']}`" for o in report["over_redactions"]] or ["- ninguna"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval")
    parser.add_argument("--no-ner", action="store_true")
    parser.add_argument("--corpus", default=str(ROOT / "corpus"))
    parser.add_argument("--out", default=str(ROOT / "reports"))
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--per-scenario", type=int, default=10)
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args(argv)

    corpus_dir = Path(args.corpus)
    samples = load_corpus(corpus_dir) if corpus_dir.exists() and any(corpus_dir.glob("*.jsonl")) else None
    if samples is None:
        samples = CorpusGenerator(args.seed).generate(args.per_scenario)
        write_corpus(samples, corpus_dir)  # queda en eval/corpus (ignorado por git) para inspeccionarlo

    report = evaluate(samples, ner=not args.no_ner)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = f"{report['date']}{'-sin-ner' if args.no_ner else ''}"
    (out / f"{stamp}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = render_markdown(report)
    (out / f"{stamp}.md").write_text(markdown, encoding="utf-8")
    sys.stdout.write(markdown)
    if args.write_baseline:
        BASELINE.write_text(
            json.dumps({"leak_rate": report["leak_rate"], "ner": report["ner"], "samples": report["samples"]}, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
