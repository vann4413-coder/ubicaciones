"""Parámetros urbanísticos de la zona según las normas del plan general (PGOU / POUM) del municipio.

Los parámetros (parcela mínima, frente mínimo, edificabilidad, ocupación, altura, usos) se extraen
una vez por municipio de las Normes urbanístiques y se guardan en app/data/pgou/<código INE>.json.
Para cada calificación de la parcela se busca la clave municipal exacta (p. ej. «2d3») y, si no
existe, la zona madre («2d», luego «2»).
"""
import json
import re
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "data" / "pgou"
CAMPOS = ("parcela_minima_m2", "frente_minimo_m", "edificabilidad", "ocupacion_max", "altura_max", "usos", "otros")


@lru_cache(maxsize=64)
def _municipio(cod_ine5: str) -> dict | None:
    f = DIR / f"{cod_ine5}.json"
    if not f.exists():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def _candidatas(clave: str) -> list[str]:
    """'2d3' -> ['2d3', '2d', '2'];  '3b28 HPP' -> ['3b28 hpp', '3b28', '3b2', '3b', '3']: de la más concreta a la zona madre."""
    c = re.sub(r"[()]", "", (clave or "").strip().lower())
    salida = [c]
    base = re.split(r"[\s/_\-*]", c)[0]
    for i in range(len(base), 0, -1):
        if base[:i] not in salida:
            salida.append(base[:i])
    return salida


def zona(cod_ine5: str, clave_municipal: str) -> dict | None:
    m = _municipio(cod_ine5)
    if not m:
        return None
    zonas = {k.lower(): v for k, v in (m.get("zonas") or {}).items()}
    for c in _candidatas(clave_municipal):
        if c in zonas:
            return {"clave": c, "exacta": c == _candidatas(clave_municipal)[0], **zonas[c]}
    return None


def segregacion(zona: dict | None, superficie: float | None, frente: float | None) -> dict | None:
    """¿Se puede segregar la parcela según la parcela mínima y el frente mínimo de la zona?"""
    if not zona:
        return None
    if zona.get("segregacion"):
        return {"posible": None, "texto": zona["segregacion"]}
    pmin, fmin = zona.get("parcela_minima_m2"), zona.get("frente_minimo_m")
    if not pmin or not superficie:
        return None
    n = int(superficie // pmin)
    if n < 2:
        return {"posible": False, "partes": 1,
                "texto": f"No: harían falta al menos {2 * pmin:,.0f} m² para dos parcelas de la mínima ({pmin:,.0f} m²).".replace(",", ".")}
    texto = f"Sí, en principio hasta {n} parcelas de " + f"{pmin:,.0f} m²".replace(",", ".")
    if fmin and frente:
        n_frente = int(frente // fmin)
        if n_frente < 2:
            return {"posible": False, "partes": 1,
                    "texto": f"No por frente: la superficie daría para {n}, pero el frente a vial ({frente:.0f} m) no llega a dos frentes mínimos de {fmin:.0f} m."}
        if n_frente < n:
            n = n_frente
            texto = f"Sí, hasta {n} parcelas (limitado por el frente a vial de {frente:.0f} m y el frente mínimo de {fmin:.0f} m)"
    return {"posible": True, "partes": n, "texto": texto + ", sujeto a licencia de parcelación."}


def consultar(cod_ine5: str, calificaciones: list[dict]) -> dict | None:
    """Parámetros de cada calificación de la parcela, o None si el municipio aún no está cargado."""
    m = _municipio(cod_ine5 or "")
    if not m:
        return None
    filas = []
    for q in calificaciones or []:
        if (q.get("codigo_muc") or "").upper().startswith("S"):
            continue  # sistemas (viario, equipamientos, espacios libres): sin parámetros de zona
        z = zona(cod_ine5, q.get("codigo_municipal", ""))
        filas.append({"clave_parcela": q.get("codigo_municipal", ""), "descripcion": q.get("descripcion_municipal", ""),
                      "pct": q.get("pct"), "zona": z})
    return {"plan": m.get("plan", ""), "documento": m.get("documento", ""), "modificaciones": m.get("modificaciones", []),
            "revisado": m.get("revisado", ""), "zonas": filas,
            "parcela_minima_m2": next((f["zona"].get("parcela_minima_m2") for f in filas
                                       if f["zona"] and f["zona"].get("parcela_minima_m2")), None)}
