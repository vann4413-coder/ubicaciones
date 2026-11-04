"""Construye los mapas del informe: imagen WMS de fondo + SVG con las capas propias."""
from shapely.geometry import Point

from statistics import median

from app import config, geo
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


COLOR_GRUPO = {"marca": "#3f5f9e", "independiente": "#1f8a70", "supermercado": "#8a4b8f"}
NOMBRE_GRUPO = {"marca": "Grandes marcas", "independiente": "Independientes y low cost", "supermercado": "Supermercados"}


def _posicion(b: tuple, lon: float, lat: float) -> tuple[float, float] | None:
    """Posición en % dentro del encuadre (para marcadores HTML sobre la imagen)."""
    x, y = geo.a_utm(lon, lat)
    minx, miny, maxx, maxy = b
    if not (minx <= x <= maxx and miny <= y <= maxy):
        return None
    return round((x - minx) / (maxx - minx) * 100, 2), round((maxy - y) / (maxy - miny) * 100, 2)


def competencia(inf: dict) -> dict:
    """Resumen de la competencia en 2 km: número por tipo, precios y la más cercana."""
    gs = inf["gasolineras"]
    if gs.get("estado") != "ok":
        return {"estado": gs.get("estado"), "mensaje": gs.get("mensaje")}
    todas = gs.get("estaciones", [])  # hasta 5 km (para el mapa de entorno)
    est = [e for e in todas if e["distancia_m"] <= 2000]
    precios = [e["gasoleo_a"] for e in est if e.get("gasoleo_a")]
    por_radio = {r: sum(1 for e in todas if e["distancia_m"] <= r) for r in (500, 1000, 2000, 5000)}
    por_grupo = {k: sum(1 for e in est if e.get("grupo") == k) for k in COLOR_GRUPO}
    mas_barata = min((e for e in est if e.get("gasoleo_a")), key=lambda e: e["gasoleo_a"], default=None)
    return {"estado": "ok", "total": len(est), "estaciones": est, "por_radio": por_radio, "por_grupo": por_grupo,
            "mediana_gasoleo": round(median(precios), 3) if precios else None,
            "min_gasoleo": min(precios) if precios else None, "max_gasoleo": max(precios) if precios else None,
            "mas_cercana": est[0] if est else None, "mas_barata": mas_barata,
            "colores": COLOR_GRUPO, "nombres": NOMBRE_GRUPO}


def construir(inf: dict) -> dict:
    g = inf["parcela"]["geom"]
    mapas = {}

    # 0. Portada: ortofoto con calles y nombres, con contexto alrededor
    b = ortofotos.encuadre(g, 2.5, 250)
    mapas["portada"] = {"bbox": b, "orto": ortofotos.url_wms(config.ICGC_BASE_WMS, "orto-hibrida", b, 1000), "px": 1000,
                        "svg": ortofotos.svg_capas(b, 1000, [{**PARCELA, "opacidad": 0.25, "ancho": 4, "geoms": [g]}])}

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

    # 4. Competencia, tráfico y red (radios de 500 m, 1 km y 2 km)
    m = ortofotos.mapa_base(g, 0.0, 4400)
    m["orto"] = ortofotos.url_wms(config.ICGC_BASE_WMS, "orto-hibrida", m["bbox"], m["px"])
    traf = inf["trafico"]
    entorno = inf["entorno"] if inf["entorno"].get("estado") == "ok" else {}
    gas = inf["gasolineras"].get("estaciones", []) if inf["gasolineras"].get("estado") == "ok" else []
    nudos = inf["red"].get("nudos", []) if inf["red"].get("estado") == "ok" else []
    capas = [
        {"trazo": "#f59e0b", "relleno": "none", "ancho": 5, "opacidad": 0, "geoms": [t["geom"] for t in traf.get("tramos", [])]},
        {"trazo": "#fff", "relleno": "#64748b", "opacidad": 0.9, "ancho": 1, "geoms": _pts([p for p in entorno.get("pois", []) if p["grupo"] != "Gasolineras"], 9)},
        {"trazo": "#fff", "relleno": "#7c3aed", "opacidad": 1, "ancho": 1.5, "geoms": _pts(nudos, 22)},
        {"trazo": "#e11d48", "relleno": "#e11d48", "opacidad": 0.6, "ancho": 3, "geoms": [g.buffer(8)]},
        {"trazo": "#ffffff", "relleno": "none", "ancho": 3, "discontinua": True, "opacidad": 0, "geoms": [g.centroid.buffer(500).exterior, g.centroid.buffer(1000).exterior, g.centroid.buffer(2000).exterior]},
    ]
    # Gasolineras como marcadores numerados (el número coincide con la tabla del informe)
    m["marcas"] = []
    for i, e in enumerate(gas, 1):
        pos = _posicion(m["bbox"], e["lon"], e["lat"])
        if pos:
            m["marcas"].append({"n": i, "x": pos[0], "y": pos[1], "color": COLOR_GRUPO.get(e.get("grupo"), "#1f8a70")})
    cx, cy = g.centroid.x, g.centroid.y
    minx, miny, maxx, maxy = m["bbox"]
    m["radios"] = [{"texto": t, "x": round((cx - minx) / (maxx - minx) * 100, 2), "y": round((maxy - (cy + r)) / (maxy - miny) * 100, 2)}
                   for r, t in ((500, "500 m"), (1000, "1 km"), (2000, "2 km"))]
    m["svg"] = ortofotos.svg_capas(m["bbox"], m["px"], capas)
    m["leyenda"] = [{"color": c, "texto": NOMBRE_GRUPO[k]} for k, c in COLOR_GRUPO.items()] + [
                    {"color": "#f59e0b", "texto": "Tramos con aforo (IMD)"}, {"color": "#7c3aed", "texto": "Nudos eléctricos"},
                    {"color": "#64748b", "texto": "Negocios y servicios"}, {"color": "#e11d48", "texto": "Parcela"}]
    m["titulo"] = "Competencia, tráfico y red eléctrica (radios de 500 m, 1 km y 2 km)"
    mapas["entorno"] = m

    # 4b. Entorno en 5 km: actividad por categorías y polígonos industriales
    e5 = inf.get("entorno5") or {}
    if e5.get("estado") == "ok":
        radio = e5.get("radio_m", 5000)
        m = ortofotos.mapa_base(g, 0.0, radio * 2 + 400, px=1000)
        m["orto"] = ortofotos.url_wms(config.ICGC_BASE_WMS, "topografic-gris", m["bbox"], m["px"])
        from app.fuentes.entorno import CATEGORIAS
        capas = [{"trazo": "#9575cd", "relleno": "#9575cd", "opacidad": 0.35, "ancho": 1, "geoms": [z["geom"] for z in e5.get("zonas_industriales", [])]}]
        for clave, (nombre, color, _, _, _) in CATEGORIAS.items():
            if clave in ("comercios", "oficinas"):
                continue
            pts = [p for p in e5.get("puntos", []) if p["cat"] == clave]
            if clave == "gasolineras" and gas:  # con dato del Ministerio, mejor que OSM
                pts = gas
            capas.append({"trazo": "#fff", "relleno": color, "opacidad": 1, "ancho": 1, "geoms": _pts(pts, 28)})
        capas += [
            {"trazo": "#12355b", "relleno": "none", "ancho": 2, "discontinua": True, "opacidad": 0,
             "geoms": [g.centroid.buffer(r).exterior for r in (1000, 2000, 5000) if r <= radio]},
            {"trazo": "#e11d48", "relleno": "#e11d48", "opacidad": 0.9, "ancho": 2, "geoms": [g.centroid.buffer(45)]},
        ]
        m["svg"] = ortofotos.svg_capas(m["bbox"], m["px"], capas)
        cx, cy = g.centroid.x, g.centroid.y
        minx, miny, maxx, maxy = m["bbox"]
        m["radios"] = [{"texto": t, "x": round((cx - minx) / (maxx - minx) * 100, 2), "y": round((maxy - (cy + r)) / (maxy - miny) * 100, 2)}
                       for r, t in ((1000, "1 km"), (2000, "2 km"), (5000, "5 km")) if r <= radio]
        m["leyenda"] = [{"color": c[1], "texto": c[0]} for k, c in CATEGORIAS.items() if k not in ("comercios", "oficinas")] + [
            {"color": "#9575cd", "texto": "Suelo industrial"}]
        mapas["entorno5"] = m

    # 5. Evolución histórica: SVG de la parcela para superponer en cada ortofoto
    evo = inf["evolucion"]
    evo["svg"] = ortofotos.svg_capas(evo["bbox"], 600, [{**PARCELA, "relleno": "none", "geoms": [g]}])
    return mapas
