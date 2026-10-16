"""Utilidades geográficas: proyecciones y geometría (todo en metros, EPSG:25831)."""
from functools import lru_cache

from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

from app import config


@lru_cache(maxsize=None)
def _tr(origen: int, destino: int) -> Transformer:
    return Transformer.from_crs(origen, destino, always_xy=True)


def a_utm(lon: float, lat: float) -> tuple[float, float]:
    return _tr(config.EPSG_WGS84, config.EPSG_UTM).transform(lon, lat)


def a_wgs84(x: float, y: float) -> tuple[float, float]:
    return _tr(config.EPSG_UTM, config.EPSG_WGS84).transform(x, y)


def geom_a_wgs84(g: BaseGeometry) -> BaseGeometry:
    return transform(_tr(config.EPSG_UTM, config.EPSG_WGS84).transform, g)


def geom_a_utm(g: BaseGeometry) -> BaseGeometry:
    return transform(_tr(config.EPSG_WGS84, config.EPSG_UTM).transform, g)


def bbox(g: BaseGeometry, margen: float = 0.0) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = g.bounds
    return (minx - margen, miny - margen, maxx + margen, maxy + margen)


def bbox_txt(b: tuple[float, float, float, float]) -> str:
    return ",".join(f"{v:.2f}" for v in b)


def geojson_a_geom(geom_json: dict | None) -> BaseGeometry | None:
    if not geom_json:
        return None
    g = shape(geom_json)
    if not g.is_valid:
        g = g.buffer(0)
    return g


def punto(x: float, y: float) -> Point:
    return Point(x, y)


def pct_interseccion(parcela: BaseGeometry, capa: BaseGeometry) -> float:
    """% de la superficie de la parcela cubierto por la geometría (0-100)."""
    if parcela.area <= 0:
        return 0.0
    try:
        inter = parcela.intersection(capa)
    except Exception:
        inter = parcela.buffer(0).intersection(capa.buffer(0))
    return round(100.0 * inter.area / parcela.area, 1)
