import asyncio

from app.fuentes import catastro, geocoder, poblacion, urbanismo
from app.informe import generar, render
from tests.conftest import leer
import json


def correr(c):
    return asyncio.run(c)


# ---------- Parsers con respuestas reales ----------

def test_rccoor_real():
    r = catastro.parse_rccoor(json.loads(leer("rccoor.json")))
    assert r == [{"rc": "4595201DF5949N", "direccion": "CL PRAT DE LA RIBA 110 MATARO (BARCELONA)"}]


def test_dnprc_real():
    d = catastro.parse_dnprc(json.loads(leer("dnprc.json")))
    assert d["clase"] == "Urbano"
    assert d["sup_construida"] == 2607
    assert d["sup_suelo"] == 10051
    assert d["anio_construccion"] == 1900
    assert d["cod_ine_prov"] + d["cod_ine_mun"] == "08121"


def test_gml_parcela_real():
    p = catastro.parse_gml_parcelas(leer("parcela.gml"))[0]
    assert p["rc"] == "4595201DF5949N"
    assert abs(p["geom"].area - 10051) / 10051 < 0.02  # área gráfica coherente con el GML


def test_idescat_real():
    assert poblacion.parse(json.loads(leer("idescat.json"))) == (131370, "2025")


def test_rpuc_separa_municipales():
    r = urbanismo.parse_rpuc(json.loads(leer("rpuc.json")), "Mataró", anios=6)
    assert r["total_municipio"] == 3
    assert [e["codigo"] for e in r["recientes"]] == ["300200", "300100"]
    assert r["supramunicipales_vigentes"][0]["codigo"] == "252472"


def test_normalizar_rc_y_coordenadas():
    assert catastro.normalizar_rc("4595201 df5949n") == "4595201DF5949N"
    assert catastro.normalizar_rc("hola") is None
    lon, lat = geocoder.interpretar_coordenadas("41.5446, 2.4527")
    assert (round(lon, 4), round(lat, 4)) == (2.4527, 41.5446)
    lon, lat = geocoder.interpretar_coordenadas("454402.58 4599346.09")
    assert abs(lon - 2.4528) < 0.001 and abs(lat - 41.5446) < 0.001


# ---------- Informe completo ----------

def test_informe_completo(fuentes_simuladas):
    inf = correr(generar.construir("4595201DF5949N"))
    assert "error" not in inf

    # Parcela y municipio
    assert inf["parcela"]["estado"] == "ok"
    assert inf["municipio"]["nombre"] == "Mataró" and inf["municipio"]["codigo_ine"] == "08121"
    assert inf["poblacion"]["poblacion"] == 131370

    # Urbanismo: dos calificaciones repartidas, la industrial domina
    u = inf["urbanismo"]
    assert u["estado"] == "ok"
    codigos = {q["codigo_muc"]: q["pct"] for q in u["calificaciones"]}
    assert set(codigos) == {"A1", "SX2"}
    assert abs(sum(codigos.values()) - 100) < 1
    assert [c["codigo"] for c in u["clasificaciones"]] == ["SUC"]  # la SNU lejana no cuenta
    assert u["plan_general"]["municipio"] == "Mataró"
    assert u["compatibilidad"]["gasolinera"]["nivel"] in ("compatible", "condicionado")

    # Inundabilidad: solo un borde en T500 (ACA) y la mitad de la imagen SNCZI T500
    r = inf["inundabilidad_resumen"]
    assert r["nivel"] == "T500"
    assert r["zfp_pct"] == 0
    assert 0 < inf["inundabilidad_aca"]["t500_pct"] < 30
    assert inf["inundabilidad_aca"]["en_zona_policia"] is True

    # Tráfico: el aforo local de 2025 gana al tramo de 2020 de la Generalitat
    c32 = next(c for c in inf["trafico"]["carreteras"] if c["carretera"] == "C-32")
    assert c32["imd"] == 61234 and c32["anio"] == 2025
    assert c32["titular"] == "Generalitat de Catalunya"
    acc = inf["trafico"]["accesos"]
    assert acc["frente_vial_m"] > 20  # la calle toca solo el borde sur de la parcela
    assert acc["salida_cercana"]["ref"] == "95"

    # Red eléctrica desde el fichero cargado
    n = inf["red"]["nudos"][0]
    assert n["nudo"] == "SE MATARO" and n["cargadores_150kw"] == 12

    # Entorno y gasolineras: la lejana se descarta
    assert [g["marca"] for g in inf["gasolineras"]["estaciones"]] == ["PLENOIL"]
    grupos = {p["grupo"] for p in inf["entorno"]["pois"]}
    assert {"Restauración", "Alojamiento", "Gasolineras"} <= grupos

    # Entorno de 5 km: categorías, anillos y polígonos; lo que pasa de 5 km se descarta
    e5 = inf["entorno5"]
    assert e5["estado"] == "ok"
    cats = {p["cat"] for p in e5["puntos"]}
    assert {"logistica", "electrolineras", "comercial", "hoteles", "restauracion"} <= cats
    assert "Hotel Lluny" not in [p["nombre"] for p in e5["puntos"]]
    fila = {f["clave"]: f for f in e5["resumen"]}
    assert fila["hoteles"]["cuenta"][1000] == 1 and fila["logistica"]["cuenta"][2000] == 0 and fila["logistica"]["cuenta"][5000] == 1
    assert fila["poligonos"]["mas_cercano"]["nombre"] == "Polígon G" and fila["poligonos"]["hectareas"][2000] == 12.0
    assert fila["comercios"]["cuenta"].get(5000) is None  # otros comercios solo hasta 1 km

    # Suelo sin tabla cargada: "sin dato", nunca inventado
    assert inf["suelo"]["estado"] == "sin_dato"

    # Puntuaciones coherentes
    for p in inf["puntuaciones"].values():
        assert p["semaforo"] in ("verde", "ambar", "rojo", "gris")
        assert p["total"] is None or 0 <= p["total"] <= 100
    assert inf["puntuaciones"]["promotor"]["subnotas"]["trafico"]["nota"] is not None

    # Suelos contaminados: el de la esquina está en la parcela, el lejano se descarta
    sc = inf["suelos_contaminados"]
    assert [e["nombre"] for e in sc["en_parcela"]] == ["SC_00001 - ANTIGA INDÚSTRIA"]
    assert 0 < sc["en_parcela"][0]["pct"] < 10
    assert [e["nombre"] for e in sc["cercanos"]] == ["SC_00002 - TALLER"]
    assert any("declarado contaminado" in p["texto"] for p in inf["pasos"])

    # Cambios de planeamiento
    assert len(inf["cambios"]["recientes"]) == 2

    # Resumen sin IA
    assert inf["resumen_origen"] == "reglas" and "Mataró" in inf["resumen"]
    assert any("cèdula" in p["texto"] for p in inf["pasos"])

    # Serializable para la API
    j = generar.para_json(inf)
    json.dumps(j, default=str)

    # HTML y PDF
    html = render.html(inf)
    for seccion in ["De un vistazo", "Riesgos y próximos pasos", "Parcela", "Urbanismo", "Cambios de planeamiento recientes",
                    "Agua: flujo preferente e inundabilidad", "Tráfico y accesos", "Entorno en 5 km: actividad económica", "Estaciones de servicio en 2 km",
                    "Red eléctrica", "Evolución histórica y suelo contaminado", "Valor de referencia del suelo",
                    "Puntuación detallada", "Fuentes y fechas"]:
        assert seccion in html, seccion
    assert "61.234" in html  # formato español
    assert "Zona de flujo preferente" in html and 'style="color:var(--verde)">No' in html
    assert "sin dato" in html.lower()


def test_fuente_caida_no_tumba_el_informe(fuentes_simuladas):
    import httpx
    from app import config
    fuentes_simuladas.get(url__startswith=config.GENCAT_WFS).mock(return_value=httpx.Response(503))
    inf = correr(generar.construir("4595201DF5949N"))
    assert inf["urbanismo"]["estado"] == "error"
    assert inf["inundabilidad_aca"]["estado"] == "error"
    # Sin urbanismo, el peso se reparte y baja la confianza
    p = inf["puntuaciones"]["gasolinera"]
    assert "urbanismo" in p["faltan"]
    assert p["confianza"] in ("media", "baja")
    assert "No disponible" in render.html(inf)


# ---------- Descarga de aforos del visor de la Generalitat ----------

def test_decodificar_powerbi_real():
    from scripts import descargar_aforos_gencat as d
    data = json.loads(leer("powerbi_dsr.json"))
    filas = d.decodificar_dsr(data)
    assert len(filas) == 4
    # Fila 1 completa; las siguientes repiten columnas según la máscara R
    assert filas[0]["COD_CARRETERA"] == "C-31" and filas[0]["IND_IMD"] == 104506 and filas[0]["DATA_ANYO"] == 2009
    assert filas[1]["COD_ESTACIO"] == "100-08" and filas[1]["IND_IMD"] == 57816 and filas[1]["DATA_ANYO"] == 2015
    assert filas[3]["IND_IMD"] == 93182 and filas[3]["DATA_ANYO"] == 2014
    aforos = d.a_aforos(filas, hasta=2025)
    assert len(aforos) == 1  # una estación: se queda con su medida más reciente
    a = aforos[0]
    assert a["anio"] == 2016 and a["carretera"] == "C-31" and a["organismo"] == "Generalitat de Catalunya"
    assert d._pk(195.108) == "195+108"


def test_familias_muc():
    from app.analisis.compatibilidad import familia
    assert familia("A2", "Activitat econòmica, Serveis") == "terciario"
    assert familia("A1", "Activitat econòmica, Industrial") == "actividad_economica"
    assert familia("SH", "Sistemes, Hidràulic") == "otros_sistemas"
    assert familia("N4", "No urbanitzable, Activitat autoritzada") == "no_urbanizable"
