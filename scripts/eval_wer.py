"""Mide el error real (WER) de tu configuración: compara una transcripción con tu corrección manual.

    python scripts/eval_wer.py referencia.txt hipotesis.txt

referencia.txt = texto corregido a mano; hipotesis.txt = salida cruda (p. ej. GET /transcript?format=json → texto).
Requiere: pip install jiwer
"""
import re
import sys
import unicodedata

import jiwer


def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t)).strip()


ref, hyp = (norm(open(p, encoding="utf-8").read()) for p in sys.argv[1:3])
out = jiwer.process_words(ref, hyp)
print(f"WER: {out.wer:.1%} | sustituciones={out.substitutions} borrados={out.deletions} inserciones={out.insertions}")
