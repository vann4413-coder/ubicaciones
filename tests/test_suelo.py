import asyncio

from shapely.geometry import box


GML_BU = """<?xml version="1.0" encoding="UTF-8"?>
<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:gml="http://www.opengis.net/gml/3.2"
 xmlns:bu-ext2d="http://inspire.jrc.ec.europa.eu/schemas/bu-ext2d/2.0" xmlns:bu-core2d="http://inspire.jrc.ec.europa.eu/schemas/bu-core2d/2.0">
<wfs:member><bu-ext2d:Building gml:id="ES.SDGC.BU.1"><bu-core2d:geometry><bu-core2d:BuildingGeometry><bu-core2d:geometry>
<gml:Surface><gml:patches><gml:PolygonPatch><gml:exterior><gml:LinearRing>
<gml:posList srsDimension="2">0 0 10 0 10 10 0 10 0 0</gml:posList></gml:LinearRing></gml:exterior></gml:PolygonPatch></gml:patches></gml:Surface>
</bu-core2d:geometry></bu-core2d:BuildingGeometry></bu-core2d:geometry></bu-ext2d:Building></wfs:member></wfs:FeatureCollection>"""


def test_parse_edificios():
    from app.fuentes import catastro
    e = catastro.parse_gml_edificios(GML_BU)
    assert len(e) == 1 and e[0].area == 100


def test_tipo_actividad():
    from app.suelo import tipo_actividad
    assert tipo_actividad({"CODI_QUAL_MUC": "A1", "DESC_QUAL_MUC": "Activitat econòmica, Indústria"}) == "industria"
    assert tipo_actividad({"CODI_QUAL_MUC": "A2", "DESC_QUAL_MUC": "Activitat econòmica, Terciari"}) == "terciario"
    assert tipo_actividad({"CODI_QUAL_MUC": "R4", "DESC_QUAL_MUC": "Residencial"}) is None
    assert tipo_actividad({"CODI_QUAL_MUC": "SX2", "DESC_QUAL_MUC": "Sistemes, Viari"}) is None


def test_buscar(monkeypatch):
    from app import geo, suelo
    from app.fuentes import catastro, gencat_wfs
    x0, y0 = geo.a_utm(2.44, 41.54)
    ind = box(x0, y0, x0 + 600, y0 + 600)

    async def ent(capa, zona, margen=0, max_entidades=500):
        return [{"props": {"CODI_QUAL_MUC": "A1", "DESC_QUAL_MUC": "Activitat econòmica, Indústria", "CODI_QUAL_AJUNT": "2d1",
                           "DESC_QUAL_AJUNT": "Zona industrial", "CODI_INE": "081213"}, "geom": ind},
                {"props": {"CODI_QUAL_MUC": "R4", "DESC_QUAL_MUC": "Residencial"}, "geom": box(x0 + 700, y0, x0 + 900, y0 + 200)}]

    vacia = box(x0 + 10, y0 + 10, x0 + 110, y0 + 110)        # 10.000 m², sin edificios
    edificada = box(x0 + 200, y0 + 10, x0 + 300, y0 + 110)   # 10.000 m², 50 % edificada
    pequena = box(x0 + 400, y0 + 10, x0 + 420, y0 + 30)      # 400 m², sola
    trozo1 = box(x0 + 400, y0 + 200, x0 + 425, y0 + 230)     # 750 m² } contiguas: 1.500 m²
    trozo2 = box(x0 + 425, y0 + 200, x0 + 450, y0 + 230)     # 750 m² }
    gasolinera = box(x0 + 10, y0 + 300, x0 + 60, y0 + 360)   # 3.000 m², sin huella en BU pero 786 m² en la ficha
    residencial = box(x0 + 710, y0 + 10, x0 + 810, y0 + 110)

    async def parc(b):
        return [{"rc": "1111111DF1111A", "area": 1e4, "geom": vacia}, {"rc": "2222222DF2222A", "area": 1e4, "geom": edificada},
                {"rc": "3333333DF3333A", "area": 400, "geom": pequena}, {"rc": "4444444DF4444A", "area": 1e4, "geom": residencial},
                {"rc": "5555555DF5555A", "area": 750, "geom": trozo1}, {"rc": "6666666DF6666A", "area": 750, "geom": trozo2},
                {"rc": "7777777DF7777A", "area": 3000, "geom": gasolinera}]

    async def edif(b):
        return [box(x0 + 200, y0 + 10, x0 + 250, y0 + 110)]
    monkeypatch.setattr(gencat_wfs, "entidades", ent)
    monkeypatch.setattr(catastro, "parcelas_en_bbox", parc)
    monkeypatch.setattr(catastro, "edificios_en_bbox", edif)
    monkeypatch.setattr(suelo, "PAUSA_S", 0)

    async def muni(lon, lat):
        return {"nombre": "Pineda de Mar", "codigo6": "081638", "codigo_ine": "08163", "comarca": "Maresme"}
    monkeypatch.setattr(suelo.geocoder, "municipio_en_punto", muni)

    async def ficha(rc):
        if rc.startswith("7777"):
            return {"uso": "Industrial (Est servicio)", "construido": 786}
        return {"uso": "Obras de urbanización y jardineria, suelos sin edificar", "construido": 0}
    monkeypatch.setattr(suelo, "ficha_catastro", ficha)
    suelo._cache.clear()
    lon1, lat1 = geo.a_wgs84(x0 + 1000, y0 + 1000)
    r = asyncio.run(suelo.buscar((2.44, 41.54, lon1, lat1), sup_min=1000, max_edif_pct=10))
    assert [p["rc"] for p in r["parcelas"]] == ["1111111DF1111A", "5555555DF5555A", "6666666DF6666A"]
    assert r["parcelas"][1]["grupo"] == r["parcelas"][2]["grupo"] and r["parcelas"][1]["superficie_grupo_m2"] == 1500
    assert r["resumen"]["conjuntos"] == 2
    assert r["parcelas"][0]["municipio"] == "Pineda de Mar" and r["resumen"]["municipios"] == ["Pineda de Mar"]
    assert r["parcelas"][0]["pct_edificado"] == 0 and r["parcelas"][0]["calificacion"] == "2d1 Zona industrial"
    r = asyncio.run(suelo.buscar((2.44, 41.54, lon1, lat1), sup_min=1000, max_edif_pct=60))
    assert {p["rc"] for p in r["parcelas"]} == {"1111111DF1111A", "2222222DF2222A", "5555555DF5555A", "6666666DF6666A", "7777777DF7777A"}
    # zona dibujada que solo abarca la parcela vacía
    pol = [geo.a_wgs84(x0, y0), geo.a_wgs84(x0 + 150, y0), geo.a_wgs84(x0 + 150, y0 + 150), geo.a_wgs84(x0, y0 + 150)]
    r = asyncio.run(suelo.buscar(None, sup_min=1000, max_edif_pct=60, poligono_wgs=[list(v) for v in pol]))
    assert [p["rc"] for p in r["parcelas"]] == ["1111111DF1111A"]
    assert r["parcelas"][0]["municipio"] == "Pineda de Mar" and r["resumen"]["municipios"] == ["Pineda de Mar"]


def test_zona_grande():
    import pytest
    from app import suelo
    with pytest.raises(ValueError):
        asyncio.run(suelo.buscar((1.5, 41.0, 2.5, 42.0)))


def test_pagina_admin(monkeypatch):
    from fastapi.testclient import TestClient
    import app.cuentas as cuentas
    import app.main as main
    import app.rutas_suelo as rs
    monkeypatch.setattr(rs, "usuario_actual", lambda r: {"id": 1, "email": "a@a"})
    monkeypatch.setattr(cuentas, "es_admin", lambda u: True)
    assert "Buscador de suelo" in TestClient(main.app).get("/admin/suelo").text
    monkeypatch.setattr(cuentas, "es_admin", lambda u: False)
    assert TestClient(main.app).get("/admin/suelo").status_code == 403
