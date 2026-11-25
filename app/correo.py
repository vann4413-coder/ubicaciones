"""Envío de correos (enlace al informe comprado).

Dos vías; se usa la primera configurada:
  1. Resend (API por HTTPS, recomendado: Railway bloquea el SMTP salvo en el plan Pro)
       UBI_RESEND_CLAVE   clave de API de Resend (re_…)
       UBI_CORREO_DESDE   remitente, p. ej. informes@parcelas360.com (dominio verificado en Resend)
       UBI_CORREO_RESPUESTA  dirección para las respuestas (por defecto tuparcela360@gmail.com)
  2. SMTP
Variables de entorno SMTP (en Railway):
  UBI_SMTP_USUARIO   cuenta que envía, p. ej. tuparcela360@gmail.com
  UBI_SMTP_CLAVE     contraseña de aplicación de esa cuenta (en Gmail: https://myaccount.google.com/apppasswords)
  UBI_SMTP_SERVIDOR  smtp.gmail.com por defecto
  UBI_SMTP_PUERTO    465 por defecto (SSL)
Sin usuario y clave, no se envía nada (la web funciona igual).
"""
import asyncio
from html import escape
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from app import config

log = logging.getLogger(__name__)


def _cfg() -> dict:
    return {
        "usuario": os.getenv("UBI_SMTP_USUARIO", "").strip(),
        "clave": os.getenv("UBI_SMTP_CLAVE", "").replace(" ", "").strip(),
        "servidor": os.getenv("UBI_SMTP_SERVIDOR", "smtp.gmail.com"),
        "puerto": int(os.getenv("UBI_SMTP_PUERTO", "465")),
    }


def _resend() -> dict:
    return {"clave": os.getenv("UBI_RESEND_CLAVE", "").strip(),
            "desde": os.getenv("UBI_CORREO_DESDE", "").strip() or "informes@parcelas360.com",
            "respuesta": os.getenv("UBI_CORREO_RESPUESTA", "").strip() or "tuparcela360@gmail.com"}


def activo() -> bool:
    c = _cfg()
    return bool(_resend()["clave"] or (c["usuario"] and c["clave"]))


def mensaje_informe(destino: str, rc: str, url_informe: str, url_pdf: str, direccion: str = "") -> EmailMessage:
    c = _cfg()
    m = EmailMessage()
    m["From"] = formataddr((config.MARCA, c["usuario"]))
    m["To"] = destino
    m["Subject"] = f"Tu informe de parcela {rc} · {config.MARCA}"
    lugar = f" ({direccion})" if direccion else ""
    m.set_content(
        f"Hola:\n\nGracias por tu compra. Tu informe de la parcela {rc}{lugar} está disponible en estos enlaces:\n\n"
        f"Ver el informe: {url_informe}\nDescargar el PDF: {url_pdf}\n\n"
        "Guarda este correo: los enlaces te permiten volver a abrir el informe cuando quieras.\n\n"
        f"Un saludo,\n{config.MARCA}\nhttps://parcelas360.com\n")
    m.add_alternative(f"""<div style="font-family:Arial,sans-serif;font-size:15px;color:#1d2b3a;max-width:560px">
<p>Hola:</p>
<p>Gracias por tu compra. Tu informe de la parcela <b>{rc}</b>{lugar} ya está disponible.</p>
<p><a href="{url_informe}" style="display:inline-block;background:#1f7a55;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none">Ver el informe</a>
&nbsp;<a href="{url_pdf}" style="display:inline-block;background:#b8e04a;color:#14231c;padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:bold">Descargar el PDF</a></p>
<p style="color:#5b6b7b;font-size:13px">Guarda este correo: los enlaces te permiten volver a abrir el informe cuando quieras.</p>
<p>Un saludo,<br><b>{config.MARCA}</b><br><a href="https://parcelas360.com">parcelas360.com</a></p></div>""", subtype="html")
    return m


def _enviar(m: EmailMessage) -> None:
    c = _cfg()
    with smtplib.SMTP_SSL(c["servidor"], c["puerto"], context=ssl.create_default_context(), timeout=30) as s:
        s.login(c["usuario"], c["clave"])
        s.send_message(m)


async def _enviar_resend(m: EmailMessage) -> None:
    from app import http
    r = _resend()
    texto = m.get_body(("plain",)).get_content()
    html = m.get_body(("html",)).get_content()
    resp = await http.cliente().post(
        "https://api.resend.com/emails", headers={"Authorization": f"Bearer {r['clave']}"},
        json={"from": formataddr((config.MARCA, r["desde"])), "to": [m["To"]], "subject": m["Subject"],
              "text": texto, "html": html, "reply_to": r["respuesta"]}, timeout=30)
    if resp.status_code >= 300:
        raise RuntimeError(f"Resend {resp.status_code}: {resp.text[:300]}")


async def enviar_informe(destino: str, rc: str, url_informe: str, url_pdf: str, direccion: str = "") -> bool:
    if not activo() or not destino:
        return False
    try:
        m = mensaje_informe(destino, rc, url_informe, url_pdf, direccion)
        if _resend()["clave"]:
            await _enviar_resend(m)
        else:
            await asyncio.to_thread(_enviar, m)
        log.info("Correo del informe %s enviado", rc)
        return True
    except Exception as e:  # noqa: BLE001  un fallo de correo no debe romper la compra
        log.warning("No se pudo enviar el correo del informe %s: %s", rc, e)
        return False


async def enviar_aviso_lista(destino: str, nombre: str, total: int) -> bool:
    """Aviso de que una lista de «Analiza tu lista» ya está terminada."""
    if not activo() or not destino:
        return False
    url = (os.getenv("UBI_URL_PUBLICA", "").rstrip("/") or "https://parcelas360.com") + "/agente/lista"
    c = _cfg()
    m = EmailMessage()
    m["From"] = formataddr((config.MARCA, c["usuario"] or _resend()["desde"]))
    m["To"] = destino
    m["Subject"] = f"Tu lista ya está analizada · {config.MARCA}"
    m.set_content(f"Hola:\n\nEl Agente 360 ha terminado de analizar «{nombre}» ({total} ubicaciones).\n\n"
                  f"Descarga el Excel con los resultados aquí: {url}\n\nUn saludo,\n{config.MARCA}\nhttps://parcelas360.com\n")
    m.add_alternative(f"""<div style="font-family:Arial,sans-serif;font-size:15px;color:#1d2b3a;max-width:560px">
<p>Hola:</p>
<p>El <b>Agente 360</b> ha terminado de analizar <b>{escape(nombre)}</b> ({total} ubicaciones).</p>
<p><a href="{url}" style="display:inline-block;background:#1f7a55;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none">Descargar resultados</a></p>
<p>Un saludo,<br><b>{config.MARCA}</b><br><a href="https://parcelas360.com">parcelas360.com</a></p></div>""", subtype="html")
    try:
        if _resend()["clave"]:
            await _enviar_resend(m)
        else:
            await asyncio.to_thread(_enviar, m)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudo enviar el aviso de lista: %s", e)
        return False


async def enviar_contacto(datos: dict) -> bool:
    """Reenvía al buzón de Parcelas 360 una consulta del formulario de contacto (responder = contestar al cliente)."""
    destino = os.getenv("UBI_CONTACTO_DESTINO", "").strip() or _resend()["respuesta"]
    if not activo():
        return False
    c = _cfg()
    m = EmailMessage()
    m["From"] = formataddr((config.MARCA, c["usuario"] or _resend()["desde"]))
    m["To"] = destino
    m["Reply-To"] = datos.get("email", "")
    m["Subject"] = f"Contacto web · {datos.get('nombre', '')}" + (f" ({datos['empresa']})" if datos.get("empresa") else "")
    filas = [("Nombre", "nombre"), ("Correo", "email"), ("Empresa", "empresa"), ("Teléfono", "telefono"), ("Interés", "interes")]
    texto = "\n".join(f"{t}: {datos.get(k) or '-'}" for t, k in filas) + "\n\n" + (datos.get("mensaje") or "")
    m.set_content(texto)
    m.add_alternative("<div style='font-family:Arial,sans-serif;font-size:14px'>" + "".join(
        f"<p><b>{t}:</b> {escape(str(datos.get(k) or '-'))}</p>" for t, k in filas) + "<p>" +
        escape(datos.get("mensaje") or "").replace("\n", "<br>") + "</p></div>", subtype="html")
    try:
        if _resend()["clave"]:
            from app import http
            r = _resend()
            resp = await http.cliente().post(
                "https://api.resend.com/emails", headers={"Authorization": f"Bearer {r['clave']}"},
                json={"from": formataddr((config.MARCA, r["desde"])), "to": [destino], "subject": m["Subject"], "text": texto,
                      "html": m.get_body(("html",)).get_content(), "reply_to": datos.get("email") or r["respuesta"]}, timeout=30)
            if resp.status_code >= 300:
                raise RuntimeError(f"Resend {resp.status_code}")
        else:
            await asyncio.to_thread(_enviar, m)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudo reenviar el contacto: %s", e)
        return False
