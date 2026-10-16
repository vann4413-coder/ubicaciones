"""Carga el fichero mensual de capacidad de acceso de una distribuidora en datos/capacidad_red.csv.

Uso:
  python -m scripts.importar_capacidad_red FICHERO --gestor "e-distribución" --fecha 2026-10

Formato de origen: el que fija la Circular 1/2024 de la CNMC (XLSX o CSV). Se reconocen
columnas de nombre del nudo/subestación, tensión, coordenadas (UTM con huso o lon/lat),
capacidad disponible, ocupada y en trámite, y la marca 0*. Las filas del mismo gestor
se sustituyen.
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pyproj import Transformer  # noqa: E402

from app import config  # noqa: E402
from scripts.tabla import columna, leer, num  # noqa: E402

CAMPOS = ["gestor", "nudo", "tension_kv", "lon", "lat", "cap_disponible_mw", "cap_ocupada_mw", "cap_tramite_mw", "marca_0", "fecha_fichero"]


def _a_wgs84(x, y, huso):
    epsg = {29: 25829, 30: 25830, 31: 25831}.get(int(huso or 31), 25831)
    return Transformer.from_crs(epsg, 4326, always_xy=True).transform(x, y)


def convertir(filas: list[dict], gestor: str, fecha: str) -> list[dict]:
    cab = list(filas[0].keys())
    c_nudo = columna(cab, "nombre subestacion", "subestacion", "nudo", "nombre")
    c_ten = columna(cab, "tension", "kv")
    c_x = columna(cab, "coordenada x", "utm x", "x")
    c_y = columna(cab, "coordenada y", "utm y", "y")
    c_huso = columna(cab, "huso")
    c_lon = columna(cab, "longitud", "lon")
    c_lat = columna(cab, "latitud", "lat")
    c_disp = columna(cab, "capacidad disponible", "disponible")
    c_ocup = columna(cab, "capacidad ocupada", "ocupada")
    c_tram = columna(cab, "tramite", "trámite", "solicitudes en curso", "pendiente")
    c_marca = columna(cab, "0*", "marca", "observaciones")
    if not c_nudo or not c_disp or not ((c_x and c_y) or (c_lon and c_lat)):
        raise SystemExit(f"No se reconocen las columnas necesarias. Cabeceras: {cab}")
    salida = []
    for f in filas:
        if not f.get(c_nudo):
            continue
        lon = num(f.get(c_lon)) if c_lon else None
        lat = num(f.get(c_lat)) if c_lat else None
        if lon is None or lat is None:
            x, y = num(f.get(c_x)), num(f.get(c_y))
            if x is None or y is None:
                continue
            lon, lat = _a_wgs84(x, y, num(f.get(c_huso)) if c_huso else 31)
        marca = str(f.get(c_marca) or "") if c_marca else ""
        disp_txt = str(f.get(c_disp) or "")
        salida.append({
            "gestor": gestor, "nudo": str(f[c_nudo]).strip(),
            "tension_kv": num(f.get(c_ten)) if c_ten else "",
            "lon": round(lon, 6), "lat": round(lat, 6),
            "cap_disponible_mw": num(disp_txt.replace("*", "")) or 0,
            "cap_ocupada_mw": num(f.get(c_ocup)) if c_ocup else "",
            "cap_tramite_mw": num(f.get(c_tram)) if c_tram else "",
            "marca_0": 1 if ("0*" in marca or "0*" in disp_txt) else 0,
            "fecha_fichero": fecha,
        })
    return salida


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fichero")
    ap.add_argument("--gestor", required=True)
    ap.add_argument("--fecha", required=True, help="Mes de publicación, p. ej. 2026-10")
    ap.add_argument("--hoja")
    a = ap.parse_args()
    nuevas = convertir(leer(a.fichero, a.hoja), a.gestor, a.fecha)
    destino = config.FICHERO_RED
    existentes = []
    if destino.exists():
        with open(destino, encoding="utf-8") as f:
            existentes = [r for r in csv.DictReader(f) if r["gestor"] != a.gestor]
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        w.writeheader()
        w.writerows(existentes + nuevas)
    print(f"Cargados {len(nuevas)} nudos de {a.gestor}.")


if __name__ == "__main__":
    main()
