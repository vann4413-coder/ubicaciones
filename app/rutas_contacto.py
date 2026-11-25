"""Página de contacto: el visitante deja sus datos y su consulta; se guarda y se reenvía al buzón de Parcelas 360."""
import re

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app import correo, cuentas
from app.rutas_cuenta import _pintar, usuario_actual

router = APIRouter()
INTERESES = ["Informe de una parcela", "Analizar una lista de ubicaciones", "Plan Equipo o condiciones para empresa",
             "Colaboración o partnership", "Otra consulta"]

cuentas.ESQUEMA += """
CREATE TABLE IF NOT EXISTS contactos (
  id INTEGER PRIMARY KEY, fecha TEXT NOT NULL, nombre TEXT, email TEXT, empresa TEXT, telefono TEXT, interes TEXT,
  mensaje TEXT, enviado INTEGER DEFAULT 0
);
"""


def _guardar(d: dict) -> int:
    con = cuentas.db()
    con.executescript(cuentas.ESQUEMA)
    with cuentas._lock:
        cur = con.execute("INSERT INTO contactos (fecha, nombre, email, empresa, telefono, interes, mensaje) VALUES (?, ?, ?, ?, ?, ?, ?)",
                          (cuentas._ahora(), d["nombre"], d["email"], d["empresa"], d["telefono"], d["interes"], d["mensaje"]))
        con.commit()
    return cur.lastrowid


@router.get("/contacto")
async def contacto(request: Request, ok: int = 0, error: str = "", interes: str = ""):
    return _pintar("contacto.html", request, titulo="Contacto", ok=ok, error=error, intereses=INTERESES,
                   interes=interes if interes in INTERESES else "",
                   descripcion="Contacta con Parcelas 360: informes de parcelas, análisis de listas de ubicaciones y planes para empresas.")


@router.post("/contacto")
async def enviar(request: Request, nombre: str = Form(""), email: str = Form(""), empresa: str = Form(""), telefono: str = Form(""),
                 interes: str = Form(""), mensaje: str = Form(""), acepto: str = Form(""), web: str = Form("")):
    from urllib.parse import quote
    if web:  # campo trampa para robots
        return RedirectResponse("/contacto?ok=1", status_code=303)
    d = {"nombre": nombre.strip()[:120], "email": email.strip()[:160], "empresa": empresa.strip()[:160],
         "telefono": telefono.strip()[:40], "interes": interes if interes in INTERESES else "Otra consulta", "mensaje": mensaje.strip()[:4000]}
    if not d["nombre"] or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", d["email"]) or len(d["mensaje"]) < 5:
        return RedirectResponse("/contacto?error=" + quote("Rellena tu nombre, un correo válido y el mensaje."), status_code=303)
    if not acepto:
        return RedirectResponse("/contacto?error=" + quote("Acepta la política de privacidad para poder responderte."), status_code=303)
    id_ = _guardar(d)
    if await correo.enviar_contacto(d):
        with cuentas._lock:
            cuentas.db().execute("UPDATE contactos SET enviado = 1 WHERE id = ?", (id_,))
            cuentas.db().commit()
    return RedirectResponse("/contacto?ok=1", status_code=303)


@router.get("/admin/contactos")
async def admin_contactos(request: Request):
    if not cuentas.es_admin(usuario_actual(request)):
        raise HTTPException(403, "Solo administradores")
    con = cuentas.db()
    con.executescript(cuentas.ESQUEMA)
    filas = [dict(f) for f in con.execute("SELECT * FROM contactos ORDER BY id DESC LIMIT 300")]
    return _pintar("contactos_admin.html", request, titulo="Contactos recibidos", filas=filas)
