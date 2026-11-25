from fastapi.testclient import TestClient


def _cliente(monkeypatch, permitido=True, clave="k"):
    import app.agente as agente
    import app.main as main
    monkeypatch.setattr(agente.config, "ANTHROPIC_API_KEY", clave)
    monkeypatch.setattr(main, "acceso", lambda r, rc, registrar=True: (permitido, "pago"))

    async def falso_informe(*a, **k):
        return {"rc": "x"}

    async def falso_preguntar(inf, pregunta, historial=None):
        return f"Respuesta a: {pregunta} ({len(historial or [])})"
    monkeypatch.setattr(main, "_informe", falso_informe)
    monkeypatch.setattr(agente, "preguntar", falso_preguntar)
    agente._uso.clear()
    return TestClient(main.app)


def test_pregunta_ok(monkeypatch):
    c = _cliente(monkeypatch)
    r = c.post("/api/pregunta/4595201DF5949N", json={"pregunta": "¿Puedo poner una gasolinera?", "historial": [{"rol": "usuario", "texto": "hola"}]})
    assert r.status_code == 200 and "gasolinera" in r.json()["respuesta"] and r.json()["quedan"] == 24


def test_pregunta_sin_acceso(monkeypatch):
    c = _cliente(monkeypatch, permitido=False)
    assert c.post("/api/pregunta/4595201DF5949N", json={"pregunta": "hola hola"}).status_code == 403


def test_pregunta_sin_clave(monkeypatch):
    c = _cliente(monkeypatch, clave="")
    assert c.post("/api/pregunta/4595201DF5949N", json={"pregunta": "hola hola"}).status_code == 503


def test_cupo(monkeypatch):
    import app.agente as agente
    c = _cliente(monkeypatch)
    monkeypatch.setattr(agente, "LIMITE_DIA", 2)
    for _ in range(2):
        assert c.post("/api/pregunta/4595201DF5949N", json={"pregunta": "pregunta"}).status_code == 200
    assert c.post("/api/pregunta/4595201DF5949N", json={"pregunta": "pregunta"}).status_code == 429


def test_contexto_sin_titulares(fuentes_simuladas):
    import asyncio
    import json
    from app import agente
    from app.informe import generar
    inf = asyncio.run(generar.construir("4595201DF5949N"))
    t = agente._texto_contexto(inf)
    d = json.loads(t)
    assert "titulares" not in d and d["parcela"]["rc"] and len(t) <= agente.MAX_CONTEXTO
