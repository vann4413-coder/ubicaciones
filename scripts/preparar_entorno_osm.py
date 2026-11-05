"""Prepara la base local del entorno (negocios, naves, polígonos industriales) a partir de OpenStreetMap.

Descarga el extracto de Cataluña de Geofabrik, se queda solo con las etiquetas que usa
la plataforma y genera dos ficheros comprimidos en datos/:
  - osm_puntos.csv.gz      un punto por negocio, nave, hotel, etc. con su categoría
  - osm_industrial.json.gz polígonos de suelo industrial (landuse=industrial) simplificados
  - osm_vias.sqlite        carreteras y calles con nombre o denominación, para saber a qué vía da la parcela

Así el informe no depende de los servidores públicos de Overpass, que se saturan a menudo.
Se ejecuta al construir la imagen Docker (y se puede repetir para refrescar los datos):
  python -m scripts.preparar_entorno_osm [--pbf fichero.osm.pbf] [--salida datos]
Necesita osmium-tool (apt) y pyosmium (pip osmium).
"""
import argparse
import csv
import gzip
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shapely.geometry import Polygon  # noqa: E402

from app import config, geo  # noqa: E402
from app.fuentes.entorno import categoria  # noqa: E402

URL_PBF = "https://download.geofabrik.de/europe/spain/cataluna-latest.osm.pbf"
FILTROS = [
    "nwr/amenity=fuel,charging_station,restaurant,fast_food,cafe,bar,food_court,post_depot,car_wash,vehicle_inspection,hospital,university,college",
    "nwr/tourism=hotel,motel,hostel,guest_house,apartment",
    "nwr/shop", "nwr/office", "nwr/industrial", "nwr/building=warehouse", "nwr/man_made=works",
    "nwr/craft=metal_construction,carpenter,electrician", "nwr/leisure=stadium", "wr/landuse=industrial",
]
FILTRO_VIAS = ["w/highway=motorway,trunk,primary,secondary,tertiary,motorway_link,trunk_link,primary_link,secondary_link,"
               "tertiary_link,residential,unclassified,living_street,pedestrian,road"]
CLASES_SIN_NOMBRE = {"motorway", "trunk", "primary", "secondary", "tertiary", "motorway_link", "trunk_link", "primary_link"}
CAMPOS = ["cat", "nombre", "tipo", "lon", "lat", "direccion", "municipio"]


def descargar(destino: Path) -> None:
    import httpx
    print(f"Descargando {URL_PBF} …", flush=True)
    with httpx.stream("GET", URL_PBF, timeout=600, follow_redirects=True) as r:
        r.raise_for_status()
        with open(destino, "wb") as f:
            for trozo in r.iter_bytes(1 << 20):
                f.write(trozo)


def _texto(tags, *claves):
    for k in claves:
        v = tags.get(k)
        if v:
            return v
    return ""


def procesar(pbf: Path, salida: Path) -> tuple[int, int]:
    import osmium
    filtrado = pbf.with_name("filtrado.osm.pbf")
    subprocess.run(["osmium", "tags-filter", str(pbf), *FILTROS, "-o", str(filtrado), "--overwrite"], check=True)

    salida.mkdir(parents=True, exist_ok=True)
    n_puntos, zonas = 0, []
    with gzip.open(salida / "osm_puntos.csv.gz", "wt", encoding="utf-8", newline="") as fcsv:
        w = csv.writer(fcsv)
        w.writerow(CAMPOS)
        for o in osmium.FileProcessor(str(filtrado)).with_locations().with_areas():
            tags = {t.k: t.v for t in o.tags}
            if not tags:
                continue
            if o.is_area():
                anillos = [[(n.lon, n.lat) for n in r] for r in o.outer_rings()]
                if not anillos or len(anillos[0]) < 4:
                    continue
                if tags.get("landuse") == "industrial":
                    try:
                        pol = geo.geom_a_utm(Polygon(anillos[0]))
                    except ValueError:
                        continue
                    if pol.is_valid and pol.area >= 5000:
                        simple = geo.geom_a_wgs84(pol.simplify(10))
                        zonas.append({"nombre": tags.get("name", ""), "area_ha": round(pol.area / 10000, 1),
                                      "coords": [[round(x, 5), round(y, 5)] for x, y in simple.exterior.coords]})
                    if not categoria(tags):
                        continue
                c = Polygon(anillos[0]).centroid
                lon, lat = c.x, c.y
            elif o.is_node():
                if not o.location.valid():
                    continue
                lon, lat = o.location.lon, o.location.lat
            elif o.is_way():
                if o.is_closed():  # ya llega como área
                    continue
                pts = [(n.lon, n.lat) for n in o.nodes if n.location.valid()]
                if not pts:
                    continue
                lon, lat = pts[len(pts) // 2]
            else:
                continue
            cat = categoria(tags)
            if not cat:
                continue
            w.writerow([cat, _texto(tags, "name", "brand", "operator"),
                        _texto(tags, "amenity", "shop", "tourism", "industrial", "building", "office", "man_made", "craft", "leisure"),
                        round(lon, 6), round(lat, 6),
                        " ".join(filter(None, [tags.get("addr:street"), tags.get("addr:housenumber")])), tags.get("addr:city", "")])
            n_puntos += 1
    with gzip.open(salida / "osm_industrial.json.gz", "wt", encoding="utf-8") as f:
        json.dump(zonas, f, ensure_ascii=False, separators=(",", ":"))
    return n_puntos, len(zonas)


def procesar_vias(pbf: Path, salida: Path) -> int:
    """Viario en SQLite con su caja envolvente indexada: se consulta por recuadro sin cargarlo en memoria."""
    import sqlite3

    import osmium
    filtrado = pbf.with_name("vias.osm.pbf")
    subprocess.run(["osmium", "tags-filter", str(pbf), *FILTRO_VIAS, "-o", str(filtrado), "--overwrite"], check=True)
    ruta = salida / "osm_vias.sqlite"
    ruta.unlink(missing_ok=True)
    db = sqlite3.connect(ruta)
    db.execute("CREATE TABLE vias (id INTEGER, nombre TEXT, ref TEXT, clase TEXT, carriles TEXT, "
               "x0 REAL, y0 REAL, x1 REAL, y1 REAL, coords TEXT)")
    n, lote = 0, []
    for w in osmium.FileProcessor(str(filtrado)).with_locations():
        if not w.is_way():
            continue
        tags = {t.k: t.v for t in w.tags}
        clase = tags.get("highway", "")
        if not (tags.get("name") or tags.get("ref")) and clase not in CLASES_SIN_NOMBRE:
            continue
        pts = [(round(nd.lon, 6), round(nd.lat, 6)) for nd in w.nodes if nd.location.valid()]
        if len(pts) < 2:
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        lote.append((w.id, tags.get("name", ""), tags.get("ref", ""), clase, tags.get("lanes"),
                     min(xs), min(ys), max(xs), max(ys), json.dumps(pts, separators=(",", ":"))))
        n += 1
        if len(lote) >= 5000:
            db.executemany("INSERT INTO vias VALUES (?,?,?,?,?,?,?,?,?,?)", lote)
            lote = []
    db.executemany("INSERT INTO vias VALUES (?,?,?,?,?,?,?,?,?,?)", lote)
    db.execute("CREATE INDEX i_caja ON vias (x0, y0)")
    db.commit()
    db.execute("VACUUM")
    db.close()
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pbf", help="Fichero .osm.pbf ya descargado (si no, se descarga el de Cataluña)")
    ap.add_argument("--salida", default=str(config.DATOS_DIR))
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        pbf = Path(a.pbf) if a.pbf else Path(tmp) / "cataluna.osm.pbf"
        if not a.pbf:
            descargar(pbf)
        n, z = procesar(pbf, Path(a.salida))
        v = procesar_vias(pbf, Path(a.salida))
    print(f"Entorno OSM preparado: {n} puntos, {z} polígonos industriales y {v} vías en {a.salida}")


if __name__ == "__main__":
    main()
