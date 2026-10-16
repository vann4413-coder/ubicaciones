"""Puntuación de idoneidad por perfil.

1. Filtros eliminatorios -> 'No apta' con su motivo.
2. Subnotas 0-100 por bloque.
3. Media ponderada con los pesos del perfil. Si falta un bloque, su peso se reparte
   entre los demás y baja la confianza; nunca se inventa un valor.
"""
from datetime import date

from app.analisis import perfiles
from app.analisis.compatibilidad import PERFILES

NOTA_URB = {"compatible": 100, "condicionado": 60, "plan_especial": 0, "incompatible": 0}
NOTA_INUND = {"fuera": 100, "T500": 80, "T100": 40, "T10": 10, "zfp": 0}


def _interp(tramos: list[tuple[float, float]], valor: float) -> float:
    if valor <= tramos[0][0]:
        return tramos[0][1]
    for (x0, y0), (x1, y1) in zip(tramos, tramos[1:]):
        if valor <= x1:
            return y0 + (y1 - y0) * (valor - x0) / (x1 - x0)
    return tramos[-1][1]


def nota_trafico(perfil: str, trafico: dict) -> tuple[float | None, str]:
    carreteras = [c for c in (trafico.get("carreteras") or []) if c.get("imd")]
    if not carreteras:
        return None, "Sin aforos oficiales en 1 km."
    efectivas = []
    for c in carreteras:
        factor = 1.0 if c["distancia_m"] <= 500 else 0.7
        efectivas.append((c["imd"] * factor, c))
    imd_ef, mejor = max(efectivas, key=lambda e: e[0])
    nota = _interp(perfiles.TRAMOS_IMD[perfil], imd_ef)
    umbral, bonus = perfiles.BONUS_PESADOS[perfil]
    if (mejor.get("pct_pesados") or 0) >= umbral:
        nota += bonus
    return min(100, round(nota)), f"{mejor['carretera']}: IMD {mejor['imd']:,} ({mejor['anio']}) a {mejor['distancia_m']} m".replace(",", ".")


def nota_red(perfil: str, red: dict, potencia_mw: float | None) -> tuple[float | None, str]:
    nudos = red.get("nudos") or []
    if red.get("estado") != "ok" or not nudos:
        return None, "Sin datos de capacidad de red."
    n = nudos[0]
    objetivo = potencia_mw or perfiles.POTENCIA_OBJETIVO_MW[perfil]
    disp = n.get("disponible_mw") or 0
    if disp <= 0:
        return (15, f"Nudo {n['nudo']}: capacidad 0 con marca 0*") if n.get("marca_0") else (0, f"Nudo {n['nudo']}: sin capacidad")
    nota = min(100, 100 * disp / objetivo)
    # Penalización por distancia: a más de 3 km la conexión encarece mucho.
    if n["distancia_m"] > 3000:
        nota *= 0.7
    return round(nota), f"Nudo {n['nudo']}: {disp:.2f} MW disponibles a {n['distancia_m']} m"


def nota_parcela(perfil: str, metr: dict, accesos: dict, sup_minima: float | None) -> tuple[float, str]:
    partes = []
    # Superficie: solo puntúa si el usuario indica la mínima que necesita.
    if sup_minima:
        util = metr["superficie_m2"] - ((accesos.get("linea_edificacion") or {}).get("superficie_afectada_m2") or 0)
        partes.append(min(100, 100 * util / sup_minima))
    frente = accesos.get("frente_vial_m") or 0
    partes.append(min(100, 100 * frente / perfiles.FRENTE_DESEABLE_M[perfil]))
    partes.append(min(100, metr["compacidad"] / 0.6 * 100))
    le = accesos.get("linea_edificacion")
    if le:
        partes.append(max(0, 100 - le["pct_afectado"]))
    nota = round(sum(partes) / len(partes))
    return nota, f"Frente a vial {frente:.0f} m, forma {metr['forma']}"


def calcular(perfil: str, datos: dict, potencia_mw: float | None = None, sup_minima: float | None = None) -> dict:
    urb = datos["urbanismo"]
    inund = datos["inundabilidad"]
    red = datos["red"]
    trafico = datos["trafico"]
    metr = datos["metricas"]
    accesos = trafico.get("accesos") or {}

    bloqueos = []
    compat = (urb.get("compatibilidad") or {}).get(perfil, {}) if urb.get("estado") == "ok" else {}
    nivel_urb = compat.get("nivel")
    if inund.get("nivel") == "zfp":
        bloqueos.append(f"Parcela en zona de flujo preferente ({inund['zfp_pct']}% de la superficie).")
    if nivel_urb == "incompatible":
        bloqueos.append("Calificación urbanística incompatible con el uso.")
    if nivel_urb == "plan_especial":
        bloqueos.append("Uso solo admisible mediante plan especial.")
    if perfil == "recarga" and red.get("estado") == "ok" and red.get("nudos"):
        n = red["nudos"][0]
        if (n.get("disponible_mw") or 0) <= 0 and not n.get("marca_0"):
            bloqueos.append(f"Nudo {n['nudo']} sin capacidad y sin marca 0*: no admite solicitudes.")

    sub: dict[str, dict] = {}
    sub["urbanismo"] = {"nota": NOTA_URB.get(nivel_urb), "detalle": compat.get("motivo", "Sin dato urbanístico")}
    sub["inundabilidad"] = {"nota": NOTA_INUND.get(inund.get("nivel")), "detalle": {
        "fuera": "Fuera de zonas inundables cartografiadas", "T500": "Dentro de la lámina de 500 años",
        "T100": "Dentro de la lámina de 100 años", "T10": "Dentro de la lámina de 10 años",
        "zfp": "Zona de flujo preferente"}.get(inund.get("nivel"), "Sin dato")}
    n, det = nota_trafico(perfil, trafico)
    sub["trafico"] = {"nota": n, "detalle": det}
    n, det = nota_red(perfil, red, potencia_mw)
    sub["red"] = {"nota": n, "detalle": det}
    n, det = nota_parcela(perfil, metr, accesos, sup_minima)
    sub["parcela"] = {"nota": n, "detalle": det}

    pesos = perfiles.PESOS[perfil]
    con_dato = {k: v for k, v in sub.items() if v["nota"] is not None}
    peso_total = sum(pesos[k] for k in con_dato)
    for k, v in sub.items():
        v["peso"] = pesos[k]
        v["peso_efectivo"] = round(100 * pesos[k] / peso_total, 1) if k in con_dato and peso_total else 0
    total = round(sum(v["nota"] * pesos[k] for k, v in con_dato.items()) / peso_total) if peso_total else None

    cobertura = peso_total / 100
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
        "perfil": perfil, "nombre_perfil": PERFILES[perfil], "total": total, "semaforo": semaforo,
        "veredicto": veredicto, "bloqueos": bloqueos, "subnotas": sub, "confianza": confianza,
        "faltan": [k for k, v in sub.items() if v["nota"] is None],
        "nota_urbanismo": compat.get("nota", ""),
    }


def calcular_todos(datos: dict, potencia_mw: float | None = None, sup_minima: float | None = None) -> dict:
    return {p: calcular(p, datos, potencia_mw, sup_minima) for p in PERFILES}
