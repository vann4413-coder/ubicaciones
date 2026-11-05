"""OpenStreetMap (Overpass API): viario, salidas, áreas de servicio y negocios del entorno."""
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry

from app import config, geo, http
from app.fuentes.base import error, resultado

FUENTE = "OpenStreetMap (© colaboradores de OpenStreetMap, ODbL)"
URL = "https://www.openstreetmap.org"

VIAS_PRINCIPALES = "motorway|trunk|primary|secondary|tertiary|motorway_link|trunk_link|primary_link|secondary_link"

# Categorías del entorno: (etiqueta OSM, valor) -> grupo legible.
GRUPOS = [
    ("amenity", "fuel", "Gasolineras"),
    ("amenity", "charging_station", "Puntos de recarga"),
    ("amenity", "restaurant|fast_food|cafe|bar", "Restauración"),
    ("shop", "supermarket|convenience|mall|department_store|hypermarket", "Supermercados y alimentación"),
    ("shop", "car|car_repair|tyres|car_parts", "Automoción"),
    ("amenity", "car_wash", "Automoción"),
    ("shop", ".*", "Otros comercios"),
    ("tourism", "hotel|motel|hostel|guest_house", "Alojamiento"),
    ("amenity", "parking", "Aparcamientos"),
    ("amenity", "school|college|university|kindergarten", "Educación"),
    ("amenity", "hospital|clinic|pharmacy|doctors", "Salud"),
    ("office", ".*", "Oficinas"),
]


def construir_query(lon: float, lat: float, r_pois: int, r_vias: int) -> str:
    return f"""
[out:json][timeout:60];
(
  way(around:{r_vias},{lat},{lon})["highway"~"^({VIAS_PRINCIPALES})$"];
  way(around:60,{lat},{lon})["highway"];
)->.vias;
.vias out geom tags;
node(around:{max(r_vias, 3000)},{lat},{lon})["highway"="motorway_junction"];
out tags;
nwr(around:{max(r_vias, 5000)},{lat},{lon})["highway"="services"];
out center tags;
(
  nwr(around:{r_pois},{lat},{lon})["amenity"~"^(fuel|charging_station|restaurant|fast_food|cafe|bar|parking|school|college|university|kindergarten|hospital|clinic|pharmacy|doctors|car_wash)$"];
  nwr(around:{r_pois},{lat},{lon})["shop"];
  nwr(around:{r_pois},{lat},{lon})["tourism"~"^(hotel|motel|hostel|guest_house)$"];
  nwr(around:{r_pois},{lat},{lon})["office"];
);
out center tags;
"""


def _grupo(tags: dict) -> str | None:
    import re
    for clave, patron, nombre in GRUPOS:
        v = tags.get(clave)
        if v and re.fullmatch(patron, v):
            return nombre
    return None


def parse(d: dict, parcela: BaseGeometry) -> dict:
    vias, junctions, servicios, pois = [], [], [], []
    for e in d.get("elements", []):
        tags = e.get("tags") or {}
        if e["type"] == "way" and "geometry" in e and "highway" in tags:
            coords = [geo.a_utm(p["lon"], p["lat"]) for p in e["geometry"]]
            if len(coords) < 2:
                continue
            linea = LineString(coords)
            vias.append({
                "id": e["id"], "nombre": tags.get("name", ""), "ref": tags.get("ref", ""),
                "clase": tags["highway"], "carriles": tags.get("lanes"), "geom": linea,
                "distancia_m": round(linea.distance(parcela), 1),
            })
            continue
        if tags.get("highway") == "motorway_junction" and e["type"] == "node":
            x, y = geo.a_utm(e["lon"], e["lat"])
            junctions.append({"nombre": tags.get("name") or tags.get("exit_to", ""), "ref": tags.get("ref", ""),
                              "distancia_m": round(Point(x, y).distance(parcela)), "lon": e["lon"], "lat": e["lat"]})
            continue
        lat = e.get("lat") or (e.get("center") or {}).get("lat")
        lon = e.get("lon") or (e.get("center") or {}).get("lon")
        if lat is None:
            continue
        x, y = geo.a_utm(lon, lat)
        dist = round(Point(x, y).distance(parcela))
        if tags.get("highway") == "services":
            servicios.append({"nombre": tags.get("name", "Área de servicio"), "distancia_m": dist, "lon": lon, "lat": lat})
            continue
        g = _grupo(tags)
        if g:
            pois.append({
                "grupo": g, "nombre": tags.get("name", ""), "marca": tags.get("brand") or tags.get("operator", ""),
                "tipo": tags.get("amenity") or tags.get("shop") or tags.get("tourism") or tags.get("office") or "",
                "distancia_m": dist, "lon": lon, "lat": lat,
            })
    # Quitar duplicados de vías (misma vía devuelta por las dos consultas)
    unicas = {v["id"]: v for v in vias}
    return {
        "vias": sorted(unicas.values(), key=lambda v: v["distancia_m"]),
        "salidas": sorted(junctions, key=lambda j: j["distancia_m"])[:5],
        "areas_servicio": sorted(servicios, key=lambda s: s["distancia_m"])[:3],
        "pois": sorted(pois, key=lambda p: p["distancia_m"]),
    }


FICHERO_VIAS = config.DATOS_DIR / "osm_vias.sqlite"


def vias_locales(parcela: BaseGeometry, radio: float) -> list[dict] | None:
    """Viario de la base local (extracto de OpenStreetMap preparado al construir la imagen)."""
    if not FICHERO_VIAS.exists():
        return None
    import json
    import sqlite3
    lon, lat = geo.a_wgs84(parcela.centroid.x, parcela.centroid.y)
    extra = (parcela.centroid.hausdorff_distance(parcela.boundary) if not parcela.is_empty else 0) + radio
    dlat, dlon = extra / 111_000, extra / 83_000
    margen = 0.05  # una vía larga puede empezar lejos: se amplía el recuadro de inicio
    con = sqlite3.connect(f"file:{FICHERO_VIAS}?mode=ro", uri=True)
    try:
        filas = con.execute(
            "SELECT id, nombre, ref, clase, carriles, coords FROM vias WHERE x0 BETWEEN ? AND ? AND y0 BETWEEN ? AND ? "
            "AND x1 >= ? AND y1 >= ?",
            (lon - dlon - margen, lon + dlon, lat - dlat - margen, lat + dlat, lon - dlon, lat - dlat)).fetchall()
    finally:
        con.close()
    vias = []
    principales = set(VIAS_PRINCIPALES.split("|"))
    for id_, nombre, ref, clase, carriles, coords in filas:
        linea = LineString([geo.a_utm(x, y) for x, y in json.loads(coords)])
        d = linea.distance(parcela)
        if d <= 60 or (d <= radio and clase in principales):
            vias.append({"id": id_, "nombre": nombre or "", "ref": ref or "", "clase": clase, "carriles": carriles,
                         "geom": linea, "distancia_m": round(d, 1)})
    return sorted(vias, key=lambda v: v["distancia_m"])


async def consultar(parcela: BaseGeometry) -> dict:
    lon, lat = geo.a_wgs84(parcela.centroid.x, parcela.centroid.y)
    # radio desde el centroide: se suma el "radio" de la parcela para no perder nada del borde
    extra = int(parcela.centroid.hausdorff_distance(parcela.boundary)) if not parcela.is_empty else 0
    q = construir_query(lon, lat, max(config.RADIOS_ENTORNO) + extra, max(config.RADIOS_TRAFICO) + extra)
    d, ultimo = None, None
    import asyncio
    hay_local = FICHERO_VIAS.exists()
    # Con la base local de viario basta un intento corto: Overpass solo aporta salidas y áreas de servicio.
    for url in config.OVERPASS_URLS[:1] if hay_local else config.OVERPASS_URLS:
        try:
            d = await asyncio.wait_for(http.post_json(url, {"data": q}), timeout=10 if hay_local else 15)
            break
        except (http.ErrorFuente, ValueError, asyncio.TimeoutError) as e:
            ultimo = e or "tiempo de espera agotado"
    if d is None:
        locales = vias_locales(parcela, max(config.RADIOS_TRAFICO))
        if locales is None:
            return error(FUENTE, f"OpenStreetMap no responde: {ultimo}", URL)
        return resultado("ok", FUENTE, URL, fecha_dato="Extracto de OpenStreetMap de Geofabrik", vias=locales,
                         salidas=[], areas_servicio=[], pois=[])
    return resultado("ok", FUENTE, URL, fecha_dato="Datos de OpenStreetMap en la fecha de consulta", **parse(d, parcela))
