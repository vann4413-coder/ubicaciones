"""Arranca la web con todas las fuentes simuladas (para probar la interfaz sin internet).
Uso: python -m tests.servidor_demo"""
import json
import tempfile
from pathlib import Path

import httpx
import respx
import uvicorn

from app import config
from tests import conftest as c


def main():
    tmp = Path(tempfile.mkdtemp())

    class MP:
        def setattr(self, obj, k, v):
            setattr(obj, k, v)
    c.datos_locales.__wrapped__(tmp, MP()) if hasattr(c.datos_locales, "__wrapped__") else None
    gen = c.fuentes_simuladas.__wrapped__(tmp) if hasattr(c.fuentes_simuladas, "__wrapped__") else None
    m = next(gen)
    m.route(host="127.0.0.1").pass_through()
    m.route(host="localhost").pass_through()
    m.get(url__startswith=f"{config.ICGC_GEOCODER}/cerca").respond(json={"features": [
        {"geometry": {"coordinates": [2.4532641, 41.54454292]}, "properties": {"etiqueta": "Carrer d'Enric Prat de la Riba 110, Mataró"}}]})
    m.get(url__startswith=f"{config.CATASTRO_COORD}/Consulta_CPMRC").respond(json={"Consulta_CPMRCResult": {"coordenadas": {"coord": [{"geo": {"xcen": "2.4527", "ycen": "41.5446"}}]}}})
    uvicorn.run("app.main:app", host="127.0.0.1", port=8765, log_level="warning")


if __name__ == "__main__":
    main()
