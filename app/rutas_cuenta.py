"""Rutas de cuenta, compra de informes, suscripciones y webhook de Stripe."""
import logging
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app import config, cuentas, pagos

log = logging.getLogger(__name__)
router = APIRouter()
_env = Environment(loader=FileSystemLoader(Path(__file__).parent / "web" / "templates"), autoescape=select_autoescape(["html"]))
COOKIE_SESION = "ubi_sesion"
COOKIE_COMPRAS = "ubi_compras"


def usuario_actual(request: Request) -> dict | None:
    return cuentas.usuario_de_cookie(request.cookies.get(COOKIE_SESION))


def _pintar(plantilla: str, request: Request, **datos) -> HTMLResponse:
    return HTMLResponse(_env.get_template(plantilla).render(marca=config.MARCA, usuario=usuario_actual(request), **datos))


def _siguiente_seguro(s: str | None) -> str:
    return s if s and s.startswith("/") and not s.startswith("//") else "/cuenta"


def _con_sesion(resp, usuario: dict, request: Request):
    resp.set_cookie(COOKIE_SESION, cuentas.cookie_sesion(usuario["id"]), max_age=cuentas.DURACION_SESION, httponly=True,
                    samesite="lax", secure=request.url.scheme == "https")
    return resp


# ---------- Acceso al informe completo ----------

def tokens_compra(request: Request) -> dict[str, str]:
    """Compras sueltas guardadas en una cookie firmada: rc -> token."""
    valor = cuentas.comprobar_firma(request.cookies.get(COOKIE_COMPRAS)) or ""
    return dict(p.split(":", 1) for p in valor.split(",") if ":" in p)


def acceso(request: Request, rc: str, registrar: bool = True) -> tuple[bool, str]:
    """¿Puede ver el informe completo? Devuelve (sí/no, motivo)."""
    if not pagos.activos():
        return True, "demo"
    u = usuario_actual(request)
    token = request.query_params.get("acceso") or tokens_compra(request).get(rc)
    if cuentas.compra_valida(rc, token) or (u and cuentas.compra_de_usuario(u["id"], rc)):
        return True, "compra"
    if u and cuentas.puede_ver_con_plan(u, rc):
        if registrar:
            cuentas.registrar_uso(u, rc)
        return True, "plan"
    if u and cuentas.plan_activo(u):
        return False, "limite"
    return False, "pago"


def redirigir_a_compra(rc: str, motivo: str) -> RedirectResponse:
    return RedirectResponse(f"/comprar/{rc}" + ("?limite=1" if motivo == "limite" else ""), status_code=303)


# ---------- Cuenta ----------

@router.get("/cuenta", response_class=HTMLResponse)
async def cuenta(request: Request, siguiente: str = "", cancelado: int = 0):
    u = usuario_actual(request)
    plan = cuentas.plan_activo(u)
    return _pintar("cuenta.html", request, titulo="Mi cuenta", siguiente=_siguiente_seguro(siguiente) if siguiente else "",
                   plan=plan, limite=cuentas.LIMITES.get(plan) if plan else None, admin=cuentas.es_admin(u),
                   usados=cuentas.usados_mes(u["id"]) if u else 0, historial=cuentas.historial(u["id"]) if u else [],
                   pagos=pagos.activos(), mensaje="Has cancelado el pago." if cancelado else "", ok=False)


@router.post("/cuenta/registro")
async def registro(request: Request, email: str = Form(...), clave: str = Form(...), siguiente: str = Form("")):
    try:
        u = cuentas.registrar(email, clave)
    except ValueError as e:
        return _pintar("cuenta.html", request, titulo="Mi cuenta", siguiente=siguiente, mensaje=str(e), ok=False)
    return _con_sesion(RedirectResponse(_siguiente_seguro(siguiente), status_code=303), u, request)


@router.post("/cuenta/entrar")
async def entrar(request: Request, email: str = Form(...), clave: str = Form(...), siguiente: str = Form("")):
    u = cuentas.entrar(email, clave)
    if not u:
        return _pintar("cuenta.html", request, titulo="Mi cuenta", siguiente=siguiente, mensaje="Correo o contraseña incorrectos.", ok=False)
    return _con_sesion(RedirectResponse(_siguiente_seguro(siguiente), status_code=303), u, request)


@router.post("/cuenta/salir")
async def salir():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(COOKIE_SESION)
    return resp


@router.get("/cuenta/facturacion")
async def facturacion(request: Request):
    u = usuario_actual(request)
    if not u or not u.get("stripe_customer") or not pagos.activos():
        return RedirectResponse("/cuenta", status_code=303)
    return RedirectResponse(pagos.portal(u, str(request.base_url)), status_code=303)


# ---------- Compra y suscripción ----------

@router.get("/comprar/{rc}", response_class=HTMLResponse)
async def comprar(request: Request, rc: str, cancelado: int = 0, limite: int = 0):
    from app.fuentes import catastro
    rc = (catastro.normalizar_rc(rc) or "")[:14]
    if not rc:
        raise HTTPException(400, "Referencia catastral no válida")
    if not pagos.activos():
        return RedirectResponse(f"/informe/{rc}", status_code=303)
    return _pintar("comprar.html", request, titulo="Comprar informe", rc=rc, direccion="", cancelado=cancelado,
                   limite_agotado=limite, limite=cuentas.LIMITES["profesional"])


def _error_pago(request: Request, e: Exception) -> HTMLResponse:
    log.exception("Error con Stripe")
    detalle = getattr(e, "user_message", None) or str(e).split("\n")[0][:300]
    return _pintar("cuenta.html", request, titulo="Error en el pago", siguiente="", ok=False,
                   mensaje=f"No se ha podido iniciar el pago ({type(e).__name__}): {detalle}")


@router.post("/comprar/{rc}")
async def pagar_informe(request: Request, rc: str):
    from app.fuentes import catastro
    rc = (catastro.normalizar_rc(rc) or "")[:14]
    if not rc or not pagos.activos():
        raise HTTPException(400, "No disponible")
    try:
        url = pagos.checkout_informe(rc, str(request.base_url), usuario_actual(request))
    except Exception as e:  # noqa: BLE001
        return _error_pago(request, e)
    return RedirectResponse(url, status_code=303)


@router.get("/suscribirse")
async def suscribirse(request: Request, plan: str = "profesional", rc: str = ""):
    if plan not in ("profesional", "premium") or not pagos.activos():
        return RedirectResponse("/#precios", status_code=303)
    u = usuario_actual(request)
    if not u:
        return RedirectResponse(f"/cuenta?siguiente=/suscribirse?plan={plan}", status_code=303)
    try:
        url = pagos.checkout_suscripcion(plan, str(request.base_url), u)
    except Exception as e:  # noqa: BLE001
        return _error_pago(request, e)
    return RedirectResponse(url, status_code=303)


@router.get("/pago/ok")
async def pago_ok(request: Request, session_id: str):
    """Vuelta de Stripe: se comprueba el pago directamente con Stripe (no nos fiamos de la URL)."""
    ses = pagos.sesion(session_id)
    meta = ses.metadata or {}
    if meta.get("tipo") == "informe":
        if ses.payment_status != "paid":
            return RedirectResponse(f"/comprar/{meta.get('rc', '')}?cancelado=1", status_code=303)
        rc = meta["rc"]
        uid = int(meta["usuario_id"]) if meta.get("usuario_id") else None
        token = cuentas.guardar_compra(ses.id, rc, (ses.customer_details or {}).get("email", ""), ses.amount_total, uid)
        compras = tokens_compra(request)
        compras[rc] = token
        resp = RedirectResponse(f"/informe/{rc}?acceso={token}", status_code=303)
        resp.set_cookie(COOKIE_COMPRAS, cuentas.firmar(",".join(f"{k}:{v}" for k, v in list(compras.items())[-30:])),
                        max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax", secure=request.url.scheme == "https")
        return resp
    if meta.get("tipo") == "suscripcion":
        _activar_suscripcion(int(meta["usuario_id"]), ses.customer, ses.subscription, meta.get("plan"))
        return RedirectResponse("/cuenta", status_code=303)
    return RedirectResponse("/", status_code=303)


def _activar_suscripcion(uid: int, customer: str, sub_id: str | None, plan: str | None) -> None:
    estado, fin = "active", None
    if sub_id:
        sub = pagos.suscripcion(sub_id)
        estado, fin = sub.status, sub.get("current_period_end")
        plan = (sub.metadata or {}).get("plan") or plan
    cuentas.actualizar_plan(uid, stripe_customer=customer, plan=plan, plan_estado=estado, suscripcion=sub_id, periodo_fin=fin)


@router.post("/stripe/webhook")
async def webhook(request: Request):
    """Stripe avisa de altas, renovaciones, impagos y bajas de las suscripciones."""
    try:
        ev = pagos.evento(await request.body(), request.headers.get("stripe-signature", ""))
    except Exception as e:  # noqa: BLE001
        log.warning("Webhook de Stripe rechazado: %s", e)
        raise HTTPException(400, "Firma no válida") from None
    obj = ev["data"]["object"]
    tipo = ev["type"]
    if tipo == "checkout.session.completed":
        meta = obj.get("metadata") or {}
        if meta.get("tipo") == "suscripcion" and meta.get("usuario_id"):
            _activar_suscripcion(int(meta["usuario_id"]), obj.get("customer"), obj.get("subscription"), meta.get("plan"))
        elif meta.get("tipo") == "informe" and obj.get("payment_status") == "paid":
            cuentas.guardar_compra(obj["id"], meta.get("rc", ""), (obj.get("customer_details") or {}).get("email", ""),
                                   obj.get("amount_total"), int(meta["usuario_id"]) if meta.get("usuario_id") else None)
    elif tipo in ("customer.subscription.updated", "customer.subscription.deleted", "customer.subscription.created"):
        u = cuentas.por_customer(obj.get("customer"))
        uid = u["id"] if u else int((obj.get("metadata") or {}).get("usuario_id") or 0)
        if uid:
            cuentas.actualizar_plan(uid, stripe_customer=obj.get("customer"), suscripcion=obj.get("id"),
                                    plan=(obj.get("metadata") or {}).get("plan") or (u or {}).get("plan"),
                                    plan_estado="canceled" if tipo.endswith("deleted") else obj.get("status"),
                                    periodo_fin=obj.get("current_period_end"))
    return {"recibido": True}
