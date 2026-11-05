"""Urbanismo: Mapa Urbanístic de Catalunya (MUC) vía WFS de la Generalitat
y expedientes del Registre de Planejament Urbanístic de Catalunya (RPUC)."""
from datetime import date, datetime

from shapely.geometry.base import BaseGeometry

from app import config, http
from app.analisis import compatibilidad
from app.fuentes import gencat_wfs
from app.fuentes.base import error, resultado

FUENTE = "Mapa Urbanístic de Catalunya (MUC), Generalitat de Catalunya"
URL_MUC = "https://sig.gencat.cat/visors/hipermapa.html"
RPUC_API = "https://planejamenturbanisme.territori.gencat.cat/RPUC-portal/rest/consulta"
RPUC_FICHA = "https://planejamenturbanisme.territori.gencat.cat/rpucportal/#/consulta/detallExpedient/{codi}"

AVISO = ""


async def consultar(parcela: BaseGeometry) -> dict:
    try:
        quals = await gencat_wfs.que_intersectan(config.CAPA_MUC_QUALIF, parcela)
        clases = await gencat_wfs.que_intersectan(config.CAPA_MUC_CLASSIF, parcela)
        sectores = await gencat_wfs.que_intersectan(config.CAPA_MUC_SECTOR, parcela)
        derivados = await gencat_wfs.que_intersectan(config.CAPA_MUC_PDERIVAT, parcela)
        planes = await gencat_wfs.entidades(config.CAPA_PLA_GENERAL, parcela.centroid.buffer(1))
    except http.ErrorFuente as e:
        return error(FUENTE, f"El servicio de urbanismo no responde: {e}", URL_MUC)

    if not quals and not clases:
        return resultado("sin_dato", FUENTE, URL_MUC, mensaje="El MUC no tiene datos para esta parcela.")

    calificaciones = [
        {
            "codigo_muc": q["props"].get("CODI_QUAL_MUC", ""),
            "descripcion_muc": q["props"].get("DESC_QUAL_MUC", ""),
            "codigo_municipal": q["props"].get("CODI_QUAL_AJUNT", ""),
            "descripcion_municipal": q["props"].get("DESC_QUAL_AJUNT", ""),
            "pct": q["pct"],
            "geom": q["geom"].intersection(parcela),
        }
        for q in quals
    ]
    clasificaciones = [
        {
            "codigo": c["props"].get("CODI_CLAS_MUC", ""),
            "descripcion": c["props"].get("DESC_CLAS_MUC", ""),
            "descripcion_municipal": c["props"].get("DESC_CLAS_AJUNT", ""),
            "pct": c["pct"],
        }
        for c in clases
    ]
    sectores_out = [
        {
            "codigo": s["props"].get("CODI_SECTOR_AJUNT", ""),
            "descripcion": s["props"].get("DESC_SECTOR_AJUNT") or s["props"].get("DESC_SECTOR_MUC", ""),
            "tipo": s["props"].get("TIPUS_SECTOR", ""),
            "desarrollo": s["props"].get("TIPUS_DESENVOL", ""),
            "indice_edificabilidad_bruta": s["props"].get("INDEX_EDIF_BRUTA"),
            "densidad": s["props"].get("DENSITAT"),
            "superficie": s["props"].get("SUPERFICIE_NORMATIVA") or s["props"].get("SUPERFICIE_CALCULADA"),
            "pct": s["pct"],
        }
        for s in sectores
    ]
    derivados_out = [
        {
            "clave": d["props"].get("CODI_CLAU_PLA_DERIVAT", ""),
            "descripcion": d["props"].get("DESC_CLAU_PLA_DERIVAT") or d["props"].get("DESC_CLAU_MUC", ""),
            "pct": d["pct"],
        }
        for d in derivados
    ]
    plan = None
    if planes:
        p = planes[0]["props"]
        plan = {
            "municipio": p.get("NOM_MUNI", ""),
            "codigo_municipio": (p.get("MUNICIPI") or "")[:5],
            "tipo": p.get("DESC_TIPEX", ""),
            "expediente": p.get("NUM_EXP", ""),
            "aprobacion": p.get("DATA_AD", ""),
            "publicacion_dogc": p.get("PUB_DOGC", ""),
            "url_rpuc": p.get("URL_RPUC", ""),
        }

    compat = compatibilidad.evaluar(calificaciones, clasificaciones)

    return resultado(
        "ok",
        FUENTE,
        URL_MUC,
        fecha_dato="MUC vigente en la fecha de consulta",
        calificaciones=calificaciones,
        clasificaciones=clasificaciones,
        sectores=sectores_out,
        planes_derivados=derivados_out,
        plan_general=plan,
        compatibilidad=compat,
        aviso=AVISO,
    )


async def cambios_planeamiento(codigo_ine5: str, nombre_municipio: str, anios: int = 6) -> dict:
    """Expedientes aprobados en el RPUC para el municipio (recientes primero)."""
    fuente = "Registre de Planejament Urbanístic de Catalunya (RPUC)"
    url = "https://planejamenturbanisme.territori.gencat.cat/rpucportal/"
    if not codigo_ine5:
        return resultado("sin_dato", fuente, url, mensaje="Municipio no identificado.")
    try:
        d = await http.get_json(
            f"{RPUC_API}/basica",
            {"tema": "", "municipi": codigo_ine5, "idioma": "ca", "firstRecord": "1", "rpp": "400", "sortDirection": "desc"},
        )
    except http.ErrorFuente as e:
        return error(fuente, f"El RPUC no responde: {e}", url)
    return resultado("ok", fuente, url, fecha_dato="Expedientes inscritos en la fecha de consulta",
                     **parse_rpuc(d, nombre_municipio, anios))


def parse_rpuc(d: dict, nombre_municipio: str, anios: int = 6) -> dict:
    limite = date.today().replace(year=date.today().year - anios)
    municipales, supramunicipales = [], []
    for e in d.get("llistat", []):
        try:
            f = datetime.strptime((e.get("data") or "")[:10], "%Y-%m-%d").date()
        except ValueError:
            f = None
        item = {
            "codigo": e.get("codi"),
            "expediente": e.get("nomComplet", ""),
            "instrumento": e.get("instrumentca", ""),
            "titulo": e.get("tema", ""),
            "vigente": e.get("vigencia") == "SI",
            "fecha": f.isoformat() if f else "",
            "url": RPUC_FICHA.format(codi=e.get("codi")),
        }
        es_local = (e.get("municipi") or "").strip().lower() == (nombre_municipio or "").strip().lower()
        (municipales if es_local else supramunicipales).append(item)
    municipales.sort(key=lambda x: x["fecha"], reverse=True)
    recientes = [m for m in municipales if m["fecha"] and m["fecha"] >= limite.isoformat()]
    return {
        "total_municipio": len(municipales),
        "recientes": recientes,
        "anios": anios,
        "supramunicipales_vigentes": [s for s in supramunicipales if s["vigente"]][:15],
        "aviso": "El RPUC recoge los instrumentos aprobados e inscritos. Los expedientes en tramitación "
                 "(aprobación inicial o provisional) se consultan en el ayuntamiento.",
    }
