from tests.helpers import drain, upload
from transcriber.adapters.outbound.analysis.fake import FakeAnalyzer


def test_auth_required(env):
    from fastapi.testclient import TestClient

    from transcriber.bootstrap.api import app

    with TestClient(app) as c:
        assert c.get("/meetings").status_code == 401
        assert c.get("/health").status_code == 200


def test_full_flow_generates_summary_and_exports_it(client, env):
    m1 = client.post("/meetings", json={"title": "Kickoff", "project": "pagos"}).json()["id"]
    upload(client, m1, 0, "El cliente quiere que el pago se haga solo con tarjeta.")
    FakeAnalyzer.script = "El cliente quiere pagos solo con tarjeta."
    assert client.post(f"/meetings/{m1}/finish").status_code == 200
    drain()

    m2 = client.post("/meetings", json={"title": "Revisión", "project": "pagos"}).json()["id"]
    upload(client, m2, 0, "Ahora también aceptamos Bizum para el pago.\n?esto se oyó muy mal")
    FakeAnalyzer.script = "Se añade Bizum como método de pago."
    client.post(f"/meetings/{m2}/finish")
    drain()

    one, two = (client.get(f"/meetings/{m}").json() for m in (m1, m2))
    assert one["status"] == two["status"] == "done"
    assert one["summary"] == "El cliente quiere pagos solo con tarjeta."
    assert two["summary"] == "Se añade Bizum como método de pago."

    md = client.get(f"/meetings/{m2}/transcript").text
    assert "[?]" in md and "Bizum" in md and "## Resumen" in md
    exported = (env / "exports" / f"meeting_{m2}.md").read_text(encoding="utf-8")
    assert "Se añade Bizum como método de pago." in exported

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

    FakeAnalyzer.script = ""
    client.post(f"/meetings/{mid}/finish")
    drain()
    p = client.get(f"/meetings/{mid}/progress").json()
    assert p["chunks_done"] == 2 and p["segments"] == 3
    info = client.get("/system").json()
    assert info["queue"] == 0 and info["analyzer"] == "fake"
