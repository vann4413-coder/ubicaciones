"""Parámetros de puntuación por perfil de cliente.

Los umbrales de IMD y la potencia objetivo son valores de partida A VALIDAR con
clientes reales. Se cambian aquí sin tocar el resto del código.
"""

PESOS = {
    #              urbanismo trafico red parcela inundabilidad
    "gasolinera": {"urbanismo": 25, "trafico": 40, "red": 5, "parcela": 20, "inundabilidad": 10},
    "recarga": {"urbanismo": 20, "trafico": 25, "red": 35, "parcela": 10, "inundabilidad": 10},
    "retail": {"urbanismo": 25, "trafico": 35, "red": 10, "parcela": 20, "inundabilidad": 10},
    "promotor": {"urbanismo": 45, "trafico": 5, "red": 5, "parcela": 25, "inundabilidad": 20},
}

# Tramos de IMD (vehículos/día) -> nota. Se usa la IMD máxima a menos de 500 m;
# la de 500 m–1 km cuenta al 70 %.
TRAMOS_IMD = {
    "gasolinera": [(0, 15), (5_000, 40), (10_000, 65), (20_000, 85), (40_000, 100)],
    "recarga": [(0, 20), (5_000, 45), (10_000, 70), (25_000, 90), (50_000, 100)],
    "retail": [(0, 15), (5_000, 45), (10_000, 70), (20_000, 90), (35_000, 100)],
    "promotor": [(0, 50), (5_000, 70), (15_000, 100)],
}

# Bonus por % de vehículos pesados (relevante para gasóleo y para recarga de flotas).
BONUS_PESADOS = {"gasolinera": (8.0, 10), "recarga": (8.0, 5), "retail": (10.0, 0), "promotor": (100.0, 0)}

# Potencia objetivo por defecto para la nota de red (MW). Hub tipo: 6 cargadores de 150 kW.
POTENCIA_OBJETIVO_MW = {"gasolinera": 0.25, "recarga": 0.9, "retail": 0.3, "promotor": 0.5}

# Frente mínimo a vial deseable (m) para la nota de parcela.
FRENTE_DESEABLE_M = {"gasolinera": 30, "recarga": 15, "retail": 20, "promotor": 10}
