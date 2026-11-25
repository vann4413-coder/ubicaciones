"""Agente 360 · «Analiza tu lista»: el cliente sube su Excel de ubicaciones y se lo devolvemos analizado."""
import io
import re
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response

from app import cuentas, lote, pagos
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
                   limites=cuentas.LIMITES_LISTA, prueba=cuentas.PRUEBA_LISTA, precio_lista=lambda n: pagos.euros(pagos.precio_lista(n)),
                   pagos=pagos.activos())


@router.post("/agente/lista")
async def subir(request: Request, fichero: UploadFile):
    """Si la lista cabe en lo que le queda al cliente, se analiza ya. Si no, queda pendiente para que elija:
    pagarla entera como lista suelta o analizar solo las ubicaciones que le cubre su plan o la prueba."""
    u = usuario_actual(request)
    if not u:
        return RedirectResponse("/cuenta?siguiente=/agente/lista", status_code=303)
    cupo = cuentas.cupo_lista(u)
    contenido = await fichero.read()
    nombre = fichero.filename or "ubicaciones.xlsx"
    try:
        n = len(lote.leer_ubicaciones(io.BytesIO(contenido))[2])
        if cupo["quedan"] is None or n <= cupo["quedan"] or not pagos.activos():
            lote.crear(nombre, contenido, usuario=u)
            return RedirectResponse("/agente/lista?ok=" + quote(f"Recibida: {n} ubicaciones en cola."), status_code=303)
        lote.crear(nombre, contenido, usuario=u, pendiente_pago=True)
    except Exception as e:  # noqa: BLE001
        return RedirectResponse("/agente/lista?error=" + quote(str(e)[:250]), status_code=303)
    return RedirectResponse("/agente/lista?error=" + quote(
        f"Tu lista tiene {n} ubicaciones y te quedan {cupo['quedan']}. Elige abajo cómo seguir."), status_code=303)


@router.post("/agente/lista/{id_}/incluidas")
async def solo_incluidas(request: Request, id_: str):
    """Analizar solo las primeras ubicaciones, las que cubre el plan o la prueba."""
    _lote_propio(request, id_)
    quedan = cuentas.cupo_lista(usuario_actual(request))["quedan"]
    if not quedan or not lote.activar(id_, maximo=quedan):
        return RedirectResponse("/agente/lista?error=" + quote("No te quedan ubicaciones incluidas."), status_code=303)
    return RedirectResponse("/agente/lista?ok=" + quote(f"Se analizan las primeras {quedan} ubicaciones."), status_code=303)


@router.get("/agente/lista/{id_}/pagar")
async def pagar(request: Request, id_: str):
    est = _lote_propio(request, id_)
    if est.get("modo") != "pendiente" or not pagos.activos():
        return RedirectResponse("/agente/lista", status_code=303)
    from app.rutas_cuenta import _error_pago
    try:
        url = pagos.checkout_lista(id_, est["total"], est.get("nombre") or "", str(request.base_url), usuario_actual(request))
    except Exception as e:  # noqa: BLE001
        return _error_pago(request, e)
    return RedirectResponse(url, status_code=303)


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
