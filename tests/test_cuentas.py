"""Cuentas, acceso al informe completo y límites de los planes (sin llamar a Stripe)."""
import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    from app import cuentas, pagos
    monkeypatch.setattr(cuentas, "RUTA_DB", tmp_path / "t.db")
    monkeypatch.setattr(cuentas, "_con", None)
    monkeypatch.setattr(cuentas, "ADMIN", {"admin@ejemplo.com"})
    monkeypatch.setattr(pagos, "CLAVE", "sk_test_x")  # pagos activados, sin red
    from app.main import app
    return TestClient(app)


def test_registro_entrar_y_cuenta(cliente):
    r = cliente.post("/cuenta/registro", data={"email": "Ana@Ejemplo.com", "clave": "12345678"}, follow_redirects=False)
    assert r.status_code == 303 and "ubi_sesion" in r.cookies
    assert "ana@ejemplo.com" in cliente.get("/cuenta").text
    cliente.post("/cuenta/salir")
    cliente.cookies.clear()
    r = cliente.post("/cuenta/entrar", data={"email": "ana@ejemplo.com", "clave": "mala"})
    assert "incorrectos" in r.text
    r = cliente.post("/cuenta/registro", data={"email": "ana@ejemplo.com", "clave": "12345678"})
    assert "Ya existe" in r.text


def test_sin_pago_redirige_a_compra(cliente):
    r = cliente.get("/informe/4595201DF5949N", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/comprar/4595201DF5949N"
    r = cliente.get("/informe/4595201DF5949N.pdf", follow_redirects=False)
    assert r.headers["location"] == "/comprar/4595201DF5949N"
    assert "1,99 €" in cliente.get("/comprar/4595201DF5949N").text


def test_compra_y_plan_dan_acceso():
    from starlette.requests import Request
    from app import cuentas
    from app.rutas_cuenta import acceso

    def req(query="", cookies=None):
        cab = [(b"cookie", "; ".join(f"{k}={v}" for k, v in (cookies or {}).items()).encode())] if cookies else []
        return Request({"type": "http", "query_string": query.encode(), "headers": cab, "path": "/", "scheme": "https"})

    token = cuentas.guardar_compra("cs_1", "RC1", "x@y.es", 241, None)
    assert acceso(req(f"acceso={token}"), "RC1")[0] is True
    assert acceso(req("acceso=falso"), "RC1") == (False, "pago")
    assert acceso(req(f"acceso={token}"), "RC2")[0] is False  # el token solo vale para su parcela

    u = cuentas.registrar("pro@ejemplo.com", "12345678")
    cuentas.actualizar_plan(u["id"], plan="profesional", plan_estado="active")
    sesion = {"ubi_sesion": cuentas.cookie_sesion(u["id"])}
    for i in range(cuentas.LIMITES["profesional"]):
        assert acceso(req(cookies=sesion), f"P{i}")[0] is True
    assert acceso(req(cookies=sesion), "P0")[0] is True          # repetir una ya vista no gasta
    assert acceso(req(cookies=sesion), "NUEVA") == (False, "limite")
    adm = cuentas.registrar("admin@ejemplo.com", "12345678")
    assert acceso(req(cookies={"ubi_sesion": cuentas.cookie_sesion(adm["id"])}), "NUEVA")[0] is True


test_compra_y_plan_dan_acceso = pytest.mark.usefixtures("cliente")(test_compra_y_plan_dan_acceso)


def test_paginas_legales(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    monkeypatch.setenv("UBI_NIF", "00000000T")
    c = TestClient(app)
    for ruta, texto in [("/aviso-legal", "00000000T"), ("/privacidad", "Agencia Española de Protección de Datos"),
                        ("/condiciones", "desistimiento"), ("/cookies", "ubi_sesion")]:
        r = c.get(ruta)
        assert r.status_code == 200 and texto in r.text


def test_correo_informe(monkeypatch):
    from app import correo, cuentas
    monkeypatch.setenv("UBI_SMTP_USUARIO", "tuparcela360@gmail.com")
    monkeypatch.setenv("UBI_SMTP_CLAVE", "abcd efgh ijkl mnop")
    assert correo.activo()
    m = correo.mensaje_informe("cliente@example.com", "3180004DF5938S", "https://x/informe/R?acceso=T", "https://x/informe/R.pdf?acceso=T")
    assert "Descargar el PDF" in m.get_body(("html",)).get_content() and m["To"] == "cliente@example.com"
    import uuid
    sid = f"cs_test_{uuid.uuid4().hex}"
    assert cuentas.reservar_correo(sid) is True
    assert cuentas.reservar_correo(sid) is False


def test_correo_por_resend(monkeypatch):
    import asyncio

    import httpx
    import respx

    from app import correo
    monkeypatch.setenv("UBI_RESEND_CLAVE", "re_prueba")
    with respx.mock() as m:
        ruta = m.post("https://api.resend.com/emails").respond(json={"id": "1"})
        ok = asyncio.run(correo.enviar_informe("cliente@example.com", "3180004DF5938S", "https://x/i", "https://x/p"))
        assert ok and ruta.called
        cuerpo = ruta.calls[0].request.content.decode()
        assert "informes@parcelas360.com" in cuerpo and "tuparcela360@gmail.com" in cuerpo


def test_robots_y_sitemap():
    from fastapi.testclient import TestClient

    from app.main import app
    c = TestClient(app)
    assert "Sitemap: https://parcelas360.com/sitemap.xml" in c.get("/robots.txt").text
    assert "https://parcelas360.com/app" in c.get("/sitemap.xml").text
