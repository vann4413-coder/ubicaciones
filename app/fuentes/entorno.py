"""Entorno de la parcela en un radio de hasta 5 km (OpenStreetMap vía Overpass).

Sirve a cualquier tipo de cliente (gasolineras, recarga, retail, logística, promotores):
cuenta y sitúa negocios, industria, logística, hoteles, centros comerciales, etc.
Las gasolineras con precio vienen del Ministerio (módulo gasolineras); aquí solo se
usan las de OSM si el Ministerio no responde.
"""
import re

from shapely.geometry import Point, Polygon, mapping
from shapely.geometry.base import BaseGeometry

from app import config, geo, http
from app.fuentes.base import error, resultado

FUENTE = "OpenStreetMap (© colaboradores de OpenStreetMap, ODbL)"
URL = "https://www.openstreetmap.org"
ANILLOS = (500, 1000, 2000, 5000)

# clave -> nombre, color, icono, radio máximo (m), reglas [(etiqueta OSM, patrón)]
CATEGORIAS = {
    "gasolineras": ("Gasolineras", "#d64032", "competencia", 5000, [("amenity", "fuel")]),
    "electrolineras": ("Electrolineras", "#1e9e5a", "red", 5000, [("amenity", "charging_station")]),
    "restauracion": ("Restauración", "#e8710a", "restauracion", 5000, [("amenity", "restaurant|fast_food|cafe|bar|food_court")]),
    "hoteles": ("Hoteles", "#8a4b8f", "hotel", 5000, [("tourism", "hotel|motel|hostel|guest_house|apartment")]),
    "supermercados": ("Supermercados", "#0f9d9a", "carro", 5000, [("shop", "supermarket|convenience|wholesale")]),
    "comercial": ("Centros comerciales", "#c2185b", "tienda", 5000,
                  [("shop", "mall|department_store|doityourself|hardware|furniture|garden_centre|electronics|sports|toys|pet")]),
    "logistica": ("Naves y logística", "#5d4037", "nave", 5000,
                  [("industrial", "warehouse|logistics|distributor|depot"), ("building", "warehouse"), ("office", "logistics"),
                   ("amenity", "post_depot")]),
    "industria": ("Industria", "#607d8b", "industria", 5000, [("man_made", "works"), ("industrial", ".+"), ("craft", "metal_construction|carpenter|electrician")]),
    "automocion": ("Automoción", "#3f5f9e", "coche", 5000, [("shop", "car|car_repair|tyres|car_parts|truck"), ("amenity", "car_wash|vehicle_inspection")]),
    "equipamientos": ("Hospitales y campus", "#1565c0", "equipamiento", 5000,
                      [("amenity", "hospital|university|college"), ("leisure", "stadium")]),
    "comercios": ("Otros comercios", "#9aa5b1", "punto", 1000, [("shop", ".+")]),
    "oficinas": ("Oficinas", "#78909c", "punto", 1000, [("office", ".+")]),
}
ORDEN = list(CATEGORIAS)


def construir_query(lon: float, lat: float, radio: int) -> str:
    """Una sola consulta: puntos con su centro y polígonos industriales con geometría."""
    # Se agrupan los valores por etiqueta y radio: una sentencia por etiqueta es mucho más rápida en Overpass.
    grupos: dict[tuple[str, int], list[str]] = {}
    for _, (_, _, _, r, reglas) in CATEGORIAS.items():
        rr = min(r, radio)
        for etiqueta, patron in reglas:
            grupos.setdefault((etiqueta, rr), []).append(patron)
    partes = []
    for (etiqueta, rr), patrones in grupos.items():
        if ".+" in patrones:
            filtro = f'["{etiqueta}"]'
        else:
            valores = list(dict.fromkeys(v for p in patrones for v in p.split("|")))
            filtro = f'["{etiqueta}"="{valores[0]}"]' if len(valores) == 1 else f'["{etiqueta}"~"^({"|".join(valores)})$"]'
        partes.append(f"  nwr(around:{rr},{lat},{lon}){filtro};")
    puntos = "\n".join(partes)
    return f"""
[out:json][timeout:90][maxsize:268435456];
(
{puntos}
);
out center tags qt;
way(around:{radio},{lat},{lon})["landuse"="industrial"];
out geom tags qt;
"""


def categoria(tags: dict) -> str | None:
    for clave in ORDEN:
        for etiqueta, patron in CATEGORIAS[clave][4]:
            v = tags.get(etiqueta)
            if v and re.fullmatch(patron, v):
                return clave
    return None


def _nombre(tags: dict) -> str:
    return tags.get("name") or tags.get("brand") or tags.get("operator") or ""


def parse(d: dict, parcela: BaseGeometry, radio: int = 5000) -> dict:
    puntos, zonas, vistos = [], [], set()
    centro = parcela.centroid
    for e in d.get("elements", []):
        tags = e.get("tags") or {}
        if tags.get("landuse") == "industrial" and e.get("geometry"):
            coords = [geo.a_utm(p["lon"], p["lat"]) for p in e["geometry"]]
            if len(coords) < 4:
                continue
            try:
                pol = Polygon(coords)
            except ValueError:
                continue
            if not pol.is_valid or pol.area < 5000:
                continue
            zonas.append({
                "nombre": tags.get("name", ""), "area_ha": round(pol.area / 10000, 1),
                "distancia_m": round(pol.distance(parcela)),
                "geojson": mapping(geo.geom_a_wgs84(pol.simplify(8))), "geom": pol,
            })
            continue
        cat = categoria(tags)
        if not cat:
            continue
        lat = e.get("lat") or (e.get("center") or {}).get("lat")
        lon = e.get("lon") or (e.get("center") or {}).get("lon")
        if lat is None:
            continue
        clave = (e["type"], e["id"])
        if clave in vistos:
            continue
        vistos.add(clave)
        x, y = geo.a_utm(lon, lat)
        dist = round(Point(x, y).distance(parcela))
        if dist > min(radio, CATEGORIAS[cat][3]):
            continue
        # Naves sin nombre: solo cuentan si son grandes y vienen como edificio; se marcan como genéricas.
        puntos.append({
            "cat": cat, "nombre": _nombre(tags), "tipo": tags.get("amenity") or tags.get("shop") or tags.get("tourism")
            or tags.get("industrial") or tags.get("building") or tags.get("office") or tags.get("man_made") or "",
            "distancia_m": dist, "lon": round(lon, 6), "lat": round(lat, 6),
            "direccion": " ".join(filter(None, [tags.get("addr:street"), tags.get("addr:housenumber")])),
            "municipio": tags.get("addr:city", ""),
        })
    puntos.sort(key=lambda p: p["distancia_m"])
    zonas.sort(key=lambda z: z["distancia_m"])
    return {"puntos": puntos, "zonas_industriales": zonas, "resumen": resumir(puntos, zonas, radio)}


def resumir(puntos: list[dict], zonas: list[dict], radio: int = 5000) -> list[dict]:
    """Recuento por categoría y anillo, y lo más cercano con nombre."""
    filas = []
    for clave in ORDEN:
        nombre, color, icono, rmax, _ = CATEGORIAS[clave]
        ps = [p for p in puntos if p["cat"] == clave]
        cuenta = {r: (sum(1 for p in ps if p["distancia_m"] <= r) if r <= rmax else None) for r in ANILLOS if r <= radio}
        cercano = next((p for p in ps if p["nombre"]), ps[0] if ps else None)
        filas.append({"clave": clave, "nombre": nombre, "color": color, "icono": icono, "radio_max": rmax,
                      "cuenta": cuenta, "mas_cercano": cercano})
    filas.append({"clave": "poligonos", "nombre": "Polígonos y suelo industrial", "color": "#9575cd", "icono": "industria",
                  "radio_max": radio, "mas_cercano": next((z for z in zonas if z["nombre"]), zonas[0] if zonas else None),
                  "cuenta": {r: sum(1 for z in zonas if z["distancia_m"] <= r) for r in ANILLOS if r <= radio},
                  "hectareas": {r: round(sum(z["area_ha"] for z in zonas if z["distancia_m"] <= r), 1) for r in ANILLOS if r <= radio}})
    return filas


# ---------- Base local (preparada con scripts/preparar_entorno_osm.py) ----------
FICHERO_PUNTOS = config.DATOS_DIR / "osm_puntos.csv.gz"
FICHERO_INDUSTRIAL = config.DATOS_DIR / "osm_industrial.json.gz"
_base: dict | None = None


def _cargar_base() -> dict | None:
    """Carga una sola vez los puntos y polígonos en memoria (arrays para filtrar por cuadro rápidamente)."""
    global _base
    if _base is not None or not FICHERO_PUNTOS.exists():
        return _base
    import csv
    import gzip
    import json
    import os
    import sys
    from datetime import datetime

    import numpy as np
    # Tuplas (no diccionarios) para que Cataluña entera quepa en poca memoria.
    with gzip.open(FICHERO_PUNTOS, "rt", encoding="utf-8") as f:
        lector = csv.reader(f)
        cab = next(lector)
        filas = [tuple(sys.intern(v) if i < 3 else v for i, v in enumerate(r)) for r in lector]
    zonas = []
    if FICHERO_INDUSTRIAL.exists():
        with gzip.open(FICHERO_INDUSTRIAL, "rt", encoding="utf-8") as f:
            zonas = json.load(f)
    fecha = datetime.fromtimestamp(os.path.getmtime(FICHERO_PUNTOS)).strftime("%d/%m/%Y")
    _base = {
        "filas": filas,
        "cab": cab,
        "lon": np.array([float(r[cab.index("lon")]) for r in filas]), "lat": np.array([float(r[cab.index("lat")]) for r in filas]),
        "zonas": zonas,
        "zlon": np.array([z["coords"][0][0] for z in zonas] or [0.0]), "zlat": np.array([z["coords"][0][1] for z in zonas] or [0.0]),
        "fecha": fecha,
    }
    return _base


def consultar_local(parcela: BaseGeometry, radio: int = 5000) -> dict | None:
    base = _cargar_base()
    if not base:
        return None
    import math

    import numpy as np
    lon, lat = geo.a_wgs84(parcela.centroid.x, parcela.centroid.y)
    margen = radio + 3000  # cuadro amplio; luego se mide la distancia exacta a la parcela
    dlat, dlon = margen / 110540, margen / (111320 * math.cos(math.radians(lat)))
    sel = np.nonzero((np.abs(base["lat"] - lat) <= dlat) & (np.abs(base["lon"] - lon) <= dlon))[0]
    puntos = []
    for i in sel:
        r = dict(zip(base["cab"], base["filas"][i]))
        x, y = geo.a_utm(float(r["lon"]), float(r["lat"]))
        dist = round(Point(x, y).distance(parcela))
        if dist <= min(radio, CATEGORIAS[r["cat"]][3]):
            puntos.append({**r, "lon": float(r["lon"]), "lat": float(r["lat"]), "distancia_m": dist})
    zonas = []
    zsel = np.nonzero((np.abs(base["zlat"] - lat) <= dlat + 0.03) & (np.abs(base["zlon"] - lon) <= dlon + 0.04))[0] if base["zonas"] else []
    for i in zsel:
        z = base["zonas"][i]
        pol = geo.geom_a_utm(Polygon(z["coords"]))
        d = round(pol.distance(parcela))
        if d <= radio:
            zonas.append({"nombre": z["nombre"], "area_ha": z["area_ha"], "distancia_m": d,
                          "geojson": {"type": "Polygon", "coordinates": [z["coords"]]}, "geom": pol})
    puntos.sort(key=lambda p: p["distancia_m"])
    zonas.sort(key=lambda z: z["distancia_m"])
    return resultado("ok", FUENTE, URL, fecha_dato=f"Extracto de OpenStreetMap del {base['fecha']}", radio_m=radio,
                     puntos=puntos, zonas_industriales=zonas, resumen=resumir(puntos, zonas, radio))


async def consultar(parcela: BaseGeometry, radio: int = 5000) -> dict:
    # 1) Base local: rápida y sin depender de servidores externos
    local = consultar_local(parcela, radio)
    if local:
        return local
    # 2) Si no se ha preparado la base, se consulta Overpass en directo
    lon, lat = geo.a_wgs84(parcela.centroid.x, parcela.centroid.y)
    extra = int(parcela.centroid.hausdorff_distance(parcela.boundary)) if not parcela.is_empty else 0
    q = construir_query(lon, lat, radio + extra)
    ultimo = None
    # Overpass a veces se satura: se prueba el servidor principal y dos réplicas públicas.
    import asyncio
    for url in config.OVERPASS_URLS:
        try:
            d = await asyncio.wait_for(http.post_json(url, {"data": q}), timeout=20)
            return resultado("ok", FUENTE, URL, fecha_dato="Datos de OpenStreetMap en la fecha de consulta",
                             radio_m=radio, **parse(d, parcela, radio))
        except (http.ErrorFuente, ValueError, asyncio.TimeoutError) as e:
            ultimo = e or "tiempo de espera agotado"
    return error(FUENTE, f"OpenStreetMap no responde: {ultimo}", URL)
