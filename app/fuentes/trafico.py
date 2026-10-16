"""Tráfico (IMD) y accesos.

Fuentes, de más reciente a más antigua, para cada carretera:
1. Fichero local `datos/aforos.csv` con lo que se carga a mano o por script:
   IMD 2025 de la Generalitat (Pla d'aforaments), IMD 2024 de la red del Estado, etc.
2. WFS de la Generalitat, capa de tramos con IMD (Generalitat + Diputacions), con el
   año real de medida de cada tramo.

Regla fija: se muestra la IMD más reciente con su año y su fuente. Si no hay aforo,
"sin dato"; nunca se estima.
"""
import csv
import re
from functools import lru_cache

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from app import config, geo, http
from app.fuentes import gencat_wfs
from app.fuentes.base import resultado

FUENTE_GENCAT = "Generalitat de Catalunya, capa de IMD por tramos (Hipermapa)"


def titular_por_denominacion(ref: str) -> str:
    r = (ref or "").upper().strip()
    if re.match(r"^(AP|A|N|E)-", r):
        return "Estado"
    if r.startswith("C-"):
        return "Generalitat de Catalunya"
    if re.match(r"^(B|BV|BP)-", r):
        return "Diputació de Barcelona"
    if re.match(r"^(GI|GIV|GIP)-", r):
        return "Diputació de Girona"
    if re.match(r"^(L|LV|LP)-", r):
        return "Diputació de Lleida"
    if re.match(r"^(T|TV|TP)-", r):
        return "Diputació de Tarragona"
    return "Municipal" if not r else "Otro"


def es_via_rapida(clase: str, ref: str) -> bool:
    return clase in ("motorway", "trunk") or bool(re.match(r"^(AP|A)-", (ref or "").upper()))


def pk_a_m(pk: str | float | None) -> float | None:
    """'99+871' -> 99871 m; 12.5 -> 12500 m."""
    if pk in (None, ""):
        return None
    s = str(pk).strip().replace(",", ".")
    m = re.match(r"^(\d+)\+(\d+)$", s)
    if m:
        return int(m.group(1)) * 1000 + int(m.group(2))
    try:
        return float(s) * 1000
    except ValueError:
        return None


def normalizar_ref(ref: str) -> str:
    return re.sub(r"\s+", "", (ref or "").upper())


@lru_cache(maxsize=1)
def _aforos_locales_cache(ruta: str, mtime: float) -> list[dict]:
    filas = []
    with open(ruta, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                filas.append({
                    "carretera": normalizar_ref(r["carretera"]),
                    "pk_m": pk_a_m(r.get("pk")),
                    "pk": r.get("pk", ""),
                    "imd": int(float(r["imd"])),
                    "pct_pesados": float(r["pct_pesados"]) if r.get("pct_pesados") else None,
                    "anio": int(r["anio"]),
                    "organismo": r.get("organismo", ""),
                    "estacion": r.get("codigo_estacion", ""),
                    "tipo": r.get("tipo", ""),
                    "lon": float(r["lon"]) if r.get("lon") else None,
                    "lat": float(r["lat"]) if r.get("lat") else None,
                    "fuente": r.get("fuente", "Aforos cargados"),
                })
            except (KeyError, ValueError):
                continue
    return filas


def aforos_locales() -> list[dict]:
    p = config.FICHERO_AFOROS
    if not p.exists():
        return []
    return _aforos_locales_cache(str(p), p.stat().st_mtime)


async def tramos_gencat(parcela: BaseGeometry, radio: float) -> tuple[list[dict], str]:
    """Tramos con IMD a menos de `radio` m. Prueba las capas de más nueva a más vieja."""
    for capa in config.CAPAS_IMD:
        try:
            ents = await gencat_wfs.entidades(capa, parcela, margen=radio)
        except http.ErrorFuente:
            continue
        tramos = []
        for e in ents:
            if e["geom"] is None:
                continue
            d = e["geom"].distance(parcela)
            if d > radio:
                continue
            p = e["props"]
            tramos.append({
                "carretera": normalizar_ref(p.get("CARRETERA", "")),
                "imd": p.get("IMD"),
                "pct_pesados": p.get("PERCENTATGE_PESANTS"),
                "anio": p.get("ANY_MESURA"),
                "pk_estacion": p.get("PK_ESTACIO", ""),
                "pk_ini_m": pk_a_m(p.get("PKINICI")),
                "pk_fin_m": pk_a_m(p.get("PKFINAL")),
                "pk_tramo": f"{p.get('PKINICI', '')} a {p.get('PKFINAL', '')}",
                "estacion": p.get("CODI_ESTACIO", ""),
                "organismo": p.get("ORGANISME", ""),
                "tipo": p.get("TIPUS_AFORAMENT", ""),
                "distancia_m": round(d),
                "geom": e["geom"],
                "fuente": f"{FUENTE_GENCAT} ({capa.split(':')[1]})",
            })
        if tramos:
            return tramos, capa
    return [], ""


def elegir_aforo(ref: str, tramo: dict | None, parcela: BaseGeometry, locales: list[dict]) -> dict | None:
    """Dato más reciente para una carretera: compara el tramo de la Generalitat con los aforos locales."""
    candidatos = []
    if tramo and tramo.get("imd"):
        candidatos.append({**tramo, "origen": "wfs"})
    for a in locales:
        if a["carretera"] != ref:
            continue
        dentro_tramo = (
            tramo is not None and a["pk_m"] is not None and tramo.get("pk_ini_m") is not None
            and tramo["pk_ini_m"] <= a["pk_m"] <= (tramo.get("pk_fin_m") or tramo["pk_ini_m"])
        )
        dist = None
        if a["lon"] is not None:
            x, y = geo.a_utm(a["lon"], a["lat"])
            dist = Point(x, y).distance(parcela)
        if dentro_tramo or (dist is not None and dist <= 3000):
            candidatos.append({
                "carretera": ref, "imd": a["imd"], "pct_pesados": a["pct_pesados"], "anio": a["anio"],
                "pk_estacion": a["pk"], "estacion": a["estacion"], "organismo": a["organismo"], "tipo": a["tipo"],
                "fuente": a["fuente"], "origen": "local", "_dist": dist if dist is not None else 0,
            })
    if not candidatos:
        return None
    return max(candidatos, key=lambda c: (c.get("anio") or 0, -(c.get("_dist") or 0)))


async def consultar(parcela: BaseGeometry, osm: dict) -> dict:
    radio = max(config.RADIOS_TRAFICO)
    tramos, capa = await tramos_gencat(parcela, radio)
    locales = aforos_locales()

    # Carreteras con denominación cerca (de OSM y de los tramos de IMD)
    vias_osm = [v for v in (osm.get("vias") or []) if v.get("ref") and v["distancia_m"] <= radio]
    refs: dict[str, dict] = {}
    for v in vias_osm:
        for r in v["ref"].split(";"):
            r = normalizar_ref(r)
            if r and (r not in refs or v["distancia_m"] < refs[r]["distancia_m"]):
                refs[r] = {"distancia_m": v["distancia_m"], "clase": v["clase"], "nombre": v["nombre"]}
    for t in tramos:
        if t["carretera"] not in refs or t["distancia_m"] < refs[t["carretera"]]["distancia_m"]:
            refs[t["carretera"]] = {**refs.get(t["carretera"], {}), "distancia_m": t["distancia_m"]}

    carreteras = []
    for ref, info in sorted(refs.items(), key=lambda kv: kv[1]["distancia_m"]):
        tramos_ref = sorted([t for t in tramos if t["carretera"] == ref], key=lambda t: t["distancia_m"])
        tramo = tramos_ref[0] if tramos_ref else None
        dato = elegir_aforo(ref, tramo, parcela, locales)
        titular = (dato or {}).get("organismo") or (tramo or {}).get("organismo") or ""
        carreteras.append({
            "carretera": ref,
            "nombre": info.get("nombre", ""),
            "distancia_m": info["distancia_m"],
            "radio": "500 m" if info["distancia_m"] <= 500 else "1 km",
            "titular": titular or titular_por_denominacion(ref),
            "titular_inferido": not titular,
            "imd": dato["imd"] if dato else None,
            "pct_pesados": dato.get("pct_pesados") if dato else None,
            "anio": dato.get("anio") if dato else None,
            "fuente": dato.get("fuente") if dato else "",
            "estacion": dato.get("estacion", "") if dato else "",
            "pk_estacion": dato.get("pk_estacion", "") if dato else "",
            "tipo_aforo": dato.get("tipo", "") if dato else "",
        })

    accesos = analizar_accesos(parcela, osm)
    estado = "ok" if any(c["imd"] for c in carreteras) else "sin_dato"
    anios = sorted({c["anio"] for c in carreteras if c["anio"]})
    return resultado(
        estado,
        "Aforos oficiales (Generalitat, Diputacions, Ministerio de Transportes)",
        "https://territori.gencat.cat/ca/03_infraestructures_i_mobilitat/carreteres/dades-viaries/",
        fecha_dato=f"Años de medida: {', '.join(map(str, anios))}" if anios else "",
        carreteras=carreteras,
        tramos=tramos,
        capa_wfs=capa,
        accesos=accesos,
        aforos_locales_cargados=len(locales),
    )


# Línea límite de edificación (orientativa) desde la arista exterior de la calzada.
# Estado: Ley 37/2015, art. 33. Cataluña: Decret legislatiu 2/2009 (Llei de carreteres).
LINEA_EDIF = {"rapida": 50, "convencional": 25}
SEMIANCHO_CALZADA = {"rapida": 12, "convencional": 4}


def analizar_accesos(parcela: BaseGeometry, osm: dict) -> dict:
    vias = osm.get("vias") or []
    if not vias:
        return {"estado": "sin_dato"}
    via_acceso = min(vias, key=lambda v: v["distancia_m"])
    carretera = next((v for v in vias if v.get("ref")), None)

    # Frente a vial: borde de la parcela a menos de 12 m del eje de cualquier vía.
    from shapely.ops import unary_union
    cercanas = [v["geom"] for v in vias if v["distancia_m"] <= 15]
    frente = 0.0
    if cercanas:
        zona = unary_union(cercanas).buffer(12)
        frente = round(parcela.boundary.intersection(zona).length, 1)

    linea = None
    if carretera and carretera["distancia_m"] <= 150:
        tipo = "rapida" if es_via_rapida(carretera["clase"], carretera["ref"]) else "convencional"
        dist_lim = LINEA_EDIF[tipo]
        franja = carretera["geom"].buffer(SEMIANCHO_CALZADA[tipo] + dist_lim)
        afectada = parcela.intersection(franja).area
        linea = {
            "carretera": carretera["ref"],
            "tipo": "autopista/autovía" if tipo == "rapida" else "carretera convencional",
            "distancia_limite_m": dist_lim,
            "superficie_afectada_m2": round(afectada),
            "pct_afectado": round(100 * afectada / parcela.area, 1) if parcela.area else 0,
            "geom": parcela.intersection(franja),
            "aviso": "Orientativo: se mide desde el eje con un ancho de calzada estimado. En tramos urbanos "
                     "y travesías rige el planeamiento. Confirmar con el titular de la vía.",
        }

    return {
        "estado": "ok",
        "via_acceso": {
            "nombre": via_acceso["nombre"] or via_acceso["ref"] or "Vía sin nombre",
            "ref": via_acceso["ref"],
            "clase": via_acceso["clase"],
            "distancia_m": via_acceso["distancia_m"],
            "titular": titular_por_denominacion(via_acceso["ref"]),
        },
        "carretera_mas_cercana": {
            "ref": carretera["ref"], "nombre": carretera["nombre"], "distancia_m": carretera["distancia_m"],
            "titular": titular_por_denominacion(carretera["ref"]),
        } if carretera else None,
        "frente_vial_m": frente,
        "linea_edificacion": linea,
        "salida_cercana": (osm.get("salidas") or [None])[0],
        "area_servicio_cercana": (osm.get("areas_servicio") or [None])[0],
        "aviso": "Cualquier acceso nuevo o modificado desde una carretera requiere autorización de su titular.",
    }
