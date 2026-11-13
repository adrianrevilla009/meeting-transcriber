from app.db import session_factory
from app.services.analyzer import FakeAnalyzer, Item
from app.workers.worker import run_once


def upload(client, mid, seq, text, offset=0.0):
    return client.post(
        f"/meetings/{mid}/chunks",
        files={"file": ("c.txt", text.encode(), "text/plain")},
        data={"seq": seq, "offset_seconds": offset, "source": "system"},
    )


def drain():
    with session_factory()() as s:
        while run_once(s):
            pass


def test_auth_required(env):
    from fastapi.testclient import TestClient

    from app.api.main import app

    with TestClient(app) as c:
        assert c.get("/meetings").status_code == 401
        assert c.get("/health").status_code == 200


def test_full_flow_with_verified_citations_and_history(client, env):
    # Reunión 1: requisito nuevo
    m1 = client.post("/meetings", json={"title": "Kickoff", "project": "pagos"}).json()["id"]
    upload(client, m1, 0, "El cliente quiere que el pago se haga solo con tarjeta.")
    FakeAnalyzer.script = [Item(kind="new_requirement", requirement="Método de pago",
                                summary="Solo tarjeta", quote="el pago se haga solo con tarjeta")]
    assert client.post(f"/meetings/{m1}/finish").status_code == 200
    drain()

    # Reunión 2: cambio + una cita inventada que debe rechazarse
    m2 = client.post("/meetings", json={"title": "Revisión", "project": "pagos"}).json()["id"]
    upload(client, m2, 0, "Ahora también aceptamos Bizum para el pago.\n?esto se oyó muy mal")
    FakeAnalyzer.script = [
        Item(kind="changed_requirement", requirement="Método de pago", summary="Se añade Bizum",
             quote="también aceptamos Bizum para el pago"),
        Item(kind="decision", requirement="Método de pago", summary="Alucinación",
             quote="esta frase nunca se dijo en la reunión"),
    ]
    client.post(f"/meetings/{m2}/finish")
    drain()

    assert client.get(f"/meetings/{m1}").json()["status"] == "done"
    events2 = client.get(f"/meetings/{m2}/events").json()
    assert len(events2) == 1  # la cita inventada se rechazó
    assert events2[0]["kind"] == "changed_requirement"

    reqs = client.get("/requirements", params={"project": "pagos"}).json()
    assert len(reqs) == 1  # ambas reuniones unidas al mismo requisito
    hist = client.get(f"/requirements/{reqs[0]['id']}/history").json()
    assert [e["meeting_id"] for e in hist["events"]] == [m1, m2]

    md = client.get(f"/meetings/{m2}/transcript").text
    assert "[?]" in md and "Bizum" in md
    assert (env / "exports" / f"meeting_{m2}.md").exists()

    hits = client.get("/search", params={"q": "bizum"}).json()
    assert hits and hits[0]["meeting_id"] == m2


def test_audio_deleted_after_transcription(client, env):
    mid = client.post("/meetings", json={}).json()["id"]
    upload(client, mid, 0, "hola a todos")
    audio_dir = env / "audio"
    assert any(audio_dir.rglob("*.txt"))
    client.post(f"/meetings/{mid}/finish")
    drain()
    assert not any(audio_dir.rglob("*.txt"))  # retención 0: borrado inmediato


def test_chunk_rejected_after_finish_and_delete(client, env):
    mid = client.post("/meetings", json={}).json()["id"]
    client.post(f"/meetings/{mid}/finish")
    assert upload(client, mid, 0, "tarde").status_code == 409
    assert client.delete(f"/meetings/{mid}").status_code == 204
    assert client.get(f"/meetings/{mid}").status_code == 404


def test_offsets_are_applied(client, env):
    mid = client.post("/meetings", json={}).json()["id"]
    upload(client, mid, 1, "segundo trozo", offset=60.0)
    client.post(f"/meetings/{mid}/finish")
    drain()
    segs = client.get(f"/meetings/{mid}/transcript", params={"format": "json"}).json()
    assert segs[0]["start"] == 60.0


def test_progress_and_system(client, env):
    mid = client.post("/meetings", json={"title": "P", "project": "x"}).json()["id"]
    upload(client, mid, 0, "hola\nadios")
    upload(client, mid, 1, "otra cosa", offset=45.0)
    p = client.get(f"/meetings/{mid}/progress").json()
    assert p["chunks_total"] == 2 and p["chunks_pending"] == 2 and p["segments"] == 0
    assert client.get("/system").json()["queue"] == 2

    FakeAnalyzer.script = []
    client.post(f"/meetings/{mid}/finish")
    drain()
    p = client.get(f"/meetings/{mid}/progress").json()
    assert p["chunks_done"] == 2 and p["segments"] == 3
    info = client.get("/system").json()
    assert info["queue"] == 0 and info["analyzer"] == "fake"
