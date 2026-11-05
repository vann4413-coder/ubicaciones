"""Catastro: parcela, datos descriptivos, geometría y colindantes.

Servicios públicos (CC BY 4.0):
- Consulta_RCCOOR: referencia catastral a partir de coordenadas.
- Consulta_CPMRC: coordenadas a partir de la referencia catastral.
- Consulta_DNPRC: datos descriptivos (uso, superficies, año, inmuebles).
- WFS INSPIRE de parcelas: geometría exacta en EPSG:25831.
"""
import re
import xml.etree.ElementTree as ET

from shapely.geometry import MultiPolygon, Polygon

from app import config, geo, http
from app.fuentes.base import error, resultado

FUENTE = "Dirección General del Catastro"
NS = {
    "gml": "http://www.opengis.net/gml/3.2",
    "cp": "http://inspire.ec.europa.eu/schemas/cp/4.0",
    "wfs": "http://www.opengis.net/wfs/2.0",
}
RE_RC = re.compile(r"^[0-9A-Z]{14}([0-9A-Z]{6})?$")


def normalizar_rc(texto: str) -> str | None:
    rc = re.sub(r"[\s\-]", "", (texto or "").upper())
    return rc if RE_RC.match(rc) else None


def _lista(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


async def rc_en_punto(lon: float, lat: float) -> list[dict]:
    """Parcelas catastrales en un punto WGS84. Lista vacía si cae en vial o fuera."""
    d = await http.get_json(
        f"{config.CATASTRO_COORD}/Consulta_RCCOOR",
        {"CoorX": f"{lon:.6f}", "CoorY": f"{lat:.6f}", "SRS": "EPSG:4326"},
    )
    return parse_rccoor(d)


def parse_rccoor(d: dict) -> list[dict]:
    res = d.get("Consulta_RCCOORResult", d)
    coords = (res.get("coordenadas") or {}).get("coord")
    salida = []
    for c in _lista(coords):
        pc = c.get("pc") or {}
        rc = f"{pc.get('pc1', '')}{pc.get('pc2', '')}"
        if len(rc) == 14:
            salida.append({"rc": rc, "direccion": c.get("ldt", "")})
    return salida


async def coordenadas_de_rc(rc14: str) -> tuple[float, float] | None:
    d = await http.get_json(
        f"{config.CATASTRO_COORD}/Consulta_CPMRC",
        {"Provincia": "", "Municipio": "", "SRS": "EPSG:4326", "RefCat": rc14},
    )
    res = d.get("Consulta_CPMRCResult", d)
    for c in _lista((res.get("coordenadas") or {}).get("coord")):
        g = c.get("geo") or {}
        try:
            return float(g["xcen"]), float(g["ycen"])
        except (KeyError, ValueError):
            continue
    return None


def _num(v) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(".", "").replace(",", ".")) if "," in str(v) else float(v)
    except ValueError:
        return None


SEDE_CDYG = "https://www1.sedecatastro.gob.es/CYCBienInmueble/SECImprimirCroquisYDatos.aspx"


def _rc20(rc: dict | None) -> str:
    rc = rc or {}
    return "".join(str(rc.get(k, "")) for k in ("pc1", "pc2", "car", "cc1", "cc2"))


def url_cdyg(rc20: str, delegacion: str, municipio_catastro: str) -> str:
    """Consulta descriptiva y gráfica oficial (PDF) de un inmueble, en la Sede del Catastro."""
    return f"{SEDE_CDYG}?del={delegacion}&mun={municipio_catastro}&refcat={rc20}"


def parse_dnprc(d: dict) -> dict:
    """Interpreta Consulta_DNPRC (un inmueble o lista de inmuebles)."""
    res = d.get("consulta_dnprcResult", d)
    control = res.get("control") or {}
    errores = res.get("lerr")
    if errores:
        msgs = [e.get("des", "") for e in _lista(errores.get("err"))]
        return {"error": "; ".join(msgs) or "Referencia no encontrada"}

    salida: dict = {"num_inmuebles": int(control.get("cudnp", 0) or 0)}
    bico = res.get("bico")
    if bico:
        bi = bico.get("bi") or {}
        debi = bi.get("debi") or {}
        finca = bico.get("finca") or {}
        dt = bi.get("dt") or {}
        salida.update(
            clase={"UR": "Urbano", "RU": "Rústico", "BI": "Bien inmueble de características especiales"}.get(
                (bi.get("idbi") or {}).get("cn", ""), (bi.get("idbi") or {}).get("cn", "")
            ),
            direccion=finca.get("ldt") or bi.get("ldt", ""),
            municipio=dt.get("nm", ""),
            provincia=dt.get("np", ""),
            cod_ine_prov=(dt.get("loine") or {}).get("cp", ""),
            cod_ine_mun=(dt.get("loine") or {}).get("cm", ""),
            fichas_catastro=[{"rc": _rc20((bi.get("idbi") or {}).get("rc")), "uso": debi.get("luso", ""),
                              "url": url_cdyg(_rc20((bi.get("idbi") or {}).get("rc")), (dt.get("loine") or {}).get("cp", ""), str(dt.get("cmc", "")))}]
            if _rc20((bi.get("idbi") or {}).get("rc")) and dt.get("cmc") else [],
            uso=debi.get("luso", ""),
            sup_construida=_num(debi.get("sfc")),
            anio_construccion=int(debi["ant"]) if str(debi.get("ant", "")).isdigit() else None,
            sup_suelo=_num((finca.get("dff") or {}).get("ss")),
            tipo_finca=finca.get("ltp", ""),
            construcciones=[
                {
                    "uso": c.get("lcd", ""),
                    "superficie": _num((c.get("dfcons") or {}).get("stl")),
                    "tipologia": (c.get("dvcons") or {}).get("dtip", ""),
                }
                for c in _lista(bico.get("lcons"))
            ],
        )
        return salida

    # Varias unidades (división horizontal): resumen de usos y superficies.
    inmuebles = []
    for r in _lista((res.get("lrcdnp") or {}).get("rcdnp")):
        debi = r.get("debi") or {}
        dt = r.get("dt") or {}
        inmuebles.append(
            {
                "uso": debi.get("luso", ""),
                "superficie": _num(debi.get("sfc")),
                "anio": int(debi["ant"]) if str(debi.get("ant", "")).isdigit() else None,
                "municipio": dt.get("nm", ""),
                "provincia": dt.get("np", ""),
                "cod_ine_prov": (dt.get("loine") or {}).get("cp", ""),
                "cod_ine_mun": (dt.get("loine") or {}).get("cm", ""),
                "rc20": _rc20(r.get("rc")), "cmc": str(dt.get("cmc", "")),
            }
        )
    if inmuebles:
        usos: dict[str, float] = {}
        for i in inmuebles:
            usos[i["uso"]] = usos.get(i["uso"], 0) + (i["superficie"] or 0)
        anios = [i["anio"] for i in inmuebles if i["anio"]]
        salida.update(
            municipio=inmuebles[0]["municipio"],
            provincia=inmuebles[0]["provincia"],
            cod_ine_prov=inmuebles[0]["cod_ine_prov"],
            cod_ine_mun=inmuebles[0]["cod_ine_mun"],
            uso=max(usos, key=usos.get) if usos else "",
            usos=usos,
            sup_construida=sum(i["superficie"] or 0 for i in inmuebles),
            anio_construccion=min(anios) if anios else None,
            tipo_finca="Parcela con división horizontal",
            num_inmuebles=len(inmuebles),
            fichas_catastro=[{"rc": i["rc20"], "uso": i["uso"], "url": url_cdyg(i["rc20"], i["cod_ine_prov"], i["cmc"])}
                             for i in inmuebles if i["rc20"] and i["cmc"]],
        )
    return salida


def parse_gml_parcelas(xml_texto: str) -> list[dict]:
    """Extrae parcelas (rc, área, geometría shapely en 25831) del GML INSPIRE."""
    root = ET.fromstring(xml_texto.encode("utf-8") if isinstance(xml_texto, str) else xml_texto)
    parcelas = []
    for cp in root.iter(f"{{{NS['cp']}}}CadastralParcel"):
        rc_el = cp.find("cp:nationalCadastralReference", NS)
        area_el = cp.find("cp:areaValue", NS)
        poligonos = []
        for patch in cp.iter(f"{{{NS['gml']}}}PolygonPatch"):
            ext = patch.find("gml:exterior//gml:posList", NS)
            if ext is None:
                continue
            shell = _poslist(ext.text)
            holes = [_poslist(i.text) for i in patch.findall("gml:interior//gml:posList", NS)]
            poligonos.append(Polygon(shell, holes))
        if not poligonos:
            continue
        g = poligonos[0] if len(poligonos) == 1 else MultiPolygon(poligonos)
        if not g.is_valid:
            g = g.buffer(0)
        parcelas.append(
            {
                "rc": rc_el.text if rc_el is not None else "",
                "area": float(area_el.text) if area_el is not None else round(g.area),
                "geom": g,
            }
        )
    return parcelas


def _poslist(texto: str) -> list[tuple[float, float]]:
    v = [float(n) for n in texto.split()]
    return list(zip(v[0::2], v[1::2]))


async def geometria(rc14: str) -> dict | None:
    xml = await http.get_text(
        config.CATASTRO_WFS_CP,
        {
            "service": "wfs",
            "version": "2.0.0",
            "request": "GetFeature",
            "STOREDQUERIE_ID": "GetParcel",
            "refcat": rc14,
            "srsname": f"EPSG::{config.EPSG_UTM}",
        },
    )
    ps = parse_gml_parcelas(xml)
    return ps[0] if ps else None


async def parcelas_en_bbox(b: tuple[float, float, float, float]) -> list[dict]:
    xml = await http.get_text(
        config.CATASTRO_WFS_CP,
        {
            "service": "wfs",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": "CP:CadastralParcel",
            "srsname": f"EPSG::{config.EPSG_UTM}",
            "bbox": geo.bbox_txt(b),
        },
    )
    return parse_gml_parcelas(xml)


async def consultar(rc: str) -> dict:
    """Ficha completa de la parcela. `rc` de 14 o 20 caracteres."""
    rc14 = rc[:14]
    url = config.CATASTRO_FICHA.format(rc=rc14)
    try:
        dnp = parse_dnprc(await http.get_json(f"{config.CATASTRO_CALLEJERO}/Consulta_DNPRC", {"RefCat": rc14}))
        if "error" in dnp:
            return error(FUENTE, dnp["error"], url)
        g = await geometria(rc14)
    except http.ErrorFuente as e:
        return error(FUENTE, f"Catastro no responde: {e}", url)
    if not g:
        return error(FUENTE, "No se encontró la geometría de la parcela", url)

    colindantes = []
    try:
        vecinas = await parcelas_en_bbox(geo.bbox(g["geom"], 5))
        for v in vecinas:
            if v["rc"] != rc14 and v["geom"].distance(g["geom"]) < 0.5:
                lindero = v["geom"].buffer(0.3).intersection(g["geom"].boundary).length
                colindantes.append({"rc": v["rc"], "area": v["area"], "lindero_m": round(lindero, 1), "geom": v["geom"]})
    except http.ErrorFuente:
        pass  # Los colindantes son complementarios.

    return resultado(
        "ok",
        FUENTE,
        url,
        fecha_dato="Datos vigentes en la fecha de consulta",
        rc=rc14,
        sup_grafica=g["area"],
        geom=g["geom"],
        colindantes=colindantes,
        **dnp,
    )
