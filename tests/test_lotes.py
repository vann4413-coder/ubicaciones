from fastapi.testclient import TestClient


def test_pagina_lotes_admin(monkeypatch, tmp_path):
    import app.cuentas as cuentas
    import app.lote as lote
    import app.main as main
    import app.rutas_cuenta as rc
    monkeypatch.setattr(lote, "DIR", tmp_path)
    monkeypatch.setattr(rc, "usuario_actual", lambda r: {"email": "a@a", "id": 1})
    monkeypatch.setattr(cuentas, "es_admin", lambda u: True)
    r = TestClient(main.app).get("/admin/lotes")
    assert r.status_code == 200 and "Verificación de suelo por lotes" in r.text
