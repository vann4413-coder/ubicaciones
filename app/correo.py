"""Envío de correos (enlace al informe comprado) por SMTP.

Variables de entorno (en Railway):
  UBI_SMTP_USUARIO   cuenta que envía, p. ej. tuparcela360@gmail.com
  UBI_SMTP_CLAVE     contraseña de aplicación de esa cuenta (en Gmail: https://myaccount.google.com/apppasswords)
  UBI_SMTP_SERVIDOR  smtp.gmail.com por defecto
  UBI_SMTP_PUERTO    465 por defecto (SSL)
Sin usuario y clave, no se envía nada (la web funciona igual).
"""
import asyncio
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


def activo() -> bool:
    c = _cfg()
    return bool(c["usuario"] and c["clave"])


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
<p><a href="{url_informe}" style="display:inline-block;background:#12355b;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none">Ver el informe</a>
&nbsp;<a href="{url_pdf}" style="display:inline-block;background:#f5a623;color:#12355b;padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:bold">Descargar el PDF</a></p>
<p style="color:#5b6b7b;font-size:13px">Guarda este correo: los enlaces te permiten volver a abrir el informe cuando quieras.</p>
<p>Un saludo,<br><b>{config.MARCA}</b><br><a href="https://parcelas360.com">parcelas360.com</a></p></div>""", subtype="html")
    return m


def _enviar(m: EmailMessage) -> None:
    c = _cfg()
    with smtplib.SMTP_SSL(c["servidor"], c["puerto"], context=ssl.create_default_context(), timeout=30) as s:
        s.login(c["usuario"], c["clave"])
        s.send_message(m)


async def enviar_informe(destino: str, rc: str, url_informe: str, url_pdf: str, direccion: str = "") -> bool:
    if not activo() or not destino:
        return False
    try:
        await asyncio.to_thread(_enviar, mensaje_informe(destino, rc, url_informe, url_pdf, direccion))
        return True
    except Exception as e:  # noqa: BLE001  un fallo de correo no debe romper la compra
        log.warning("No se pudo enviar el correo del informe %s: %s", rc, e)
        return False
