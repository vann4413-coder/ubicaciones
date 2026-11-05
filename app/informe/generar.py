"""Orquesta todas las consultas y construye el informe completo de una parcela."""
import asyncio
import logging
from datetime import datetime

from app import config, geo
from app.analisis import evolucion, parcela_metricas, puntuacion, resumen
from app.fuentes import (catastro, gasolineras, geocoder, inundabilidad, osm, poblacion, red_electrica, suelo,
                         suelos_contaminados, trafico, urbanismo)
from app.fuentes import entorno as entorno_5km
from app.fuentes import titulares
from app.fuentes.base import error, resultado

log = logging.getLogger(__name__)


async def _seguro(coro, fuente: str, limite: float = 60):
    """Ninguna fuente puede tumbar ni bloquear el informe: si falla o tarda demasiado, queda marcada como error."""
    try:
        return await asyncio.wait_for(coro, timeout=limite)
    except asyncio.TimeoutError:
        log.warning("Tiempo agotado en %s", fuente)
        return error(fuente, "La fuente no ha respondido a tiempo.")
    except Exception as e:  # noqa: BLE001
        log.exception("Fallo en %s", fuente)
        return error(fuente, f"Error inesperado: {e}")


async def construir(rc: str, potencia_mw: float | None = None, sup_minima: float | None = None,
                    grupos: list[str] | None = None, usos: dict | None = None) -> dict:
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

    urb, aca, snczi, entorno, gas, pob, cambios, evo, contam, entorno5, titul = await asyncio.gather(
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
        _seguro(titulares.consultar(g, parcela["rc"][:14]), titulares.FUENTE),
    )
    titul = completar_titulares(titul, gas, entorno5)
    traf = await _seguro(trafico.consultar(g, entorno if entorno.get("estado") == "ok" else {}), "Aforos")
    if traf.get("estado") in ("ok", "sin_dato"):
        traf["via_parcela"] = trafico.via_de_la_parcela(traf, parcela.get("direccion", ""), nombre_muni)
    red = red_electrica.consultar(g)
    snu = any(c.get("codigo", "").upper().startswith("SNU") and c.get("pct", 0) >= 50 for c in (urb.get("clasificaciones") or []))
    precio = suelo.consultar(cod_ine, pob.get("poblacion") if pob.get("estado") == "ok" else None,
                             parcela.get("sup_grafica"), suelo_no_urbanizable=snu)
    metr = parcela_metricas.metricas(g)
    inund_res = inundabilidad.combinar(aca, snczi)

    datos_puntuacion = {"urbanismo": urb, "inundabilidad": inund_res, "red": red, "trafico": traf, "metricas": metr,
                        "entorno": entorno5}
    punt = puntuacion.calcular_todos(datos_puntuacion, potencia_mw, sup_minima, grupos, usos)

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
        "titulares": titul,
        "gasolineras": gas,
        "poblacion": pob,
        "suelo": precio,
        "puntuaciones": punt,
        "parametros": {"potencia_mw": potencia_mw, "sup_minima": sup_minima, "grupos": list(punt), "usos": usos or {}},
    }
    inf["resumen"], inf["resumen_origen"] = await resumen.resumen_ia(inf)
    inf["pasos"] = resumen.riesgos_y_pasos(inf)
    inf["anexo"] = anexo(inf)
    return inf


def completar_titulares(titul: dict, gas: dict, entorno5: dict) -> dict:
    """Añade a los registros públicos la estación de servicio y los negocios con rótulo que están en la parcela."""
    if titul.get("estado") != "ok":
        titul = {**titul, "registros": []}
    extra = []
    for e in (gas.get("estaciones") or []) if gas.get("estado") == "ok" else []:
        if e["distancia_m"] == 0:
            extra.append({"fuente": "Geoportal de carburantes (Ministerio)", "nombre": e["marca"], "actividad": "Estación de servicio",
                          "empresa": "", "cif": "", "contacto": "", "detalle": e.get("direccion", ""),
                          "situacion": "En la parcela", "distancia_m": 0})
    for p in (entorno5.get("puntos") or []) if entorno5.get("estado") == "ok" else []:
        if p["distancia_m"] == 0 and p.get("nombre") and p["cat"] != "gasolineras":
            extra.append({"fuente": "OpenStreetMap", "nombre": p["nombre"], "actividad": p.get("tipo", ""),
                          "empresa": "", "cif": "", "contacto": "", "detalle": p.get("direccion", ""),
                          "situacion": "En la parcela", "distancia_m": 0})
    titul["registros"] = extra + (titul.get("registros") or [])
    return titul


def anexo(inf: dict) -> list[dict]:
    """Fuente, fecha y estado de cada dato."""
    filas = []
    for seccion, clave in [
        ("Parcela", "parcela"), ("Urbanismo", "urbanismo"), ("Cambios de planeamiento", "cambios"), ("Suelos contaminados", "suelos_contaminados"),
        ("Inundabilidad (ACA)", "inundabilidad_aca"), ("Inundabilidad (SNCZI)", "inundabilidad_snczi"),
        ("Tráfico", "trafico"), ("Red eléctrica", "red"), ("Entorno (2 km)", "entorno"), ("Entorno (5 km)", "entorno5"),
        ("Gasolineras", "gasolineras"), ("Actividades y titulares", "titulares"),
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
