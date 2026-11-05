"""Descarga la capacidad de acceso de demanda publicada por e-distribución (Circular 1/2024 CNMC)
y guarda los nudos de Cataluña en datos/capacidad_red.csv.

La distribuidora publica cada mes un CSV nuevo; la dirección cambia, así que se busca en su página.
Se ejecuta al arrancar el servidor (rápido, ~250 KB) y se puede lanzar a mano:
  python -m scripts.descargar_capacidad_red
"""
import csv
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from pyproj import Transformer  # noqa: E402

from app import config  # noqa: E402

PAGINA = "https://www.edistribucion.com/es/red-electrica/nodos-capacidad-red/capacidad-demanda.html"
BASE = "https://www.edistribucion.com"
PROVINCIAS_CAT = {"08", "17", "25", "43"}
CAMPOS = ["gestor", "nudo", "tension_kv", "lon", "lat", "cap_disponible_mw", "cap_ocupada_mw", "cap_tramite_mw", "marca_0",
          "fecha_fichero", "municipio", "comentario"]


def _f(v: str) -> float | None:
    try:
        return float(str(v).replace(".", "").replace(",", ".")) if "," in str(v) else float(v)
    except (TypeError, ValueError):
        return None


def enlace_csv(html: str) -> tuple[str, str]:
    """Último CSV de demanda de e-distribución (R1-299). Devuelve (url, fecha AAAA-MM)."""
    m = re.findall(r'href="([^"]*?/demanda/(\d{4})(\d{2})/[^"]*?R1299_demanda\.csv)"', html)
    if not m:
        raise SystemExit("No se encuentra el CSV de capacidad en la página de e-distribución.")
    ruta, anio, mes = sorted(m, key=lambda x: x[1] + x[2])[-1]
    return (ruta if ruta.startswith("http") else BASE + ruta), f"{anio}-{mes}"


def convertir(texto: str, fecha: str) -> list[dict]:
    a_wgs = Transformer.from_crs(config.EPSG_UTM, config.EPSG_WGS84, always_xy=True)
    filas = list(csv.reader(io.StringIO(texto), delimiter=";"))
    salida = []
    for r in filas[1:]:
        if len(r) < 17 or r[1].strip().zfill(2) not in PROVINCIAS_CAT:
            continue
        x, y = _f(r[3]), _f(r[4])
        if not x or not y:
            continue
        lon, lat = a_wgs.transform(x, y)
        salida.append({
            "gestor": "e-distribución", "nudo": r[16].strip() or r[5].strip(), "tension_kv": _f(r[6]),
            "lon": round(lon, 6), "lat": round(lat, 6), "cap_disponible_mw": _f(r[7]), "cap_ocupada_mw": _f(r[9]),
            "cap_tramite_mw": _f(r[10]), "marca_0": "1" if r[13].strip() in ("1", "S", "Sí", "SI") else "0",
            "fecha_fichero": fecha, "municipio": r[18].strip() if len(r) > 18 else "", "comentario": r[14].strip(),
        })
    return salida


def main():
    with httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36", "Accept-Language": "es-ES,es;q=0.9"}) as c:
        url, fecha = enlace_csv(c.get(PAGINA).text)
        datos = c.get(url).content
    try:
        texto = datos.decode("utf-8")
    except UnicodeDecodeError:
        texto = datos.decode("latin-1")
    filas = convertir(texto, fecha)
    config.FICHERO_RED.parent.mkdir(parents=True, exist_ok=True)
    with open(config.FICHERO_RED, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        w.writeheader()
        w.writerows(filas)
    print(f"Capacidad de red: {len(filas)} posiciones de Cataluña ({fecha}) en {config.FICHERO_RED}")


if __name__ == "__main__":
    main()
