"""Lectura flexible de CSV/XLSX con cabeceras que cambian de un fichero a otro."""
import csv
import re
import unicodedata
from pathlib import Path


def norm(t: str) -> str:
    t = unicodedata.normalize("NFD", str(t or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def leer(ruta: str | Path, hoja: str | None = None) -> list[dict]:
    """Devuelve filas como dicts. Detecta la fila de cabecera (la primera con varias celdas de texto)."""
    ruta = Path(ruta)
    if ruta.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(ruta, read_only=True, data_only=True)
        ws = wb[hoja] if hoja else wb.worksheets[0]
        filas = [list(r) for r in ws.iter_rows(values_only=True)]
    else:
        texto = ruta.read_bytes()
        for cod in ("utf-8-sig", "latin-1"):
            try:
                texto = texto.decode(cod)
                break
            except UnicodeDecodeError:
                continue
        dialecto = csv.Sniffer().sniff(texto[:5000], delimiters=";,\t")
        filas = list(csv.reader(texto.splitlines(), dialecto))
    for i, f in enumerate(filas[:30]):
        textos = [c for c in f if isinstance(c, str) and c.strip()]
        if len(textos) >= 3:
            cab = [str(c or "").strip() for c in f]
            return [dict(zip(cab, r)) for r in filas[i + 1:] if any(v not in (None, "") for v in r)]
    raise ValueError("No se encontró la fila de cabecera")


def columna(cabeceras: list[str], *patrones: str) -> str | None:
    """Primera cabecera que contiene todas las palabras de alguno de los patrones."""
    nc = {c: norm(c) for c in cabeceras}
    for p in patrones:
        palabras = norm(p).split()
        for c, n in nc.items():
            if all(w in n.split() or w in n for w in palabras):
                return c
    return None


def num(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None
