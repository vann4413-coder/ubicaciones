"""Valor de referencia del suelo (horquilla orientativa por municipio).

Fichero `datos/precio_suelo.csv` cargado con `scripts/importar_precio_suelo.py` a partir
de la estadística de precio del suelo urbano del Ministerio de Transportes
(municipios de más de 50.000 habitantes) u otras fuentes públicas.
Columnas: cod_ine,municipio,anio,trimestre,precio_m2,num_transacciones,fuente
"""
import csv
from functools import lru_cache

from app import config
from app.fuentes.base import resultado

FUENTE = "Ministerio de Transportes, estadística de precios de suelo urbano"
URL = "https://www.transportes.gob.es/informacion-para-el-ciudadano/informacion-estadistica/vivienda-y-actuaciones-urbanas/estadisticas/precios-de-suelo-urbano"
AVISO = ("Referencia de zona a partir de estadística pública, no es una tasación. "
         "Los datos públicos de alquiler de suelo son escasos.")


@lru_cache(maxsize=1)
def _tabla(ruta: str, mtime: float) -> list[dict]:
    with open(ruta, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def consultar(cod_ine5: str) -> dict:
    p = config.FICHERO_SUELO
    if not p.exists():
        return resultado("sin_dato", FUENTE, URL, mensaje="Aún no se ha cargado la tabla de precios del suelo.", aviso=AVISO)
    filas = [r for r in _tabla(str(p), p.stat().st_mtime) if r.get("cod_ine", "").zfill(5) == (cod_ine5 or "").zfill(5)]
    precios = []
    for r in filas:
        try:
            precios.append((int(r["anio"]), int(r.get("trimestre") or 0), float(r["precio_m2"]), r))
        except (KeyError, ValueError):
            continue
    if not precios:
        return resultado("sin_dato", FUENTE, URL,
                         mensaje="Sin estadística pública para este municipio (solo se publica para municipios de más de 50.000 habitantes).",
                         aviso=AVISO)
    precios.sort(reverse=True)
    ultimos = precios[:4]  # último año móvil
    valores = [p[2] for p in ultimos]
    a, t, v, r = precios[0]
    return resultado(
        "ok", r.get("fuente") or FUENTE, URL,
        fecha_dato=f"{a}" + (f" T{t}" if t else ""),
        ultimo_precio_m2=round(v),
        horquilla_m2=(round(min(valores)), round(max(valores))),
        periodos=[{"anio": p[0], "trimestre": p[1], "precio_m2": round(p[2])} for p in ultimos],
        aviso=AVISO,
    )
