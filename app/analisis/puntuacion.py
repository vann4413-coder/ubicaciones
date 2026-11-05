"""Puntuación de idoneidad por grupo de uso y por uso concreto.

1. Filtros eliminatorios -> 'No apta' con su motivo.
2. Subnotas 0-100 por bloque (urbanismo, tráfico, red, parcela, inundabilidad, entorno).
3. Media ponderada con los pesos del uso. Si falta un bloque, su peso se reparte entre
   los demás; nunca se inventa un valor.
4. La nota de cada grupo es la del uso que mejor encaja.
"""
from datetime import date

from app.analisis import perfiles

NOTA_URB = {"compatible": 100, "condicionado": 60, "plan_especial": 0, "incompatible": 0}
NOTA_INUND = {"fuera": 100, "T500": 80, "T100": 40, "T10": 10, "zfp": 0}


def _interp(tramos: list[tuple[float, float]], valor: float) -> float:
    if valor <= tramos[0][0]:
        return tramos[0][1]
    for (x0, y0), (x1, y1) in zip(tramos, tramos[1:]):
        if valor <= x1:
            return y0 + (y1 - y0) * (valor - x0) / (x1 - x0)
    return tramos[-1][1]


def nota_trafico(cfg: dict, trafico: dict) -> tuple[float | None, str]:
    if cfg["imd"] == perfiles.IMD_NEUTRA:
        return 100, "El tráfico no condiciona este uso."
    carreteras = [c for c in (trafico.get("carreteras") or []) if c.get("imd")]
    if not carreteras:
        return None, "Sin aforos oficiales en 1 km."
    efectivas = []
    for c in carreteras:
        factor = 1.0 if c["distancia_m"] <= 500 else 0.7
        efectivas.append((c["imd"] * factor, c))
    imd_ef, mejor = max(efectivas, key=lambda e: e[0])
    nota = _interp(cfg["imd"], imd_ef)
    umbral, bonus = cfg["pesados"]
    if (mejor.get("pct_pesados") or 0) >= umbral:
        nota += bonus
    return min(100, round(nota)), f"{mejor['carretera']}: IMD {mejor['imd']:,} ({mejor['anio']}) a {mejor['distancia_m']} m".replace(",", ".")


def nota_red(cfg: dict, red: dict, potencia_mw: float | None) -> tuple[float | None, str]:
    nudos = red.get("nudos") or []
    if red.get("estado") != "ok" or not nudos:
        return None, "Sin datos de capacidad de red."
    n = nudos[0]
    objetivo = potencia_mw or cfg["potencia_mw"]
    disp = n.get("disponible_mw") or 0
    if disp <= 0:
        return (15, f"Nudo {n['nudo']}: capacidad 0 con marca 0*") if n.get("marca_0") else (0, f"Nudo {n['nudo']}: sin capacidad")
    nota = min(100, 100 * disp / objetivo)
    # Penalización por distancia: a más de 3 km la conexión encarece mucho.
    if n["distancia_m"] > 3000:
        nota *= 0.7
    return round(nota), f"Nudo {n['nudo']}: {disp:.2f} MW disponibles a {n['distancia_m']} m"


def nota_parcela(cfg: dict, metr: dict, accesos: dict, sup_minima: float | None) -> tuple[float, str]:
    partes = []
    # Superficie: frente a la que indica el usuario o, si no, la habitual del uso.
    sup_minima = sup_minima or cfg.get("superficie_m2")
    if sup_minima:
        util = metr["superficie_m2"] - ((accesos.get("linea_edificacion") or {}).get("superficie_afectada_m2") or 0)
        partes.append(min(100, 100 * util / sup_minima))
    frente = accesos.get("frente_vial_m") or 0
    if accesos.get("estado") == "ok" or frente:
        partes.append(min(100, 100 * frente / cfg["frente_m"]))
    partes.append(min(100, metr["compacidad"] / 0.6 * 100))
    le = accesos.get("linea_edificacion")
    if le:
        partes.append(max(0, 100 - le["pct_afectado"]))
    nota = round(sum(partes) / len(partes))
    sup_txt = f"{metr['superficie_m2']:,.0f} m² (habitual {sup_minima:,.0f} m²)".replace(",", ".") if sup_minima else f"{metr['superficie_m2']:,.0f} m²".replace(",", ".")
    return nota, f"{sup_txt}, frente a vial {frente:.0f} m, forma {metr['forma']}"


def nota_entorno(cfg: dict, entorno: dict) -> tuple[float | None, str]:
    """Actividad alrededor que favorece el uso: cuántos hay frente a los que dan la nota máxima."""
    if not cfg["entorno"]:
        return None, "No aplica a este uso."
    if not entorno or entorno.get("estado") != "ok":
        return None, "Sin datos del entorno."
    notas, textos = [], []
    for cat, radio, objetivo in cfg["entorno"]:
        if cat == "poligonos":
            n = sum(1 for z in entorno.get("zonas_industriales", []) if z["distancia_m"] <= radio)
            etiqueta = "polígonos"
        else:
            n = sum(1 for p in entorno.get("puntos", []) if p["cat"] == cat and p["distancia_m"] <= radio)
            etiqueta = next((f["nombre"].lower() for f in entorno.get("resumen", []) if f["clave"] == cat), cat)
        notas.append(min(100, 100 * n / objetivo))
        textos.append(f"{n} {etiqueta} en {radio // 1000 if radio >= 1000 else radio} {'km' if radio >= 1000 else 'm'}")
    return round(sum(notas) / len(notas)), ", ".join(textos)


def calcular_uso(grupo: str, clave_uso: str, datos: dict, potencia_mw: float | None = None, sup_minima: float | None = None) -> dict:
    cfg = perfiles.GRUPOS[grupo]["usos"][clave_uso]
    regla = cfg["regla"]
    urb = datos["urbanismo"]
    inund = datos["inundabilidad"]
    red = datos["red"]
    trafico = datos["trafico"]
    metr = datos["metricas"]
    accesos = trafico.get("accesos") or {}

    bloqueos = []
    compat = (urb.get("compatibilidad") or {}).get(regla, {}) if urb.get("estado") == "ok" else {}
    nivel_urb = compat.get("nivel")
    if inund.get("nivel") == "zfp":
        bloqueos.append(f"Parcela en zona de flujo preferente ({inund['zfp_pct']}% de la superficie).")
    if nivel_urb == "incompatible":
        bloqueos.append("Calificación urbanística incompatible con el uso.")
    if nivel_urb == "plan_especial":
        bloqueos.append("Uso solo admisible mediante plan especial.")
    if regla == "recarga" and clave_uso == "electrolinera" and red.get("estado") == "ok" and red.get("nudos"):
        n = red["nudos"][0]
        if (n.get("disponible_mw") or 0) <= 0 and not n.get("marca_0"):
            bloqueos.append(f"Nudo {n['nudo']} sin capacidad y sin marca 0*: no admite solicitudes.")

    sub: dict[str, dict] = {}
    sub["urbanismo"] = {"nota": NOTA_URB.get(nivel_urb), "detalle": compat.get("motivo", "Sin dato urbanístico")}
    sub["inundabilidad"] = {"nota": NOTA_INUND.get(inund.get("nivel")), "detalle": {
        "fuera": "Fuera de zonas inundables cartografiadas", "T500": "Dentro de la lámina de 500 años",
        "T100": "Dentro de la lámina de 100 años", "T10": "Dentro de la lámina de 10 años",
        "zfp": "Zona de flujo preferente"}.get(inund.get("nivel"), "Sin dato")}
    n, det = nota_trafico(cfg, trafico)
    sub["trafico"] = {"nota": n, "detalle": det}
    n, det = nota_red(cfg, red, potencia_mw)
    sub["red"] = {"nota": n, "detalle": det}
    n, det = nota_parcela(cfg, metr, accesos, sup_minima)
    sub["parcela"] = {"nota": n, "detalle": det}
    n, det = nota_entorno(cfg, datos.get("entorno"))
    sub["entorno"] = {"nota": n, "detalle": det}

    pesos = cfg["pesos"]
    sub = {k: v for k, v in sub.items() if pesos.get(k)}  # los bloques que no pesan en este uso no se muestran
    con_dato = {k: v for k, v in sub.items() if v["nota"] is not None}
    peso_total = sum(pesos[k] for k in con_dato)
    for k, v in sub.items():
        v["peso"] = pesos[k]
        v["peso_efectivo"] = round(100 * pesos[k] / peso_total, 1) if k in con_dato and peso_total else 0
    total = round(sum(v["nota"] * pesos[k] for k, v in con_dato.items()) / peso_total) if peso_total else None

    cobertura = peso_total / sum(pesos.values())
    confianza = "alta" if cobertura >= 0.9 else "media" if cobertura >= 0.65 else "baja"
    anios = [c["anio"] for c in (trafico.get("carreteras") or []) if c.get("anio")]
    if anios and date.today().year - max(anios) > 3 and confianza == "alta":
        confianza = "media"

    if bloqueos:
        semaforo, veredicto = "rojo", "No apta"
    elif total is None:
        semaforo, veredicto = "gris", "Sin datos suficientes"
    elif total >= 75:
        semaforo, veredicto = "verde", "Apta"
    elif total >= 50:
        semaforo, veredicto = "ambar", "Apta con condiciones"
    else:
        semaforo, veredicto = "rojo", "Poco apta"

    return {
        "uso": clave_uso, "nombre_uso": cfg["nombre"], "regla": regla, "total": total, "semaforo": semaforo,
        "veredicto": veredicto, "bloqueos": bloqueos, "subnotas": sub, "confianza": confianza,
        "faltan": [k for k, v in sub.items() if v["nota"] is None],
        "nota_urbanismo": compat.get("nota", ""),
    }


def _orden(r: dict) -> tuple:
    return (0 if r["bloqueos"] else 1, r["total"] if r["total"] is not None else -1)


def calcular_grupo(grupo: str, datos: dict, potencia_mw: float | None = None, sup_minima: float | None = None,
                   uso: str | None = None) -> dict:
    """Nota del grupo = la del uso indicado o, si no se indica, la del uso que mejor encaja."""
    usos = {u: calcular_uso(grupo, u, datos, potencia_mw, sup_minima) for u in perfiles.GRUPOS[grupo]["usos"]}
    mejor = usos[uso] if uso in usos else max(usos.values(), key=_orden)
    return {**mejor, "grupo": grupo, "perfil": grupo, "nombre_perfil": perfiles.nombre_grupo(grupo),
            "mejor_uso": mejor["nombre_uso"], "uso_elegido": uso in usos, "usos": usos}


def calcular_todos(datos: dict, potencia_mw: float | None = None, sup_minima: float | None = None,
                   grupos: list[str] | None = None, usos: dict | None = None) -> dict:
    grupos = [g for g in (grupos or perfiles.ORDEN_GRUPOS) if g in perfiles.GRUPOS] or perfiles.ORDEN_GRUPOS
    usos = usos or {}
    return {g: calcular_grupo(g, datos, potencia_mw, sup_minima, usos.get(g)) for g in grupos}
