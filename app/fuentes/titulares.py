"""Actividades, empresas y titulares registrados en la parcela (registros públicos).

Fuentes (Dades obertes de Catalunya, API Socrata, consulta en directo):
  - Registre de Turisme de Catalunya: establecimientos de alojamiento por referencia catastral,
    con la razón social y el CIF del titular cuando es una empresa.
  - Indústries agroalimentàries de Catalunya (RIAAC): empresa, forma jurídica, teléfono y web.
  - Establiments sanitaris autoritzats: centro, titular y teléfono.
  - Cens d'activitats municipal amb establiment (municipios con el gestor de la Diputació de
    Barcelona): nombre comercial y actividad.
Además, el informe añade la estación de servicio del Ministerio y los negocios de
OpenStreetMap que caen dentro de la parcela.

Protección de datos: nunca se muestran nombres de personas físicas. Del Registre de Turisme
solo se toma la razón social y el CIF si el CIF es de una persona jurídica; de las demás
fuentes, solo nombres de establecimientos y de empresas.
"""
import asyncio
import math

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from app import geo, http
from app.fuentes.base import error, resultado

BASE = "https://analisi.transparenciacatalunya.cat/resource"
FUENTE = "Dades obertes de Catalunya (Registre de Turisme, RIAAC, establiments sanitaris, censos municipals d'activitats)"
URL = "https://analisi.transparenciacatalunya.cat"
MARGEN_M = 25  # las direcciones se geolocalizan en fachada: se acepta un pequeño margen fuera del polígono

TURISMO, AGRO, SANITARIO, CENSO = "t2h3-cgys", "p28j-xe65", "nrmq-ytje", "txvw-xc3g"
PERSONA_JURIDICA = set("ABCDEFGHJNPQRSUVW")  # primera letra del CIF de sociedades y entidades
FORMAS_PERSONA_FISICA = ("PERSONA F", "EMPRESARI INDIVIDUAL", "EMPRESARIO INDIVIDUAL", "AUTÒNOM", "AUTONOM")


def es_empresa(cif: str) -> bool:
    c = (cif or "").strip().upper()
    return len(c) == 9 and c[0] in PERSONA_JURIDICA


import re

SIGLAS_EMPRESA = {"SL", "SA", "SLP", "SLU", "SAU", "SCCL", "SCP", "SC", "SLL", "AIE", "COOP", "CB", "SCOOP"}
PALABRAS_ENTIDAD = ("FUNDACI", "ASSOCIACI", "ASOCIACI", "AJUNTAMENT", "AYUNTAMIENTO", "CONSORCI", "INSTITUT", "HOSPITAL",
                    "SERVEI", "SERVICIO", "GENERALITAT", "MUTUA", "MÚTUA", "CORPORACI", "GRUP", "CENTRE", "CENTRO", "CLÍNICA",
                    "CLINICA", "ORDE", "ORDEN", "CONGREGACI", "ENTITAT", "EMPRESA", "COOPERATIV", "SOCIETAT", "SOCIEDAD")


def es_nombre_empresa(nombre: str) -> bool:
    """Heurística prudente: solo se muestra el titular si su nombre es claramente de una entidad."""
    n = (nombre or "").upper()
    palabras = re.findall(r"[A-ZÀ-Ü]+", n.replace(".", ""))
    return any(p in SIGLAS_EMPRESA for p in palabras) or any(p.startswith(PALABRAS_ENTIDAD) for p in palabras)


def _caja(parcela: BaseGeometry) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = parcela.buffer(MARGEN_M + 5).bounds
    lon1, lat1 = geo.a_wgs84(minx, miny)
    lon2, lat2 = geo.a_wgs84(maxx, maxy)
    return lat1, lon1, lat2, lon2


def _situacion(parcela: BaseGeometry, lon, lat) -> tuple[str, int] | None:
    try:
        x, y = geo.a_utm(float(lon), float(lat))
    except (TypeError, ValueError):
        return None
    d = Point(x, y).distance(parcela)
    if d > MARGEN_M:
        return None
    return ("En la parcela" if d == 0 else f"Junto a la parcela ({math.ceil(d)} m)"), round(d)


async def _turismo(rc14: str) -> list[dict]:
    filas = await http.get_json(f"{BASE}/{TURISMO}.json", {"$where": f"referencia_cadastral like '{rc14}%'", "$limit": 50})
    salida = []
    for r in filas:
        cif = (r.get("cif") or "").strip().upper()
        empresa = es_empresa(cif)
        salida.append({
            "fuente": "Registre de Turisme de Catalunya",
            "nombre": r.get("r_tol") or "", "actividad": " · ".join(filter(None, [r.get("tipus_establiment"), r.get("categoria")])),
            "empresa": (r.get("ra_social_del_titular") or "").strip() if empresa else "",
            "cif": cif if empresa else "", "contacto": "",
            "detalle": f"{r.get('total_places')} plazas" if r.get("total_places") else "",
            "situacion": "En la parcela (misma referencia catastral)", "distancia_m": 0,
        })
    return salida


async def _por_coordenadas(parcela: BaseGeometry, dataset: str, campo_lat: str, campo_lon: str, convertir) -> list[dict]:
    lat1, lon1, lat2, lon2 = _caja(parcela)
    filas = await http.get_json(f"{BASE}/{dataset}.json", {
        "$where": f"{campo_lat} between {lat1} and {lat2} and {campo_lon} between {lon1} and {lon2}", "$limit": 200})
    salida = []
    for r in filas:
        sit = _situacion(parcela, r.get(campo_lon), r.get(campo_lat))
        if not sit:
            continue
        item = convertir(r)
        if item:
            salida.append({**item, "situacion": sit[0], "distancia_m": sit[1]})
    return salida


def _agro(r: dict) -> dict | None:
    forma = (r.get("titularitat") or "").upper()
    persona = any(f in forma for f in FORMAS_PERSONA_FISICA)
    return {"fuente": "Indústries agroalimentàries (RIAAC)", "nombre": "" if persona else (r.get("establiment") or ""),
            "actividad": r.get("descripci_activitat_principal") or r.get("sector") or "",
            "empresa": "" if persona else (r.get("establiment") or ""), "cif": "",
            "contacto": " · ".join(filter(None, [r.get("tel_fon"), r.get("web")])) if not persona else "",
            "detalle": (r.get("titularitat") or "").capitalize() if not persona else "Titular persona física (no se muestra)"}


def _sanitario(r: dict) -> dict:
    titular = r.get("titular_nom") or ""
    empresa = es_nombre_empresa(titular)
    return {"fuente": "Establiments sanitaris autoritzats", "nombre": r.get("establiment_nom") or "",
            "actividad": r.get("tipus_establiment_nom") or "", "empresa": titular if empresa else "", "cif": "",
            "contacto": (r.get("telefon") or "") if empresa else "", "detalle": "" if empresa else "Titular persona física (no se muestra)"}


def _censo(r: dict) -> dict:
    return {"fuente": f"Cens d'activitats ({r.get('nom_ens') or 'ajuntament'})", "nombre": r.get("nom_comercial") or "",
            "actividad": r.get("descripcio_activitat") or r.get("descripcio_ccae") or "", "empresa": "", "cif": "",
            "contacto": "", "detalle": r.get("adreca_complerta") or ""}


async def consultar(parcela: BaseGeometry, rc14: str) -> dict:
    tareas = {
        "turismo": _turismo(rc14),
        "agro": _por_coordenadas(parcela, AGRO, "latitud", "longitud", _agro),
        "sanitario": _por_coordenadas(parcela, SANITARIO, "latitud", "longitud", _sanitario),
        "censo": _por_coordenadas(parcela, CENSO, "latitud", "longitud", _censo),
    }
    res = await asyncio.gather(*tareas.values(), return_exceptions=True)
    registros, fallos = [], []
    for nombre, r in zip(tareas, res):
        if isinstance(r, Exception):
            fallos.append(nombre)
        else:
            registros.extend(r)
    if fallos and len(fallos) == len(tareas):
        return error(FUENTE, "Los registros públicos de Dades obertes de Catalunya no responden.", URL)
    registros.sort(key=lambda r: (r["distancia_m"], r["fuente"]))
    return resultado("ok", FUENTE, URL, fecha_dato="Registros vigentes en la fecha de consulta",
                     registros=registros, fuentes_sin_respuesta=fallos)
