"""Páginas públicas de normativa urbanística por municipio y zona (para que Google las encuentre).

Se generan solas a partir de app/data/pgou/*.json: un índice, una página por municipio y una por zona,
cada una con la consulta gratuita de la parcela. Cada municipio nuevo que se carga añade sus páginas.
"""
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

DATOS = Path(__file__).parent / "data" / "pgou"
BASE_URL = "https://parcelas360.com"
router = APIRouter()

# Municipios del Pla General Metropolità (comparten normativa: pgm.json)
NOMBRES_PGM = {
    "08015": "Badalona", "08019": "Barcelona", "08020": "Begues", "08054": "Castellbisbal", "08056": "Castelldefels",
    "08068": "Cervelló", "08072": "Corbera de Llobregat", "08073": "Cornellà de Llobregat", "08077": "Esplugues de Llobregat",
    "08089": "Gavà", "08101": "L'Hospitalet de Llobregat", "08123": "Molins de Rei", "08125": "Montcada i Reixac",
    "08126": "Montgat", "08157": "Pallejà", "08158": "El Papiol", "08169": "El Prat de Llobregat", "08180": "Ripollet",
    "08194": "Sant Adrià de Besòs", "08196": "Sant Andreu de la Barca", "08200": "Sant Boi de Llobregat",
    "08204": "Sant Climent de Llobregat", "08205": "Sant Cugat del Vallès", "08211": "Sant Feliu de Llobregat",
    "08217": "Sant Joan Despí", "08221": "Sant Just Desvern", "08244": "Santa Coloma de Cervelló",
    "08245": "Santa Coloma de Gramenet", "08263": "Sant Vicenç dels Horts", "08266": "Cerdanyola del Vallès",
    "08282": "Tiana", "08289": "Torrelles de Llobregat", "08301": "Viladecans", "08904": "Badia del Vallès",
}
USOS = [  # (etiqueta, patrón en el texto de usos de la zona; castellano o catalán)
    ("Vivienda", r"vivienda|habitatge|residencial|unifamiliar|plurifamiliar"),
    ("Industria y naves", r"industri"),
    ("Almacén y logística", r"almac[eé]n|magatzem|log[ií]stic"),
    ("Comercio y tiendas", r"comerc"),
    ("Oficinas y despachos", r"oficin|despatx|despacho"),
    ("Hotel y alojamiento", r"hotel|hoteler|allotjament"),
    ("Restauración (bar, restaurante)", r"restaura|\bbar\b"),
    ("Talleres de vehículos", r"taller"),
    ("Gasolinera / estación de servicio", r"estaci[oó]n(es)? de servicio|gasolinera|benziner|estaci[oó] de servei|carburant"),
    ("Aparcamiento", r"aparcamiento|aparcament|estacionament|garaje|garatge"),
    ("Equipamientos (sanitario, educativo, deportivo…)", r"equipament|equipamiento|sanitari|educati|esportiu|deportiv|dotaci"),
    ("Recreativo y ocio", r"recreati|ocio|lleure|l[uú]dic|espect[aá]cul"),
]
NEGACION = re.compile(r"^(no|nunca|prohib|excepto|salvo)\b|\bno se admite|\bno s.admet|\bno se permite|\bno es permet|\bprohib", re.I)


def slug(t: str) -> str:
    t = "".join(c for c in unicodedata.normalize("NFD", t or "") if unicodedata.category(c) != "Mn").lower()
    t = t.replace("·", "").replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


@lru_cache(maxsize=1)
def municipios() -> dict:
    """slug de municipio -> {nombre, ine, plan, documento, zonas: {slug_zona: {clave, ...}}}"""
    salida = {}
    alias = json.loads((DATOS / "alias.json").read_text(encoding="utf-8")) if (DATOS / "alias.json").exists() else {}
    ficheros = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in DATOS.glob("*.json") if f.stem != "alias"}

    def zonas_de(d):
        zs, vistos = {}, set()
        for clave, z in (d.get("zonas") or {}).items():
            if not isinstance(z, dict) or id(z) in vistos:
                continue
            firma = json.dumps(z, sort_keys=True, ensure_ascii=False)
            if firma in vistos:
                continue
            vistos.add(firma)
            zs["zona-" + slug(clave)] = {"clave": clave.upper() if clave[:1].isalpha() else clave, **z}
        return zs

    for ine, d in ficheros.items():
        if ine == "pgm" or not d.get("municipio"):
            continue
        salida[slug(d["municipio"])] = {"nombre": d["municipio"], "ine": ine, "plan": d.get("plan", ""),
                                        "documento": d.get("documento", ""), "zonas": zonas_de(d)}
    pgm = ficheros.get("pgm")
    if pgm:
        zs = zonas_de(pgm)
        for ine, base in alias.items():
            if base == "pgm" and ine in NOMBRES_PGM:
                salida[slug(NOMBRES_PGM[ine])] = {"nombre": NOMBRES_PGM[ine], "ine": ine, "plan": pgm.get("plan", ""),
                                                  "documento": pgm.get("documento", ""), "zonas": zs, "pgm": True}
    return dict(sorted(salida.items(), key=lambda kv: slug(kv[1]["nombre"]).replace("l-", "").replace("el-", "")))


def que_se_puede(z: dict) -> tuple[list[str], list[str]]:
    """Usos que el texto de la zona admite y los que excluye expresamente (lectura orientativa del resumen)."""
    texto = " ".join(str(z.get(k) or "") for k in ("usos", "otros"))
    trozos = [t.strip() for t in re.split(r"[.;]\s+|\.\s*$|:\s+(?=No\b)", texto) if t.strip()]
    si, no = [], []
    for etiqueta, patron in USOS:
        rx = re.compile(patron, re.I)
        for t in trozos:
            if rx.search(t):
                (no if NEGACION.search(t) else si).append(etiqueta)
    si = [u for u in dict.fromkeys(si)]
    no = [u for u in dict.fromkeys(no) if u not in si]
    return si, no


def _n(v):
    return f"{v:,.0f}".replace(",", ".") if isinstance(v, (int, float)) else v


def urls() -> list[str]:
    salida = ["/normativa"]
    for ms, m in municipios().items():
        salida.append(f"/normativa/{ms}")
        salida += [f"/normativa/{ms}/{zs}" for zs in m["zonas"]]
    return salida


def _pintar(plantilla: str, request: Request, **datos) -> HTMLResponse:
    from app.rutas_cuenta import _pintar as pintar
    return pintar(plantilla, request, base_url=BASE_URL, n=_n, **datos)


@router.get("/normativa", response_class=HTMLResponse)
async def indice(request: Request):
    ms = municipios()
    return _pintar("normativa.html", request, vista="indice", municipios=ms, ruta="/normativa",
                   titulo="Qué se puede construir en tu parcela: normativa urbanística por municipio en Cataluña",
                   descripcion=f"Qué se puede construir o instalar en una parcela o solar: usos permitidos, parcela mínima, edificabilidad "
                               f"y altura de cada zona urbanística en {len(ms)} municipios de Cataluña. Consulta gratis tu parcela.")


@router.get("/normativa/{ms}", response_class=HTMLResponse)
async def municipio(request: Request, ms: str):
    m = municipios().get(ms)
    if not m:
        raise HTTPException(404, "Municipio no encontrado")
    return _pintar("normativa.html", request, vista="municipio", m=m, ms=ms, ruta=f"/normativa/{ms}",
                   titulo=f"Qué se puede construir en {m['nombre']}: zonas urbanísticas, parcela mínima y usos",
                   descripcion=f"Qué se puede construir o poner en una parcela o solar de {m['nombre']}: zonas urbanísticas con su parcela "
                               "mínima, edificabilidad, altura y usos permitidos (vivienda, naves, comercio, oficinas…). Consulta gratis tu parcela.")


@router.get("/normativa/{ms}/{zs}", response_class=HTMLResponse)
async def zona(request: Request, ms: str, zs: str):
    m = municipios().get(ms)
    z = m and m["zonas"].get(zs)
    if not z:
        raise HTTPException(404, "Zona no encontrada")
    pm = f", parcela mínima {_n(z['parcela_minima_m2'])} m²" if z.get("parcela_minima_m2") else ""
    otras = [(k, v) for k, v in m["zonas"].items() if k != zs]
    return _pintar("normativa.html", request, vista="zona", m=m, ms=ms, z=z, zs=zs, otras=otras,
                   puede=que_se_puede(z), ruta=f"/normativa/{ms}/{zs}",
                   titulo=f"Qué se puede construir en la zona {z['clave']} de {m['nombre']} ({z.get('nombre', '')})",
                   descripcion=f"Qué se puede construir o instalar en un solar de la zona {z['clave']} ({z.get('nombre', '')}) de {m['nombre']}{pm}: "
                               "usos permitidos, edificabilidad, ocupación y altura. Consulta gratis tu parcela.")
