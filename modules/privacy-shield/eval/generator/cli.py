"""`python -m eval.generator` o `privacy-shield gen-corpus`: genera transcripciones sintéticas con etiquetas."""

import argparse
import sys
from pathlib import Path

from eval.generator.generate import CorpusGenerator, write_corpus


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gen-corpus")
    parser.add_argument("--out", default="eval/corpus")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--per-scenario", type=int, default=10)
    args = parser.parse_args(argv)
    samples = CorpusGenerator(args.seed).generate(args.per_scenario)
    paths = write_corpus(samples, Path(args.out))
    sys.stdout.write(f"{len(samples)} muestras en {len(paths)} ficheros ({args.out})" + chr(10))
    return 0
