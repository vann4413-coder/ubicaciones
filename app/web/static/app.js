/* Herramienta: mapa tipo Google Maps (MapLibre + OpenFreeMap), búsqueda de parcela,
   informe en pantalla y entorno de 5 km por categorías. */
const $ = (id) => document.getElementById(id);
const fmt = (n, d = 0) => n == null ? "—" : Number(n).toLocaleString("es-ES", { maximumFractionDigits: d, minimumFractionDigits: d });
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const vacio = () => ({ type: "FeatureCollection", features: [] });
const wms = (base, capa, fmtImg = "image/jpeg", transp = false) =>
  `${base}?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=${capa}&STYLES=&SRS=EPSG:3857&BBOX={bbox-epsg-3857}&WIDTH=256&HEIGHT=256&FORMAT=${fmtImg}${transp ? "&TRANSPARENT=TRUE" : ""}`;
const ICGC = "https://geoserveis.icgc.cat/servei/catalunya/mapa-base/wms";

// Iconos (mismos trazos que el informe): se dibujan en blanco sobre un círculo del color de la categoría.
const TRAZOS = {
  competencia: "M4 21V5a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v16 M3 21h12 M6 8h6 M14 10h2a2 2 0 0 1 2 2v4a1.5 1.5 0 0 0 3 0V8l-3-3",
  red: "M13 2L4 14h7l-1 8 9-12h-7z",
  restauracion: "M7 3v8 M4 3v5a3 3 0 0 0 6 0V3 M7 11v10 M17 3c-2 2-3 5-3 8h3v10",
  hotel: "M3 20V6 M3 14h18v6 M21 14v-2a3 3 0 0 0-3-3h-7v5 M7 11.5a1.5 1.5 0 1 0 0-.01",
  carro: "M3 4h2l2.5 11h11L21 7H7 M9 20a1 1 0 1 0 0-.01 M18 20a1 1 0 1 0 0-.01",
  tienda: "M4 9l1-5h14l1 5 M4 9h16v11H4z M9 20v-6h6v6",
  nave: "M3 21V10l9-6 9 6v11 M3 21h18 M7 21v-7h10v7",
  industria: "M3 21V11l5 3V11l5 3V11l5 3V4h3v17z",
  coche: "M5 17h14 M6 17l1.5-6h9L18 17 M8 19a1.5 1.5 0 1 0 0-.01 M16 19a1.5 1.5 0 1 0 0-.01 M8 11l1-4h6l1 4",
  equipamiento: "M12 3v18 M3 12h18",
  punto: "M12 12a1 1 0 1 0 0-.01",
};

// ---------- Mapa ----------
const mapa = new maplibregl.Map({
  container: "mapa", style: "https://tiles.openfreemap.org/styles/liberty", center: [1.8, 41.7], zoom: 7.3,
  attributionControl: { compact: true, customAttribution: "© ICGC · © Catastro" },
});
mapa.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
mapa.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

const estado = { categorias: [], activas: new Set(), radio: 5000, centro: null, puntos: [], listo: false };

function imagenIcono(color, trazo) {
  const t = 64, c = document.createElement("canvas");
  c.width = c.height = t;
  const x = c.getContext("2d");
  x.fillStyle = color; x.beginPath(); x.arc(32, 32, 29, 0, Math.PI * 2); x.fill();
  x.lineWidth = 4; x.strokeStyle = "#fff"; x.stroke();
  x.save(); x.translate(14, 14); x.scale(1.5, 1.5);
  x.strokeStyle = "#fff"; x.lineWidth = 2; x.lineCap = "round"; x.lineJoin = "round";
  x.stroke(new Path2D(trazo)); x.restore();
  return x.getImageData(0, 0, t, t);
}

mapa.on("load", () => {
  const primeraEtiqueta = mapa.getStyle().layers.find((l) => l.type === "symbol")?.id;
  mapa.addSource("orto", { type: "raster", tiles: [wms(ICGC, "orto-hibrida")], tileSize: 256, attribution: "© ICGC" });
  mapa.addSource("topo", { type: "raster", tiles: [wms(ICGC, "topografic")], tileSize: 256, attribution: "© ICGC" });
  mapa.addSource("catastro", { type: "raster", tiles: [wms("https://ovc.catastro.meh.es/cartografia/INSPIRE/spadgcwms.aspx", "CP.CadastralParcel", "image/png", true)], tileSize: 256, minzoom: 15 });
  mapa.addLayer({ id: "orto", type: "raster", source: "orto", layout: { visibility: "none" } });
  mapa.addLayer({ id: "topo", type: "raster", source: "topo", layout: { visibility: "none" } });
  mapa.addLayer({ id: "catastro", type: "raster", source: "catastro", minzoom: 15 }, primeraEtiqueta);

  mapa.addSource("industrial", { type: "geojson", data: vacio() });
  mapa.addLayer({ id: "industrial", type: "fill", source: "industrial", paint: { "fill-color": "#9575cd", "fill-opacity": 0.3 } });
  mapa.addLayer({ id: "industrial-borde", type: "line", source: "industrial", paint: { "line-color": "#7e57c2", "line-width": 1 } });
  mapa.addLayer({ id: "industrial-nombre", type: "symbol", source: "industrial", minzoom: 12.5,
    layout: { "text-field": ["get", "nombre"], "text-font": ["Noto Sans Bold"], "text-size": 12 },
    paint: { "text-color": "#5e35b1", "text-halo-color": "#fff", "text-halo-width": 1.5 } });

  mapa.addSource("radios", { type: "geojson", data: vacio() });
  mapa.addLayer({ id: "radios", type: "line", source: "radios", paint: { "line-color": "#12355b", "line-width": 2, "line-dasharray": [3, 3] } });
  mapa.addSource("radios-etq", { type: "geojson", data: vacio() });
  mapa.addLayer({ id: "radios-etq", type: "symbol", source: "radios-etq",
    layout: { "text-field": ["get", "t"], "text-font": ["Noto Sans Bold"], "text-size": 12, "text-allow-overlap": true },
    paint: { "text-color": "#fff", "text-halo-color": "#12355b", "text-halo-width": 3 } });

  mapa.addSource("parcela", { type: "geojson", data: vacio() });
  mapa.addLayer({ id: "parcela", type: "fill", source: "parcela", paint: { "fill-color": "#e11d48", "fill-opacity": 0.18 } });
  mapa.addLayer({ id: "parcela-borde", type: "line", source: "parcela", paint: { "line-color": "#e11d48", "line-width": 3 } });

  mapa.addSource("pois", { type: "geojson", data: vacio() });
  // Lejos: puntos de color. Cerca: chinchetas con icono que no se pisan (como Google Maps).
  mapa.addLayer({ id: "pois-punto", type: "circle", source: "pois",
    paint: { "circle-color": ["get", "color"], "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 2.5, 14, 5],
      "circle-stroke-color": "#fff", "circle-stroke-width": 1 } });
  mapa.addLayer({ id: "pois-icono", type: "symbol", source: "pois", minzoom: 13,
    layout: { "icon-image": ["get", "img"], "icon-size": ["interpolate", ["linear"], ["zoom"], 13, 0.6, 17, 0.9],
      "icon-allow-overlap": false, "symbol-sort-key": ["get", "orden"],
      "text-field": ["step", ["zoom"], "", 15, ["get", "nombre"]], "text-font": ["Noto Sans Regular"], "text-size": 12,
      "text-offset": [1.3, 0], "text-anchor": "left", "text-optional": true, "text-max-width": 12 },
    paint: { "text-color": ["get", "color"], "text-halo-color": "#fff", "text-halo-width": 1.5 } });

  mapa.on("click", "pois-icono", (e) => abrirFicha(e.features[0].properties));
  mapa.on("click", "pois-punto", (e) => abrirFicha(e.features[0].properties));
  ["pois-icono", "pois-punto"].forEach((l) => {
    mapa.on("mouseenter", l, () => (mapa.getCanvas().style.cursor = "pointer"));
    mapa.on("mouseleave", l, () => (mapa.getCanvas().style.cursor = ""));
  });
  estado.listo = true;
  const qInicial = new URLSearchParams(location.search).get("q");
  if (qInicial) { $("q").value = qInicial; buscar(qInicial); }
});

// Fondo del mapa
document.querySelectorAll(".capas button").forEach((b) => b.addEventListener("click", () => {
  mapa.setLayoutProperty("orto", "visibility", b.dataset.base === "orto" ? "visible" : "none");
  mapa.setLayoutProperty("topo", "visibility", b.dataset.base === "topo" ? "visible" : "none");
  document.querySelectorAll(".capas button").forEach((o) => o.setAttribute("aria-pressed", String(o === b)));
}));
$("capa-catastro").addEventListener("change", (e) => mapa.setLayoutProperty("catastro", "visibility", e.target.checked ? "visible" : "none"));

// Clic en el mapa (fuera de un punto): elegir parcela
mapa.on("click", (e) => {
  const sobrePunto = mapa.queryRenderedFeatures(e.point, { layers: ["pois-icono", "pois-punto"] }).length;
  if (!sobrePunto) elegirPunto({ lon: e.lngLat.lng, lat: e.lngLat.lat });
});

// ---------- Utilidades ----------
function mostrarMensaje(txt) { $("mensaje").textContent = txt; $("mensaje").hidden = !txt; }
let popup = null;
function limpiarResultado() {
  $("resultado").hidden = true; $("resultado").innerHTML = "";
  $("barra-mapa").hidden = true;
  if (popup) popup.remove();
  if (estado.listo) ["pois", "industrial", "radios", "radios-etq"].forEach((s) => mapa.getSource(s).setData(vacio()));
}
async function pedir(url) {
  const r = await fetch(url);
  if (!r.ok) {
    let msg = `Error ${r.status}`;
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return r.json();
}
function encuadrar(geojson, padding = 60) {
  const b = new maplibregl.LngLatBounds();
  const recorrer = (c) => (typeof c[0] === "number" ? b.extend(c) : c.forEach(recorrer));
  recorrer(geojson.coordinates);
  mapa.fitBounds(b, { padding, maxZoom: 18.5, animate: false });
}

// ---------- Búsqueda ----------
async function buscar(q) {
  mostrarMensaje("");
  $("resultados").innerHTML = "<li>Buscando…</li>";
  try {
    const { resultados } = await pedir(`/api/buscar?q=${encodeURIComponent(q)}`);
    $("resultados").innerHTML = "";
    if (!resultados.length) { mostrarMensaje("No se ha encontrado nada. Prueba con otra dirección o haz clic en el mapa."); return; }
    if (resultados.length === 1) return elegirPunto(resultados[0]);
    resultados.forEach((r) => {
      const li = document.createElement("li");
      li.textContent = r.etiqueta;
      li.onclick = () => { $("resultados").innerHTML = ""; elegirPunto(r); };
      $("resultados").appendChild(li);
    });
  } catch (err) { $("resultados").innerHTML = ""; mostrarMensaje(err.message); }
}
$("buscador").addEventListener("submit", (e) => { e.preventDefault(); buscar($("q").value); });

async function elegirPunto(p) {
  mostrarMensaje("");
  limpiarResultado();
  mapa.jumpTo({ center: [p.lon, p.lat], zoom: Math.max(mapa.getZoom(), 17.5) });
  try {
    if (p.rc) {
      const parc = await pedir(`/api/parcela/${p.rc}`);
      return seleccionarParcela({ rc: parc.rc, direccion: p.etiqueta, superficie: parc.superficie, geojson: parc.geojson });
    }
    const { parcelas, mensaje } = await pedir(`/api/parcela?lon=${p.lon}&lat=${p.lat}`);
    if (!parcelas.length) { $("ficha").hidden = true; mostrarMensaje(mensaje); return; }
    seleccionarParcela(parcelas[0], parcelas);
  } catch (err) { mostrarMensaje(err.message); }
}

function seleccionarParcela(parc, todas = []) {
  if (parc.geojson) {
    mapa.getSource("parcela").setData(parc.geojson);
    encuadrar(parc.geojson, 80);
  }
  $("ficha").hidden = false;
  $("ficha").dataset.rc = parc.rc;
  $("f-direccion").textContent = parc.direccion || "Parcela seleccionada";
  $("f-rc").textContent = parc.rc;
  $("f-sup").textContent = parc.superficie ? `${fmt(parc.superficie)} m²` : "—";
  const otras = todas.filter((t) => t.rc !== parc.rc);
  $("otras").hidden = !otras.length;
  $("lista-parcelas").innerHTML = "";
  otras.forEach((o) => {
    const li = document.createElement("li");
    li.textContent = `${o.rc} · ${o.direccion}`;
    li.onclick = () => seleccionarParcela(o, todas);
    $("lista-parcelas").appendChild(li);
  });
  limpiarResultado();
}

// ---------- Informe ----------
// Grupos de uso (catálogo del servidor)
pedir("/api/perfiles").then((cat) => {
  const fs = $("grupos");
  Object.entries(cat).forEach(([g, d]) => {
    const l = document.createElement("label");
    l.innerHTML = `<input type="checkbox" value="${g}"><span>${esc(d.nombre)}<em>${esc(Object.values(d.usos).join(", "))}</em></span>`;
    fs.appendChild(l);
  });
}).catch(() => {});

function parametros() {
  const q = new URLSearchParams();
  const grupos = [...document.querySelectorAll("#grupos input:checked")].map((i) => i.value);
  if (grupos.length) q.set("grupos", grupos.join(","));
  if ($("potencia").value) q.set("potencia_mw", $("potencia").value);
  if ($("supmin").value) q.set("sup_minima", $("supmin").value);
  return q.toString();
}

const PASOS = ["Consultando Catastro", "Leyendo el Mapa Urbanístic de Catalunya", "Comprobando flujo preferente e inundabilidad",
  "Buscando aforos de tráfico", "Revisando la red eléctrica", "Recorriendo el entorno en 5 km", "Calculando la puntuación"];

$("generar").addEventListener("submit", async (e) => {
  e.preventDefault();
  const rc = $("ficha").dataset.rc;
  if (!rc) return;
  $("btn-generar").disabled = true;
  $("progreso").hidden = false;
  limpiarResultado();
  let i = 0;
  $("paso-progreso").textContent = PASOS[0];
  const reloj = setInterval(() => { i = Math.min(i + 1, PASOS.length - 1); $("paso-progreso").textContent = PASOS[i]; }, 4500);
  try {
    const qs = parametros();
    const inf = await pedir(`/api/informe/${rc}${qs ? "?" + qs : ""}`);
    pintarResultado(inf, rc, qs);
  } catch (err) {
    mostrarMensaje(`No se pudo generar el informe: ${err.message}`);
  } finally {
    clearInterval(reloj);
    $("btn-generar").disabled = false;
    $("progreso").hidden = true;
  }
});

const COLOR_SEM = { verde: "#1e9e5a", ambar: "#e08a00", rojo: "#d64032", gris: "#9aa5b1" };
function rosco(valor, sem) {
  const arco = valor == null ? "" : `<circle cx="40" cy="40" r="34" fill="none" stroke="${COLOR_SEM[sem]}" stroke-width="8" stroke-linecap="round" stroke-dasharray="${(213.6 * valor / 100).toFixed(1)} 213.6" transform="rotate(-90 40 40)"/>`;
  return `<svg viewBox="0 0 80 80"><circle cx="40" cy="40" r="34" fill="none" stroke="#e7ecf1" stroke-width="8"/>${arco}
    <text x="40" y="47" text-anchor="middle" font-size="22" font-weight="800" fill="#12263a" font-family="Inter, sans-serif">${valor ?? "—"}</text></svg>`;
}

function pintarResultado(inf, rc, qs) {
  const sufijo = qs ? "?" + qs : "";
  const bloqueos = [...new Set(Object.values(inf.puntuaciones).flatMap((p) => p.bloqueos))];
  const n = Object.keys(inf.puntuaciones).length;
  let html = `<div class="sec-tit">Puntuación por grupo de uso</div><div class="notas ${n > 4 ? "seis" : ""}">`;
  Object.values(inf.puntuaciones).forEach((p) => {
    const v = p.bloqueos.length ? null : p.total;
    html += `<div class="nota"><span class="p">${esc(p.nombre_perfil)}</span>${rosco(v, p.semaforo)}<span class="chip ${p.semaforo}">${esc(p.veredicto)}</span><span class="mejor">${esc(p.mejor_uso)}</span></div>`;
  });
  html += `</div>`;
  bloqueos.forEach((b) => (html += `<div class="bloqueo">${esc(b)}</div>`));
  const acc = inf.acceso || { completo: true };
  if (acc.completo) {
    html += `<div class="acciones"><a href="/informe/${rc}${sufijo}" target="_blank" rel="noopener">Ver informe completo</a>
      <a class="sec" href="/informe/${rc}.pdf${sufijo}">Descargar PDF</a></div>`;
    const ficha = ((inf.parcela && inf.parcela.fichas_catastro) || [])[0];
    if (ficha) html += `<a class="enlace-ficha" href="${esc(ficha.url)}" target="_blank" rel="noopener">Ficha oficial del Catastro (consulta descriptiva y gráfica) ↗</a>`;
  } else {
    html += `<div class="acciones una"><a href="/comprar/${rc}">${acc.motivo === "limite" ? "Has agotado tus informes del mes · ver opciones" : "Ver informe completo y PDF · " + esc(acc.precio_informe)}</a></div>
      <p class="nota-acceso">Incluye urbanismo, agua, tráfico, entorno, valor del suelo, empresas registradas y la ficha oficial del Catastro. <a href="/cuenta">¿Tienes suscripción? Entra</a>.</p>`;
  }
  html += `<p class="resumen">${esc(inf.resumen)}</p>`;
  html += `<div class="sec-tit">De un vistazo</div><div class="vistazo">`;
  inf.panorama.forEach((f) => (html += `<div class="fv e-${f.estado}"><div class="t">${esc(f.titulo)}</div><div class="v">${esc(f.valor)}</div><div class="d">${esc(f.detalle)}</div></div>`));
  html += `</div>`;
  html += `<div class="sec-tit" id="entorno-tit">Entorno</div><ul class="comp-lista" id="lista-pois"></ul>`;
  $("resultado").innerHTML = html;
  $("resultado").hidden = false;
  prepararEntorno(inf);
}

// ---------- Entorno de 5 km ----------
function circulo([lon, lat], r, n = 96) {
  const c = [];
  for (let i = 0; i <= n; i++) {
    const a = (i / n) * 2 * Math.PI;
    c.push([lon + (r / (111320 * Math.cos((lat * Math.PI) / 180))) * Math.cos(a), lat + (r / 110540) * Math.sin(a)]);
  }
  return c;
}

function prepararEntorno(inf) {
  const e5 = inf.entorno5 || {};
  const centro = [inf.lon, inf.lat];
  estado.centro = centro;
  estado.categorias = (e5.resumen || []).filter((f) => f.clave !== "poligonos");
  estado.categorias.forEach((c) => {
    const id = "ico-" + c.clave;
    if (!mapa.hasImage(id)) mapa.addImage(id, imagenIcono(c.color, TRAZOS[c.icono] || TRAZOS.punto), { pixelRatio: 2 });
  });
  const color = Object.fromEntries(estado.categorias.map((c) => [c.clave, c.color]));
  const nombreCat = Object.fromEntries(estado.categorias.map((c) => [c.clave, c.nombre]));
  // Gasolineras con precio del Ministerio; si no hay, las de OpenStreetMap.
  const gas = ((inf.gasolineras && inf.gasolineras.estaciones) || []).map((g) => ({
    cat: "gasolineras", nombre: g.marca, direccion: g.direccion, distancia_m: g.distancia_m, lon: g.lon, lat: g.lat,
    extra: `Gasóleo A ${fmt(g.gasoleo_a, 3)} €/l · Gasolina 95 ${fmt(g.gasolina_95, 3)} €/l · ${g.horario || ""}`,
  }));
  const osm = (e5.puntos || []).filter((p) => !(gas.length && p.cat === "gasolineras"));
  const orden = Object.fromEntries(estado.categorias.map((c, i) => [c.clave, i]));
  estado.puntos = [...gas, ...osm].map((p) => ({ ...p, color: color[p.cat] || "#9aa5b1", nombreCat: nombreCat[p.cat] || "",
    img: "ico-" + p.cat, orden: orden[p.cat] ?? 99 })).sort((a, b) => a.distancia_m - b.distancia_m);

  // Por defecto se ven todas menos «otros comercios» y «oficinas» (son muchísimos).
  estado.activas = new Set(estado.categorias.map((c) => c.clave).filter((k) => !["comercios", "oficinas"].includes(k)));
  mapa.getSource("industrial").setData({ type: "FeatureCollection", features: (e5.zonas_industriales || []).map((z) => ({
    type: "Feature", geometry: z.geojson, properties: { nombre: z.nombre, ha: z.area_ha } })) });

  const chips = $("chips-cat");
  chips.innerHTML = "";
  estado.categorias.forEach((c) => {
    const b = document.createElement("button");
    b.type = "button"; b.dataset.c = c.clave;
    b.innerHTML = `<i style="background:${c.color}"></i>${esc(c.nombre)} <small></small>`;
    b.onclick = () => { estado.activas.has(c.clave) ? estado.activas.delete(c.clave) : estado.activas.add(c.clave); pintarEntorno(); };
    chips.appendChild(b);
  });
  document.querySelectorAll("#chips-radio button").forEach((b) => (b.onclick = () => {
    estado.radio = Number(b.dataset.r);
    document.querySelectorAll("#chips-radio button").forEach((o) => o.setAttribute("aria-pressed", String(o === b)));
    pintarEntorno(true);
  }));
  $("barra-mapa").hidden = false;
  if (e5.estado !== "ok") mostrarMensaje(`Entorno: ${e5.mensaje || "sin datos"}. Se muestran solo las gasolineras.`);
  pintarEntorno(true);
}

function pintarEntorno(encuadre = false) {
  const { radio, centro } = estado;
  const dentro = estado.puntos.filter((p) => p.distancia_m <= radio);
  const visibles = dentro.filter((p) => estado.activas.has(p.cat));
  mapa.getSource("pois").setData({ type: "FeatureCollection", features: visibles.map((p, i) => ({
    type: "Feature", id: i, geometry: { type: "Point", coordinates: [p.lon, p.lat] },
    properties: { nombre: p.nombre || "", cat: p.cat, nombreCat: p.nombreCat, color: p.color, img: p.img, orden: p.orden,
      distancia: p.distancia_m, direccion: p.direccion || "", extra: p.extra || "", tipo: p.tipo || "", lon: p.lon, lat: p.lat } })) });
  const rs = [500, 1000, 2000, 5000].filter((r) => r <= radio);
  mapa.getSource("radios").setData({ type: "FeatureCollection", features: rs.map((r) => ({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: circulo(centro, r) } })) });
  mapa.getSource("radios-etq").setData({ type: "FeatureCollection", features: rs.map((r) => ({ type: "Feature", properties: { t: r >= 1000 ? `${r / 1000} km` : `${r} m` },
    geometry: { type: "Point", coordinates: [centro[0], centro[1] + r / 110540] } })) });

  document.querySelectorAll("#chips-cat button").forEach((b) => {
    const n = dentro.filter((p) => p.cat === b.dataset.c).length;
    b.setAttribute("aria-pressed", String(estado.activas.has(b.dataset.c)));
    b.querySelector("small").textContent = n;
    b.hidden = n === 0;
  });

  $("entorno-tit").textContent = `Entorno en ${radio >= 1000 ? radio / 1000 + " km" : radio + " m"} · ${fmt(visibles.length)} lugares`;
  const ul = $("lista-pois");
  ul.innerHTML = visibles.length ? "" : `<li class="comp-vacia">Nada con estos filtros. Activa categorías en la barra del mapa.</li>`;
  visibles.slice(0, 150).forEach((p) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="n" style="background:${p.color}"></span>
      <span><span class="nom">${esc(p.nombre || p.nombreCat)}</span><span class="dir">${esc(p.nombreCat)}${p.direccion ? " · " + esc(p.direccion) : ""}</span></span>
      <span class="pr">${fmt(p.distancia_m)} m</span>`;
    li.onclick = () => { mapa.flyTo({ center: [p.lon, p.lat], zoom: 17 }); abrirFicha({ ...p, distancia: p.distancia_m }); };
    ul.appendChild(li);
  });
  if (visibles.length > 150) ul.insertAdjacentHTML("beforeend", `<li class="comp-vacia">Y ${fmt(visibles.length - 150)} más en el mapa.</li>`);
  if (encuadre) {
    const b = new maplibregl.LngLatBounds();
    circulo(centro, radio, 24).forEach((c) => b.extend(c));
    mapa.fitBounds(b, { padding: 30, animate: false });
  }
}

function abrirFicha(p) {
  if (popup) popup.remove();
  popup = new maplibregl.Popup({ offset: 14, maxWidth: "280px" }).setLngLat([p.lon, p.lat]).setHTML(
    `<div class="ficha-poi"><small style="color:${p.color}">${esc(p.nombreCat)}</small><b>${esc(p.nombre || "Sin nombre")}</b>
     ${p.direccion ? `<span>${esc(p.direccion)}</span>` : ""}${p.extra ? `<span>${esc(p.extra)}</span>` : ""}
     <span>A ${fmt(p.distancia)} m de la parcela</span></div>`).addTo(mapa);
}
