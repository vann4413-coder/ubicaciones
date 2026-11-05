"""Terreno, afecciones y riesgos de la parcela con los servicios del ICGC.

- API Territorial del ICGC (https://api.icgc.cat/territorial/docs): cota, dirección postal, geología,
  pendientes, espacios protegidos, patrimonio, riesgo químico, mercancías peligrosas y sondeos geotécnicos.
  La intersección se pide por referencia catastral, así se evalúa la parcela entera y no un punto.
- WMS de riesgos geológicos del ICGC (mapa de prevención 1:25 000): desprendimientos, deslizamientos,
  hundimientos y multiperillositat. Solo existe en las hojas ya publicadas.
"""
import asyncio
import logging
import re
from xml.etree import ElementTree

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from app import geo, http
from app.fuentes.base import resultado

log = logging.getLogger(__name__)

FUENTE = "Institut Cartogràfic i Geològic de Catalunya (ICGC): API Territorial y mapa de prevención de riesgos geológicos"
URL = "https://api.icgc.cat/territorial/docs"
API = "https://api.icgc.cat/territorial"
WMS_RIESGOS = "https://geoserveis.icgc.cat/serveis/catalunya/riscos-geologics/wms"
RADIO_SONDEOS_M = 500

# capa -> (grupo, título, función que da el detalle a partir de las propiedades)
AFECCIONES = {
    "pendents-20-percent": ("Terreno", "Pendientes superiores al 20 %", lambda p: p.get("CLASSEPEN", "")),
    "zones-potencialment-inundables": ("Agua", "Zona potencialmente inundable (criterio geomorfológico)", lambda p: ""),
    "arees-susceptibles-dinamica-torrencial": ("Agua", "Área susceptible de dinámica torrencial",
                                               lambda p: " · ".join(filter(None, [p.get("TOPONIM"), p.get("TIPUS_FLUX")]))),
    "zona-servitud-fluvial": ("Agua", "Zona de servidumbre fluvial (5 m)", lambda p: p.get("NOM_AA", "")),
    "zona-policia-fluvial": ("Agua", "Zona de policía fluvial (100 m)", lambda p: p.get("NOM_AA", "")),
    "espais-naturals-proteccio-especial": ("Protección", "Espacio natural de protección especial", lambda p: p.get("NOM", "") or p.get("AMBIT", "")),
    "espais-interes-natural": ("Protección", "Espacio PEIN", lambda p: p.get("NOM_PEIN", "")),
    "natura-2000": ("Protección", "Red Natura 2000", lambda p: p.get("NOM_XN2", "")),
    "espais-interes-geologic-poligons": ("Protección", "Espacio de interés geológico", lambda p: p.get("NOM_ELEMEN", "")),
    "patrimoni-arquitectonic": ("Patrimonio", "Patrimonio arquitectónico", lambda p: " · ".join(filter(None, [p.get("NOM_ACTUAL"), p.get("PROTECCIO")]))),
    "jaciment-arqueologic": ("Patrimonio", "Yacimiento arqueológico", lambda p: " · ".join(filter(None, [p.get("NOM_ACTUAL"), p.get("PROTECCIO")]))),
    "jaciment-paleontologic": ("Patrimonio", "Yacimiento paleontológico", lambda p: p.get("NOM_ACTUAL", "")),
    "intensitat-limit-risc-quimic": ("Riesgo químico", "Zona de intensidad límite de riesgo químico (PLASEQCAT)", lambda p: p.get("TIPUS_ZONA", "")),
    "intervencio-risc-quimic": ("Riesgo químico", "Zona de intervención por riesgo químico (PLASEQCAT)", lambda p: p.get("TIPUS_ZONA", "")),
    "autoproteccio-risc-quimic": ("Riesgo químico", "Zona de autoprotección por riesgo químico (PLASEQCAT)", lambda p: p.get("TIPUS_ZONA", "")),
    "mercaderies-perilloses-viari": ("Riesgo químico", "Afectada por el transporte de mercancías peligrosas por carretera",
                                     lambda p: p.get("AFECTACIO", "")),
    "proteccio-cel-nocturn": ("Otras", "Zona de protección del cielo nocturno (limita la iluminación exterior)", lambda p: p.get("NOM", "")),
    "capacitat-agrologica": ("Otras", "Capacidad agrológica del suelo", lambda p: p.get("CAP_TXT", "")),
}
# Capas que se informan aunque no supongan una afección (dato descriptivo)
DESCRIPTIVAS = {"capacitat-agrologica"}

RIESGOS_WMS = [
    ("G6MP_PA", "Multiperillositat"),
    ("G6PE_PA", "Deslizamientos"),
    ("G6PD_PA", "Desprendimientos"),
    ("G6PS_PA", "Hundimientos"),
]


async def _interseccion(capa: str, rc: str) -> list[dict] | None:
    try:
        r = await asyncio.wait_for(http.cliente().post(
            f"{API}/processes/intersection/execution",
            json={"inputs": {"capa": capa, "refCadastral": rc, "skipgeometry": True}}), timeout=20)
    except Exception as e:  # noqa: BLE001
        log.info("ICGC %s: %s", capa, e)
        return None
    if r.status_code == 400:  # «No intersecta»
        return []
    if r.status_code != 200:
        return None
    return [f.get("properties") or {} for f in (r.json().get("features") or [])]


async def _punto(capas: str, lon: float, lat: float) -> list[dict]:
    try:
        r = await asyncio.wait_for(http.cliente().get(f"{API}/elements/{capas}/{lon:.6f},{lat:.6f}", params={"f": "json"}), timeout=15)
        return r.json().get("features") or [] if r.status_code == 200 else []
    except Exception:  # noqa: BLE001
        return []


async def _cota(lon: float, lat: float) -> float | None:
    for f in await _punto("elevacions", lon, lat):
        try:
            return float(f["properties"]["value"])
        except (KeyError, TypeError, ValueError):
            pass
    return None


def puntos_muestra(parcela: BaseGeometry, n: int = 8) -> list[tuple[float, float]]:
    """Centro de la parcela y puntos repartidos por su contorno, un poco hacia dentro (UTM)."""
    interior = parcela.buffer(-2) if parcela.area > 400 else parcela
    if interior.is_empty:
        interior = parcela
    borde = interior.exterior if hasattr(interior, "exterior") else interior.convex_hull.exterior
    pts = [parcela.representative_point()]
    pts += [borde.interpolate(i / n, normalized=True) for i in range(n)]
    return [(p.x, p.y) for p in pts]


async def relieve(parcela: BaseGeometry) -> dict | None:
    pts = puntos_muestra(parcela)
    cotas = await asyncio.gather(*[_cota(*geo.a_wgs84(x, y)) for x, y in pts])
    validos = [(p, c) for p, c in zip(pts, cotas) if c is not None]
    if len(validos) < 2:
        return {"cota_media": round(validos[0][1], 1)} if validos else None
    (pmin, cmin) = min(validos, key=lambda v: v[1])
    (pmax, cmax) = max(validos, key=lambda v: v[1])
    dist = Point(pmin).distance(Point(pmax))
    desnivel = cmax - cmin
    return {
        "cota_media": round(sum(c for _, c in validos) / len(validos), 1), "cota_min": round(cmin, 1),
        "cota_max": round(cmax, 1), "desnivel_m": round(desnivel, 1),
        "pendiente_pct": round(desnivel / dist * 100, 1) if dist > 5 else None, "puntos": len(validos),
    }


async def direccion_postal(lon: float, lat: float) -> dict | None:
    for f in await _punto("adreces", lon, lat):
        p = f.get("properties") or {}
        if p.get("etiqueta"):
            return {"etiqueta": p["etiqueta"], "codigo_postal": p.get("codi_postal", ""), "via": p.get("nom", ""),
                    "distancia_m": round(float(p.get("distancia") or 0) * 1000)}
    return None


async def geologia(rc: str) -> list[dict]:
    props = await _interseccion("unitats-geologiques-50000", rc) or []
    vistas, salida = set(), []
    for p in props:
        clave = p.get("Codi")
        if clave in vistas:
            continue
        vistas.add(clave)
        salida.append({"codigo": clave, "descripcion": p.get("Descripcio", ""),
                       "edad": " · ".join(filter(None, [p.get("Periode"), p.get("Epoca")]))})
    return salida


async def sondeos(lon: float, lat: float, parcela: BaseGeometry) -> list[dict]:
    try:
        r = await asyncio.wait_for(http.cliente().post(
            f"{API}/processes/intersection/execution",
            json={"inputs": {"capa": "prospeccions-geotecniques", "X": lon, "Y": lat, "EPSG": "4326",
                             "buffer": RADIO_SONDEOS_M, "skipgeometry": False}}), timeout=20)
        feats = r.json().get("features") or [] if r.status_code == 200 else []
    except Exception:  # noqa: BLE001
        return []
    salida = []
    for f in feats:
        p = f.get("properties") or {}
        dist = None
        try:
            x, y = (f.get("geometry") or {}).get("coordinates")[:2]
            if abs(x) <= 180:
                x, y = geo.a_utm(x, y)
            dist = round(Point(x, y).distance(parcela))
        except (TypeError, ValueError):
            pass
        freatico = str(p.get("profunditat nivell freàtic") or "").strip()
        salida.append({
            "sondeo": p.get("sondeig", ""), "informe": p.get("informe", ""), "anio": p.get("any", ""),
            "tipo": p.get("tècnica") or p.get("tipus", ""), "profundidad_m": p.get("profunditat"),
            "freatico_m": freatico or None, "promotor": p.get("promotor", ""), "pdf": p.get("columna", ""),
            "ensayos": bool(p.get("assaig laboratori") or p.get("assaig in situ")), "distancia_m": dist,
        })
    salida.sort(key=lambda s: (s["distancia_m"] is None, s["distancia_m"] or 0))
    return salida[:8]


def _campos_xml(texto: str) -> list[dict]:
    try:
        raiz = ElementTree.fromstring(texto)
    except ElementTree.ParseError:
        return []
    return [dict(e.attrib) for e in raiz.iter() if e.tag.endswith("FIELDS")]


async def riesgos_geologicos(x: float, y: float) -> dict:
    """Mapa de prevención de riesgos geológicos 1:25 000 en el centro de la parcela."""
    async def gfi(capa: str) -> list[dict]:
        params = {"SERVICE": "WMS", "REQUEST": "GetFeatureInfo", "VERSION": "1.3.0", "LAYERS": capa, "QUERY_LAYERS": capa,
                  "CRS": "EPSG:25831", "BBOX": f"{x - 50},{y - 50},{x + 50},{y + 50}", "WIDTH": 101, "HEIGHT": 101,
                  "I": 50, "J": 50, "INFO_FORMAT": "text/xml", "FEATURE_COUNT": 5, "STYLES": ""}
        try:
            return _campos_xml(await asyncio.wait_for(http.get_text(WMS_RIESGOS, params), timeout=15))
        except Exception:  # noqa: BLE001
            return []
    hoja, municipal, *capas = await asyncio.gather(gfi("G6F25_PA"), gfi("EIRG_PA"), *[gfi(c) for c, _ in RIESGOS_WMS])
    cubierto = bool(hoja)
    peligros = []
    for (codigo, titulo), filas in zip(RIESGOS_WMS, capas):
        for f in filas:
            desc = (f.get("Descripció") or f.get("Descripcio") or "").strip()
            if desc and f.get("Coditipus") != "NO_OBS":
                peligros.append({"tipo": titulo, "descripcion": desc, "nivel": _nivel(desc)})
    estudios = []
    for f in municipal:
        for k, v in f.items():
            if k.startswith("Títolinforme") and v.strip():
                estudios.append(v.strip())
    return {"cubierto": cubierto, "hoja": (hoja[0].get("Full25Mabsolut") if hoja else ""),
            "estado_hoja": (hoja[0].get("Estat") if hoja else ""), "peligros": peligros, "estudios_municipales": estudios}


def _nivel(desc: str) -> str:
    d = desc.lower()
    return "alta" if "alta" in d else "mitjana" if re.search(r"mitjana|moderada|mitja", d) else "baixa" if "baixa" in d else ""


async def consultar(parcela: BaseGeometry, rc: str) -> dict:
    rc = (rc or "")[:14]
    c = parcela.representative_point()
    lon, lat = geo.a_wgs84(c.x, c.y)
    capas = list(AFECCIONES)
    rel, postal, geol, sond, riesgos, *afec = await asyncio.gather(
        relieve(parcela), direccion_postal(lon, lat), geologia(rc), sondeos(lon, lat, parcela),
        riesgos_geologicos(c.x, c.y), *[_interseccion(capa, rc) for capa in capas])
    afecciones, descriptivas, sin_respuesta = [], {}, []
    for capa, props in zip(capas, afec):
        grupo, titulo, detalle = AFECCIONES[capa]
        if props is None:
            sin_respuesta.append(titulo)
            continue
        if not props:
            continue
        detalles = sorted({d for d in (detalle(p) for p in props) if d})
        if capa in DESCRIPTIVAS:
            descriptivas[capa] = ", ".join(detalles)
            continue
        afecciones.append({"grupo": grupo, "titulo": titulo, "detalle": "; ".join(detalles[:3]), "capa": capa})
    if rel is None and not geol and not afecciones and len(sin_respuesta) == len(capas):
        return resultado("error", FUENTE, URL, mensaje="El servicio del ICGC no responde.")
    return resultado(
        "ok", FUENTE, URL, fecha_dato="Datos vigentes en la fecha de consulta",
        relieve=rel, direccion_postal=postal, geologia=geol, sondeos=sond, radio_sondeos_m=RADIO_SONDEOS_M,
        riesgos=riesgos, afecciones=afecciones, capacidad_agrologica=descriptivas.get("capacitat-agrologica", ""),
        sin_respuesta=sin_respuesta,
    )
