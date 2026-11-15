"""Adaptador de entrada por línea de comandos: `privacy-shield anonymize "texto"`, `eval`, `gen-corpus`."""

import argparse
import sys

from privacy_shield.application.runtime import Runtime
from privacy_shield.domain.session import SessionId


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="privacy-shield", description="Ofuscación de datos personales")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("anonymize", help="Pseudonimiza un texto (o stdin con '-')")
    p.add_argument("text")
    p.add_argument("--session", default=None, help="Reutiliza una sesión (mismo valor = mismo token)")

    p = sub.add_parser("deanonymize", help="Revierte los tokens de una sesión (solo vale en el mismo proceso)")
    p.add_argument("session")
    p.add_argument("text")

    p = sub.add_parser("eval", help="Evalúa fugas y sobre-redacción sobre un corpus sintético")
    p.add_argument("--no-ner", action="store_true", help="Sin spaCy (más rápido, menos recall)")
    p.add_argument("--corpus", default="eval/corpus")
    p.add_argument("--out", default="eval/reports")
    p.add_argument("--seed", type=int, default=7)

    p = sub.add_parser("gen-corpus", help="Genera transcripciones sintéticas con etiquetas")
    p.add_argument("--out", default="eval/corpus")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--per-scenario", type=int, default=10)
    return parser


def run_anonymize(rt: Runtime, text: str, session: str | None) -> int:
    source = sys.stdin.read() if text == "-" else text
    result = rt.anonymize.execute(source, SessionId(session) if session else None)
    sys.stdout.write(result.text + "\n")
    counts: dict[str, int] = {}
    for r in result.replacements:
        counts[r.type.value] = counts.get(r.type.value, 0) + 1
    sys.stderr.write(f"session_id={result.session_id} entidades={counts}\n")  # recuentos, nunca valores
    return 0


def run_deanonymize(rt: Runtime, session: str, text: str) -> int:
    sys.stdout.write(rt.deanonymize.execute(SessionId(session), text) + "\n")
    return 0
