"""Rutas del buscador de suelo industrial (solo administración)."""
import io

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from app import cuentas, suelo
from app.rutas_cuenta import _pintar, usuario_actual

router = APIRouter()


def _admin(request: Request):
    if not cuentas.es_admin(usuario_actual(request)):
        raise HTTPException(403, "Solo administradores")


def _bbox(txt: str) -> tuple[float, float, float, float]:
    try:
        v = tuple(float(x) for x in txt.split(","))
        assert len(v) == 4
        return v  # type: ignore[return-value]
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Zona no válida") from None


@router.get("/admin/suelo")
async def pagina(request: Request):
    _admin(request)
    return _pintar("suelo.html", request, titulo="Buscador de suelo industrial")


@router.get("/api/admin/suelo")
async def api(request: Request, bbox: str, sup_min: float = 1000, max_edif: float = 10, terciario: bool = False):
    _admin(request)
    try:
        return JSONResponse(await suelo.buscar(_bbox(bbox), sup_min, max_edif, terciario))
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


@router.post("/api/admin/suelo")
async def api_poligono(request: Request):
    """Búsqueda en una zona dibujada: {poligono: [[lon, lat], ...], sup_min, max_edif, terciario}."""
    _admin(request)
    d = await request.json()
    try:
        return JSONResponse(await suelo.buscar(None, float(d.get("sup_min") or 1000), float(d.get("max_edif") or 10),
                                               bool(d.get("terciario")), d.get("poligono")))
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


@router.post("/admin/suelo.xlsx")
async def excel_poligono(request: Request):
    _admin(request)
    import json
    form = await request.form()
    d = json.loads(form.get("datos") or "{}")
    res = await suelo.buscar(None, float(d.get("sup_min") or 1000), float(d.get("max_edif") or 10), bool(d.get("terciario")), d.get("poligono"))
    return _excel(res)


@router.get("/admin/suelo.xlsx")
async def excel(request: Request, bbox: str, sup_min: float = 1000, max_edif: float = 10, terciario: bool = False):
    _admin(request)
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    return _excel(await suelo.buscar(_bbox(bbox), sup_min, max_edif, terciario))


def _excel(res: dict) -> Response:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Suelo disponible"
    cab = ["CONJUNTO", "SUP. CONJUNTO (m²)", "REF. CATASTRAL", "MUNICIPIO", "SUPERFICIE (m²)", "% EDIFICADO", "TIPO", "CALIFICACIÓN", "CALIFICACIÓN MUC", "USO SEGÚN CATASTRO", "LATITUD", "LONGITUD",
           "INFORME", "CATASTRO"]
    ws.append(cab)
    for i, w in enumerate([10, 14, 17, 22, 14, 12, 12, 40, 36, 40, 11, 11, 40, 50], start=1):
        c = ws.cell(1, i)
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="102E35")
        ws.column_dimensions[c.column_letter].width = w
    for p in res["parcelas"]:
        ws.append([p.get("grupo"), p.get("superficie_grupo_m2"), p["rc"], p.get("municipio", ""), p["superficie_m2"], p["pct_edificado"], p["tipo"], p["calificacion"], p["calificacion_muc"], p.get("uso_catastro", ""), p["lat"], p["lon"],
                   f"https://parcelas360.com/informe/{p['rc']}",
                   f"https://www1.sedecatastro.gob.es/CYCBienInmueble/OVCConCiud.aspx?RefC={p['rc']}"])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="suelo_industrial_disponible.xlsx"'})
