"""Carga precios del suelo urbano por municipio en datos/precio_suelo.csv.

Uso:
  python -m scripts.importar_precio_suelo FICHERO --fuente "Ministerio de Transportes"

Columnas que se reconocen: código INE del municipio, municipio, año, trimestre,
precio €/m² y número de transacciones. Si el fichero no trae código INE, se puede
pasar --municipio-ine con una tabla nombre;codigo.
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from scripts.tabla import columna, leer, norm, num  # noqa: E402

CAMPOS = ["cod_ine", "municipio", "anio", "trimestre", "precio_m2", "num_transacciones", "fuente"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fichero")
    ap.add_argument("--fuente", default="Ministerio de Transportes, precio del suelo urbano")
    ap.add_argument("--hoja")
    ap.add_argument("--municipio-ine", help="CSV nombre;codigo para asignar códigos INE")
    a = ap.parse_args()
    filas = leer(a.fichero, a.hoja)
    cab = list(filas[0].keys())
    c_ine = columna(cab, "codigo ine", "cod ine", "ine", "codigo")
    c_mun = columna(cab, "municipio", "municipi")
    c_any = columna(cab, "ano", "año", "any", "periodo")
    c_tri = columna(cab, "trimestre")
    c_pre = columna(cab, "precio", "valor", "euros m2")
    c_num = columna(cab, "transacciones", "numero")
    tabla_ine = {}
    if a.municipio_ine:
        for f in leer(a.municipio_ine):
            v = list(f.values())
            tabla_ine[norm(v[0])] = str(v[1]).zfill(5)
    nuevas = []
    for f in filas:
        precio = num(f.get(c_pre))
        if not precio:
            continue
        ine = str(f.get(c_ine) or "").strip().zfill(5) if c_ine else tabla_ine.get(norm(f.get(c_mun)), "")
        if not ine.strip("0"):
            continue
        nuevas.append({"cod_ine": ine, "municipio": f.get(c_mun, ""), "anio": int(num(f.get(c_any)) or 0),
                       "trimestre": int(num(f.get(c_tri)) or 0) if c_tri else 0, "precio_m2": precio,
                       "num_transacciones": num(f.get(c_num)) if c_num else "", "fuente": a.fuente})
    destino = config.FICHERO_SUELO
    destino.parent.mkdir(parents=True, exist_ok=True)
    existentes = []
    if destino.exists():
        with open(destino, encoding="utf-8") as fh:
            existentes = [r for r in csv.DictReader(fh) if r["fuente"] != a.fuente]
    with open(destino, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS)
        w.writeheader()
        w.writerows(existentes + nuevas)
    print(f"Cargados {len(nuevas)} registros de precio del suelo.")


if __name__ == "__main__":
    main()
