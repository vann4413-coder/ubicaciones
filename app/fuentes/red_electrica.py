"""Capacidad de acceso a la red de distribución.

Las distribuidoras publican cada mes un fichero con la capacidad disponible por nudo
(formato fijado por la Circular 1/2024 de la CNMC). Se descarga y se carga con
`scripts/importar_capacidad_red.py` en `datos/capacidad_red.csv`.
"""
import csv
from functools import lru_cache

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from app import config, geo
from app.fuentes.base import resultado

FUENTE = "Mapas de capacidad de acceso de las distribuidoras (Circular 1/2024 CNMC)"
URL = "https://www.edistribucion.com/es/red-electrica/nodos-capacidad-red/capacidad-demanda.html"
POTENCIA_CARGADOR_KW = 150
RADIO_BUSQUEDA_M = 15_000


def _f(v):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def _nudos(ruta: str, mtime: float) -> list[dict]:
    salida = []
    with open(ruta, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            lon, lat = _f(r.get("lon")), _f(r.get("lat"))
            if lon is None or lat is None:
                continue
            x, y = geo.a_utm(lon, lat)
            salida.append({
                "gestor": r.get("gestor", ""),
                "nudo": r.get("nudo", ""),
                "tension_kv": _f(r.get("tension_kv")),
                "disponible_mw": _f(r.get("cap_disponible_mw")),
                "ocupada_mw": _f(r.get("cap_ocupada_mw")),
                "tramite_mw": _f(r.get("cap_tramite_mw")),
                "marca_0": str(r.get("marca_0", "")).strip().lower() in ("1", "si", "sí", "true", "x", "0*"),
                "fecha_fichero": r.get("fecha_fichero", ""),
                "x": x, "y": y, "lon": lon, "lat": lat,
            })
    return salida


def nudos() -> list[dict]:
    p = config.FICHERO_RED
    if not p.exists():
        return []
    return _nudos(str(p), p.stat().st_mtime)


def consultar(parcela: BaseGeometry, n: int = 3) -> dict:
    todos = nudos()
    if not todos:
        return resultado("sin_dato", FUENTE, URL,
                         mensaje="Aún no se ha cargado el fichero de capacidad de la distribuidora.")
    cerca = []
    for nd in todos:
        d = Point(nd["x"], nd["y"]).distance(parcela)
        if d <= RADIO_BUSQUEDA_M:
            disp = nd["disponible_mw"] or 0
            cerca.append({
                **{k: v for k, v in nd.items() if k not in ("x", "y")},
                "distancia_m": round(d),
                "cargadores_150kw": int(disp * 1000 // POTENCIA_CARGADOR_KW) if disp > 0 else 0,
            })
    cerca.sort(key=lambda c: c["distancia_m"])
    if not cerca:
        return resultado("sin_dato", FUENTE, URL, mensaje="No hay nudos publicados a menos de 15 km.")
    fecha = cerca[0]["fecha_fichero"]
    return resultado(
        "ok", FUENTE, URL, fecha_dato=f"Fichero publicado {fecha}" if fecha else "",
        nudos=cerca[:n],
        aviso="La capacidad publicada es orientativa y cambia cada mes. No garantiza la conexión: "
              "hace falta solicitar acceso y conexión a la distribuidora. Los nudos con capacidad 0 sin "
              "marca 0* no admiten solicitudes (art. 8.1.d RD 1183/2020).",
    )
