"""Construye los mapas del informe: imagen WMS de fondo + SVG con las capas propias."""
from shapely.geometry import Point

from app import geo
from app.fuentes import ortofotos

PARCELA = {"trazo": "#e11d48", "relleno": "#e11d48", "opacidad": 0.12, "ancho": 3}
COLORES_CALIF = ["#2563eb", "#16a34a", "#d97706", "#9333ea", "#0891b2", "#be123c"]


def _pts(items, radio=4):
    out = []
    for it in items:
        if it.get("lon") is None:
            continue
        x, y = geo.a_utm(it["lon"], it["lat"])
        out.append(Point(x, y).buffer(radio))
    return out


def construir(inf: dict) -> dict:
    g = inf["parcela"]["geom"]
    mapas = {}

    # 1. Parcela sobre ortofoto + catastro
    m = ortofotos.mapa_base(g, 0.8, 120)
    m["svg"] = ortofotos.svg_capas(m["bbox"], m["px"], [
        {**PARCELA, "geoms": [g]},
        {"trazo": "#facc15", "relleno": "none", "ancho": 1.5, "discontinua": True,
         "geoms": [c["geom"] for c in inf["parcela"].get("colindantes", [])]},
    ])
    m["titulo"] = "Parcela y colindantes sobre ortofoto vigente"
    mapas["parcela"] = m

    # 2. Calificación urbanística
    urb = inf["urbanismo"]
    if urb.get("estado") == "ok":
        m = ortofotos.mapa_base(g, 0.4, 80)
        capas = []
        leyenda = []
        for i, q in enumerate(urb["calificaciones"]):
            color = COLORES_CALIF[i % len(COLORES_CALIF)]
            capas.append({"trazo": color, "relleno": color, "opacidad": 0.45, "ancho": 1, "geoms": [q["geom"]]})
            leyenda.append({"color": color, "texto": f"{q['codigo_municipal'] or q['codigo_muc']} · {q['descripcion_municipal'] or q['descripcion_muc']} ({q['pct']}%)"})
        capas.append({**PARCELA, "relleno": "none", "geoms": [g]})
        m["svg"] = ortofotos.svg_capas(m["bbox"], m["px"], capas)
        m["leyenda"] = leyenda
        m["titulo"] = "Calificación urbanística (MUC) dentro de la parcela"
        mapas["urbanismo"] = m

    # 3. Inundabilidad
    aca = inf["inundabilidad_aca"]
    m = ortofotos.mapa_base(g, 3.0, 300)
    capas = []
    if aca.get("estado") == "ok":
        gs = aca.get("geoms") or {}
        capas += [
            {"trazo": "#93c5fd", "relleno": "#93c5fd", "opacidad": 0.35, "ancho": 0.5, "geoms": gs.get("t500", [])},
            {"trazo": "#3b82f6", "relleno": "#3b82f6", "opacidad": 0.4, "ancho": 0.5, "geoms": gs.get("t100", [])},
            {"trazo": "#1e3a8a", "relleno": "#1e3a8a", "opacidad": 0.5, "ancho": 1, "geoms": gs.get("zfp", [])},
        ]
    le = (inf["trafico"].get("accesos") or {}).get("linea_edificacion")
    if le and not le["geom"].is_empty:
        capas.append({"trazo": "#f97316", "relleno": "#f97316", "opacidad": 0.35, "ancho": 1, "discontinua": True, "geoms": [le["geom"]]})
    capas.append({**PARCELA, "geoms": [g]})
    m["svg"] = ortofotos.svg_capas(m["bbox"], m["px"], capas)
    m["leyenda"] = [{"color": "#1e3a8a", "texto": "Zona de flujo preferente"}, {"color": "#3b82f6", "texto": "Inundable T100"},
                    {"color": "#93c5fd", "texto": "Inundable T500"}, {"color": "#f97316", "texto": "Franja de línea límite de edificación"}]
    m["titulo"] = "Inundabilidad (ACA) y afecciones de carreteras"
    mapas["inundabilidad"] = m

    # 4. Tráfico, red y entorno (1 km)
    m = ortofotos.mapa_base(g, 0.0, 2200)
    traf = inf["trafico"]
    entorno = inf["entorno"] if inf["entorno"].get("estado") == "ok" else {}
    gas = inf["gasolineras"].get("estaciones", []) if inf["gasolineras"].get("estado") == "ok" else []
    nudos = inf["red"].get("nudos", []) if inf["red"].get("estado") == "ok" else []
    capas = [
        {"trazo": "#f59e0b", "relleno": "none", "ancho": 5, "opacidad": 0, "geoms": [t["geom"] for t in traf.get("tramos", [])]},
        {"trazo": "#fff", "relleno": "#64748b", "opacidad": 0.9, "ancho": 1, "geoms": _pts([p for p in entorno.get("pois", []) if p["grupo"] != "Gasolineras"], 9)},
        {"trazo": "#fff", "relleno": "#dc2626", "opacidad": 1, "ancho": 1.5, "geoms": _pts(gas, 18)},
        {"trazo": "#fff", "relleno": "#7c3aed", "opacidad": 1, "ancho": 1.5, "geoms": _pts(nudos, 22)},
        {"trazo": "#e11d48", "relleno": "#e11d48", "opacidad": 0.6, "ancho": 3, "geoms": [g.buffer(8)]},
        {"trazo": "#e11d48", "relleno": "none", "ancho": 1.5, "discontinua": True, "opacidad": 0, "geoms": [g.centroid.buffer(500).exterior, g.centroid.buffer(1000).exterior]},
    ]
    m["svg"] = ortofotos.svg_capas(m["bbox"], m["px"], capas)
    m["leyenda"] = [{"color": "#f59e0b", "texto": "Tramos con aforo (IMD)"}, {"color": "#dc2626", "texto": "Gasolineras"},
                    {"color": "#7c3aed", "texto": "Nudos eléctricos"}, {"color": "#64748b", "texto": "Negocios y servicios"},
                    {"color": "#e11d48", "texto": "Parcela; círculos de 500 m y 1 km"}]
    m["titulo"] = "Tráfico, red eléctrica y entorno (radio 1 km)"
    mapas["entorno"] = m

    # 5. Evolución histórica: SVG de la parcela para superponer en cada ortofoto
    evo = inf["evolucion"]
    evo["svg"] = ortofotos.svg_capas(evo["bbox"], 600, [{**PARCELA, "relleno": "none", "geoms": [g]}])
    return mapas
