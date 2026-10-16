"""Convierte lo que escribe el usuario (dirección, RC o coordenadas) en candidatos con coordenadas."""
import re

from app import config, geo, http
from app.fuentes import catastro

RE_COORD = re.compile(r"^\s*(-?\d+(?:[.,]\d+)?)\s*[,;\s]\s*(-?\d+(?:[.,]\d+)?)\s*$")


def interpretar_coordenadas(texto: str) -> tuple[float, float] | None:
    """Admite 'lat, lon' (WGS84) o 'x, y' (UTM 31N). Devuelve (lon, lat)."""
    m = RE_COORD.match(texto or "")
    if not m:
        return None
    a, b = (float(v.replace(",", ".")) for v in m.groups())
    if 39 < a < 44 and -1 < b < 4:  # lat, lon
        return b, a
    if -1 < a < 4 and 39 < b < 44:  # lon, lat
        return a, b
    if 200_000 < a < 600_000 and 4_400_000 < b < 4_800_000:  # UTM
        return geo.a_wgs84(a, b)
    return None


async def buscar(texto: str) -> list[dict]:
    """Lista de candidatos {etiqueta, lon, lat, rc?}."""
    texto = (texto or "").strip()
    if not texto:
        return []

    rc = catastro.normalizar_rc(texto)
    if rc:
        c = await catastro.coordenadas_de_rc(rc[:14])
        return [{"etiqueta": f"Referencia catastral {rc[:14]}", "lon": c[0], "lat": c[1], "rc": rc[:14]}] if c else []

    c = interpretar_coordenadas(texto)
    if c:
        return [{"etiqueta": f"Coordenadas {c[1]:.6f}, {c[0]:.6f}", "lon": c[0], "lat": c[1]}]

    d = await http.get_json(f"{config.ICGC_GEOCODER}/cerca", {"text": texto, "size": 8})
    return parse_icgc(d)


async def municipio_en_punto(lon: float, lat: float) -> dict | None:
    """Municipio (nombre, código Idescat de 6 dígitos y comarca) que contiene el punto."""
    d = await http.get_json(f"{config.ICGC_GEOCODER}/invers", {"lon": f"{lon:.6f}", "lat": f"{lat:.6f}", "size": 1})
    for f in d.get("features", []):
        p = f.get("properties") or {}
        if p.get("id_municipi"):
            return {"nombre": p.get("municipi", ""), "codigo6": p["id_municipi"], "codigo_ine": p["id_municipi"][:5],
                    "comarca": p.get("comarca", "")}
    return None


def parse_icgc(d: dict) -> list[dict]:
    salida = []
    for f in d.get("features", []):
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        p = f.get("properties") or {}
        salida.append({"etiqueta": p.get("etiqueta") or p.get("label") or p.get("nom", ""), "lon": coords[0], "lat": coords[1]})
    return salida
