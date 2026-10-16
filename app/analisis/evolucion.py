"""Evolución histórica de la parcela con ortofotos del ICGC.

Con clave de API, la IA mira las cuatro imágenes y describe qué había en cada época
(edificios, actividad industrial, posible gasolinera, terreno libre). Sin clave,
el informe muestra las imágenes para que las interprete el usuario.
"""
import base64
import json
import logging

from shapely.geometry.base import BaseGeometry

from app import config, http
from app.fuentes import ortofotos

log = logging.getLogger(__name__)

PROMPT = (
    "Tienes ortofotos aéreas de la misma parcela en varios años (la parcela está en el centro de cada imagen; "
    "cada imagen indica su año). Para cada año di en una frase qué se ve dentro de la parcela "
    "(terreno libre, cultivo, edificios, naves, depósitos, marquesina de gasolinera, aparcamiento...). "
    "Después indica si hay indicios de un uso anterior que pudiera haber contaminado el suelo "
    "(gasolinera, industria, depósitos, desguace) y si aparecen construcciones en los años recientes. "
    "Responde SOLO con JSON: {\"anios\": [{\"anio\": \"...\", \"descripcion\": \"...\"}], "
    "\"alerta_contaminacion\": true|false, \"construcciones_recientes\": true|false, \"nota\": \"una frase\"}. "
    "Si una imagen no se ve bien, dilo. No inventes."
)


async def consultar(parcela: BaseGeometry) -> dict:
    h = ortofotos.historicas(parcela)
    salida = {**h, "analisis": None, "nota": "", "alerta_contaminacion": False}
    if not config.ANTHROPIC_API_KEY:
        return salida
    try:
        import anthropic
        contenido = []
        for img in h["imagenes"]:
            r = await http.cliente().get(img["url"])
            if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image"):
                continue
            contenido.append({"type": "text", "text": f"Año {img['anio']}:"})
            contenido.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                           "data": base64.b64encode(r.content).decode()}})
        if not contenido:
            return salida
        contenido.append({"type": "text", "text": PROMPT})
        cliente = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        msg = await cliente.messages.create(model=config.ANTHROPIC_MODEL, max_tokens=600,
                                            messages=[{"role": "user", "content": contenido}])
        texto = msg.content[0].text.strip()
        texto = texto[texto.find("{"): texto.rfind("}") + 1]
        datos = json.loads(texto)
        salida.update(analisis=datos.get("anios"), nota=datos.get("nota", ""),
                      alerta_contaminacion=bool(datos.get("alerta_contaminacion")),
                      construcciones_recientes=bool(datos.get("construcciones_recientes")))
    except Exception as e:
        log.warning("Análisis de ortofotos no disponible: %s", e)
    return salida
