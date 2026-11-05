"""Compatibilidad de usos según la calificación sintética del MUC.

Es una lectura de la clave sintética y su descripción, no de la normativa
municipal. Por eso el resultado siempre se presenta como orientativo.

Niveles: 'compatible', 'condicionado', 'plan_especial', 'incompatible'.
"""
import unicodedata

# Reglas de compatibilidad (cada uso de perfiles.GRUPOS apunta a una de ellas).
PERFILES = {
    "gasolinera": "Estación de servicio y lavado",
    "recarga": "Recarga eléctrica y aparcamiento",
    "retail": "Comercio y restauración",
    "industrial": "Industria, logística e ITV",
    "residencial": "Residencial",
    "terciario": "Hotelero, oficinas y equipamientos",
    "energia": "Fotovoltaica, baterías y subestaciones",
}


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFD", (t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def familia(codigo: str, descripcion: str) -> str:
    """Agrupa una calificación MUC en una familia de uso."""
    c, d = (codigo or "").upper(), _norm(descripcion)
    if c.startswith("SX") or "viari" in d:
        return "viario"
    if c.startswith("SV") or "espais lliures" in d or "zona verda" in d or "parcs" in d:
        return "espacios_libres"
    if c.startswith("SE") or "equipament" in d:
        return "equipamientos"
    if c.startswith("ST") or "serveis tecnics" in d:
        return "servicios_tecnicos"
    if c.startswith("S") and "sistem" in d:
        return "otros_sistemas"
    if "industri" in d or "logistic" in d or "activitat economica" in d or c.startswith("A"):
        # En el MUC, A1 = industrial y A2 = serveis (terciario, comercial, hotelero).
        if c.startswith("A2") or "terciari" in d or "comercial" in d or "serveis" in d:
            return "terciario"
        return "actividad_economica"
    if "terciari" in d or "comercial" in d or "hoteler" in d or "oficines" in d:
        return "terciario"
    if "mixt" in d:
        return "mixto"
    if "residencial" in d or "habitatge" in d or "nucli" in d or "eixample" in d or c.startswith("R"):
        return "residencial"
    if c.startswith("N") or "no urbanitzable" in d or "agricol" in d or "forestal" in d or "rustic" in d:
        return "no_urbanizable"
    return "otros"


# familia -> perfil -> nivel
MATRIZ = {
    #                      gasolinera      recarga         retail          industrial      residencial     terciario       energia
    "actividad_economica": dict(gasolinera="compatible", recarga="compatible", retail="condicionado", industrial="compatible",
                                residencial="incompatible", terciario="condicionado", energia="compatible"),
    "terciario": dict(gasolinera="condicionado", recarga="compatible", retail="compatible", industrial="condicionado",
                      residencial="condicionado", terciario="compatible", energia="condicionado"),
    "mixto": dict(gasolinera="condicionado", recarga="compatible", retail="compatible", industrial="condicionado",
                  residencial="compatible", terciario="compatible", energia="condicionado"),
    "residencial": dict(gasolinera="condicionado", recarga="condicionado", retail="condicionado", industrial="incompatible",
                        residencial="compatible", terciario="condicionado", energia="incompatible"),
    "viario": dict(gasolinera="condicionado", recarga="condicionado", retail="incompatible", industrial="incompatible",
                   residencial="incompatible", terciario="incompatible", energia="incompatible"),
    "servicios_tecnicos": dict(gasolinera="condicionado", recarga="condicionado", retail="incompatible", industrial="condicionado",
                               residencial="incompatible", terciario="incompatible", energia="compatible"),
    "equipamientos": dict(gasolinera="incompatible", recarga="condicionado", retail="incompatible", industrial="incompatible",
                          residencial="incompatible", terciario="condicionado", energia="incompatible"),
    "espacios_libres": dict(gasolinera="incompatible", recarga="incompatible", retail="incompatible", industrial="incompatible",
                            residencial="incompatible", terciario="incompatible", energia="incompatible"),
    "otros_sistemas": dict(gasolinera="incompatible", recarga="incompatible", retail="incompatible", industrial="incompatible",
                           residencial="incompatible", terciario="incompatible", energia="incompatible"),
    # En suelo no urbanizable, la fotovoltaica y las baterías se tramitan por proyecto de actuación específica: se condicionan, no se bloquean.
    "no_urbanizable": dict(gasolinera="plan_especial", recarga="plan_especial", retail="incompatible", industrial="incompatible",
                           residencial="incompatible", terciario="incompatible", energia="condicionado"),
    "otros": dict(gasolinera="condicionado", recarga="condicionado", retail="condicionado", industrial="condicionado",
                  residencial="condicionado", terciario="condicionado", energia="condicionado"),
}


MOTIVOS = {
    "compatible": "Uso habitualmente admitido en esta calificación.",
    "condicionado": "Puede admitirse según la normativa municipal concreta (usos, distancias, ordenanza).",
    "plan_especial": "Solo mediante plan especial urbanístico o procedimiento de proyecto de actuación específica en suelo no urbanizable.",
    "incompatible": "Calificación de sistema público o protegido: el uso no es admisible sin modificar el planeamiento.",
}

ORDEN = {"compatible": 0, "condicionado": 1, "plan_especial": 2, "incompatible": 3}

# Superficie mínima de una calificación para que cuente en el veredicto (evita astillas de borde).
PCT_MINIMO_RELEVANTE = 5.0


def evaluar(calificaciones: list[dict], clasificaciones: list[dict]) -> dict:
    """Veredicto por perfil usando la calificación dominante (mayor %) y señalando las demás."""
    relevantes = [q for q in calificaciones if q["pct"] >= PCT_MINIMO_RELEVANTE] or calificaciones[:1]
    if not relevantes:
        return {p: {"nivel": "sin_dato", "motivo": "Sin calificación en el MUC."} for p in PERFILES}

    suelo_no_urbanizable = any(c["codigo"].upper().startswith("SNU") and c["pct"] >= 50 for c in clasificaciones)
    salida = {}
    for perfil in PERFILES:
        detalle = []
        for q in relevantes:
            fam = familia(q["codigo_muc"], q["descripcion_muc"])
            if suelo_no_urbanizable and fam not in ("viario",):
                fam = "no_urbanizable" if fam in ("otros", "residencial", "actividad_economica") else fam
            detalle.append({"codigo": q["codigo_muc"], "familia": fam, "pct": q["pct"], "nivel": MATRIZ[fam][perfil]})
        dominante = max(detalle, key=lambda x: x["pct"])
        nivel = dominante["nivel"]
        # Si una parte relevante es peor que la dominante, se avisa (afecta a la implantación).
        peor = max(detalle, key=lambda x: ORDEN[x["nivel"]])
        nota = ""
        if ORDEN[peor["nivel"]] > ORDEN[nivel]:
            nota = f"El {peor['pct']}% de la parcela está calificado {peor['codigo']} ({peor['nivel']})."
        salida[perfil] = {"nivel": nivel, "motivo": MOTIVOS[nivel], "nota": nota, "detalle": detalle}
    return salida
