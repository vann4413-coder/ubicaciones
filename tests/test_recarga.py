import io

from shapely.geometry import Point

from app import geo
from app.fuentes import recarga

XML = """<?xml version="1.0" encoding="UTF-8"?>
<d2:payload xmlns:d2="http://datex2.eu/schema/3/d2Payload" xmlns:egi="http://datex2.eu/schema/3/energyInfrastructure"
 xmlns:fac="http://datex2.eu/schema/3/facilities" xmlns:loc="http://datex2.eu/schema/3/locationReferencing"
 xmlns:com="http://datex2.eu/schema/3/common" xmlns:locx="http://datex2.eu/schema/3/locationReferencingExtension">
 <egi:energyInfrastructureTable>
  <egi:energyInfrastructureSite id="S1">
   <fac:name><com:values><com:value lang="es">Electrolinera Test</com:value></com:values></fac:name>
   <fac:operator><fac:name><com:values><com:value>IBERDROLA</com:value></com:values></fac:name></fac:operator>
   <fac:locationReference>
    <loc:coordinatesForDisplay><loc:latitude>41.5400</loc:latitude><loc:longitude>2.4400</loc:longitude></loc:coordinatesForDisplay>
    <loc:_locationReferenceExtension><locx:facilityLocation><locx:address>
      <locx:postcode>08301</locx:postcode>
      <locx:addressLine><locx:text><com:values><com:value>Dirección: Carrer Major 1</com:value></com:values></locx:text></locx:addressLine>
      <locx:addressLine><locx:text><com:values><com:value>Municipio: Mataró</com:value></com:values></locx:text></locx:addressLine>
    </locx:address></locx:facilityLocation></loc:_locationReferenceExtension>
   </fac:locationReference>
   <egi:energyInfrastructureStation>
    <egi:refillPoint><egi:connector><egi:maxPowerAtSocket>150000</egi:maxPowerAtSocket></egi:connector>
      <egi:connector><egi:maxPowerAtSocket>50000</egi:maxPowerAtSocket></egi:connector></egi:refillPoint>
    <egi:refillPoint><egi:connector><egi:maxPowerAtSocket>22</egi:maxPowerAtSocket></egi:connector></egi:refillPoint>
   </egi:energyInfrastructureStation>
  </egi:energyInfrastructureSite>
  <egi:energyInfrastructureSite id="S2">
   <fac:name><com:values><com:value>Lejos</com:value></com:values></fac:name>
   <fac:locationReference><loc:coordinatesForDisplay><loc:latitude>41.70</loc:latitude><loc:longitude>2.80</loc:longitude></loc:coordinatesForDisplay></fac:locationReference>
  </egi:energyInfrastructureSite>
 </egi:energyInfrastructureTable>
</d2:payload>"""


def test_parse_y_busqueda():
    sitios = recarga.parse_xml(io.BytesIO(XML.encode("utf-8")))
    assert len(sitios) == 2
    s = sitios[0]
    assert s["operador"] == "IBERDROLA" and s["nombre"] == "Electrolinera Test"
    assert s["direccion"] == "Carrer Major 1" and s["municipio"] == "Mataró" and s["cp"] == "08301"
    assert s["puntos"] == 2 and s["max_kw"] == 150 and s["ultrarrapidos"] == 1
    for x in sitios:
        x["x"], x["y"] = geo.a_utm(x["lon"], x["lat"])
    px, py = geo.a_utm(2.445, 41.54)
    cerca = recarga.buscar(sitios, Point(px, py).buffer(5), 2000)
    assert [c["id"] for c in cerca] == ["S1"] and cerca[0]["categoria"] == "ultrarrapida"
    r = recarga.resumen({"estado": "ok", "sitios": cerca})
    assert r["ultra_2km"] == 1 and r["puntos_2km"] == 2 and r["ultra_mas_cercana"]["id"] == "S1"
