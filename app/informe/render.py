"""Convierte el informe en HTML y PDF."""
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app import config
from app.analisis.compatibilidad import PERFILES
from app.informe import mapas

PLANTILLAS = Path(__file__).parent / "templates"

NIVELES = {"compatible": "Compatible", "condicionado": "Condicionado", "plan_especial": "Solo con plan especial",
           "incompatible": "Incompatible", "sin_dato": "Sin dato"}
BLOQUES = {"urbanismo": "Urbanismo", "trafico": "Tráfico", "red": "Red eléctrica", "parcela": "Parcela",
           "inundabilidad": "Inundabilidad", "entorno": "Entorno"}
ESTADOS = {"ok": "Correcto", "sin_dato": "Sin dato", "error": "No disponible", "no_aplica": "No aplica"}


def num(v, dec: int = 0) -> str:
    """Formato español: 12.345,6"""
    if v is None or v == "":
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    s = f"{v:,.{dec}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def fecha(v) -> str:
    if not v:
        return "—"
    s = str(v)[:10]
    try:
        return date.fromisoformat(s).strftime("%d/%m/%Y")
    except ValueError:
        return str(v)


_env = Environment(loader=FileSystemLoader(PLANTILLAS), autoescape=select_autoescape(["html"]))
_env.filters.update(num=num, fecha=fecha, bloque=lambda b: BLOQUES.get(b, b))


def panorama(inf: dict, comp: dict) -> list[dict]:
    """Fichas «de un vistazo» de la portada: un dato por tema con su color (verde, ámbar, rojo o gris)."""
    fichas = []

    u = inf["urbanismo"]
    if u.get("estado") == "ok" and u.get("calificaciones"):
        q = max(u["calificaciones"], key=lambda x: x["pct"])
        clas = u["clasificaciones"][0]["descripcion"] if u.get("clasificaciones") else ""
        niveles = [c["nivel"] for c in u["compatibilidad"].values()]
        estado = "verde" if "compatible" in niveles else "ambar" if "condicionado" in niveles else "rojo"
        fichas.append({"icono": "urbanismo", "titulo": "Urbanismo", "valor": q["codigo_municipal"] or q["codigo_muc"],
                       "detalle": f"{clas} · {q['descripcion_municipal'] or q['descripcion_muc']}", "estado": estado})
    else:
        fichas.append({"icono": "urbanismo", "titulo": "Urbanismo", "valor": "Sin dato", "detalle": "", "estado": "gris"})

    r = inf["inundabilidad_resumen"]
    if inf["inundabilidad_aca"].get("estado") != "ok" and inf["inundabilidad_snczi"].get("estado") != "ok":
        fichas.append({"icono": "agua", "titulo": "Flujo preferente", "valor": "Sin dato", "detalle": "", "estado": "gris"})
    else:
        zfp = (r.get("zfp_pct") or 0) > 0
        nivel = r.get("nivel")
        inund = {"T10": "Inundable T10 (alta probabilidad)", "T100": "Inundable T100", "T500": "Inundable T500 (baja probabilidad)"}.get(nivel, "Fuera de zona inundable")
        estado = "rojo" if zfp or nivel == "T10" else "ambar" if nivel in ("T100", "T500") else "verde"
        fichas.append({"icono": "agua", "titulo": "Flujo preferente", "valor": "Sí" if zfp else "No", "detalle": inund, "estado": estado})

    carr = [c for c in inf["trafico"].get("carreteras", []) if c.get("imd")]
    if carr:
        c = max(carr, key=lambda c: c["imd"] if c["distancia_m"] <= 500 else 0) if any(c["distancia_m"] <= 500 for c in carr) else min(carr, key=lambda c: c["distancia_m"])
        estado = "verde" if c["imd"] >= 10000 and c["distancia_m"] <= 300 else "ambar" if c["imd"] >= 3000 else "rojo"
        fichas.append({"icono": "trafico", "titulo": "Tráfico", "valor": f"{num(c['imd'])} veh/día",
                       "detalle": f"{c['carretera']} a {num(c['distancia_m'])} m ({c['anio']})", "estado": estado})
    else:
        fichas.append({"icono": "trafico", "titulo": "Tráfico", "valor": "Sin aforo", "detalle": "Ninguna vía con aforo cerca", "estado": "gris"})

    red = inf["red"]
    if red.get("estado") == "ok" and red.get("nudos"):
        n = red["nudos"][0]
        disp = n.get("disponible_mw") or 0
        fichas.append({"icono": "red", "titulo": "Red eléctrica", "valor": f"{num(disp, 2)} MW",
                       "detalle": f"{n['nudo']} a {num(n['distancia_m'])} m", "estado": "verde" if disp >= 1 else "ambar" if disp > 0 else "rojo"})
    else:
        fichas.append({"icono": "red", "titulo": "Red eléctrica", "valor": "Sin dato", "detalle": "Capacidad de acceso no cargada", "estado": "gris"})

    pob = inf["poblacion"]
    fichas.append({"icono": "entorno", "titulo": "Población", "valor": f"{num(pob['poblacion'])} hab." if pob.get("estado") == "ok" else "Sin dato",
                   "detalle": f"{inf['municipio']['nombre']} ({pob['fecha_dato']})" if pob.get("estado") == "ok" else inf["municipio"]["nombre"],
                   "estado": "neutro" if pob.get("estado") == "ok" else "gris"})

    sc = inf["suelos_contaminados"]
    if sc.get("estado") == "ok":
        if sc.get("en_parcela"):
            fichas.append({"icono": "suelo", "titulo": "Suelo contaminado", "valor": "En registro", "detalle": sc["en_parcela"][0]["nombre"], "estado": "rojo"})
        else:
            fichas.append({"icono": "suelo", "titulo": "Suelo contaminado", "valor": "No consta",
                           "detalle": f"{len(sc.get('cercanos', []))} emplazamientos cercanos" if sc.get("cercanos") else "Nada en el entorno",
                           "estado": "ambar" if sc.get("cercanos") else "verde"})
    else:
        fichas.append({"icono": "suelo", "titulo": "Suelo contaminado", "valor": "Sin dato", "detalle": "", "estado": "gris"})

    c = inf["cambios"]
    if c.get("estado") == "ok":
        n = len(c.get("recientes", []))
        fichas.append({"icono": "planeamiento", "titulo": "Cambios de planeamiento", "valor": f"{n} recientes",
                       "detalle": f"Últimos {c['anios']} años en el municipio", "estado": "ambar" if n else "verde"})

    e5 = inf.get("entorno5") or {}
    if e5.get("estado") == "ok":
        filas = {f["clave"]: f for f in e5["resumen"]}
        radio = e5.get("radio_m", 5000)
        clave_r = max(r for r in filas["restauracion"]["cuenta"])
        negocios = sum((f["cuenta"].get(clave_r) or 0) for k, f in filas.items() if k not in ("comercios", "oficinas", "poligonos", "gasolineras"))
        partes = [f"Hoteles: {filas['hoteles']['cuenta'][clave_r]}", f"Naves y logística: {filas['logistica']['cuenta'][clave_r]}",
                  f"Polígonos: {filas['poligonos']['cuenta'][clave_r]}"]
        fichas.append({"icono": "entorno", "titulo": f"Entorno en {radio // 1000} km", "valor": f"{num(negocios)} actividades",
                       "detalle": " · ".join(partes), "estado": "neutro"})
    else:
        su = inf["suelo"]
        fichas.append({"icono": "valor", "titulo": "Valor del suelo", "valor": f"{num(su['ultimo_precio_m2'])} €/m²" if su.get("estado") == "ok" else "Sin dato",
                       "detalle": f"Referencia: {su['ambito']}" if su.get("estado") == "ok" else "Estadística no cargada", "estado": "neutro" if su.get("estado") == "ok" else "gris"})
    return fichas


def html(inf: dict) -> str:
    comp = mapas.competencia(inf)
    return _env.get_template("informe.html").render(
        inf=inf, mapas=mapas.construir(inf), perfiles=PERFILES, niveles=NIVELES, bloques=BLOQUES, estados=ESTADOS,
        comp=comp, panorama=panorama(inf, comp), marca=config.MARCA, lema=config.MARCA_LEMA,
    )


def pdf(inf: dict, anexos: list[bytes] | None = None) -> bytes:
    """PDF del informe; los anexos (p. ej. la ficha oficial del Catastro) se añaden al final."""
    from weasyprint import HTML
    base = HTML(string=html(inf)).write_pdf()
    if not anexos:
        return base
    import io

    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    w.append(PdfReader(io.BytesIO(base)))
    for a in anexos:
        try:
            w.append(PdfReader(io.BytesIO(a)))
        except Exception:  # noqa: BLE001  un anexo dañado no debe impedir el informe
            continue
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


async def fichas_catastro(inf: dict, maximo: int = 3) -> list[bytes]:
    """Descarga las consultas descriptivas y gráficas oficiales (solo si la parcela tiene pocos inmuebles)."""
    from app import http
    fichas = inf["parcela"].get("fichas_catastro") or []
    if not fichas or len(fichas) > maximo:
        return []
    salida = []
    for f in fichas:
        try:
            contenido, tipo = await http.get_bytes(f["url"])
            if contenido[:5] == b"%PDF-":
                salida.append(contenido)
        except Exception:  # noqa: BLE001
            continue
    return salida
