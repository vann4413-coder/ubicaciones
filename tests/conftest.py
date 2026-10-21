"""Simula todas las fuentes externas.

Las respuestas de Catastro, ICGC, Idescat y RPUC son copias reales capturadas el
16/10/2026 para la parcela 4595201DF5949N (Mataró). Las capas geométricas (MUC,
ACA, tramos de IMD, OSM) se construyen alrededor de la parcela real con los mismos
nombres de campo que devuelven los servicios.
"""
import io
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from PIL import Image
from shapely.geometry import LineString, Polygon, box, mapping

from app import config, geo
from app.fuentes import catastro

FIX = Path(__file__).parent / "fixtures"


def leer(n):
    return (FIX / n).read_text(encoding="utf-8")


PARCELA = catastro.parse_gml_parcelas(leer("parcela.gml"))[0]["geom"]
MINX, MINY, MAXX, MAXY = PARCELA.bounds
MEDIO_X = (MINX + MAXX) / 2


def fc(features):
    return {"type": "FeatureCollection", "features": features, "totalFeatures": len(features)}


def feat(geom, props):
    return {"type": "Feature", "geometry": mapping(geom), "properties": props}


def capas_wfs():
    oeste = box(MINX - 50, MINY - 50, MEDIO_X + 10, MAXY + 50)
    este = box(MEDIO_X + 10, MINY - 50, MAXX + 50, MAXY + 50)
    c32 = LineString([(MINX - 400, MINY - 300), (MAXX + 400, MINY - 250)])
    return {
        config.CAPA_MUC_QUALIF: fc([
            feat(oeste, {"CODI_QUAL_MUC": "A1", "DESC_QUAL_MUC": "Activitat econòmica, Indústria", "CODI_QUAL_AJUNT": "22a",
                         "DESC_QUAL_AJUNT": "Zona industrial", "CODI_INE": "08121"}),
            feat(este, {"CODI_QUAL_MUC": "SX2", "DESC_QUAL_MUC": "Sistemes, Viari, Altre viari en sòl urbà",
                        "CODI_QUAL_AJUNT": "SX2", "DESC_QUAL_AJUNT": "Sistema viari", "CODI_INE": "08121"}),
        ]),
        config.CAPA_MUC_CLASSIF: fc([feat(box(MINX - 500, MINY - 500, MAXX + 500, MAXY + 500),
                                          {"CODI_CLAS_MUC": "SUC", "DESC_CLAS_MUC": "Sòl urbà", "CODI_CLAS_AJUNT": "SU", "DESC_CLAS_AJUNT": "Sòl Urbà"}),
                                     feat(box(MAXX + 2000, MAXY + 2000, MAXX + 3000, MAXY + 3000),
                                          {"CODI_CLAS_MUC": "SNU", "DESC_CLAS_MUC": "Sòl no urbanitzable", "CODI_CLAS_AJUNT": "SNU", "DESC_CLAS_AJUNT": "SNU"})]),
        config.CAPA_MUC_SECTOR: fc([]),
        config.CAPA_MUC_PDERIVAT: fc([]),
        config.CAPA_PLA_GENERAL: fc([feat(box(MINX - 5000, MINY - 5000, MAXX + 5000, MAXY + 5000), {
            "MUNICIPI": "081213", "NOM_MUNI": "Mataró", "CODI_TIPEX": "004", "TIPEX": "PGO", "NUM_EXP": "1994 / 000689 / B",
            "DESC_TIPEX": "Pla general d'ordenació", "DATA_AD": "1997-04-03", "PUB_DOGC": "1997-04-24",
            "URL_RPUC": "https://planejamenturbanisme.territori.gencat.cat/rpucportal/#/consulta/detallExpedient/84123"})]),
        config.CAPA_ZFP: fc([]),
        config.CAPA_LI10: fc([]),
        config.CAPA_LI100: fc([]),
        config.CAPA_LI500: fc([feat(box(MINX - 100, MINY - 100, MINX + 20, MAXY + 100), {"NOM_AV": "Riera de prova", "ARPSI": "ES100700"})]),
        config.CAPA_DPH: fc([feat(LineString([(MINX - 60, MINY - 200), (MINX - 60, MAXY + 200)]).buffer(3), {"NOM_AV": "Riera de prova"})]),
        "XARXES_TRANSPORT:XT_VIARI_IMD_2023": fc([]),
        "XARXES_TRANSPORT:XT_VIARI_IMD_2022": fc([feat(c32, {
            "CARRETERA": "C-32", "IMD": 56289, "PERCENTATGE_PESANTS": 4.69, "PK_ESTACIO": "100+544", "PKINICI": "100+000",
            "PKFINAL": "104+000", "CODI_ESTACIO": "AC321018", "ORGANISME": "Generalitat de Catalunya",
            "TIPUS_AFORAMENT": "Permanent", "ANY_MESURA": 2020})]),
    }, c32


def png(transparente=True, mitad=False):
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    if not transparente:
        img = Image.new("RGBA", (256, 256), (0, 0, 255, 200))
    if mitad:
        for x in range(128):
            for y in range(256):
                img.putpixel((x, y), (0, 0, 255, 200))
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


def overpass(c32):
    def nodo_wgs(x, y):
        lon, lat = geo.a_wgs84(x, y)
        return {"lon": lon, "lat": lat}

    calle = LineString([(MINX - 30, MINY - 3), (MAXX + 30, MINY - 3)])
    els = [
        {"type": "way", "id": 1, "tags": {"highway": "motorway", "ref": "C-32", "name": "Autopista del Maresme"},
         "geometry": [nodo_wgs(*c) for c in c32.coords]},
        {"type": "way", "id": 2, "tags": {"highway": "residential", "name": "Carrer de prova"},
         "geometry": [nodo_wgs(*c) for c in calle.coords]},
        {"type": "node", "id": 3, **nodo_wgs(MAXX + 900, MINY - 250), "tags": {"highway": "motorway_junction", "ref": "95", "name": "Mataró Centre"}},
        {"type": "node", "id": 4, **nodo_wgs(MAXX + 300, MAXY + 100), "tags": {"amenity": "restaurant", "name": "Restaurant A"}},
        {"type": "node", "id": 5, **nodo_wgs(MAXX + 1500, MAXY), "tags": {"shop": "supermarket", "name": "Super B", "brand": "Marca B"}},
        {"type": "node", "id": 6, **nodo_wgs(MINX - 700, MINY), "tags": {"tourism": "hotel", "name": "Hotel C"}},
        {"type": "node", "id": 7, **nodo_wgs(MINX - 200, MINY), "tags": {"amenity": "fuel", "name": "Estació D", "brand": "Plenoil"}},
    ]
    return {"elements": els}


def carburantes():
    lon, lat = geo.a_wgs84(MINX - 200, MINY)
    lon2, lat2 = geo.a_wgs84(MAXX + 5000, MAXY)
    f = lambda v: str(v).replace(".", ",")  # noqa: E731
    return {"Fecha": "16/10/2026 15:52:27", "ListaEESSPrecio": [
        {"Rótulo": "PLENOIL", "Dirección": "CARRETERA PROVA, KM 1", "Municipio": "Mataró", "Horario": "L-D: 24H",
         "Latitud": f(lat), "Longitud (WGS84)": f(lon), "Precio Gasoleo A": "1,399", "Precio Gasolina 95 E5": "1,459"},
        {"Rótulo": "LEJOS", "Dirección": "LEJOS", "Municipio": "X", "Horario": "", "Latitud": f(lat2), "Longitud (WGS84)": f(lon2)},
    ]}


def suelos():
    """Mismo formato que la API del ICGC: un emplazamiento que pisa la esquina de la parcela y otro cercano."""
    esquina = geo.geom_a_wgs84(box(MINX - 20, MINY - 20, MINX + 30, MINY + 30))
    cerca = geo.geom_a_wgs84(box(MAXX + 80, MAXY + 80, MAXX + 120, MAXY + 120))
    lejos = geo.geom_a_wgs84(box(MAXX + 5000, MAXY, MAXX + 5100, MAXY + 100))
    def f(g, nombre, tipus, estat):
        return {"type": "Feature", "geometry": mapping(g), "properties": {
            "Denominació finca": nombre, "Tipus": tipus, "Estat": estat, "Data de declaració": "20210315",
            "Municipi": "MATARÓ", "Adreça": "C/ PROVA", "Data de desclassificació": None}}
    return {"type": "FeatureCollection", "numberMatched": 3, "features": [
        f(esquina, "SC_00001 - ANTIGA INDÚSTRIA", "Declaració de sòl contaminat", "Actiu"),
        f(cerca, "SC_00002 - TALLER", "Recuperació voluntària", "Inactiu"),
        f(lejos, "SC_00003 - LLUNY", "Recuperació voluntària", "Inactiu")]}


@pytest.fixture
def datos_locales(tmp_path, monkeypatch):
    lon, lat = geo.a_wgs84(MAXX + 800, MAXY + 400)
    red = tmp_path / "capacidad_red.csv"
    red.write_text("gestor,nudo,tension_kv,lon,lat,cap_disponible_mw,cap_ocupada_mw,cap_tramite_mw,marca_0,fecha_fichero\n"
                   f"e-distribución,SE MATARO,25,{lon},{lat},1.8,12.5,0.6,0,2026-10\n", encoding="utf-8")
    afor = tmp_path / "aforos.csv"
    afor.write_text("carretera,pk,imd,pct_pesados,anio,organismo,tipo,codigo_estacion,lon,lat,fuente\n"
                    "C-32,100+544,61234,4.9,2025,Generalitat de Catalunya,Permanent,AC321018,,,"
                    "\"Generalitat, Pla d'aforaments 2025\"\n", encoding="utf-8")
    monkeypatch.setattr(config, "FICHERO_RED", red)
    monkeypatch.setattr(config, "FICHERO_AFOROS", afor)
    monkeypatch.setattr(config, "FICHERO_SUELO", tmp_path / "no_existe.csv")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    return tmp_path


@pytest.fixture
def fuentes_simuladas(datos_locales):
    capas, c32 = capas_wfs()
    with respx.mock(assert_all_called=False) as m:
        m.get(url__startswith=f"{config.CATASTRO_COORD}/Consulta_RCCOOR").respond(json=json.loads(leer("rccoor.json")))
        m.get(url__startswith=f"{config.CATASTRO_CALLEJERO}/Consulta_DNPRC").respond(json=json.loads(leer("dnprc.json")))
        m.get(url__startswith=config.CATASTRO_WFS_CP).respond(text=leer("parcela.gml"))

        def wfs(request):
            capa = parse_qs(urlparse(str(request.url)).query)["typeNames"][0]
            return httpx.Response(200, json=capas.get(capa, fc([])))
        m.get(url__startswith=config.GENCAT_WFS).mock(side_effect=wfs)

        def idee(request):
            capa = parse_qs(urlparse(str(request.url)).query)["layers"][0]
            return httpx.Response(200, content=png(mitad=(capa == "NZ.Flood.FluvialT500")), headers={"content-type": "image/png"})
        m.get(url__startswith=config.IDEE_INUNDACIONES_WMS).mock(side_effect=idee)

        m.post(config.OVERPASS_URL).respond(json=overpass(c32))
        m.get(url__startswith="https://sedeaplicaciones.minetur.gob.es").respond(json=carburantes())
        m.get(url__startswith=config.IDESCAT_EMEX).respond(json=json.loads(leer("idescat.json")))
        m.get(url__startswith=f"{config.ICGC_GEOCODER}/invers").respond(json=json.loads(leer("icgc_invers.json")))
        m.get(url__startswith="https://api.icgc.cat/territorial/collections/sols-contaminats").respond(json=suelos())
        m.get(url__startswith="https://planejamenturbanisme.territori.gencat.cat").respond(json=json.loads(leer("rpuc.json")))
        yield m


@pytest.fixture(autouse=True)
def limpiar_cache():
    from app import http
    http._cache.clear()
    http._cliente = None
    yield
