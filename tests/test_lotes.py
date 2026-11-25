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


def _excel(tmp_path, filas, cab=("NOMBRE", "DIRECCIÓN", "MUNICIPIO")):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(list(cab))
    for f in filas:
        ws.append(list(f))
    ruta = tmp_path / "e.xlsx"
    wb.save(ruta)
    return ruta


def test_leer_direcciones(tmp_path):
    import app.lote as lote
    ruta = _excel(tmp_path, [("A", "Carrer Major 1", "Tàrrega"), ("B", "Av. Catalunya 3, Vic", "Vic"), ("C", None, None)])
    hoja, fila, ubic = lote.leer_ubicaciones(ruta)
    assert [u["dir"] for u in ubic] == ["Carrer Major 1, Tàrrega", "Av. Catalunya 3, Vic"]


def test_usos_en_fila():
    import app.lote as lote
    r = {"rc": "X", "sup_parcela": 2000, "urbanismo": {"compatibilidad": {}},
         "pgou": {"zonas": [{"zona": {"usos": "Industrial y logístico. Comercial. No se admite el uso residencial."}, "pct": 100,
                             "clave_parcela": "22a"}]}, "aca": {}}
    vals, _ = lote.fila_resultado(r)
    usos = vals[lote.CAB.index("USOS ADMITIDOS EN LA ZONA (orientativo)")]
    assert usos.startswith("Sí:") and "No:" in usos
    assert len(vals) == len(lote.CAB) == len(lote.ANCHO)


def test_agente_lista_cliente(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import app.cuentas as cuentas
    import app.lote as lote
    import app.main as main
    import app.pagos as pagos
    import app.rutas_agente as ra
    monkeypatch.setattr(lote, "DIR", tmp_path / "lotes")
    monkeypatch.setattr(lote, "lanzar", lambda id_: None)
    monkeypatch.setattr(pagos, "activos", lambda: True)
    usuario = {"id": 7, "email": "c@c.es", "plan": None, "plan_estado": None}
    monkeypatch.setattr(ra, "usuario_actual", lambda r: usuario)
    import app.rutas_cuenta as rc
    monkeypatch.setattr(rc, "usuario_actual", lambda r: usuario)
    cli = TestClient(main.app)
    assert "Analiza tu lista" in cli.get("/agente/lista").text
    ruta = _excel(tmp_path, [(str(i), f"Carrer Major {i}", "Vic") for i in range(1, 9)])
    r = cli.post("/agente/lista", files={"fichero": ("mi.xlsx", ruta.read_bytes())}, follow_redirects=False)
    assert r.status_code == 303 and "te%20quedan%203" in r.headers["location"]
    mios = lote.lista(7)
    assert len(mios) == 1 and mios[0]["modo"] == "pendiente" and mios[0]["total"] == 8
    assert cuentas.cupo_lista(usuario)["quedan"] == 3  # una lista pendiente no consume la prueba
    pag = cli.get("/agente/lista").text
    assert "Pagar 99 €" in pag and "primeras 3" in pag
    r = cli.post(f"/agente/lista/{mios[0]['id']}/incluidas", follow_redirects=False)
    assert "primeras%203" in r.headers["location"]
    mios = lote.lista(7)
    assert mios[0]["modo"] == "incluida" and mios[0]["total"] == 3
    assert cuentas.cupo_lista(usuario)["quedan"] == 0
    # una lista pagada no consume cupo
    pequeña = _excel(tmp_path, [("1", "Carrer Major 1", "Vic")])
    r = cli.post("/agente/lista", files={"fichero": ("b.xlsx", pequeña.read_bytes())}, follow_redirects=False)
    pend = [l for l in lote.lista(7) if l["modo"] == "pendiente"][0]
    assert lote.activar(pend["id"], pagada=True) and lote.lista_por_id(pend["id"])["modo"] == "pagada"
    assert cuentas.cupo_lista(usuario)["quedan"] == 0 and not lote.activar(pend["id"], pagada=True)
    # otro usuario no ve ni descarga la lista
    otro = {"id": 8, "email": "o@o.es"}
    monkeypatch.setattr(ra, "usuario_actual", lambda r: otro)
    monkeypatch.setattr(cuentas, "es_admin", lambda u: False)
    assert cli.get(f"/agente/lista/{mios[0]['id']}.xlsx?parcial=1").status_code == 404
    assert cli.get("/agente/plantilla.xlsx").status_code == 200


def test_cupo_plan(monkeypatch, tmp_path):
    import app.cuentas as cuentas
    import app.lote as lote
    import app.pagos as pagos
    monkeypatch.setattr(lote, "DIR", tmp_path)
    monkeypatch.setattr(pagos, "activos", lambda: True)
    u = {"id": 3, "email": "p@p.es", "plan": "empresa", "plan_estado": "active"}
    c = cuentas.cupo_lista(u)
    assert c["tipo"] == "plan" and c["quedan"] == cuentas.LIMITES_LISTA["empresa"]


def test_precio_lista():
    from app import pagos
    assert pagos.precio_lista(40) == 9900 and pagos.precio_lista(100) == 9900 and pagos.precio_lista(439) == 9900 + 80 * 339
    assert pagos.euros(9900) == "99 €" and pagos.euros(37020) == "370,20 €"
