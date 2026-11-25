from fastapi.testclient import TestClient


def test_contacto(monkeypatch, tmp_path):
    import app.cuentas as cuentas
    import app.correo as correo
    import app.main as main
    import sqlite3
    monkeypatch.setattr(cuentas, "_con", sqlite3.connect(str(tmp_path / "t.db"), check_same_thread=False))
    cuentas._con.row_factory = sqlite3.Row
    cuentas._con.executescript(cuentas.ESQUEMA)
    enviados = []

    async def falso(d):
        enviados.append(d)
        return True
    monkeypatch.setattr(correo, "enviar_contacto", falso)
    c = TestClient(main.app)
    assert "Contacto" in c.get("/contacto").text
    r = c.post("/contacto", data={"nombre": "Ana", "email": "ana@ejemplo.com", "mensaje": "Quiero el plan Equipo", "acepto": "1"},
               follow_redirects=False)
    assert r.headers["location"] == "/contacto?ok=1" and enviados[0]["nombre"] == "Ana"
    fila = cuentas._con.execute("SELECT * FROM contactos").fetchone()
    assert fila["email"] == "ana@ejemplo.com" and fila["enviado"] == 1
    r = c.post("/contacto", data={"nombre": "Ana", "email": "mal", "mensaje": "hola hola", "acepto": "1"}, follow_redirects=False)
    assert "error" in r.headers["location"]
    r = c.post("/contacto", data={"nombre": "X", "email": "x@x.es", "mensaje": "spam spam", "acepto": "1", "web": "http://spam"}, follow_redirects=False)
    assert len(enviados) == 1
