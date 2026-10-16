"""Imágenes de mapa (WMS) para el informe: ortofotos históricas del ICGC y catastro."""
from urllib.parse import urlencode

from shapely.geometry.base import BaseGeometry

from app import config, geo


def encuadre(parcela: BaseGeometry, margen_rel: float = 0.6, minimo: float = 120) -> tuple[float, float, float, float]:
    """Rectángulo cuadrado centrado en la parcela."""
    minx, miny, maxx, maxy = parcela.bounds
    lado = max(maxx - minx, maxy - miny, minimo) * (1 + margen_rel)
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    return (cx - lado / 2, cy - lado / 2, cx + lado / 2, cy + lado / 2)


def url_wms(base: str, capa: str, b: tuple, px: int = 800, transparente: bool = False, fmt: str = "image/jpeg") -> str:
    q = {
        "SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap", "LAYERS": capa, "STYLES": "",
        "SRS": f"EPSG:{config.EPSG_UTM}", "BBOX": ",".join(f"{v:.1f}" for v in b),
        "WIDTH": px, "HEIGHT": px, "FORMAT": "image/png" if transparente else fmt,
    }
    if transparente:
        q["TRANSPARENT"] = "TRUE"
    return f"{base}?{urlencode(q)}"


def historicas(parcela: BaseGeometry) -> dict:
    b = encuadre(parcela)
    return {
        "bbox": b,
        "imagenes": [{"anio": anio, "url": url_wms(config.ICGC_ORTO_WMS, capa, b, 600)} for anio, capa in config.ORTOS_HISTORICAS],
        "fuente": "Institut Cartogràfic i Geològic de Catalunya (ICGC), ortofotos históricas",
        "url": "https://betaportal.icgc.cat/canurb/",
    }


def mapa_base(parcela: BaseGeometry, margen_rel: float = 0.6, minimo: float = 120, px: int = 900) -> dict:
    b = encuadre(parcela, margen_rel, minimo)
    return {
        "bbox": b,
        "orto": url_wms(config.ICGC_ORTO_WMS, "ortofoto_color_vigent", b, px),
        "catastro": url_wms(config.CATASTRO_WMS, "CP.CadastralParcel", b, px, transparente=True),
        "px": px,
    }


def svg_capas(b: tuple, px: int, capas: list[dict]) -> str:
    """SVG con geometrías (en 25831) superpuestas a una imagen del mismo encuadre.
    capas: [{geoms: [...], trazo, relleno, opacidad, ancho, discontinua}]"""
    minx, miny, maxx, maxy = b
    escala = px / (maxx - minx)

    def pt(x, y):
        return f"{(x - minx) * escala:.1f},{(maxy - y) * escala:.1f}"

    def path(g):
        if g.is_empty:
            return ""
        t = g.geom_type
        if t == "Polygon":
            anillos = [g.exterior] + list(g.interiors)
            return " ".join("M" + " L".join(pt(x, y) for x, y in a.coords) + " Z" for a in anillos)
        if t in ("LineString", "LinearRing"):
            return "M" + " L".join(pt(x, y) for x, y in g.coords)
        if t == "Point":
            x, y = pt(g.x, g.y).split(",")
            return f"M{float(x)-4},{y} a4,4 0 1,0 8,0 a4,4 0 1,0 -8,0"
        if hasattr(g, "geoms"):
            return " ".join(path(s) for s in g.geoms)
        return ""

    partes = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {px} {px}" width="{px}" height="{px}">']
    from shapely.geometry import box
    marco = box(*b)
    for c in capas:
        d = " ".join(path(g.intersection(marco)) for g in c.get("geoms", []) if g is not None)
        if not d.strip():
            continue
        dash = ' stroke-dasharray="8 5"' if c.get("discontinua") else ""
        partes.append(
            f'<path d="{d}" fill="{c.get("relleno", "none")}" fill-opacity="{c.get("opacidad", 0.25)}" '
            f'stroke="{c.get("trazo", "#000")}" stroke-width="{c.get("ancho", 2)}"{dash} fill-rule="evenodd"/>'
        )
    partes.append("</svg>")
    return "".join(partes)
