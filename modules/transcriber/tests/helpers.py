"""Utilidades compartidas por los tests de integración."""

from transcriber.application.pipeline import run_once
from transcriber.bootstrap import get_runtime


def upload(client, mid, seq, text, offset=0.0, source="system"):
    """Sube un 'audio' de texto: el FakeTranscriber devuelve una frase por línea ('?' = baja confianza)."""
    return client.post(
        f"/meetings/{mid}/chunks",
        files={"file": ("c.txt", text.encode(), "text/plain")},
        data={"seq": seq, "offset_seconds": offset, "source": source},
    )


def drain():
    """Ejecuta el worker hasta que no quede trabajo."""
    rt = get_runtime()
    with rt.session() as s:
        while run_once(s, rt):
            pass


def new_meeting(client, title="", project="") -> int:
    return client.post("/meetings", json={"title": title, "project": project}).json()["id"]
