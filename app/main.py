"""Servidor web: API + página con mapa + informes HTML/PDF."""
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from shapely.geometry import mapping

from app import config, geo, http, pagos
from app.legal import router as rutas_legales
from app.rutas_cuenta import acceso, redirigir_a_compra, router as rutas_cuenta
from app.analisis.compatibilidad import PERFILES
from app.fuentes import catastro, geocoder, poblacion
from app.informe import generar, mapas, render

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
WEB = Path(__file__).parent / "web" / "static"


async def _refrescar_capacidad_red():
    """La distribuidora publica la capacidad cada mes: se vuelve a descargar si el fichero tiene más de 10 días."""
    import asyncio
    import time
    while True:
        await asyncio.sleep(6 * 3600)
        f = config.FICHERO_RED
        if not f.exists() or time.time() - f.stat().st_mtime > 10 * 86400:
            try:
                from scripts import descargar_capacidad_red
                await asyncio.to_thread(descargar_capacidad_red.main)
            except BaseException as e:  # noqa: BLE001 - SystemExit incluido: no debe tumbar el servidor
                logging.getLogger(__name__).warning("No se pudo refrescar la capacidad de red: %s", e)


@asynccontextmanager
async def ciclo(app: FastAPI):
    import asyncio
    tarea = asyncio.create_task(_refrescar_capacidad_red())
    yield
    tarea.cancel()
    await http.cerrar()


app = FastAPI(title=config.MARCA, lifespan=ciclo)
app.mount("/static", StaticFiles(directory=WEB), name="static")
app.include_router(rutas_cuenta)
app.include_router(rutas_legales)

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


# Campos que se ven gratis (vista previa en el mapa); el resto solo con acceso al informe completo.
CAMPOS_PREVIA = {"rc", "lon", "lat", "generado", "municipio", "resumen", "panorama", "gasolineras", "entorno5", "parcela_geojson",
                 "competencia", "poblacion"}


@app.get("/api/informe/{rc}")
async def informe_json(request: Request, rc: str, potencia_mw: float | None = None, sup_minima: float | None = None,
                       grupos: str | None = None):
    rc = _rc_valida(rc)
    inf = await _informe(rc, potencia_mw, sup_minima, grupos)
    comp = mapas.competencia(inf)
    salida = generar.para_json(inf)
    salida["panorama"] = render.panorama(inf, comp)
    salida["competencia"] = generar.para_json(comp)
    salida["parcela_geojson"] = mapping(geo.geom_a_wgs84(inf["parcela"]["geom"]))
    permitido, motivo = acceso(request, rc, registrar=False)
    salida["acceso"] = {"completo": permitido, "motivo": motivo, "pagos": pagos.activos(), "precio_informe": "1,99 €"}
    if not permitido:
        previa = {k: v for k, v in salida.items() if k in CAMPOS_PREVIA or k == "acceso"}
        previa["parcela"] = {k: salida["parcela"].get(k) for k in ("rc", "direccion", "sup_grafica", "municipio")}
        previa["puntuaciones"] = {g: {k: p.get(k) for k in ("nombre_perfil", "total", "semaforo", "veredicto", "mejor_uso", "bloqueos")}
                                  for g, p in salida["puntuaciones"].items()}
        return JSONResponse(previa)
    return JSONResponse(salida)


@app.get("/informe/{rc}.pdf")
async def informe_pdf(request: Request, rc: str, potencia_mw: float | None = None, sup_minima: float | None = None,
                      grupos: str | None = None):
    rc = _rc_valida(rc)
    permitido, motivo = acceso(request, rc)
    if not permitido:
        return redirigir_a_compra(rc, motivo)
    inf = await _informe(rc, potencia_mw, sup_minima, grupos)
    anexos = await render.fichas_catastro(inf)
    return Response(render.pdf(inf, anexos), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="informe_{rc}.pdf"'})


@app.get("/informe/{rc}", response_class=HTMLResponse)
async def informe_html(request: Request, rc: str, potencia_mw: float | None = None, sup_minima: float | None = None,
                       grupos: str | None = None):
    rc = _rc_valida(rc)
    permitido, motivo = acceso(request, rc)
    if not permitido:
        return redirigir_a_compra(rc, motivo)
    inf = await _informe(rc, potencia_mw, sup_minima, grupos)
    from urllib.parse import urlencode
    q = {k: v for k, v in request.query_params.items() if k in ("acceso", "potencia_mw", "sup_minima", "grupos")}
    if request.query_params.get("enviado"):
        aviso = "Te hemos enviado el enlace del informe por correo."
    elif request.query_params.get("acceso"):
        aviso = "Guarda esta página en favoritos: con este enlace puedes volver a abrir el informe cuando quieras."
    else:
        aviso = ""
    return render.html(inf, barra={"pdf": f"/informe/{rc}.pdf" + (f"?{urlencode(q)}" if q else ""), "aviso": aviso})


@app.get("/robots.txt", include_in_schema=False)
async def robots():
    return Response("User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /informe/\nDisallow: /comprar/\n"
                    "Disallow: /cuenta\nDisallow: /pago/\n\nSitemap: https://parcelas360.com/sitemap.xml\n",
                    media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap():
    paginas = ["", "app", "aviso-legal", "privacidad", "condiciones", "cookies"]
    urls = "".join(f"<url><loc>https://parcelas360.com/{p}</loc></url>" for p in paginas)
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
                    media_type="application/xml")


@app.get("/salud")
async def salud():
    from app.fuentes import red_electrica
    nudos = red_electrica.nudos()
    from app import pagos
    return {"ok": True, "capacidad_red": {"posiciones": len(nudos), "fichero": nudos[0]["fecha_fichero"] if nudos else None},
            "pagos": {"metodos": pagos.METODOS, "rechazados": pagos.diagnostico},
            "ficha_catastro": await _prueba_ficha_catastro()}


_prueba_ficha: dict = {}


async def _prueba_ficha_catastro() -> dict:
    """Comprueba (como mucho una vez por hora) que la Sede del Catastro entrega la ficha en PDF a este servidor."""
    if _prueba_ficha and time.time() - _prueba_ficha["t"] < 3600:
        return _prueba_ficha["r"]
    from app import http
    url = catastro.url_cdyg("1332401DG6013S0005LO", "8", "6")
    try:
        contenido, tipo = await http.get_bytes(url)
        r = {"pdf": contenido[:5] == b"%PDF-", "tipo": tipo, "bytes": len(contenido)}
    except Exception as e:  # noqa: BLE001
        r = {"pdf": False, "error": str(e)[:200]}
    _prueba_ficha.update(t=time.time(), r=r)
    return r
