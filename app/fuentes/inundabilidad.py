"""Inundabilidad.

- ACA (cuencas internas de Cataluña), vectorial vía WFS de la Generalitat:
  zona de flujo preferente (ZFP), láminas T10/T100/T500 y dominio público hidráulico.
- SNCZI (MITECO) vía WMS INSPIRE del IDEE: cubre toda España, incluida la cuenca
  del Ebro, y la inundación de origen marino. Es un ráster: se pide la imagen del
  entorno de la parcela y se mide qué parte de la parcela queda pintada.
"""
import io

from PIL import Image, ImageDraw
from shapely.geometry.base import BaseGeometry

from app import config, geo, http
from app.fuentes import gencat_wfs
from app.fuentes.base import error, resultado

FUENTE_ACA = "Agència Catalana de l'Aigua (ACA)"
FUENTE_SNCZI = "SNCZI, Ministerio para la Transición Ecológica"
URL_ACA = "https://sig.gencat.cat/visors/hipermapa.html"
URL_SNCZI = "https://sig.mapama.gob.es/snczi/"

# Zona de policía: 100 m a cada lado del cauce. Servidumbre: 5 m (art. 6 TRLA).
ZONA_POLICIA_M = 100
SERVIDUMBRE_M = 5


async def consultar_aca(parcela: BaseGeometry) -> dict:
    try:
        zfp = await gencat_wfs.que_intersectan(config.CAPA_ZFP, parcela)
        li10 = await gencat_wfs.que_intersectan(config.CAPA_LI10, parcela)
        li100 = await gencat_wfs.que_intersectan(config.CAPA_LI100, parcela)
        li500 = await gencat_wfs.que_intersectan(config.CAPA_LI500, parcela)
        dph_cerca = await gencat_wfs.entidades(config.CAPA_DPH, parcela, margen=ZONA_POLICIA_M)
    except http.ErrorFuente as e:
        return error(FUENTE_ACA, f"El servicio del ACA no responde: {e}", URL_ACA)

    def pct_total(lista):
        if not lista:
            return 0.0
        from shapely.ops import unary_union
        return geo.pct_interseccion(parcela, unary_union([e["geom"] for e in lista]))

    dph_geoms = [e["geom"] for e in dph_cerca if e["geom"] is not None]
    dist_dph = round(min(g.distance(parcela) for g in dph_geoms), 1) if dph_geoms else None
    tramo = None
    if zfp:
        p = zfp[0]["props"]
        tramo = {"rio": p.get("NOM_AV") or p.get("NOM_AA") or "", "arpsi": p.get("ARPSI", ""), "ficha": p.get("HISTORIA", "")}

    return resultado(
        "ok",
        FUENTE_ACA,
        URL_ACA,
        fecha_dato="Cartografía vigente de espacios fluviales (planificación del ACA)",
        zfp_pct=pct_total(zfp),
        t10_pct=pct_total(li10),
        t100_pct=pct_total(li100),
        t500_pct=pct_total(li500),
        dph_pct=pct_total([e for e in dph_cerca if e["geom"] is not None and e["geom"].intersects(parcela)]),
        distancia_dph_m=dist_dph,
        en_zona_policia=dist_dph is not None and dist_dph <= ZONA_POLICIA_M,
        en_servidumbre=dist_dph is not None and dist_dph <= SERVIDUMBRE_M,
        tramo_zfp=tramo,
        geoms={"zfp": [e["geom"] for e in zfp], "t100": [e["geom"] for e in li100], "t500": [e["geom"] for e in li500]},
    )


async def _pct_wms(parcela: BaseGeometry, capa: str, px: int = 256) -> float | None:
    """% de la parcela pintado en la capa ráster del SNCZI."""
    g = geo.geom_a_wgs84(parcela)
    minx, miny, maxx, maxy = geo.bbox(g, 0.0)
    pad_x, pad_y = (maxx - minx) * 0.05 + 1e-5, (maxy - miny) * 0.05 + 1e-5
    minx, miny, maxx, maxy = minx - pad_x, miny - pad_y, maxx + pad_x, maxy + pad_y
    r = await http.cliente().get(
        config.IDEE_INUNDACIONES_WMS,
        params={
            "service": "WMS", "version": "1.1.1", "request": "GetMap", "layers": capa, "styles": "",
            "srs": "EPSG:4326", "bbox": f"{minx},{miny},{maxx},{maxy}", "width": px, "height": px,
            "format": "image/png", "transparent": "true",
        },
    )
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image"):
        raise http.ErrorFuente(f"SNCZI {capa}: {r.status_code}")
    img = Image.open(io.BytesIO(r.content)).convert("RGBA")
    mascara = Image.new("L", (px, px), 0)

    def a_px(x, y):
        return ((x - minx) / (maxx - minx) * px, (maxy - y) / (maxy - miny) * px)

    polys = [g] if g.geom_type == "Polygon" else list(g.geoms)
    dibujo = ImageDraw.Draw(mascara)
    for p in polys:
        dibujo.polygon([a_px(x, y) for x, y in p.exterior.coords], fill=255)
        for hueco in p.interiors:
            dibujo.polygon([a_px(x, y) for x, y in hueco.coords], fill=0)
    dentro = pintado = 0
    alfa = img.getchannel("A").load()
    m = mascara.load()
    for i in range(px):
        for j in range(px):
            if m[i, j]:
                dentro += 1
                if alfa[i, j] > 20:
                    pintado += 1
    return round(100 * pintado / dentro, 1) if dentro else None


async def consultar_snczi(parcela: BaseGeometry) -> dict:
    salida = {}
    try:
        for clave, capa in config.SNCZI_CAPAS.items():
            salida[f"{clave}_pct"] = await _pct_wms(parcela, capa)
    except (http.ErrorFuente, OSError, ValueError) as e:
        return error(FUENTE_SNCZI, f"El SNCZI no responde: {e}", URL_SNCZI)
    return resultado("ok", FUENTE_SNCZI, URL_SNCZI, fecha_dato="Mapas de peligrosidad vigentes (2.º/3.er ciclo)", **salida)


def combinar(aca: dict, snczi: dict) -> dict:
    """Veredicto único: el peor caso entre ACA y SNCZI."""
    def v(d, k):
        return (d.get(k) or 0) if d.get("estado") == "ok" else 0

    zfp = v(aca, "zfp_pct")
    t10 = max(v(aca, "t10_pct"), v(snczi, "T10_pct"))
    t100 = max(v(aca, "t100_pct"), v(snczi, "T100_pct"), v(snczi, "MarinaT100_pct"))
    t500 = max(v(aca, "t500_pct"), v(snczi, "T500_pct"), v(snczi, "MarinaT500_pct"))
    if zfp > 0:
        nivel = "zfp"
    elif t10 > 0:
        nivel = "T10"
    elif t100 > 0:
        nivel = "T100"
    elif t500 > 0:
        nivel = "T500"
    else:
        nivel = "fuera"
    hay_dato = aca.get("estado") == "ok" or snczi.get("estado") == "ok"
    return {
        "nivel": nivel if hay_dato else "sin_dato",
        "zfp_pct": zfp, "t10_pct": t10, "t100_pct": t100, "t500_pct": t500,
        "fuente_zfp": FUENTE_ACA if aca.get("estado") == "ok" else None,
        "marina": max(v(snczi, "MarinaT100_pct"), v(snczi, "MarinaT500_pct")) > 0,
    }
