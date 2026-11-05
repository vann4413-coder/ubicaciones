"""Grupos de uso, usos concretos y sus parámetros de puntuación.

El usuario elige uno o varios GRUPOS; cada grupo agrupa USOS con criterios parecidos.
La nota del grupo es la del uso que mejor encaja en la parcela, y el informe dice cuál es.

Todos los valores son de partida, A VALIDAR con clientes reales. Se cambian aquí sin
tocar el resto del código.

Bloques que puntúan (0-100 cada uno):
  urbanismo      compatibilidad de la calificación con el uso (regla de compatibilidad)
  trafico        IMD de las vías cercanas (tramos por uso) y bonus por pesados
  red            capacidad de acceso del nudo eléctrico frente a la potencia que necesita el uso
  parcela        superficie frente a la ideal del uso, frente a vial, forma y línea de edificación
  inundabilidad  láminas del ACA y SNCZI
  entorno        actividad alrededor que favorece el uso (restauración, polígonos, servicios…)
"""

# Tramos de IMD reutilizables (vehículos/día -> nota)
IMD_ALTA = [(0, 15), (5_000, 40), (10_000, 65), (20_000, 85), (40_000, 100)]      # depende mucho del tráfico de paso
IMD_MEDIA = [(0, 25), (5_000, 50), (10_000, 70), (20_000, 90), (35_000, 100)]
IMD_BAJA = [(0, 50), (3_000, 70), (10_000, 90), (15_000, 100)]                     # el tráfico ayuda, pero poco
IMD_NEUTRA = [(0, 100)]                                                           # no depende del tráfico


def uso(nombre, regla, pesos, imd=IMD_MEDIA, pesados=(100.0, 0), potencia_mw=0.1, frente_m=15,
        superficie_m2=None, entorno=()):
    """entorno: [(categoria del entorno, radio m, número que da la nota máxima)]."""
    return {"nombre": nombre, "regla": regla, "pesos": pesos, "imd": imd, "pesados": pesados,
            "potencia_mw": potencia_mw, "frente_m": frente_m, "superficie_m2": superficie_m2, "entorno": list(entorno)}


def P(urbanismo, trafico, red, parcela, inundabilidad, entorno=0):
    return {"urbanismo": urbanismo, "trafico": trafico, "red": red, "parcela": parcela,
            "inundabilidad": inundabilidad, "entorno": entorno}


GRUPOS = {
    "movilidad": {
        "nombre": "Movilidad y energía",
        "usos": {
            "estacion_servicio": uso("Estación de servicio", "gasolinera", P(25, 40, 5, 20, 10), IMD_ALTA, (8.0, 10), 0.25, 30, 1500),
            "electrolinera": uso("Electrolinera", "recarga", P(20, 25, 30, 10, 10, 5), IMD_ALTA, (8.0, 5), 0.9, 15, 600,
                                 [("restauracion", 500, 5), ("supermercados", 500, 2)]),
            "lavado": uso("Lavado de vehículos", "gasolinera", P(25, 35, 5, 25, 10), IMD_MEDIA, frente_m=20, superficie_m2=1000),
            "itv_taller": uso("ITV y talleres", "industrial", P(30, 25, 5, 25, 10, 5), IMD_MEDIA, (8.0, 5), 0.2, 20, 3000,
                              [("automocion", 2000, 8)]),
            "aparcamiento": uso("Aparcamiento", "recarga", P(30, 20, 5, 25, 10, 10), IMD_MEDIA, frente_m=10, superficie_m2=2000,
                                entorno=[("restauracion", 500, 15), ("comercios", 500, 30)]),
        },
    },
    "comercio": {
        "nombre": "Comercio y restauración",
        "usos": {
            "retail": uso("Retail y medianas superficies", "retail", P(25, 30, 5, 20, 10, 10), IMD_MEDIA, potencia_mw=0.3, frente_m=25,
                          superficie_m2=3000, entorno=[("comercial", 2000, 4), ("supermercados", 2000, 6)]),
            "supermercado": uso("Supermercado", "retail", P(25, 25, 5, 20, 10, 15), IMD_MEDIA, potencia_mw=0.3, frente_m=20,
                                superficie_m2=2500, entorno=[("restauracion", 1000, 20), ("comercios", 1000, 30)]),
            "restauracion": uso("Restauración y drive-thru", "retail", P(25, 35, 5, 15, 10, 10), IMD_ALTA, frente_m=20,
                                superficie_m2=1500, entorno=[("comercial", 2000, 3), ("restauracion", 1000, 10)]),
            "centro_comercial": uso("Centro comercial", "retail", P(30, 25, 5, 20, 10, 10), IMD_ALTA, potencia_mw=1.0, frente_m=40,
                                    superficie_m2=15000, entorno=[("hoteles", 5000, 5), ("equipamientos", 5000, 3)]),
        },
    },
    "industria": {
        "nombre": "Industria y logística",
        "usos": {
            "nave_industrial": uso("Nave industrial", "industrial", P(35, 15, 15, 20, 10, 5), IMD_BAJA, (8.0, 10), 0.5, 20, 5000,
                                   [("poligonos", 2000, 2)]),
            "logistica": uso("Logística y almacén", "industrial", P(30, 25, 5, 25, 10, 5), IMD_MEDIA, (10.0, 15), 0.3, 30, 10000,
                             [("poligonos", 5000, 3), ("logistica", 5000, 5)]),
            "ultima_milla": uso("Logística de última milla", "industrial", P(30, 20, 10, 20, 10, 10), IMD_MEDIA, potencia_mw=0.3,
                                frente_m=20, superficie_m2=2000, entorno=[("comercios", 1000, 30), ("restauracion", 1000, 15)]),
            "autoalmacenaje": uso("Autoalmacenaje (trasteros)", "industrial", P(35, 20, 5, 20, 10, 10), IMD_MEDIA, frente_m=15,
                                  superficie_m2=2000, entorno=[("comercios", 1000, 20)]),
        },
    },
    "residencial": {
        "nombre": "Residencial y hotelero",
        "usos": {
            "promocion": uso("Promoción residencial", "residencial", P(45, 5, 5, 20, 15, 10), IMD_NEUTRA, frente_m=10,
                             entorno=[("supermercados", 1000, 3), ("equipamientos", 2000, 1), ("restauracion", 1000, 5)]),
            "hotel": uso("Hotel", "terciario", P(35, 20, 5, 15, 10, 15), IMD_MEDIA, potencia_mw=0.3, frente_m=15, superficie_m2=2000,
                         entorno=[("restauracion", 1000, 15), ("comercial", 5000, 3), ("poligonos", 5000, 2)]),
            "residencia": uso("Residencia (mayores, estudiantes)", "residencial", P(40, 5, 5, 20, 15, 15), IMD_NEUTRA, potencia_mw=0.2,
                              frente_m=15, superficie_m2=2500, entorno=[("equipamientos", 2000, 1), ("supermercados", 1000, 2)]),
        },
    },
    "terciario": {
        "nombre": "Terciario y equipamientos",
        "usos": {
            "oficinas": uso("Oficinas", "terciario", P(40, 15, 5, 15, 10, 15), IMD_BAJA, potencia_mw=0.2, frente_m=15,
                            entorno=[("oficinas", 1000, 20), ("restauracion", 1000, 10)]),
            "clinica": uso("Clínica o centro de salud", "terciario", P(40, 15, 5, 20, 10, 10), IMD_BAJA, potencia_mw=0.2, frente_m=15,
                           superficie_m2=1500, entorno=[("supermercados", 1000, 3), ("comercios", 1000, 20)]),
            "educacion": uso("Centro educativo", "terciario", P(40, 10, 5, 25, 10, 10), IMD_NEUTRA, frente_m=20, superficie_m2=4000,
                             entorno=[("supermercados", 1000, 3), ("restauracion", 1000, 5)]),
            "gimnasio": uso("Gimnasio", "terciario", P(35, 20, 5, 20, 10, 10), IMD_BAJA, potencia_mw=0.2, frente_m=15, superficie_m2=1500,
                            entorno=[("comercios", 1000, 20), ("restauracion", 1000, 10)]),
        },
    },
    "energia": {
        "nombre": "Energía e infraestructuras",
        "usos": {
            "fotovoltaica": uso("Fotovoltaica en suelo", "energia", P(30, 0, 35, 25, 10), IMD_NEUTRA, potencia_mw=1.0, frente_m=5,
                                superficie_m2=20000),
            "baterias": uso("Almacenamiento con baterías", "energia", P(25, 0, 45, 20, 10), IMD_NEUTRA, potencia_mw=2.0, frente_m=5,
                            superficie_m2=3000),
            "subestacion": uso("Subestación o centro de transformación", "energia", P(30, 5, 35, 20, 10), IMD_NEUTRA,
                               potencia_mw=1.0, frente_m=10, superficie_m2=2000),
        },
    },
}

ORDEN_GRUPOS = list(GRUPOS)


def nombre_grupo(g: str) -> str:
    return GRUPOS[g]["nombre"]


def catalogo() -> dict:
    """Grupos y usos para la web (sin parámetros internos)."""
    return {g: {"nombre": d["nombre"], "usos": {u: v["nombre"] for u, v in d["usos"].items()}} for g, d in GRUPOS.items()}
