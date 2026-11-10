"""Páginas legales: aviso legal (LSSI), privacidad (RGPD), condiciones de contratación y cookies.

Los datos del titular se configuran con variables de entorno (en Railway) para no dejarlos en el código:
  UBI_TITULAR    nombre y apellidos o razón social
  UBI_NIF        NIF / CIF
  UBI_DIRECCION  domicilio a efectos de notificaciones
  UBI_EMAIL      correo de contacto (por defecto tuparcela360@gmail.com)
"""
import os
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app import config

router = APIRouter()
_env = Environment(loader=FileSystemLoader(Path(__file__).parent / "web" / "templates"), autoescape=select_autoescape(["html"]))

PAGINAS = {
    "aviso-legal": "Aviso legal",
    "privacidad": "Política de privacidad",
    "condiciones": "Condiciones de contratación",
    "cookies": "Política de cookies",
}
ACTUALIZADO = date(2026, 11, 6)


def titular() -> dict:
    pendiente = "[pendiente de completar]"
    return {
        "nombre": os.getenv("UBI_TITULAR", "").strip() or pendiente,
        "nif": os.getenv("UBI_NIF", "").strip() or pendiente,
        "direccion": os.getenv("UBI_DIRECCION", "").strip() or pendiente,
        "email": os.getenv("UBI_EMAIL", "").strip() or "tuparcela360@gmail.com",
        "web": "parcelas360.com",
    }


def _pintar(request: Request, pagina: str) -> HTMLResponse:
    if pagina not in PAGINAS:
        raise HTTPException(404)
    from app.rutas_cuenta import usuario_actual
    html = _env.get_template("legal.html").render(
        marca=config.MARCA, usuario=usuario_actual(request), titulo=PAGINAS[pagina], pagina=pagina, paginas=PAGINAS,
        t=titular(), actualizado=ACTUALIZADO.strftime("%d/%m/%Y"))
    return HTMLResponse(html)


@router.get("/aviso-legal", response_class=HTMLResponse)
async def aviso_legal(request: Request):
    return _pintar(request, "aviso-legal")


@router.get("/privacidad", response_class=HTMLResponse)
async def privacidad(request: Request):
    return _pintar(request, "privacidad")


@router.get("/condiciones", response_class=HTMLResponse)
async def condiciones(request: Request):
    return _pintar(request, "condiciones")


@router.get("/cookies", response_class=HTMLResponse)
async def cookies(request: Request):
    return _pintar(request, "cookies")
