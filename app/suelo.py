"""Buscador de suelo industrial sin edificar (uso interno, administración).

Para una zona del mapa: toma del Mapa Urbanístic de Catalunya las calificaciones de actividad económica, busca en el
Catastro las parcelas que caen dentro (al menos la mitad de su superficie) y calcula qué parte está ocupada por
edificios. Las parcelas con poca o ninguna construcción son suelo industrial «disponible» (sin edificar).
"""
import asyncio
import logging
import math
import time

from shapely.geometry import box, mapping
from shapely.ops import unary_union

from app import config, geo
from app.fuentes import catastro, gencat_wfs, geocoder

log = logging.getLogger(__name__)
MAX_KM2 = 5.0       # zona máxima por búsqueda (unos 2 x 2 km)
CELDA_M = 500       # el Catastro se consulta en cuadrículas de 500 m (las grandes tardan demasiado)
PAUSA_S = 0.6
_cache: dict[tuple, tuple[float, dict]] = {}

TIPOS = {
    "industria": ("indústri", "industri", "logístic", "logistic", "magatzem", "productiu"),
    "terciario": ("terciari", "comerç", "comercial", "serveis", "oficin", "hoteler"),
}


def tipo_actividad(props: dict) -> str | None:
    """'industria', 'terciario' o None según la calificación del MUC."""
    cod = str(props.get("CODI_QUAL_MUC") or "").upper()
    txt = " ".join(str(props.get(k) or "") for k in ("DESC_QUAL_MUC", "DESC_QUAL_AJUNT")).lower()
    if not (cod.startswith("A") or "activitat econ" in txt or any(p in txt for v in TIPOS.values() for p in v)):
        return None
    if cod.startswith("S") or "sistema" in txt:
        return None
    for t, palabras in TIPOS.items():
        if any(p in txt for p in palabras):
            return t
    return "industria" if cod.startswith("A1") else ("terciario" if cod.startswith("A") else None)


def _celdas(b: tuple[float, float, float, float]):
    x0, y0, x1, y1 = b
    for i in range(math.ceil((x1 - x0) / CELDA_M)):
        for j in range(math.ceil((y1 - y0) / CELDA_M)):
            yield (x0 + i * CELDA_M, y0 + j * CELDA_M, min(x1, x0 + (i + 1) * CELDA_M), min(y1, y0 + (j + 1) * CELDA_M))


async def buscar(bbox_wgs: tuple[float, float, float, float] | None = None, sup_min: float = 1000, max_edif_pct: float = 10,
                 incluir_terciario: bool = False, poligono_wgs: list | None = None) -> dict:
    """Busca en el rectángulo visible (bbox_wgs) o en un polígono dibujado ([[lon, lat], ...])."""
    from shapely.geometry import Polygon
    if poligono_wgs and len(poligono_wgs) >= 3:
        zona = Polygon([geo.a_utm(float(lon), float(lat)) for lon, lat in poligono_wgs])
        if not zona.is_valid:
            zona = zona.buffer(0)
        if zona.is_empty or zona.area < 100:
            raise ValueError("La zona dibujada no es válida: marca al menos tres puntos.")
        b = zona.bounds
    else:
        lon0, lat0, lon1, lat1 = bbox_wgs
        x0, y0 = geo.a_utm(lon0, lat0)
        x1, y1 = geo.a_utm(lon1, lat1)
        b = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        zona = box(*b)
    km2 = zona.area / 1e6
    if km2 > MAX_KM2 or (b[2] - b[0]) * (b[3] - b[1]) / 1e6 > MAX_KM2 * 3:
        raise ValueError(f"La zona es de {km2:.1f} km²: como máximo unos {MAX_KM2:.0f} km² (acerca el mapa o dibuja una zona más pequeña).")
    clave = (zona.wkt[:2000], sup_min, max_edif_pct, incluir_terciario)
    if clave in _cache and time.time() - _cache[clave][0] < 3600:
        return _cache[clave][1]

    quals = await gencat_wfs.entidades(config.CAPA_MUC_QUALIF, zona, max_entidades=5000)
    activ = []
    for q in quals:
        t = tipo_actividad(q["props"])
        if q["geom"] is None or t is None or (t == "terciario" and not incluir_terciario):
            continue
        activ.append({**q, "tipo": t})
    if not activ:
        return {"parcelas": [], "resumen": {"zonas_actividad": 0, "parcelas": 0, "sin_edificar": 0, "km2": round(km2, 1)}}
    suelo = unary_union([q["geom"] for q in activ]).intersection(zona)

    parcelas: dict[str, dict] = {}
    edificios = []
    for celda in _celdas(b):
        if suelo.is_empty or not box(*celda).intersects(suelo):
            continue
        try:
            for p in await catastro.parcelas_en_bbox(celda):
                parcelas.setdefault(p["rc"], p)
            await asyncio.sleep(PAUSA_S)
            edificios += await catastro.edificios_en_bbox(celda)
            await asyncio.sleep(PAUSA_S)
        except Exception as e:  # noqa: BLE001  una cuadrícula que falla no tumba la búsqueda
            log.warning("Buscador de suelo: cuadrícula %s sin datos (%s)", celda, e)
    huellas = unary_union(edificios) if edificios else None

    salida = []
    for rc, p in parcelas.items():
        g = p["geom"]
        area = g.area
        if area < sup_min or not g.intersects(suelo) or not g.centroid.within(zona.buffer(1)):
            continue
        pct_act = g.intersection(suelo).area / area * 100
        if pct_act < 50:
            continue
        edif = g.intersection(huellas).area if huellas is not None and g.intersects(huellas) else 0.0
        pct_edif = edif / area * 100
        if pct_edif > max_edif_pct:
            continue
        q = max(activ, key=lambda q: q["geom"].intersection(g).area if q["geom"].intersects(g) else 0)
        c = g.centroid
        lon, lat = geo.a_wgs84(c.x, c.y)
        salida.append({
            "rc": rc[:14], "superficie_m2": round(area), "pct_edificado": round(pct_edif, 1), "pct_en_zona_actividad": round(pct_act),
            "tipo": q["tipo"], "calificacion": f"{q['props'].get('CODI_QUAL_AJUNT', '')} {q['props'].get('DESC_QUAL_AJUNT', '')}".strip()
            or q["props"].get("DESC_QUAL_MUC", ""), "calificacion_muc": q["props"].get("DESC_QUAL_MUC", ""),
            "municipio_ine": str(q["props"].get("CODI_INE") or "")[:5], "lon": round(lon, 6), "lat": round(lat, 6),
            "geometria": mapping(geo.geom_a_wgs84(g.simplify(0.5))),
        })
    salida.sort(key=lambda x: -x["superficie_m2"])
    # nombre del municipio de cada parcela (una consulta por municipio distinto)
    nombres: dict[tuple, str] = {}
    for x in salida:
        k = x["municipio_ine"] or (round(x["lon"], 2), round(x["lat"], 2))
        if k not in nombres:
            try:
                m = await geocoder.municipio_en_punto(x["lon"], x["lat"])
                nombres[k] = m["nombre"] if m else ""
            except Exception:  # noqa: BLE001
                nombres[k] = ""
        x["municipio"] = nombres[k]
    res = {"parcelas": salida, "resumen": {"zonas_actividad": len(activ), "parcelas": len(salida),
                                            "sin_edificar": sum(1 for x in salida if x["pct_edificado"] < 1),
                                            "superficie_total_m2": sum(x["superficie_m2"] for x in salida), "km2": round(km2, 1),
                                            "municipios": sorted({x["municipio"] for x in salida if x.get("municipio")})}}
    _cache[clave] = (time.time(), res)
    return res
