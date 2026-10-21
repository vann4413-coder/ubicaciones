"""Suelos contaminados (Agència de Residus de Catalunya, publicado por el ICGC).

API OGC Features: https://api.icgc.cat/territorial/collections/sols-contaminats/items
Visor: https://visors.icgc.cat/sols-contaminats/
Incluye las declaraciones de suelo contaminado y las recuperaciones voluntarias,
activas o inactivas (cerradas), con su polígono. Comprobado el 21/10/2026: 171 emplazamientos.
"""
from datetime import datetime

from shapely.geometry.base import BaseGeometry

from app import geo, http
from app.fuentes.base import error, resultado

FUENTE = "Agència de Residus de Catalunya, mapa de suelos contaminados (ICGC)"
URL = "https://visors.icgc.cat/sols-contaminats/"
API = "https://api.icgc.cat/territorial/collections/sols-contaminats/items"
RADIO_ENTORNO_M = 250


def _fecha(v) -> str:
    try:
        return datetime.strptime(str(v), "%Y%m%d").date().isoformat()
    except (TypeError, ValueError):
        return ""


def parse(d: dict, parcela: BaseGeometry, radio: float = RADIO_ENTORNO_M) -> dict:
    en_parcela, cerca = [], []
    for f in d.get("features", []):
        g = geo.geojson_a_geom(f.get("geometry"))
        if g is None:
            continue
        g = geo.geom_a_utm(g)
        p = f.get("properties") or {}
        item = {
            "nombre": p.get("Denominació finca", ""),
            "tipo": p.get("Tipus", ""),
            "estado": p.get("Estat", ""),
            "activo": (p.get("Estat") or "").lower() == "actiu",
            "fecha_declaracion": _fecha(p.get("Data de declaració")),
            "fecha_desclasificacion": _fecha(p.get("Data de desclassificació")),
            "municipio": p.get("Municipi", ""),
            "direccion": p.get("Adreça", ""),
            "geom": g,
        }
        if g.intersects(parcela):
            en_parcela.append({**item, "pct": geo.pct_interseccion(parcela, g)})
        else:
            dist = g.distance(parcela)
            if dist <= radio:
                cerca.append({**item, "distancia_m": round(dist)})
    return {"en_parcela": en_parcela, "cercanos": sorted(cerca, key=lambda c: c["distancia_m"]), "radio_m": radio}


async def consultar(parcela: BaseGeometry) -> dict:
    zona = geo.geom_a_wgs84(parcela.buffer(RADIO_ENTORNO_M + 50))
    minx, miny, maxx, maxy = zona.bounds
    try:
        d = await http.get_json(API, {"bbox": f"{minx:.6f},{miny:.6f},{maxx:.6f},{maxy:.6f}", "limit": "1000", "f": "json"})
    except http.ErrorFuente as e:
        return error(FUENTE, f"El servicio de suelos contaminados no responde: {e}", URL)
    return resultado(
        "ok", FUENTE, URL, fecha_dato="Registro vigente en la fecha de consulta", **parse(d, parcela),
        aviso="El registro recoge los suelos declarados contaminados y las recuperaciones voluntarias tramitadas "
              "ante la ARC. Que una parcela no aparezca no garantiza que su suelo esté limpio.",
    )
