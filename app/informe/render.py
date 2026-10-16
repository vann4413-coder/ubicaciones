"""Convierte el informe en HTML y PDF."""
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.analisis.compatibilidad import PERFILES
from app.informe import mapas

PLANTILLAS = Path(__file__).parent / "templates"

NIVELES = {"compatible": "Compatible", "condicionado": "Condicionado", "plan_especial": "Solo con plan especial",
           "incompatible": "Incompatible", "sin_dato": "Sin dato"}
BLOQUES = {"urbanismo": "Urbanismo", "trafico": "Tráfico", "red": "Red eléctrica", "parcela": "Parcela",
           "inundabilidad": "Inundabilidad"}
ESTADOS = {"ok": "Correcto", "sin_dato": "Sin dato", "error": "No disponible", "no_aplica": "No aplica"}


def num(v, dec: int = 0) -> str:
    """Formato español: 12.345,6"""
    if v is None or v == "":
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    s = f"{v:,.{dec}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def fecha(v) -> str:
    if not v:
        return "—"
    s = str(v)[:10]
    try:
        return date.fromisoformat(s).strftime("%d/%m/%Y")
    except ValueError:
        return str(v)


_env = Environment(loader=FileSystemLoader(PLANTILLAS), autoescape=select_autoescape(["html"]))
_env.filters.update(num=num, fecha=fecha, bloque=lambda b: BLOQUES.get(b, b))


def html(inf: dict) -> str:
    return _env.get_template("informe.html").render(
        inf=inf, mapas=mapas.construir(inf), perfiles=PERFILES, niveles=NIVELES, bloques=BLOQUES, estados=ESTADOS,
    )


def pdf(inf: dict) -> bytes:
    from weasyprint import HTML
    return HTML(string=html(inf)).write_pdf()
