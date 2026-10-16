"""Población municipal (Idescat, El municipi en xifres)."""
from app import config, http
from app.fuentes.base import error, resultado

FUENTE = "Idescat, El municipi en xifres"
URL = "https://www.idescat.cat/emex/"
INDICADOR_POBLACION = "f171"


def _buscar_indicador(nodo, codigo):
    if isinstance(nodo, dict):
        if nodo.get("id") == codigo or nodo.get("c") == codigo:
            return nodo
        for v in nodo.values():
            r = _buscar_indicador(v, codigo)
            if r:
                return r
    elif isinstance(nodo, list):
        for v in nodo:
            r = _buscar_indicador(v, codigo)
            if r:
                return r
    return None


def parse(d: dict) -> tuple[int | None, str]:
    ind = _buscar_indicador(d, INDICADOR_POBLACION)
    if not ind:
        return None, ""
    v = ind.get("v")
    if isinstance(v, dict):
        v = v.get("content", "")
    primero = str(v).split(",")[0].strip()
    try:
        valor = int(float(primero))
    except ValueError:
        valor = None
    anio = ind.get("r") or ind.get("updated") or ""
    if isinstance(anio, dict):
        anio = anio.get("content", "")
    return valor, str(anio)


async def consultar(codigo_municipio6: str) -> dict:
    """`codigo_municipio6`: código Idescat de 6 dígitos (INE + dígito de control), p. ej. 081213."""
    if not codigo_municipio6:
        return resultado("sin_dato", FUENTE, URL, mensaje="Municipio no identificado.")
    try:
        d = await http.get_json(config.IDESCAT_EMEX, {"id": codigo_municipio6, "i": INDICADOR_POBLACION, "lang": "es"})
    except http.ErrorFuente as e:
        return error(FUENTE, f"Idescat no responde: {e}", URL)
    valor, anio = parse(d)
    if valor is None:
        return resultado("sin_dato", FUENTE, URL, mensaje="Sin dato de población.")
    return resultado("ok", FUENTE, URL, fecha_dato=anio, poblacion=valor)
