"""Descarga la IMD de la red de la Generalitat desde el visor Power BI del Pla d'aforaments
y la guarda en datos/aforos.csv (la web la usa sin mandar al usuario fuera).

Uso:
  python -m scripts.descargar_aforos_gencat               # último año cerrado
  python -m scripts.descargar_aforos_gencat --hasta 2025

El visor es público (https://territori.gencat.cat/.../pla-aforaments/). Se repite la
misma consulta que hace la tabla del visor, sin filtro de año ni provincia, y se
guarda, para cada estación, la medida más reciente hasta el año indicado. El año en
curso se excluye por defecto porque la IMD aún no es anual completa.

Comprobado el 16/10/2026: 11.682 filas (2008-2026), 1.220 estaciones con dato ≤ 2025.
Si la Generalitat cambia el informe, la consulta dejará de funcionar: el script avisa
y conserva el fichero anterior.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

URL = "https://wabi-north-europe-g-primary-api.analysis.windows.net/public/reports/querydata?synchronous=true"
CLAVE_PUBLICA = "b26d609f-0d13-4f6d-b5f0-0b9d35838d31"  # clave del enlace público del visor
CONSULTA = Path(__file__).parent / "consulta_gaf.json"
FUENTE = "Generalitat de Catalunya, Pla d'aforaments (visor GAF)"


def decodificar_dsr(data: dict) -> list[dict]:
    """Convierte el formato comprimido DSR de Power BI en filas {columna: valor}.

    Cada fila trae en 'C' solo los valores nuevos. El bit i de 'R' indica que la
    columna i repite el valor de la fila anterior; el bit i de 'Ø' indica nulo.
    Las columnas con 'DN' guardan un índice al diccionario ValueDicts.
    """
    nombres = {s["Value"]: s["Name"].split(".")[-1].rstrip(")") for s in data["descriptor"]["Select"]}
    ds = data["dsr"]["DS"][0]
    dicts = ds.get("ValueDicts", {})
    filas = ds["PH"][0]["DM0"]
    if not filas:
        return []
    esquema = filas[0]["S"]
    salida, previa = [], {}
    for f in filas:
        valores = f.get("C", [])
        repetidas, nulas, k, fila = f.get("R", 0), f.get("Ø", 0), 0, {}
        for i, col in enumerate(esquema):
            n = nombres.get(col["N"], col["N"])
            if repetidas & (1 << i):
                fila[n] = previa.get(n)
            elif nulas & (1 << i):
                fila[n] = None
            else:
                v = valores[k]
                k += 1
                if "DN" in col and isinstance(v, int):
                    v = dicts[col["DN"]][v]
                fila[n] = v
        previa = fila
        salida.append(fila)
    return salida


def _pk(km) -> str:
    if km in (None, ""):
        return ""
    km = float(km)
    entero = int(km + 1e-9)
    return f"{entero}+{round((km - entero) * 1000):03d}"


def organismo(org: str) -> str:
    o = (org or "").strip()
    if o.startswith("S.T.C.") or o.startswith("S.V.") or o.startswith("S.G."):
        return "Generalitat de Catalunya"
    if o.startswith("D. "):
        return "Diputació de " + o[3:]
    if o and o != "Desconegut":
        return f"Generalitat de Catalunya (concesión {o})"
    return "Generalitat de Catalunya"


def a_aforos(filas: list[dict], hasta: int) -> list[dict]:
    ultimas: dict[tuple, dict] = {}
    for f in filas:
        anio, imd = f.get("DATA_ANYO"), f.get("IND_IMD")
        if not anio or not imd or int(anio) > hasta:
            continue
        clave = (f.get("COD_ESTACIO"), f.get("COD_CARRETERA"))
        if clave not in ultimas or int(anio) > int(ultimas[clave]["DATA_ANYO"]):
            ultimas[clave] = f
    salida = []
    for f in ultimas.values():
        salida.append({
            "carretera": f.get("COD_CARRETERA", ""),
            "pk": _pk(f.get("NUM_PK")),
            "imd": int(f["IND_IMD"]),
            "pct_pesados": f.get("IND_PESANTS") if f.get("IND_PESANTS") is not None else "",
            "anio": int(f["DATA_ANYO"]),
            "organismo": organismo(f.get("DESC_RESUM_ORG", "")),
            "tipo": f.get("DESC_TIPUS_ESTACIO", ""),
            "codigo_estacion": f.get("COD_ESTACIO", ""),
            "lon": "", "lat": "",
            "fuente": FUENTE,
        })
    return sorted(salida, key=lambda r: (r["carretera"], r["pk"]))


def descargar() -> list[dict]:
    cuerpo = json.loads(CONSULTA.read_text(encoding="utf-8"))
    ventana = cuerpo["queries"][0]["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]["Binding"]["DataReduction"]["Primary"]["Window"]
    filas: list[dict] = []
    with httpx.Client(timeout=120) as c:
        while True:
            r = c.post(URL, json=cuerpo, headers={"X-PowerBI-ResourceKey": CLAVE_PUBLICA})
            r.raise_for_status()
            data = r.json()["results"][0]["result"]["data"]
            lote = decodificar_dsr(data)
            filas += lote
            rt = data["dsr"]["DS"][0].get("RT")
            if not rt or len(lote) < ventana["Count"]:
                return filas
            ventana["RestartTokens"] = rt  # siguiente página


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hasta", type=int, default=date.today().year - 1, help="Último año a considerar (por defecto, el anterior al actual)")
    a = ap.parse_args()
    try:
        filas = descargar()
    except Exception as e:  # noqa: BLE001
        print(f"No se pudo descargar del visor (se conserva el fichero actual): {e}")
        sys.exit(1)
    aforos = a_aforos(filas, a.hasta)
    if len(aforos) < 300:
        print(f"Solo {len(aforos)} estaciones: parece que el visor ha cambiado. No se modifica el fichero.")
        sys.exit(1)
    total = _guardar(aforos)
    print(f"{len(filas)} filas descargadas; {len(aforos)} estaciones con su IMD más reciente (≤ {a.hasta}). Total en fichero: {total}.")


def _guardar(aforos: list[dict]) -> int:
    """Sustituye todas las filas de esta fuente (de cualquier año) por las nuevas."""
    import csv
    from app import config
    from scripts.importar_aforos import CAMPOS
    destino = config.FICHERO_AFOROS
    existentes = []
    if destino.exists():
        with open(destino, encoding="utf-8") as f:
            existentes = [r for r in csv.DictReader(f) if r["fuente"] != FUENTE]
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        w.writeheader()
        w.writerows(existentes + aforos)
    return len(existentes) + len(aforos)


if __name__ == "__main__":
    main()
