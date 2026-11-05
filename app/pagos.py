"""Cobros con Stripe: informe suelto (pago único) y suscripciones Profesional y Premium.

Variables de entorno (en Railway):
  STRIPE_SECRET_KEY       clave secreta de Stripe (sk_test_… en pruebas, sk_live_… en real)
  STRIPE_WEBHOOK_SECRET   secreto del webhook (whsec_…) del endpoint /stripe/webhook
  UBI_URL_PUBLICA         dirección pública de la web (p. ej. https://ubicaciones-production.up.railway.app)
  UBI_IVA                 IVA en % incluido en el precio (21 por defecto): 1,99 € es el total que paga el cliente

Sin STRIPE_SECRET_KEY los pagos están desactivados y los informes se ven gratis (modo demostración).
Los productos, precios y el tipo de IVA se crean solos en Stripe la primera vez (claves lookup_key).
"""
import logging
import os

log = logging.getLogger(__name__)

CLAVE = os.getenv("STRIPE_SECRET_KEY", "")
WEBHOOK = os.getenv("STRIPE_WEBHOOK_SECRET", "")
URL_PUBLICA = os.getenv("UBI_URL_PUBLICA", "").rstrip("/")
IVA = float(os.getenv("UBI_IVA", "21"))

PRODUCTOS = {
    "informe": {"lookup_key": "ubi_informe_suelto_iva_incl", "nombre": "Informe completo de parcela", "importe": 199, "recurrente": False},
    "profesional": {"lookup_key": "ubi_plan_profesional_iva_incl", "nombre": "Plan Profesional (50 informes al mes)", "importe": 9900, "recurrente": True},
    "premium": {"lookup_key": "ubi_plan_premium_iva_incl", "nombre": "Plan Premium (informes ilimitados)", "importe": 13900, "recurrente": True},
}

# Datos para una factura completa: dirección de facturación y NIF/CIF del cliente (opcional para particulares).
FACTURA = {"locale": "es", "billing_address_collection": "required", "tax_id_collection": {"enabled": True}}

_precios: dict[str, str] = {}
_tasa_iva: str | None = None


def activos() -> bool:
    return bool(CLAVE)


def _stripe():
    import stripe
    stripe.api_key = CLAVE
    return stripe


def precio(clave: str) -> str:
    """Id del precio en Stripe; lo crea (producto + precio) si aún no existe."""
    if clave in _precios:
        return _precios[clave]
    s = _stripe()
    p = PRODUCTOS[clave]
    encontrados = s.Price.list(lookup_keys=[p["lookup_key"]], active=True, limit=1).data
    if encontrados:
        _precios[clave] = encontrados[0].id
    else:
        prod = s.Product.create(name=p["nombre"], tax_code="txcd_10000000")  # servicios prestados por vía electrónica
        datos = {"product": prod.id, "currency": "eur", "unit_amount": p["importe"], "lookup_key": p["lookup_key"],
                 "tax_behavior": "inclusive"}
        if p["recurrente"]:
            datos["recurring"] = {"interval": "month"}
        _precios[clave] = s.Price.create(**datos).id
    return _precios[clave]


def tasa_iva() -> list[str]:
    """Tipo de IVA incluido en el precio (se desglosa en la factura). Se reutiliza si ya existe."""
    global _tasa_iva
    if IVA <= 0:
        return []
    if not _tasa_iva:
        s = _stripe()
        for t in s.TaxRate.list(active=True, limit=100).data:
            if (t.metadata or {}).get("ubi") == "iva_incl" and float(t.percentage) == IVA and t.inclusive:
                _tasa_iva = t.id
                break
        else:
            _tasa_iva = s.TaxRate.create(display_name="IVA", percentage=IVA, inclusive=True, country="ES",
                                         jurisdiction="ES", metadata={"ubi": "iva_incl"}).id
    return [_tasa_iva]


def _crear_sesion(datos: dict) -> str:
    """Crea la sesión de Checkout. El IVA lo ponemos nosotros (tax_rates), así que se desactiva
    «Managed Payments» de Stripe, que algunas cuentas traen activado y exige códigos fiscales."""
    s = _stripe()
    try:
        return s.checkout.Session.create(**datos, managed_payments={"enabled": False}).url
    except s.error.InvalidRequestError as e:
        if "managed_payments" not in str(e):
            raise
        return s.checkout.Session.create(**datos).url


def _url(ruta: str, base: str) -> str:
    return (URL_PUBLICA or base.rstrip("/")) + ruta


def checkout_informe(rc: str, base: str, usuario: dict | None) -> str:
    s = _stripe()
    datos = dict(
        mode="payment",
        line_items=[{"price": precio("informe"), "quantity": 1, "tax_rates": tasa_iva()}],
        success_url=_url("/pago/ok?session_id={CHECKOUT_SESSION_ID}", base),
        cancel_url=_url(f"/comprar/{rc}?cancelado=1", base),
        metadata={"tipo": "informe", "rc": rc, "usuario_id": str(usuario["id"]) if usuario else ""},
        invoice_creation={"enabled": True},
        **FACTURA,
    )
    if usuario and usuario.get("stripe_customer"):
        datos["customer"] = usuario["stripe_customer"]
        datos["customer_update"] = {"name": "auto", "address": "auto"}
    elif usuario:
        datos["customer_email"] = usuario["email"]
    return _crear_sesion(datos)


def checkout_suscripcion(plan: str, base: str, usuario: dict) -> str:
    s = _stripe()
    datos = dict(
        mode="subscription",
        line_items=[{"price": precio(plan), "quantity": 1, "tax_rates": tasa_iva()}],
        success_url=_url("/pago/ok?session_id={CHECKOUT_SESSION_ID}", base),
        cancel_url=_url("/cuenta?cancelado=1", base),
        metadata={"tipo": "suscripcion", "plan": plan, "usuario_id": str(usuario["id"])},
        subscription_data={"metadata": {"plan": plan, "usuario_id": str(usuario["id"])}},
        **FACTURA,
    )
    if usuario.get("stripe_customer"):
        datos["customer"] = usuario["stripe_customer"]
        datos["customer_update"] = {"name": "auto", "address": "auto"}
    else:
        datos["customer_email"] = usuario["email"]
    return _crear_sesion(datos)


def portal(usuario: dict, base: str) -> str:
    """Portal de cliente de Stripe: cambiar tarjeta, ver facturas, cancelar la suscripción."""
    s = _stripe()
    return s.billing_portal.Session.create(customer=usuario["stripe_customer"], return_url=_url("/cuenta", base)).url


def sesion(session_id: str):
    return _stripe().checkout.Session.retrieve(session_id)


def evento(cuerpo: bytes, firma: str):
    return _stripe().Webhook.construct_event(cuerpo, firma, WEBHOOK)


def suscripcion(sub_id: str):
    return _stripe().Subscription.retrieve(sub_id)
