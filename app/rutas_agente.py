"""Agente 360 · «Analiza tu lista»: el cliente sube su Excel de ubicaciones y se lo devolvemos analizado."""
import io
import re
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response

from app import cuentas, lote
from app.rutas_cuenta import _pintar, usuario_actual

router = APIRouter()


def _lote_propio(request: Request, id_: str) -> dict:
    u = usuario_actual(request)
    if not u or not re.fullmatch(r"[0-9a-f-]+", id_):
        raise HTTPException(404)
    est = lote.lista_por_id(id_)
    if not est or (est.get("usuario_id") != u["id"] and not cuentas.es_admin(u)):
        raise HTTPException(404)
    return est


@router.get("/agente")
async def agente():
    return RedirectResponse("/agente/lista", status_code=303)


@router.get("/agente/lista")
async def lista(request: Request, error: str = "", ok: str = ""):
    u = usuario_actual(request)
    return _pintar("agente_lista.html", request, titulo="Analiza tu lista · Agente 360",
                   descripcion="Sube un Excel con tus ubicaciones y el Agente 360 te lo devuelve con catastro, "
                               "urbanismo, usos admitidos, parcela mínima e inundabilidad de cada una.",
                   cupo=cuentas.cupo_lista(u), lotes=lote.lista(u["id"]) if u else [], error=error, ok=ok,
                   limites=cuentas.LIMITES_LISTA, prueba=cuentas.PRUEBA_LISTA)


@router.post("/agente/lista")
async def subir(request: Request, fichero: UploadFile):
    u = usuario_actual(request)
    if not u:
        return RedirectResponse("/cuenta?siguiente=/agente/lista", status_code=303)
    cupo = cuentas.cupo_lista(u)
    if cupo["quedan"] == 0:
        return RedirectResponse("/agente/lista?error=" + quote("Has agotado las ubicaciones disponibles. "
                                                               "Elige un plan para seguir analizando listas."), status_code=303)
    try:
        id_ = lote.crear(fichero.filename or "ubicaciones.xlsx", await fichero.read(), usuario=u, maximo=cupo["quedan"])
    except Exception as e:  # noqa: BLE001
        return RedirectResponse("/agente/lista?error=" + quote(str(e)[:250]), status_code=303)
    est = lote.lista_por_id(id_)
    ok = f"Recibida: {est['total']} ubicaciones en cola."
    if est.get("en_fichero", 0) > est["total"]:
        ok += (f" Tu fichero tiene {est['en_fichero']}; se analizan las primeras {est['total']} "
               "porque es lo que te queda disponible.")
    return RedirectResponse("/agente/lista?ok=" + quote(ok), status_code=303)


@router.get("/agente/lista/{id_}.xlsx")
async def descargar(request: Request, id_: str, parcial: bool = False):
    est = _lote_propio(request, id_)
    f = lote.regenerar(id_) if parcial else lote.fichero_salida(id_)
    if not f:
        raise HTTPException(404, "Aún no está terminado")
    nombre = (est.get("nombre") or "ubicaciones.xlsx").rsplit(".", 1)[0] + "_analisis_agente360.xlsx"
    return FileResponse(f, filename=nombre)


@router.post("/agente/lista/{id_}/borrar")
async def borrar(request: Request, id_: str):
    _lote_propio(request, id_)
    lote.borrar(id_)
    return RedirectResponse("/agente/lista", status_code=303)


@router.get("/agente/plantilla.xlsx")
async def plantilla():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Ubicaciones"
    cab = ["NOMBRE", "DIRECCIÓN", "MUNICIPIO", "REFERENCIA CATASTRAL", "LATITUD", "LONGITUD"]
    ws.append(cab)
    ws.append(["Ejemplo con dirección", "Carrer Prat de la Riba 110", "Mataró", None, None, None])
    ws.append(["Ejemplo con referencia catastral", None, None, "25026A01300135", None, None])
    ws.append(["Ejemplo con coordenadas", None, None, None, 41.6436, 0.6085])
    for i, w in enumerate([30, 34, 18, 24, 12, 12], start=1):
        c = ws.cell(1, i)
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F3A5F")
        ws.column_dimensions[c.column_letter].width = w
    ws.cell(6, 1, "Rellena una fila por ubicación con la dirección y el municipio, la referencia catastral o las "
                  "coordenadas (basta con una de las tres). Puedes añadir las columnas propias que quieras.").font = Font(italic=True, color="667085")
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="plantilla_agente360.xlsx"'})
