"""Punto de entrada de la CLI: `privacy-shield ...` (ver pyproject [project.scripts])."""

import importlib
import sys

from privacy_shield.adapters.inbound.cli import build_parser, run_anonymize, run_deanonymize
from privacy_shield.bootstrap import build_runtime
from privacy_shield.config import get_settings


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in {"eval", "gen-corpus"}:
        # El evaluador vive en eval/ (fuera del paquete): se ejecuta desde la raíz del módulo.
        module = "eval.run_eval" if args.command == "eval" else "eval.generator.cli"
        sys.path.insert(0, ".")
        return int(importlib.import_module(module).main(sys.argv[2:]))
    settings = get_settings()
    rt = build_runtime(settings)
    if args.command == "anonymize":
        return run_anonymize(rt, args.text, args.session)
    return run_deanonymize(rt, args.session, args.text)


if __name__ == "__main__":
    raise SystemExit(main())
