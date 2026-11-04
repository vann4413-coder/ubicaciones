"""Valor de referencia del suelo urbano.

Fuente: Estadística de precios de suelo urbano del Ministerio de Vivienda y Agenda Urbana
(tablas 4 a 4.5 del boletín online). El Ministerio publica el precio medio del m² de suelo
urbano por provincia y por tamaño de municipio (menos de 1.000 hab., 1.000-5.000,
5.000-10.000, 10.000-50.000 y más de 50.000), trimestre a trimestre, a partir de las
compraventas ante notario. No publica el dato de cada municipio.

Para cada parcela se toma la serie de su provincia y su tramo de población: media del
último año (cuatro trimestres, sin los no significativos), horquilla, variación anual y
la media provincial como contraste. Se puede actualizar con scripts/actualizar_precio_suelo.py.
"""
import json
from functools import lru_cache
from pathlib import Path
from statistics import mean

from app.fuentes.base import resultado

FICHERO = Path(__file__).resolve().parent.parent / "data" / "precio_suelo_cataluna.json"
FUENTE = "Ministerio de Vivienda y Agenda Urbana, estadística de precios de suelo urbano"
URL = "https://apps.fomento.gob.es/BoletinOnline2/?nivel=2&orden=36000000"
AVISO = ("Referencia estadística de compraventas de suelo urbano en la provincia y en municipios de tamaño similar; "
         "no es una tasación ni el precio de esta parcela. Los datos públicos de alquiler de suelo son escasos.")
PROVINCIAS = {"08": "Barcelona", "17": "Girona", "25": "Lleida", "43": "Tarragona"}
TRAMOS = [(1000, "<1000", "menos de 1.000 habitantes"), (5000, "1000-5000", "1.000 a 5.000 habitantes"),
          (10000, "5000-10000", "5.000 a 10.000 habitantes"), (50000, "10000-50000", "10.000 a 50.000 habitantes"),
          (float("inf"), ">50000", "más de 50.000 habitantes")]


@lru_cache(maxsize=1)
def _datos() -> dict:
    with open(FICHERO, encoding="utf-8") as f:
        return json.load(f)


def _tramo(poblacion: int | None):
    if not poblacion:
        return None
    return next(t for t in TRAMOS if poblacion < t[0])


def _ultimo_anio(serie: list, periodos: list) -> list[tuple[str, float]]:
    validos = [(p, v) for p, v in zip(periodos, serie) if v is not None]
    return validos[-4:]


def consultar(cod_ine5: str, poblacion: int | None = None, superficie_m2: float | None = None,
              suelo_no_urbanizable: bool = False) -> dict:
    prov = (cod_ine5 or "")[:2]
    if prov not in PROVINCIAS:
        return resultado("sin_dato", FUENTE, URL, mensaje="Solo hay serie cargada para las provincias de Cataluña.", aviso=AVISO)
    d = _datos()
    periodos = d["periodos"]
    tramo = _tramo(poblacion)
    clave = tramo[1] if tramo else "total"
    serie = d["series"][clave][prov]
    ultimos = _ultimo_anio(serie, periodos)
    ambito = (f"municipios de {tramo[2]} de la provincia de {PROVINCIAS[prov]}" if tramo
              else f"provincia de {PROVINCIAS[prov]}")
    if len(ultimos) < 2:  # tramo con pocas operaciones: se usa la media provincial
        clave, ambito = "total", f"provincia de {PROVINCIAS[prov]} (el tramo de su tamaño tiene pocas operaciones)"
        ultimos = _ultimo_anio(d["series"]["total"][prov], periodos)
    valores = [v for _, v in ultimos]
    media = mean(valores)
    previos = [(p, v) for p, v in zip(periodos, d["series"][clave][prov]) if v is not None and p not in dict(ultimos)][-4:]
    variacion = round((media / mean(v for _, v in previos) - 1) * 100, 1) if len(previos) >= 2 else None
    provincial = mean(v for _, v in _ultimo_anio(d["series"]["total"][prov], periodos))
    salida = dict(
        fecha_dato=f"{ultimos[0][0]}–{ultimos[-1][0]}",
        ambito=ambito,
        ultimo_precio_m2=round(media),
        horquilla_m2=(round(min(valores)), round(max(valores))),
        variacion_anual_pct=variacion,
        provincia_m2=round(provincial),
        periodos=[{"periodo": p, "precio_m2": round(v)} for p, v in ultimos],
        aviso=AVISO,
    )
    if superficie_m2 and not suelo_no_urbanizable:
        salida["valor_orientativo"] = (round(min(valores) * superficie_m2, -3), round(max(valores) * superficie_m2, -3))
    if suelo_no_urbanizable:
        salida["nota"] = ("La parcela es mayoritariamente suelo no urbanizable: el precio del suelo urbano no le es aplicable "
                          "y su valor de mercado es el de suelo rústico, muy inferior.")
    return resultado("ok", d.get("fuente", FUENTE), d.get("url", URL), **salida)
