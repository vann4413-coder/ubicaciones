"""Carga aforos (IMD) en datos/aforos.csv.

Uso:
  python -m scripts.importar_aforos FICHERO --anio 2025 --fuente "Generalitat, Pla d'aforaments 2025"
  python -m scripts.importar_aforos FICHERO --anio 2024 --fuente "Ministerio de Transportes, estimación de tráfico 2024" --organismo Estado

El fichero puede ser CSV o XLSX (p. ej. la exportación de la tabla del Power BI del
Pla d'aforaments, o la tabla extraída del PDF anual del Ministerio). Columnas que se
reconocen (en catalán o castellano): carretera, PK, IMD, % pesados, código de estación,
organismo, tipo, y coordenadas (lon/lat o X/Y UTM 31N). Las filas de la misma fuente y
año se sustituyen; las demás se conservan.
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, geo  # noqa: E402
from scripts.tabla import columna, leer, num  # noqa: E402

CAMPOS = ["carretera", "pk", "imd", "pct_pesados", "anio", "organismo", "tipo", "codigo_estacion", "lon", "lat", "fuente"]


def convertir(filas: list[dict], anio: int, fuente: str, organismo: str = "") -> list[dict]:
    if not filas:
        return []
    cab = list(filas[0].keys())
    c_carr = columna(cab, "carretera", "via", "road")
    c_pk = columna(cab, "pk estacio", "pk", "punt quilometric", "punto kilometrico")
    c_imd = columna(cab, "imd total", "imd")
    c_pes = columna(cab, "pesants", "pesados")
    c_any = columna(cab, "any", "ano", "año")
    c_org = columna(cab, "organisme", "organismo", "titular")
    c_tipo = columna(cab, "tipus", "tipo")
    c_est = columna(cab, "codi estacio", "codigo estacion", "estacio", "estacion")
    c_lat = columna(cab, "lat", "latitud")
    # "Longitud" también es la longitud del tramo en km: solo se usa como coordenada si hay latitud.
    c_lon = columna(cab, "lon", "longitud") if c_lat else None
    c_x = columna(cab, "utm x", "coord x", "x")
    c_y = columna(cab, "utm y", "coord y", "y")
    if not c_carr or not c_imd:
        raise SystemExit(f"Faltan columnas de carretera o IMD. Cabeceras: {cab}")
    salida = []
    for f in filas:
        imd = num(f.get(c_imd))
        if not imd or not f.get(c_carr):
            continue
        lon = num(f.get(c_lon)) if c_lon else None
        lat = num(f.get(c_lat)) if c_lat else None
        if (lon is None or lat is None) and c_x and c_y and num(f.get(c_x)) and num(f.get(c_y)):
            lon, lat = geo.a_wgs84(num(f[c_x]), num(f[c_y]))
        salida.append({
            "carretera": str(f[c_carr]).strip(),
            "pk": str(f.get(c_pk) or "").strip() if c_pk else "",
            "imd": int(imd),
            "pct_pesados": num(f.get(c_pes)) if c_pes else "",
            "anio": int(num(f.get(c_any)) or anio) if c_any else anio,
            "organismo": (str(f.get(c_org) or "").strip() if c_org else "") or organismo,
            "tipo": str(f.get(c_tipo) or "").strip() if c_tipo else "",
            "codigo_estacion": str(f.get(c_est) or "").strip() if c_est else "",
            "lon": round(lon, 6) if lon is not None else "",
            "lat": round(lat, 6) if lat is not None else "",
            "fuente": fuente,
        })
    return salida


def mas_recientes(filas: list[dict]) -> list[dict]:
    """Una fila por estación de aforo: la de la medida más reciente (los planes anuales repiten estaciones)."""
    sin_codigo = [f for f in filas if not f["codigo_estacion"]]
    mejor: dict[tuple, dict] = {}
    for f in filas:
        if f["codigo_estacion"]:
            k = (f["carretera"], f["codigo_estacion"])
            if k not in mejor or f["anio"] > mejor[k]["anio"]:
                mejor[k] = f
    return list(mejor.values()) + sin_codigo


def guardar(nuevas: list[dict], fuente: str, anio: int, destino: Path = config.FICHERO_AFOROS) -> int:
    existentes = []
    if destino.exists():
        with open(destino, encoding="utf-8") as f:
            existentes = [r for r in csv.DictReader(f) if not (r["fuente"] == fuente and r["anio"] == str(anio))]
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        w.writeheader()
        w.writerows(existentes + nuevas)
    return len(existentes) + len(nuevas)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fichero")
    ap.add_argument("--anio", type=int, required=True)
    ap.add_argument("--fuente", required=True)
    ap.add_argument("--organismo", default="")
    ap.add_argument("--hoja")
    a = ap.parse_args()
    filas = mas_recientes(convertir(leer(a.fichero, a.hoja), a.anio, a.fuente, a.organismo))
    total = guardar(filas, a.fuente, a.anio)
    sin_coord = sum(1 for f in filas if f["lon"] == "")
    print(f"Cargados {len(filas)} aforos ({sin_coord} sin coordenadas: se asignan por carretera y PK). Total en fichero: {total}.")


if __name__ == "__main__":
    main()
