"""Indicadores geométricos de la parcela."""
import math

from shapely.geometry.base import BaseGeometry


def metricas(parcela: BaseGeometry) -> dict:
    area = parcela.area
    perimetro = parcela.length
    # Compacidad (Polsby-Popper): 1 = círculo, ~0,785 = cuadrado; valores bajos = alargada o irregular.
    compacidad = 4 * math.pi * area / perimetro**2 if perimetro else 0
    rect = parcela.minimum_rotated_rectangle
    lados = []
    if rect.geom_type == "Polygon":
        c = list(rect.exterior.coords)
        lados = sorted(math.dist(c[i], c[i + 1]) for i in range(2))
    lado_min = lados[0] if lados else 0
    lado_max = lados[-1] if lados else 0
    # Círculo inscrito máximo aproximado: radio del mayor buffer negativo no vacío.
    ancho_util = _ancho_util(parcela)
    return {
        "superficie_m2": round(area),
        "perimetro_m": round(perimetro, 1),
        "compacidad": round(compacidad, 2),
        "forma": "regular" if compacidad >= 0.6 else "algo irregular" if compacidad >= 0.4 else "irregular o alargada",
        "lado_menor_m": round(lado_min, 1),
        "lado_mayor_m": round(lado_max, 1),
        "ancho_util_m": round(ancho_util, 1),
    }


def _ancho_util(g: BaseGeometry) -> float:
    """Diámetro del mayor círculo que cabe dentro (búsqueda binaria con buffer negativo)."""
    lo, hi = 0.0, max(g.bounds[2] - g.bounds[0], g.bounds[3] - g.bounds[1]) / 2
    for _ in range(20):
        mid = (lo + hi) / 2
        if g.buffer(-mid).is_empty:
            hi = mid
        else:
            lo = mid
    return 2 * lo
