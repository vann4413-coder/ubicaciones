"""Estructura común de los resultados de cada fuente."""
from datetime import date
from typing import Any


def resultado(estado: str, fuente: str, url: str = "", fecha_dato: str = "", **datos: Any) -> dict:
    """estado: 'ok' | 'sin_dato' | 'error' | 'no_aplica'."""
    return {
        "estado": estado,
        "fuente": fuente,
        "url": url,
        "fecha_dato": fecha_dato,
        "fecha_consulta": date.today().isoformat(),
        **datos,
    }


def error(fuente: str, mensaje: str, url: str = "") -> dict:
    return resultado("error", fuente, url, mensaje=mensaje)
