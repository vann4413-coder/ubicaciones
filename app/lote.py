"""Verificación de suelo por lotes («Analiza tu lista» del Agente 360, para clientes y administración).

Se sube un Excel con una pestaña que tenga columnas LATITUD y LONGITUD, REFERENCIA CATASTRAL o DIRECCIÓN y,
en segundo plano y despacio para no saturar al Catastro, se añade a cada fila: referencia catastral,
superficies, uso, año, clasificación y calificación urbanística, compatibilidad con gasolinera,
parcela mínima de la zona, segregación e inundabilidad. Al terminar se descarga el mismo Excel ampliado.
"""
import asyncio
import json
import logging
import time
import unicodedata
import uuid

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app import config, geo
from app.fuentes import catastro, geocoder

log = logging.getLogger(__name__)
DIR = config.DATOS_DIR / "lotes"
PAUSA_S = 3
_tareas: dict[str, asyncio.Task] = {}
_turno = asyncio.Lock()  # una sola consulta a la vez entre todos los lotes: el Catastro limita por IP


# ------------------------------------------------------------------ ficha de una ubicación

async def ficha(e: dict) -> dict:
    """Verificación resumida de una ubicación: catastro, urbanismo, PGOU e inundabilidad (ACA)."""
    from app.informe import generar
    from app.fuentes import inundabilidad, pgou, urbanismo
    sal = {"id": e.get("id")}
    try:
        rc = (e.get("rc") or "").strip().upper()[:14]
        if not rc and "lat" not in e and e.get("dir"):
            cands = await geocoder.buscar(e["dir"])
            if not cands:
                return {**sal, "error": f"No se encuentra la dirección «{e['dir']}»"}
            e = {**e, "lon": cands[0]["lon"], "lat": cands[0]["lat"]}
            rc = (cands[0].get("rc") or "")[:14]
            sal["ubicada_por"] = cands[0].get("etiqueta") or e["dir"]
        if not rc:
            cands = await catastro.rc_cercana(float(e["lon"]), float(e["lat"]))
            if not cands:
                return {**sal, "error": "Sin parcela catastral junto al punto"}
            rc = cands[0]["rc"]
            sal["dist_punto_m"] = cands[0].get("distancia_m")
        p = await catastro.consultar(rc)
        if p.get("estado") != "ok":
            return {**sal, "rc": rc, "error": p.get("mensaje", "Catastro sin datos")}
        g = p["geom"]
        lon, lat = geo.a_wgs84(g.centroid.x, g.centroid.y)
        muni = await geocoder.municipio_en_punto(lon, lat) or {}
        cod_ine = muni.get("codigo_ine") or (p.get("cod_ine_prov", "") + p.get("cod_ine_mun", ""))
        urb = await urbanismo.consultar(g)
        aca = await inundabilidad.consultar_aca(g)
        pg = None
        if urb.get("estado") == "ok":
            pg = pgou.consultar(cod_ine, urb.get("calificaciones"))
            if pg:
                principal = max((f for f in pg["zonas"] if f["zona"]), key=lambda f: f["pct"] or 0, default=None)
                pg["segregacion"] = pgou.segregacion(principal["zona"] if principal else None, p.get("sup_grafica"), None)
        sal.update({
            "rc": rc, "direccion_catastro": p.get("direccion"), "clase": p.get("clase"), "uso": p.get("uso"),
            "sup_parcela": p.get("sup_grafica"), "sup_construida": p.get("sup_construida"), "anio": p.get("anio_construccion"),
            "num_inmuebles": p.get("num_inmuebles"), "cod_ine": cod_ine,
            "urbanismo": generar.para_json({k: urb.get(k) for k in ("estado", "mensaje", "calificaciones", "clasificaciones",
                                                                     "sectores", "compatibilidad", "plan_general")}),
            "pgou": generar.para_json(pg),
            "aca": {k: aca.get(k) for k in ("estado", "mensaje", "zfp_pct", "t10_pct", "t100_pct", "t500_pct", "distancia_dph_m")},
        })
        return sal
    except Exception as ex:  # noqa: BLE001
        log.exception("Ficha de lote %s", e)
        return {**sal, "error": f"{type(ex).__name__}: {ex}"}


def _bloqueo(r: dict) -> bool:
    t = (r.get("error") or "") + " " + ((r.get("urbanismo") or {}).get("mensaje") or "")
    return any(k in t for k in ("403", "429", "Forbidden", "no responde", "Timeout", "tiempo"))


# ------------------------------------------------------------------ lectura del Excel de entrada

def _norm(t) -> str:
    t = "".join(c for c in unicodedata.normalize("NFD", str(t or "").upper()) if unicodedata.category(c) != "Mn")
    return " ".join(t.split())


def _cabecera(ws):
    """Fila de cabecera y columnas de latitud, longitud y referencia catastral."""
    for fila in range(1, min(ws.max_row, 15) + 1):
        cols = {}
        for c in range(1, ws.max_column + 1):
            h = _norm(ws.cell(fila, c).value)
            if h.startswith("LATITUD"):
                cols.setdefault("lat", c)
            elif h.startswith("LONGITUD"):
                cols.setdefault("lon", c)
            elif "REFERENCIA CATASTRAL" in h or h in ("RC", "REF. CATASTRAL", "REF CATASTRAL"):
                cols.setdefault("rc", c)
            elif (h.startswith("DIRECCION") or h.startswith("ADRECA") or h == "DOMICILIO") and "CATASTRAL" not in h:
                cols.setdefault("dir", c)
            elif h in ("MUNICIPIO", "MUNICIPI", "POBLACION", "LOCALIDAD", "POBLACIO", "CIUDAD"):
                cols.setdefault("mun", c)
        if ("lat" in cols and "lon" in cols) or "rc" in cols or "dir" in cols:
            return fila, cols
    return None, {}


def leer_ubicaciones(ruta) -> tuple[str, int, list[dict]]:
    wb = load_workbook(ruta, read_only=False, data_only=True)
    for ws in wb.worksheets:
        fila_cab, cols = _cabecera(ws)
        if not fila_cab:
            continue
        salida = []
        for f in range(fila_cab + 1, ws.max_row + 1):
            e = {"id": f}
            try:
                if "lat" in cols:
                    lat, lon = ws.cell(f, cols["lat"]).value, ws.cell(f, cols["lon"]).value
                    if lat not in (None, "") and lon not in (None, ""):
                        e["lat"], e["lon"] = float(str(lat).replace(",", ".")), float(str(lon).replace(",", "."))
                if "rc" in cols:
                    rc = catastro.normalizar_rc(str(ws.cell(f, cols["rc"]).value or ""))
                    if rc:
                        e["rc"] = rc[:14]
                if "dir" in cols and "lat" not in e and "rc" not in e:
                    d = str(ws.cell(f, cols["dir"]).value or "").strip()
                    m = str(ws.cell(f, cols["mun"]).value or "").strip() if "mun" in cols else ""
                    if d:
                        e["dir"] = f"{d}, {m}" if m and m.lower() not in d.lower() else d
            except ValueError:
                pass
            if "lat" in e or "rc" in e or "dir" in e:
                salida.append(e)
        if salida:
            return ws.title, fila_cab, salida
    raise ValueError("No encuentro ninguna pestaña con columnas LATITUD y LONGITUD, REFERENCIA CATASTRAL o DIRECCIÓN. Descarga la plantilla y copia tus ubicaciones en ella.")


# ------------------------------------------------------------------ escritura del Excel de salida

CAB = ["REF. CATASTRAL", "DIST. PUNTO A PARCELA (m)", "DIRECCIÓN CATASTRAL", "USO CATASTRAL", "SUP. PARCELA (m²)",
       "SUP. CONSTRUIDA (m²)", "AÑO CONSTRUCCIÓN", "Nº INMUEBLES", "CLASIFICACIÓN DEL SUELO", "CALIFICACIÓN URBANÍSTICA",
       "USOS ADMITIDOS EN LA ZONA (orientativo)", "COMPATIBILIDAD GASOLINERA", "PARCELA MÍNIMA DE LA ZONA", "PARCELA MÍNIMA PARA GASOLINERA", "¿CUMPLE PARCELA MÍNIMA?", "¿SEGREGABLE?",
       "FLUJO PREFERENTE (%)", "INUNDABLE T100 / T500 (%)", "OBSERVACIONES SUELO"]
ANCHO = [17, 11, 32, 16, 11, 11, 9, 9, 24, 44, 40, 30, 24, 26, 12, 32, 11, 13, 70]
NIVEL = {"compatible": ("Compatible", "verde"), "condicionado": ("Condicionado (normativa municipal)", "ambar"),
         "plan_especial": ("Solo con plan especial (suelo no urbanizable)", "rojo"), "incompatible": ("No compatible", "rojo")}
RELLENO = {"verde": "D1FADF", "ambar": "FEF0C7", "rojo": "FEE4E2"}


def _r(v, d=0):
    if v is None or v == "":
        return None
    return round(v, d) if d else int(round(v))


def _agrupa(lista, con_codigo: bool) -> str:
    m: dict[str, float] = {}
    for x in lista or []:
        k = ((x.get("codigo_municipal") or "") + " " if con_codigo else "") + (x.get("descripcion_municipal") or x.get("descripcion") or "")
        m[k.strip()] = m.get(k.strip(), 0) + (x.get("pct") or 0)
    orden = sorted(((k, v) for k, v in m.items() if v >= 1), key=lambda kv: -kv[1])
    return "; ".join(f"{k} ({v:.0f} %)" for k, v in orden[:5])


def _usos(z: dict) -> str | None:
    """Usos que admite y que excluye la zona principal según su normativa (lectura orientativa)."""
    from app.normativa import que_se_puede
    si, no = que_se_puede(z)
    partes = []
    if si:
        partes.append("Sí: " + ", ".join(si))
    if no:
        partes.append("No: " + ", ".join(no))
    return ". ".join(partes) or (z.get("usos") or None)


def fila_resultado(r: dict) -> tuple[list, dict]:
    vals, col = [None] * len(CAB), {}
    if r.get("error"):
        vals[0], vals[-1] = r.get("rc"), f"Sin datos: {r['error']}"
        return vals, col
    u, pg, aca = r.get("urbanismo") or {}, r.get("pgou") or {}, r.get("aca") or {}
    sup = r.get("sup_parcela")
    obs = []
    comp = (u.get("compatibilidad") or {}).get("gasolinera") or {}
    txt, c = NIVEL.get(comp.get("nivel"), (comp.get("nivel") or u.get("mensaje") or "Sin datos", None))
    zonas = [z for z in (pg.get("zonas") or []) if z.get("zona")]
    principal = max(zonas, key=lambda z: z.get("pct") or 0) if zonas else None
    z = (principal or {}).get("zona") or {}
    pm = z.get("parcela_minima_m2")
    if pm:
        pm_txt = f"{pm:,.0f} m²".replace(",", ".") + f" (zona {principal['clave_parcela']})"
        cumple = "Sí" if sup and sup >= pm else "NO"
        if cumple == "NO":
            obs.append(f"Parcela ({_r(sup)} m²) menor que la mínima de la zona ({pm} m²): verificar licencia y obras admitidas.")
    elif pg:
        pm_txt, cumple = "No fijada en la zona", "—"
        if z.get("otros"):
            obs.append(f"Zona {principal['clave_parcela']}: {z['otros']}")
    else:
        pm_txt, cumple = "Normativa municipal no cargada", "—"
    g = (z.get("gasolinera") if z else None) or (pg.get("gasolinera") if pg else None) or {}
    if g.get("parcela_minima_m2"):
        pmg = g["parcela_minima_m2"]
        g_txt = f"{pmg:,.0f} m²".replace(",", ".") + (" (distinta de la de la zona)" if pm and pm != pmg else "")
        if sup and sup < pmg:
            cumple = "NO"
            obs.append(f"Para gasolinera el plan exige {pmg:,.0f} m²".replace(",", ".") + f" y la parcela tiene {_r(sup)} m².")
        elif cumple == "—" and sup:
            cumple = "Sí"
    elif g.get("superficie_maxima_m2"):
        g_txt = f"Sin mínima; estación de {g['superficie_maxima_m2']:,.0f} m² como máximo".replace(",", ".")
    elif pg:
        g_txt = "No fija una específica: rige la de la zona"
    else:
        g_txt = "—"
    if g.get("condiciones"):
        obs.append("Gasolinera: " + g["condiciones"])
    zfp = aca.get("zfp_pct") or 0
    if zfp:
        obs.append("Parte de la parcela en zona de flujo preferente: no se autorizan nuevas gasolineras en esa parte.")
    if comp.get("nota"):
        obs.append(comp["nota"])
    if r.get("ubicada_por"):
        obs.append(f"Ubicada a partir de la dirección ({r['ubicada_por']}): confirmar que es la parcela correcta.")
    if r.get("dist_punto_m"):
        obs.append(f"El punto de origen cae fuera de parcela; se ha tomado la más cercana (a {_r(r['dist_punto_m'])} m): confirmar.")
    if (r.get("num_inmuebles") or 0) > 1:
        obs.append(f"Finca con {r['num_inmuebles']} inmuebles: la estación puede ocupar solo una parte.")
    if sup and sup > 15000:
        obs.append("Parcela muy grande: probablemente la estación ocupa solo una parte (centro comercial, polígono…).")
    vals = [r.get("rc"), _r(r.get("dist_punto_m")) or 0, r.get("direccion_catastro"), r.get("uso"), _r(sup),
            _r(r.get("sup_construida")), r.get("anio"), r.get("num_inmuebles"), _agrupa(u.get("clasificaciones"), False),
            _agrupa(u.get("calificaciones"), True) or u.get("mensaje"), _usos(z) if z else None, txt, pm_txt, g_txt, cumple,
            (pg.get("segregacion") or {}).get("texto") if pg else None, _r(zfp, 1),
            f"{_r(aca.get('t100_pct') or 0, 1)} / {_r(aca.get('t500_pct') or 0, 1)}" if aca.get("estado") == "ok" else "Sin dato",
            " ".join(obs) or None]
    if c:
        col[11] = c
    if cumple in ("Sí", "NO"):
        col[14] = "verde" if cumple == "Sí" else "rojo"
    if zfp:
        col[16] = "rojo"
    return vals, col


def escribir(entrada, salida, hoja: str, fila_cab: int, resultados: dict) -> None:
    wb = load_workbook(entrada)
    ws = wb[hoja]
    c0 = ws.max_column + 1
    for i, (h, w) in enumerate(zip(CAB, ANCHO)):
        c = ws.cell(fila_cab, c0 + i, h)
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F3A5F")
        c.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(c0 + i)].width = w
    for fila, r in resultados.items():
        vals, col = fila_resultado(r)
        for i, v in enumerate(vals):
            c = ws.cell(int(fila), c0 + i, v)
            c.alignment = Alignment(wrap_text=i in (2, 8, 9, 10, 11, 12, 13, 15, 18), vertical="top")
            if i in col:
                c.fill = PatternFill("solid", fgColor=RELLENO[col[i]])
    nota = ws.cell(fila_cab, c0 + len(CAB) + 1, f"Verificación de suelo generada el {time.strftime('%d/%m/%Y')} con datos públicos: "
                   "Catastro, Mapa Urbanístic de Catalunya, normas urbanísticas municipales y ACA. Orientativo: confirmar con "
                   "cédula urbanística y nota simple.")
    nota.font = Font(italic=True, size=8, color="667085")
    wb.save(salida)


# ------------------------------------------------------------------ trabajos en segundo plano

def _estado(id_: str) -> dict:
    f = DIR / id_ / "estado.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def _guardar(id_: str, estado: dict, resultados: dict | None = None) -> None:
    d = DIR / id_
    (d / "estado.json").write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
    if resultados is not None:
        (d / "resultados.json").write_text(json.dumps(resultados, ensure_ascii=False), encoding="utf-8")


def lista(usuario_id: int | None = None) -> list[dict]:
    """Todos los lotes (administración) o solo los de un usuario."""
    if not DIR.exists():
        return []
    salida = [{"id": d.name, **_estado(d.name)} for d in DIR.iterdir() if d.is_dir()]
    if usuario_id is not None:
        salida = [e for e in salida if e.get("usuario_id") == usuario_id]
    return sorted(salida, key=lambda e: e.get("creado", ""), reverse=True)


def ubicaciones_usadas(usuario_id: int, mes: str | None = None) -> int:
    """Ubicaciones enviadas por un usuario (en un mes «AAAA-MM» o en total)."""
    return sum(e.get("total") or 0 for e in lista(usuario_id)
               if e.get("modo", "incluida") == "incluida" and (not mes or (e.get("creado") or "").startswith(mes)))


def lista_por_id(id_: str) -> dict:
    return _estado(id_)


MAX_FILAS = 1000


def crear(nombre: str, contenido: bytes, usuario: dict | None = None, maximo: int | None = None,
          pendiente_pago: bool = False) -> str:
    """Guarda el Excel y lanza el proceso. Con «maximo» solo se analizan las primeras filas.

    Con «pendiente_pago» se guarda entera sin lanzarla: espera a que se pague (lista suelta) o a que el
    cliente elija analizar solo lo que le cubre su plan (ver activar).
    """
    import shutil
    id_ = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    d = DIR / id_
    d.mkdir(parents=True)
    try:
        (d / "entrada.xlsx").write_bytes(contenido)
        hoja, fila_cab, ubic = leer_ubicaciones(d / "entrada.xlsx")
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise
    en_fichero = len(ubic)
    tope = min(MAX_FILAS, maximo if maximo is not None else MAX_FILAS)
    ubic = ubic[:max(0, tope)]
    (d / "ubicaciones.json").write_text(json.dumps(ubic), encoding="utf-8")
    est = {"nombre": nombre, "hoja": hoja, "fila_cab": fila_cab, "total": len(ubic), "en_fichero": en_fichero,
           "hechos": 0, "errores": 0, "situacion": "en cola", "creado": time.strftime("%Y-%m-%d %H:%M")}
    if usuario:
        est.update(usuario_id=usuario["id"], email=usuario.get("email"))
    if pendiente_pago:
        est.update(situacion="pendiente de pago", modo="pendiente")
        _guardar(id_, est, {})
        return id_
    est["modo"] = "incluida"
    _guardar(id_, est, {})
    lanzar(id_)
    return id_


def activar(id_: str, pagada: bool = False, maximo: int | None = None) -> bool:
    """Lanza una lista pendiente: pagada (entera) o recortada a las ubicaciones incluidas en el plan."""
    d = DIR / id_
    est = _estado(id_)
    if not est or est.get("modo") != "pendiente":
        return False
    if not pagada:
        ubic = json.loads((d / "ubicaciones.json").read_text(encoding="utf-8"))[:max(0, maximo or 0)]
        if not ubic:
            return False
        (d / "ubicaciones.json").write_text(json.dumps(ubic), encoding="utf-8")
        est["total"] = len(ubic)
    est.update(modo="pagada" if pagada else "incluida", situacion="en cola")
    _guardar(id_, est)
    lanzar(id_)
    return True


def lanzar(id_: str) -> None:
    if id_ in _tareas and not _tareas[id_].done():
        return
    _tareas[id_] = asyncio.create_task(_procesar(id_))


async def _procesar(id_: str) -> None:
    d = DIR / id_
    est = _estado(id_)
    ubic = json.loads((d / "ubicaciones.json").read_text(encoding="utf-8"))
    res = json.loads((d / "resultados.json").read_text(encoding="utf-8")) if (d / "resultados.json").exists() else {}
    pend = [e for e in ubic if str(e["id"]) not in res or res[str(e["id"])].get("error")]
    est["situacion"] = "procesando"
    _guardar(id_, est)
    espera = PAUSA_S
    for i, e in enumerate(pend):
        for intento in range(6):
            if not (d / "estado.json").exists():
                return  # lote borrado
            try:
                async with _turno:
                    r = await asyncio.wait_for(ficha(e), 150)
            except asyncio.TimeoutError:
                r = {"id": e["id"], "error": "Tiempo agotado"}
            if not _bloqueo(r):
                espera = max(PAUSA_S, espera * 0.8)
                break
            espera = min(300, max(60, espera * 2))  # el Catastro limita: se frena y se reintenta
            est["situacion"] = f"servicio saturado, reintento en {int(espera)} s"
            _guardar(id_, est)
            await asyncio.sleep(espera)
        res[str(e["id"])] = r
        est.update(hechos=sum(1 for x in res.values() if not x.get("error")), errores=sum(1 for x in res.values() if x.get("error")),
                   situacion=f"procesando ({len(res)}/{est['total']})")
        _guardar(id_, est, res)
        await asyncio.sleep(espera)
    escribir(d / "entrada.xlsx", d / "salida.xlsx", est["hoja"], est["fila_cab"], res)
    est["situacion"] = "terminado"
    est["terminado"] = time.strftime("%Y-%m-%d %H:%M")
    _guardar(id_, est)
    if est.get("email") and not est.get("avisado"):
        from app import correo
        if await correo.enviar_aviso_lista(est["email"], est.get("nombre") or "tu lista", est["total"]):
            est["avisado"] = True
            _guardar(id_, est)


def reanudar_pendientes() -> None:
    for e in lista():
        if e.get("situacion") not in ("terminado", "pendiente de pago"):
            lanzar(e["id"])


def borrar(id_: str) -> None:
    """Detiene y elimina un lote."""
    import shutil
    t = _tareas.pop(id_, None)
    if t and not t.done():
        t.cancel()
    d = DIR / id_
    if d.is_dir() and d.parent == DIR:
        shutil.rmtree(d, ignore_errors=True)


def fichero_salida(id_: str):
    f = DIR / id_ / "salida.xlsx"
    return f if f.exists() and "/" not in id_ and ".." not in id_ else None


def regenerar(id_: str):
    """Escribe el Excel con lo que haya hasta ahora (para descargar un parcial)."""
    d = DIR / id_
    est = _estado(id_)
    res = json.loads((d / "resultados.json").read_text(encoding="utf-8"))
    escribir(d / "entrada.xlsx", d / "parcial.xlsx", est["hoja"], est["fila_cab"], res)
    return d / "parcial.xlsx"
