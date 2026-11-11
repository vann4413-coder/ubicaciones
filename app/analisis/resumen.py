"""Resumen ejecutivo (IA si hay clave de API; si no, texto generado por reglas)
y lista de riesgos y próximos pasos."""
import json
import logging

from app import config

log = logging.getLogger(__name__)


def hechos_clave(inf: dict) -> dict:
    """Datos esenciales y ya verificados que se pasan a la IA (nada más, para que no invente)."""
    p, u, i, t, r = inf["parcela"], inf["urbanismo"], inf["inundabilidad_resumen"], inf["trafico"], inf["red"]
    cal = (u.get("calificaciones") or [{}])[0] if u.get("estado") == "ok" else {}
    return {
        "direccion": p.get("direccion"), "municipio": inf["municipio"]["nombre"] or p.get("municipio"), "superficie_m2": p.get("sup_grafica"),
        "uso_catastral": p.get("uso"), "clase_suelo": [c["descripcion"] for c in u.get("clasificaciones", [])],
        "calificacion": f"{cal.get('codigo_municipal', '')} {cal.get('descripcion_municipal', '')}".strip(),
        "inundabilidad": i.get("nivel"),
        "carreteras": [
            {k: c[k] for k in ("carretera", "distancia_m", "imd", "anio", "pct_pesados", "titular")}
            for c in (t.get("carreteras") or [])[:4]
        ],
        "red_nudo": (r.get("nudos") or [None])[0] and {k: r["nudos"][0][k] for k in ("nudo", "distancia_m", "disponible_mw", "marca_0")},
        "puntuaciones": {v["nombre_perfil"]: {"total": v["total"], "veredicto": v["veredicto"], "mejor_uso": v["mejor_uso"],
                                              "bloqueos": v["bloqueos"]}
                         for v in inf["puntuaciones"].values()},
        "usos_previos": inf.get("evolucion", {}).get("nota", ""),
    }


def _n(v, dec: int = 0) -> str:
    s = f"{float(v):,.{dec}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def resumen_reglas(inf: dict) -> str:
    h = hechos_clave(inf)
    frases = [f"Parcela de {_n(h['superficie_m2'] or 0)} m² en {h['municipio']}"
              + (f", calificada como {h['calificacion']}." if h["calificacion"] else ".")]
    inund = {"fuera": "Fuera de zonas inundables cartografiadas.", "T500": "Afectada por la lámina de 500 años.",
             "T100": "Afectada por la lámina de 100 años.", "T10": "Afectada por la lámina de 10 años.",
             "zfp": "Dentro de zona de flujo preferente: no autorizable para la mayoría de usos."}
    frases.append(inund.get(h["inundabilidad"], "Inundabilidad sin dato."))
    con_imd = [c for c in h["carreteras"] if c["imd"]]
    if con_imd:
        c = max(con_imd, key=lambda x: x["imd"])
        frases.append(f"La vía con más tráfico cercana es la {c['carretera']} con {_n(c['imd'])} vehículos/día "
                      f"({c['anio']}) a {_n(c['distancia_m'])} m.")
    else:
        frases.append("No hay aforos oficiales de tráfico a menos de 1 km.")
    if h["red_nudo"]:
        n = h["red_nudo"]
        frases.append(f"El nudo eléctrico más cercano ({n['nudo']}, a {_n(n['distancia_m'])} m) publica "
                      f"{_n(n['disponible_mw'] or 0, 2)} MW disponibles.")
    mejores = sorted(h["puntuaciones"].items(), key=lambda kv: -(kv[1]["total"] or 0))
    aptos = [v["mejor_uso"].lower() for k, v in mejores if v["veredicto"] in ("Apta", "Apta con condiciones")]
    frases.append(f"Mejor encaje: {', '.join(aptos)}." if aptos else "Ningún uso obtiene una valoración favorable.")
    return " ".join(frases)


async def resumen_ia(inf: dict) -> tuple[str, str]:
    """Devuelve (texto, origen). Origen: 'ia' o 'reglas'."""
    if not config.ANTHROPIC_API_KEY:
        return resumen_reglas(inf), "reglas"
    try:
        import anthropic
        cliente = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        msg = await cliente.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=400,
            system=(
                "Eres analista de suelo para implantaciones de cualquier uso (movilidad, comercio, logística, residencial, terciario, energía). "
                "Redacta en español un resumen ejecutivo de 5 o 6 líneas, en prosa, tono neutro y profesional, "
                "usando EXCLUSIVAMENTE los datos JSON facilitados. No inventes cifras ni normas. Si un dato falta, "
                "di que falta. Menciona primero los bloqueos si los hay."
            ),
            messages=[{"role": "user", "content": json.dumps(hechos_clave(inf), ensure_ascii=False, default=str)}],
        )
        return msg.content[0].text.strip(), "ia"
    except Exception as e:  # La IA es un extra: si falla, el informe sale igual.
        log.warning("Resumen IA no disponible: %s", e)
        return resumen_reglas(inf), "reglas"


def riesgos_y_pasos(inf: dict) -> list[dict]:
    pasos = []
    u, i, t, r, ev = inf["urbanismo"], inf["inundabilidad_resumen"], inf["trafico"], inf["red"], inf.get("evolucion", {})
    pasos.append({"tipo": "paso", "texto": "Solicitar la cèdula urbanística o el certificado de compatibilidad urbanística al ayuntamiento."})
    if u.get("estado") == "ok" and len([c for c in u.get("calificaciones", []) if c["pct"] >= 5]) > 1:
        pasos.append({"tipo": "riesgo", "texto": "La parcela tiene varias calificaciones: comprobar qué parte admite el uso."})
    viario = sum(c["pct"] for c in u.get("calificaciones", []) if (c.get("codigo_muc") or "").upper().startswith("SX"))
    if u.get("estado") == "ok" and viario >= 2:
        sup = (inf.get("parcela") or {}).get("sup_grafica")
        m2 = f" (unos {sup * viario / 100:,.0f} m²)".replace(",", ".") if sup else ""
        carretera = ((t.get("accesos") or {}).get("carretera_mas_cercana") or {})
        junto = f" junto a la {carretera['ref']}" if carretera.get("ref") and carretera.get("distancia_m", 999) <= 50 else ""
        pasos.append({"tipo": "riesgo", "texto": f"El {viario:.1f}% de la parcela{m2} está calificado como sistema viario{junto}: "
                      "es suelo reservado para la carretera o la calle (ampliación, desdoblamiento o enlace), no edificable y "
                      "susceptible de expropiación o cesión. Preguntar al ayuntamiento y al titular de la vía si hay un "
                      "proyecto aprobado o en estudio que lo ocupe."})
    if (inf.get("cambios") or {}).get("recientes"):
        pasos.append({"tipo": "riesgo", "texto": "Hay modificaciones de planeamiento recientes en el municipio: revisar si afectan a la parcela."})
    if i.get("nivel") in ("zfp", "T10", "T100"):
        pasos.append({"tipo": "riesgo", "texto": "Riesgo de inundación relevante: consultar a la ACA (o la confederación) antes de avanzar."})
    if (inf.get("inundabilidad_aca") or {}).get("en_zona_policia"):
        pasos.append({"tipo": "paso", "texto": "La parcela está en zona de policía de cauces: cualquier obra necesita autorización del organismo de cuenca."})
    acc = t.get("accesos") or {}
    if acc.get("linea_edificacion") and acc["linea_edificacion"]["pct_afectado"] > 0:
        pasos.append({"tipo": "riesgo", "texto": f"El {acc['linea_edificacion']['pct_afectado']}% de la parcela queda dentro de la línea límite de edificación de la {acc['linea_edificacion']['carretera']}."})
    if acc.get("carretera_mas_cercana") and acc["carretera_mas_cercana"]["distancia_m"] <= 100:
        pasos.append({"tipo": "paso", "texto": f"Consultar al titular de la {acc['carretera_mas_cercana']['ref']} ({acc['carretera_mas_cercana']['titular']}) la viabilidad del acceso."})
    if r.get("estado") == "ok":
        pasos.append({"tipo": "paso", "texto": "Pedir a la distribuidora un estudio de acceso y conexión para la potencia necesaria."})
    else:
        pasos.append({"tipo": "paso", "texto": "Consultar la capacidad de red con la distribuidora de la zona."})
    sc = inf.get("suelos_contaminados") or {}
    for e in sc.get("en_parcela", []):
        if e["tipo"].startswith("Declaració") and e["activo"]:
            pasos.append({"tipo": "riesgo", "texto": f"Suelo declarado contaminado y aún activo en el registro de la ARC ({e['nombre']}). "
                          "Pedir el expediente: la descontaminación corresponde al causante y, subsidiariamente, al propietario."})
        else:
            pasos.append({"tipo": "riesgo", "texto": f"La parcela figura en el registro de suelos contaminados de la ARC ({e['tipo'].lower()}, "
                          f"{e['estado'].lower()}). Pedir el expediente y comprobar las restricciones de uso que imponga la resolución."})
    if sc.get("cercanos") and not sc.get("en_parcela"):
        pasos.append({"tipo": "riesgo", "texto": f"Hay {len(sc['cercanos'])} emplazamiento(s) con suelo contaminado a menos de {sc['radio_m']} m."})
    if ev.get("alerta_contaminacion"):
        pasos.append({"tipo": "riesgo", "texto": "Uso anterior con posible afectación del suelo: valorar un estudio de caracterización del suelo."})
    pg = (inf.get("urbanismo") or {}).get("parametros_pgou") or {}
    sup = (inf.get("parcela") or {}).get("sup_grafica")
    if pg.get("parcela_minima_m2") and sup and sup < pg["parcela_minima_m2"]:
        pasos.append({"tipo": "riesgo", "texto": f"La parcela es menor que la parcela mínima de la zona ({_n(pg['parcela_minima_m2'])} m²): "
                      "confirmar con el ayuntamiento que es edificable."})
    te = inf.get("terreno") or {}
    for a in te.get("afecciones") or []:
        if a["grupo"] in ("Protección", "Patrimonio", "Riesgo químico") or a["capa"] in ("zona-servitud-fluvial", "pendents-20-percent"):
            pasos.append({"tipo": "riesgo", "texto": f"{a['titulo']}{': ' + a['detalle'] if a.get('detalle') else ''}. "
                          "Consultar las limitaciones con el organismo competente."})
    for r in (te.get("riesgos") or {}).get("peligros") or []:
        if r.get("nivel") in ("alta", "mitjana"):
            pasos.append({"tipo": "riesgo", "texto": f"Peligrosidad geológica ({r['tipo'].lower()}): {r['descripcion']}."})
    rel = te.get("relieve") or {}
    if (rel.get("desnivel_m") or 0) >= 3:
        pasos.append({"tipo": "paso", "texto": f"Desnivel de {rel['desnivel_m']:.1f} m".replace('.', ',', 1) + f" dentro de la parcela: valorar el movimiento de tierras."})
    return pasos
