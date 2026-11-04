"""Estaciones de servicio del geoportal de carburantes (Ministerio para la Transición Ecológica)."""
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from app import config, geo, http
from app.fuentes.base import error, resultado

FUENTE = "Geoportal de carburantes, Ministerio para la Transición Ecológica"
URL = "https://geoportalgasolineras.es"


def _f(v):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


GRANDES_MARCAS = ("REPSOL", "CEPSA", "MOEVE", "SHELL", "GALP", "BP", "Q8", "PETRONOR", "CAMPSA", "PETROCAT", "AVIA", "DISA")
SUPERMERCADOS = ("CARREFOUR", "ALCAMPO", "EROSKI", "BONAREA", "BON AREA", "CAPRABO", "E.LECLERC", "LECLERC", "INTERMARCHE", "COSTCO", "MAKRO", "SIMPLY")


def grupo(marca: str) -> str:
    """Tipo de competidor: gran marca, supermercado o independiente / low cost."""
    import unicodedata
    u = "".join(c for c in unicodedata.normalize("NFD", (marca or "").upper()) if unicodedata.category(c) != "Mn")
    if u.startswith(SUPERMERCADOS):
        return "supermercado"
    if u.startswith(GRANDES_MARCAS):
        return "marca"
    return "independiente"


def parse(d: dict, parcela: BaseGeometry, radio: float) -> list[dict]:
    salida = []
    for e in d.get("ListaEESSPrecio", []):
        lat, lon = _f(e.get("Latitud")), _f(e.get("Longitud (WGS84)"))
        if lat is None or lon is None:
            continue
        x, y = geo.a_utm(lon, lat)
        dist = Point(x, y).distance(parcela)
        if dist > radio:
            continue
        salida.append({
            "marca": (e.get("Rótulo") or "").strip(),
            "grupo": grupo(e.get("Rótulo") or ""),
            "direccion": (e.get("Dirección") or "").strip(),
            "municipio": e.get("Municipio", ""),
            "horario": e.get("Horario", ""),
            "gasoleo_a": _f(e.get("Precio Gasoleo A")),
            "gasolina_95": _f(e.get("Precio Gasolina 95 E5")),
            "distancia_m": round(dist),
            "lon": lon, "lat": lat,
        })
    return sorted(salida, key=lambda g: g["distancia_m"])


async def consultar(parcela: BaseGeometry, cod_prov: str, radio: float = 2000) -> dict:
    if not cod_prov:
        return resultado("sin_dato", FUENTE, URL, mensaje="Provincia no identificada.")
    try:
        d = await http.get_json(config.CARBURANTES_URL.format(prov=cod_prov.zfill(2)))
    except http.ErrorFuente as e:
        return error(FUENTE, f"El geoportal de carburantes no responde: {e}", URL)
    return resultado("ok", FUENTE, URL, fecha_dato=d.get("Fecha", ""), estaciones=parse(d, parcela, radio))
