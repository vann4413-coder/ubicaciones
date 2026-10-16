"""Genera un informe de muestra (HTML y PDF) con las fuentes simuladas.
Se ejecuta con: UBI_MUESTRA=/ruta pytest tests/test_render_muestra.py"""
import asyncio
import os
from pathlib import Path

import pytest

from app.informe import generar, render


@pytest.mark.skipif(not os.getenv("UBI_MUESTRA"), reason="solo bajo demanda")
def test_muestra(fuentes_simuladas):
    inf = asyncio.run(generar.construir("4595201DF5949N"))
    destino = Path(os.environ["UBI_MUESTRA"])
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "informe_muestra.html").write_text(render.html(inf), encoding="utf-8")
    (destino / "informe_muestra.pdf").write_bytes(render.pdf(inf))
