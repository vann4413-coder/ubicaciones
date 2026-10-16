"""Consulta genérica al WFS de la Generalitat (https://sig.gencat.cat/ows/wfs).

Restricciones comprobadas: un solo tipo de entidad por petición; acepta
outputFormat=application/json; las coordenadas van en EPSG:25831.
"""
from shapely.geometry.base import BaseGeometry

from app import config, geo, http


async def entidades(capa: str, zona: BaseGeometry, margen: float = 0.0, max_entidades: int = 500) -> list[dict]:
    """Devuelve [{props, geom}] de la capa que tocan el rectángulo de `zona` (+ margen)."""
    b = geo.bbox(zona, margen)
    d = await http.get_json(
        config.GENCAT_WFS,
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": capa,
            "srsName": f"EPSG:{config.EPSG_UTM}",
            "bbox": f"{geo.bbox_txt(b)},EPSG:{config.EPSG_UTM}",
            "outputFormat": "application/json",
            "count": str(max_entidades),
        },
    )
    if not isinstance(d, dict) or "features" not in d:
        raise http.ErrorFuente(f"Respuesta inesperada del WFS para {capa}")
    salida = []
    for f in d["features"]:
        salida.append({"props": f.get("properties") or {}, "geom": geo.geojson_a_geom(f.get("geometry"))})
    return salida


async def que_intersectan(capa: str, parcela: BaseGeometry) -> list[dict]:
    """Entidades que se solapan realmente con la parcela, con % de superficie afectada."""
    salida = []
    for e in await entidades(capa, parcela):
        if e["geom"] is None or not e["geom"].intersects(parcela):
            continue
        pct = geo.pct_interseccion(parcela, e["geom"])
        if pct > 0:
            salida.append({**e, "pct": pct})
    return sorted(salida, key=lambda e: -e["pct"])
