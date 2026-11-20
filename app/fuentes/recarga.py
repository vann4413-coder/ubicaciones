"""Puntos de recarga eléctrica: registro oficial publicado en el Punto de Acceso Nacional (DGT / MITERD).

Los operadores están obligados a publicar sus puntos de recarga de acceso público (RD 184/2022).
El fichero es un XML DATEX II v3 de unos 80 MB que se actualiza cada 24 h: se descarga en segundo
plano, se reduce a lo que usa el informe (ubicación, operador, número de puntos y potencia) y se
guarda en `datos/puntos_recarga.json`.
"""
import json
import logging
import os
import tempfile
import time
import xml.etree.ElementTree as ET
from functools import lru_cache

import httpx
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from app import config, geo
from app.fuentes.base import resultado

log = logging.getLogger(__name__)

FUENTE = "Punto de Acceso Nacional de Tráfico y Movilidad (DGT) – puntos de recarga de vehículos eléctricos"
URL = "https://nap.dgt.es/dataset/puntos-de-recarga-electrica-para-vehiculos"
URL_XML = "https://nap.dgt.es/datex2/v3/miterd/EnergyInfrastructureTablePublication/electrolineras.xml"
FICHERO = config.DATOS_DIR / "puntos_recarga.json"
CADUCIDAD_S = 24 * 3600

ULTRARRAPIDA_KW = 150
RAPIDA_KW = 50
SEMIRRAPIDA_KW = 22


def categoria(kw: float | None) -> str:
    if not kw:
        return "sin_dato"
    if kw >= ULTRARRAPIDA_KW:
        return "ultrarrapida"
    if kw >= RAPIDA_KW:
        return "rapida"
    if kw >= SEMIRRAPIDA_KW:
        return "semirrapida"
    return "lenta"


NOMBRE_CATEGORIA = {"ultrarrapida": "Ultrarrápida (≥150 kW)", "rapida": "Rápida (50–149 kW)",
                    "semirrapida": "Semirrápida (22–49 kW)", "lenta": "Lenta (<22 kW)", "sin_dato": "Potencia sin dato"}


# ---------------------------------------------------------------- lectura del XML DATEX II

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _hijos(el, nombre: str):
    return [c for c in el if _local(c.tag) == nombre]


def _hijo(el, nombre: str):
    for c in el:
        if _local(c.tag) == nombre:
            return c
    return None


def _desc(el, nombre: str):
    """Todos los descendientes con ese nombre local."""
    return [c for c in el.iter() if _local(c.tag) == nombre]


def _texto(el) -> str:
    """Primer texto no vacío del subárbol (los textos DATEX II van en values/value)."""
    if el is None:
        return ""
    for c in el.iter():
        if c.text and c.text.strip():
            return c.text.strip()
    return ""


def _num(s: str) -> float | None:
    try:
        return float(str(s).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _kw(valor: float | None) -> float | None:
    """La potencia viene en W (lo habitual) o en kW."""
    if valor is None or valor <= 0:
        return None
    return round(valor / 1000, 1) if valor >= 1000 else round(valor, 1)


def _direccion(site) -> tuple[str, str, str]:
    calle, municipio, cp, libres = "", "", "", []
    for addr in _desc(site, "address"):
        for linea in _hijos(addr, "addressLine"):
            t = _texto(linea)
            if not t:
                continue
            low = t.lower()
            if low.startswith(("dirección", "direccion")):
                calle = calle or t.split(":", 1)[-1].strip()
            elif low.startswith("municipio"):
                municipio = municipio or t.split(":", 1)[-1].strip()
            elif low.startswith(("provincia", "comunidad")):
                continue
            else:
                libres.append(t)
        cp = cp or _texto(_hijo(addr, "postcode"))
    return (calle or ", ".join(libres)), municipio, cp


def parse_site(site) -> dict | None:
    coords = next(iter(_desc(site, "coordinatesForDisplay")), None)
    if coords is None:
        return None
    lat, lon = _num(_texto(_hijo(coords, "latitude"))), _num(_texto(_hijo(coords, "longitude")))
    if lat is None or lon is None:
        return None
    operador = ""
    for op in _desc(site, "operator"):
        operador = _texto(_hijo(op, "name")) or _texto(op)
        if operador:
            break
    calle, municipio, cp = _direccion(site)
    puntos = []  # potencia máxima de cada punto de recarga (refillPoint)
    for rp in _desc(site, "refillPoint"):
        pot = [_kw(_num(_texto(m))) for m in _desc(rp, "maxPowerAtSocket")]
        pot = [p for p in pot if p]
        if not pot:  # algunos operadores solo informan la potencia del punto
            pot = [p for p in (_kw(_num(_texto(m))) for m in _desc(rp, "availableChargingPower")) if p]
        puntos.append(max(pot) if pot else None)
    potencias = [p for p in puntos if p]
    return {
        "id": site.get("id", ""),
        "nombre": _texto(_hijo(site, "name")),
        "operador": operador,
        "direccion": calle,
        "municipio": municipio,
        "cp": cp,
        "lat": round(lat, 6), "lon": round(lon, 6),
        "puntos": len(puntos),
        "max_kw": max(potencias) if potencias else None,
        "ultrarrapidos": sum(1 for p in potencias if p >= ULTRARRAPIDA_KW),
        "rapidos": sum(1 for p in potencias if RAPIDA_KW <= p < ULTRARRAPIDA_KW),
    }


def parse_xml(origen) -> list[dict]:
    """Lee el XML por partes (no carga los 80 MB en memoria)."""
    salida = []
    for _, el in ET.iterparse(origen, events=("end",)):
        if _local(el.tag) == "energyInfrastructureSite":
            try:
                s = parse_site(el)
                if s:
                    salida.append(s)
            except Exception:  # noqa: BLE001  un sitio mal formado no debe impedir el resto
                log.debug("Punto de recarga ilegible", exc_info=True)
            el.clear()
    return salida


# ---------------------------------------------------------------- descarga y caché en disco

def descargar() -> int:
    """Descarga el registro, lo reduce y lo guarda. Devuelve el número de ubicaciones."""
    FICHERO.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".xml", dir=FICHERO.parent, delete=False) as tmp:
        ruta_xml = tmp.name
    try:
        with httpx.stream("GET", URL_XML, timeout=httpx.Timeout(60, read=300), follow_redirects=True,
                          headers={"User-Agent": config.USER_AGENT}) as r:
            r.raise_for_status()
            with open(ruta_xml, "wb") as f:
                for trozo in r.iter_bytes(1 << 20):
                    f.write(trozo)
        sitios = parse_xml(ruta_xml)
        if not sitios:
            raise ValueError("El registro de puntos de recarga ha llegado vacío")
        datos = {"descargado": time.strftime("%Y-%m-%d %H:%M"), "sitios": sitios}
        tmp_json = FICHERO.with_suffix(".tmp")
        tmp_json.write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp_json, FICHERO)
        log.info("Puntos de recarga actualizados: %d ubicaciones", len(sitios))
        return len(sitios)
    finally:
        try:
            os.remove(ruta_xml)
        except OSError:
            pass


def caducado() -> bool:
    return not FICHERO.exists() or time.time() - FICHERO.stat().st_mtime > CADUCIDAD_S


@lru_cache(maxsize=1)
def _cargar(ruta: str, mtime: float) -> dict:
    d = json.loads(open(ruta, encoding="utf-8").read())
    for s in d["sitios"]:
        s["x"], s["y"] = geo.a_utm(s["lon"], s["lat"])
    return d


def datos() -> dict | None:
    if not FICHERO.exists():
        return None
    return _cargar(str(FICHERO), FICHERO.stat().st_mtime)


# ---------------------------------------------------------------- consulta para el informe

def buscar(sitios: list[dict], parcela: BaseGeometry, radio: float) -> list[dict]:
    c = parcela.centroid
    salida = []
    for s in sitios:
        if abs(s["x"] - c.x) > radio + 2000 or abs(s["y"] - c.y) > radio + 2000:
            continue
        dist = Point(s["x"], s["y"]).distance(parcela)
        if dist > radio:
            continue
        salida.append({k: v for k, v in s.items() if k not in ("x", "y")} | {"distancia_m": round(dist),
                                                                             "categoria": categoria(s.get("max_kw"))})
    return sorted(salida, key=lambda s: s["distancia_m"])


def consultar(parcela: BaseGeometry, radio: float = 5000) -> dict:
    d = datos()
    if not d:
        return resultado("sin_dato", FUENTE, URL,
                         mensaje="El registro oficial de puntos de recarga se está descargando; estará disponible en los próximos informes.")
    return resultado("ok", FUENTE, URL, fecha_dato=f"Registro descargado el {d['descargado']}",
                     sitios=buscar(d["sitios"], parcela, radio))


def resumen(rec: dict, radio: int = 2000) -> dict:
    """KPIs y lista para la sección del informe (sin los puntos de la propia parcela)."""
    if rec.get("estado") != "ok":
        return {"estado": rec.get("estado"), "mensaje": rec.get("mensaje")}
    todos = [s for s in rec.get("sitios", []) if s["distancia_m"] > 0]
    en_parcela = [s for s in rec.get("sitios", []) if s["distancia_m"] == 0]
    cerca = [s for s in todos if s["distancia_m"] <= radio]
    ultra = [s for s in todos if s["categoria"] == "ultrarrapida"]
    return {
        "estado": "ok",
        "sitios": cerca,
        "en_parcela": en_parcela,
        "por_radio": {r: sum(1 for s in todos if s["distancia_m"] <= r) for r in (500, 1000, 2000, 5000)},
        "puntos_2km": sum(s["puntos"] for s in cerca),
        "ultra_2km": sum(1 for s in cerca if s["categoria"] == "ultrarrapida"),
        "rapidas_2km": sum(1 for s in cerca if s["categoria"] == "rapida"),
        "ultra_mas_cercana": ultra[0] if ultra else None,
        "mas_cercana": cerca[0] if cerca else None,
        "nombres": NOMBRE_CATEGORIA,
    }
