"""Orquesta todas las consultas y construye el informe completo de una parcela."""
import asyncio
import logging
from datetime import datetime

from app import config, geo
from app.analisis import evolucion, parcela_metricas, puntuacion, resumen
from app.fuentes import (catastro, gasolineras, geocoder, inundabilidad, osm, poblacion, red_electrica, suelo,
                         suelos_contaminados, trafico, urbanismo)
from app.fuentes import entorno as entorno_5km
from app.fuentes.base import error, resultado

log = logging.getLogger(__name__)


async def _seguro(coro, fuente: str):
    """Ninguna fuente puede tumbar el informe: si falla, queda marcada como error."""
    try:
        return await coro
    except Exception as e:  # noqa: BLE001
        log.exception("Fallo en %s", fuente)
        return error(fuente, f"Error inesperado: {e}")


async def construir(rc: str, potencia_mw: float | None = None, sup_minima: float | None = None) -> dict:
    parcela = await catastro.consultar(rc)
    if parcela["estado"] != "ok":
        return {"error": parcela.get("mensaje", "No se pudo obtener la parcela"), "parcela": parcela}
    g = parcela["geom"]
    lon, lat = geo.a_wgs84(g.centroid.x, g.centroid.y)

    muni = await _seguro(geocoder.municipio_en_punto(lon, lat), "ICGC") or {}
    if "estado" in muni:  # devolvió un error
        muni = {}
    cod6 = muni.get("codigo6", "")
    cod_ine = muni.get("codigo_ine") or (parcela.get("cod_ine_prov", "") + parcela.get("cod_ine_mun", "")).strip()
    nombre_muni = muni.get("nombre") or parcela.get("municipio", "").title()
    prov = (cod_ine or "")[:2] or parcela.get("cod_ine_prov", "")

    urb, aca, snczi, entorno, gas, pob, cambios, evo, contam, entorno5 = await asyncio.gather(
        _seguro(urbanismo.consultar(g), urbanismo.FUENTE),
        _seguro(inundabilidad.consultar_aca(g), inundabilidad.FUENTE_ACA),
        _seguro(inundabilidad.consultar_snczi(g), inundabilidad.FUENTE_SNCZI),
        _seguro(osm.consultar(g), osm.FUENTE),
        _seguro(gasolineras.consultar(g, prov, config.RADIO_ENTORNO_MAX), gasolineras.FUENTE),
        _seguro(poblacion.consultar(cod6), poblacion.FUENTE),
        _seguro(urbanismo.cambios_planeamiento(cod_ine, nombre_muni), "RPUC"),
        _seguro(evolucion.consultar(g), "ICGC"),
        _seguro(suelos_contaminados.consultar(g), suelos_contaminados.FUENTE),
        _seguro(entorno_5km.consultar(g, config.RADIO_ENTORNO_MAX), entorno_5km.FUENTE),
    )
    traf = await _seguro(trafico.consultar(g, entorno if entorno.get("estado") == "ok" else {}), "Aforos")
    red = red_electrica.consultar(g)
    precio = suelo.consultar(cod_ine)
    metr = parcela_metricas.metricas(g)
    inund_res = inundabilidad.combinar(aca, snczi)

    datos_puntuacion = {"urbanismo": urb, "inundabilidad": inund_res, "red": red, "trafico": traf, "metricas": metr}
    punt = puntuacion.calcular_todos(datos_puntuacion, potencia_mw, sup_minima)

    inf = {
        "generado": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "rc": parcela["rc"],
        "lon": lon, "lat": lat,
        "utm": (round(g.centroid.x, 1), round(g.centroid.y, 1)),
        "municipio": {"nombre": nombre_muni, "codigo_ine": cod_ine, "codigo6": cod6, "comarca": muni.get("comarca", "")},
        "parcela": parcela,
        "metricas": metr,
        "urbanismo": urb,
        "cambios": cambios,
        "evolucion": evo,
        "suelos_contaminados": contam,
        "inundabilidad_aca": aca,
        "inundabilidad_snczi": snczi,
        "inundabilidad_resumen": inund_res,
        "red": red,
        "trafico": traf,
        "entorno": entorno,
        "entorno5": entorno5,
        "gasolineras": gas,
        "poblacion": pob,
        "suelo": precio,
        "puntuaciones": punt,
        "parametros": {"potencia_mw": potencia_mw, "sup_minima": sup_minima},
    }
    inf["resumen"], inf["resumen_origen"] = await resumen.resumen_ia(inf)
    inf["pasos"] = resumen.riesgos_y_pasos(inf)
    inf["anexo"] = anexo(inf)
    return inf


def anexo(inf: dict) -> list[dict]:
    """Fuente, fecha y estado de cada dato."""
    filas = []
    for seccion, clave in [
        ("Parcela", "parcela"), ("Urbanismo", "urbanismo"), ("Cambios de planeamiento", "cambios"), ("Suelos contaminados", "suelos_contaminados"),
        ("Inundabilidad (ACA)", "inundabilidad_aca"), ("Inundabilidad (SNCZI)", "inundabilidad_snczi"),
        ("Tráfico", "trafico"), ("Red eléctrica", "red"), ("Entorno (2 km)", "entorno"), ("Entorno (5 km)", "entorno5"),
        ("Gasolineras", "gasolineras"),
        ("Población", "poblacion"), ("Valor del suelo", "suelo"),
    ]:
        d = inf.get(clave) or {}
        filas.append({
            "seccion": seccion, "fuente": d.get("fuente", ""), "url": d.get("url", ""),
            "fecha_dato": d.get("fecha_dato", ""), "fecha_consulta": d.get("fecha_consulta", ""),
            "estado": d.get("estado", ""), "mensaje": d.get("mensaje", ""),
        })
    ev = inf.get("evolucion") or {}
    filas.append({"seccion": "Evolución histórica", "fuente": ev.get("fuente", ""), "url": ev.get("url", ""),
                  "fecha_dato": ", ".join(i["anio"] for i in ev.get("imagenes", [])), "fecha_consulta": "",
                  "estado": "ok", "mensaje": ""})
    return filas


def para_json(obj):
    """Quita geometrías y objetos no serializables para la API."""
    from shapely.geometry.base import BaseGeometry
    if isinstance(obj, BaseGeometry):
        return None
    if isinstance(obj, dict):
        return {k: para_json(v) for k, v in obj.items() if k not in ("geom", "geoms")}
    if isinstance(obj, (list, tuple)):
        return [para_json(v) for v in obj]
    return obj


# Reexport para pruebas
__all__ = ["construir", "para_json", "resultado"]
