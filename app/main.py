"""Servidor web: API + página con mapa + informes HTML/PDF."""
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from shapely.geometry import mapping

from app import config, geo, http
from app.analisis.compatibilidad import PERFILES
from app.fuentes import catastro, geocoder, poblacion
from app.informe import generar, mapas, render

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
WEB = Path(__file__).parent / "web" / "static"


@asynccontextmanager
async def ciclo(app: FastAPI):
    yield
    await http.cerrar()


app = FastAPI(title=config.MARCA, lifespan=ciclo)
app.mount("/static", StaticFiles(directory=WEB), name="static")

_informes: dict[tuple, tuple[float, dict]] = {}
TTL_INFORME = 3600


def _grupos(grupos: str | None) -> list[str] | None:
    from app.analisis.perfiles import GRUPOS
    lista = [g.strip() for g in (grupos or "").split(",") if g.strip() in GRUPOS]
    return lista or None


async def _informe(rc: str, potencia_mw: float | None, sup_minima: float | None, grupos: str | None = None) -> dict:
    lista = _grupos(grupos)
    clave = (rc, potencia_mw, sup_minima, tuple(lista or ()))
    if clave in _informes and time.time() - _informes[clave][0] < TTL_INFORME:
        return _informes[clave][1]
    inf = await generar.construir(rc, potencia_mw, sup_minima, lista)
    if "error" in inf:
        raise HTTPException(404, inf["error"])
    _informes[clave] = (time.time(), inf)
    return inf


def _rc_valida(rc: str) -> str:
    r = catastro.normalizar_rc(rc)
    if not r:
        raise HTTPException(400, "Referencia catastral no válida")
    return r[:14]


def _pagina(nombre: str) -> HTMLResponse:
    """Páginas estáticas con el nombre de la marca (provisional, configurable con UBI_MARCA)."""
    html = (WEB / nombre).read_text(encoding="utf-8")
    return HTMLResponse(html.replace("{{MARCA}}", config.MARCA).replace("{{LEMA}}", config.MARCA_LEMA))


@app.get("/", response_class=HTMLResponse)
async def inicio():
    return _pagina("index.html")


@app.get("/app", response_class=HTMLResponse)
async def herramienta():
    return _pagina("app.html")


@app.get("/api/buscar")
async def buscar(q: str = Query(..., min_length=2)):
    try:
        return {"resultados": await geocoder.buscar(q)}
    except http.ErrorFuente as e:
        raise HTTPException(503, f"El buscador no responde: {e}")


@app.get("/api/parcela")
async def parcela_en_punto(lon: float, lat: float):
    """Parcela(s) catastral(es) en un punto, con su contorno para dibujarla en el mapa."""
    try:
        rcs = await catastro.rc_en_punto(lon, lat)
    except http.ErrorFuente as e:
        raise HTTPException(503, f"Catastro no responde: {e}")
    if not rcs:
        return {"parcelas": [], "mensaje": "El punto cae en un vial o fuera de parcela. Haz clic sobre la parcela."}
    salida = []
    for r in rcs:
        g = await catastro.geometria(r["rc"])
        salida.append({**r, "superficie": g["area"] if g else None,
                       "geojson": mapping(geo.geom_a_wgs84(g["geom"])) if g else None})
    return {"parcelas": salida}


@app.get("/api/parcela/{rc}")
async def parcela_por_rc(rc: str):
    rc = _rc_valida(rc)
    g = await catastro.geometria(rc)
    if not g:
        raise HTTPException(404, "Parcela no encontrada")
    lon, lat = geo.a_wgs84(g["geom"].centroid.x, g["geom"].centroid.y)
    return {"rc": rc, "superficie": g["area"], "lon": lon, "lat": lat, "geojson": mapping(geo.geom_a_wgs84(g["geom"]))}


@app.get("/api/municipio")
async def municipio(lon: float, lat: float):
    m = await geocoder.municipio_en_punto(lon, lat)
    if not m:
        return {}
    p = await poblacion.consultar(m["codigo6"])
    return {**m, "poblacion": p.get("poblacion"), "anio_poblacion": p.get("fecha_dato")}


@app.get("/api/perfiles")
async def perfiles():
    from app.analisis.perfiles import catalogo
    return catalogo()


@app.get("/api/informe/{rc}")
async def informe_json(rc: str, potencia_mw: float | None = None, sup_minima: float | None = None, grupos: str | None = None):
    inf = await _informe(_rc_valida(rc), potencia_mw, sup_minima, grupos)
    comp = mapas.competencia(inf)
    salida = generar.para_json(inf)
    salida["panorama"] = render.panorama(inf, comp)
    salida["competencia"] = generar.para_json(comp)
    salida["parcela_geojson"] = mapping(geo.geom_a_wgs84(inf["parcela"]["geom"]))
    return JSONResponse(salida)


@app.get("/informe/{rc}.pdf")
async def informe_pdf(rc: str, potencia_mw: float | None = None, sup_minima: float | None = None, grupos: str | None = None):
    rc = _rc_valida(rc)
    inf = await _informe(rc, potencia_mw, sup_minima, grupos)
    anexos = await render.fichas_catastro(inf)
    return Response(render.pdf(inf, anexos), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="informe_{rc}.pdf"'})


@app.get("/informe/{rc}", response_class=HTMLResponse)
async def informe_html(rc: str, potencia_mw: float | None = None, sup_minima: float | None = None, grupos: str | None = None):
    inf = await _informe(_rc_valida(rc), potencia_mw, sup_minima, grupos)
    return render.html(inf)


@app.get("/salud")
async def salud():
    return {"ok": True}
