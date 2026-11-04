/* Herramienta: mapa, búsqueda de parcela, informe en pantalla y competencia en el mapa. */
const $ = (id) => document.getElementById(id);
const fmt = (n, d = 0) => n == null ? "—" : Number(n).toLocaleString("es-ES", { maximumFractionDigits: d, minimumFractionDigits: d });
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------- Mapa ----------
const mapa = L.map("mapa", { zoomControl: true }).setView([41.7, 1.8], 8);
const bases = {
  calles: L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 20, maxNativeZoom: 19, attribution: "© OpenStreetMap" }),
  orto: L.tileLayer.wms("https://geoserveis.icgc.cat/servei/catalunya/mapa-base/wms", { layers: "orto-hibrida", format: "image/jpeg", maxZoom: 21, attribution: "© ICGC" }),
  topo: L.tileLayer.wms("https://geoserveis.icgc.cat/servei/catalunya/mapa-base/wms", { layers: "topografic", format: "image/jpeg", maxZoom: 21, attribution: "© ICGC" }),
};
let baseActual = bases.calles.addTo(mapa);
const capaCatastro = L.tileLayer.wms("https://ovc.catastro.meh.es/cartografia/INSPIRE/spadgcwms.aspx", {
  layers: "CP.CadastralParcel", format: "image/png", transparent: true, minZoom: 15, maxZoom: 21, attribution: "© Catastro",
}).addTo(mapa);
let capaParcela = null, marcador = null, capaComp = null;

document.querySelectorAll(".capas button").forEach((b) => b.addEventListener("click", () => {
  mapa.removeLayer(baseActual);
  baseActual = bases[b.dataset.base].addTo(mapa).bringToBack();
  document.querySelectorAll(".capas button").forEach((o) => o.setAttribute("aria-pressed", String(o === b)));
}));
$("capa-catastro").addEventListener("change", (e) => e.target.checked ? capaCatastro.addTo(mapa) : mapa.removeLayer(capaCatastro));

// Municipio y población al detener el ratón
let tPob = null;
const tooltip = L.tooltip({ className: "tooltip-pob", direction: "top", offset: [0, -8] });
mapa.on("mousemove", (e) => {
  clearTimeout(tPob);
  tPob = setTimeout(async () => {
    if (mapa.getZoom() < 11) return;
    try {
      const r = await fetch(`/api/municipio?lon=${e.latlng.lng}&lat=${e.latlng.lat}`).then((r) => r.json());
      if (!r.nombre) return;
      tooltip.setLatLng(e.latlng).setContent(`${esc(r.nombre)}${r.poblacion ? " · " + fmt(r.poblacion) + " hab." : ""}`).addTo(mapa);
    } catch (_) {}
  }, 700);
});
mapa.on("mouseout", () => { clearTimeout(tPob); mapa.removeLayer(tooltip); });

// ---------- Utilidades ----------
function mostrarMensaje(txt) { $("mensaje").textContent = txt; $("mensaje").hidden = !txt; }
function limpiarResultado() {
  $("resultado").hidden = true; $("resultado").innerHTML = "";
  if (capaComp) { mapa.removeLayer(capaComp); capaComp = null; }
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
mapa.on("click", (e) => elegirPunto({ lon: e.latlng.lng, lat: e.latlng.lat }));

// Búsqueda que llega desde la portada (/app?q=...)
const qInicial = new URLSearchParams(location.search).get("q");
if (qInicial) { $("q").value = qInicial; buscar(qInicial); }

async function elegirPunto(p) {
  mostrarMensaje("");
  limpiarResultado();
  mapa.setView([p.lat, p.lon], Math.max(mapa.getZoom(), 18), { animate: false });
  if (marcador) mapa.removeLayer(marcador);
  marcador = L.circleMarker([p.lat, p.lon], { radius: 5, color: "#e11d48" }).addTo(mapa);
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
  if (capaParcela) mapa.removeLayer(capaParcela);
  if (parc.geojson) {
    capaParcela = L.geoJSON(parc.geojson, { style: { color: "#e11d48", weight: 3, fillOpacity: 0.15 } }).addTo(mapa);
    mapa.fitBounds(capaParcela.getBounds(), { maxZoom: 19, padding: [40, 40], animate: false });
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
function parametros() {
  const q = new URLSearchParams();
  if ($("potencia").value) q.set("potencia_mw", $("potencia").value);
  if ($("supmin").value) q.set("sup_minima", $("supmin").value);
  return q.toString();
}

const PASOS = ["Consultando Catastro", "Leyendo el Mapa Urbanístic de Catalunya", "Comprobando flujo preferente e inundabilidad",
  "Buscando aforos de tráfico", "Revisando la red eléctrica", "Localizando la competencia", "Calculando la puntuación"];

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
  let html = `<div class="sec-tit">Puntuación por uso</div><div class="notas">`;
  Object.values(inf.puntuaciones).forEach((p) => {
    const v = p.bloqueos.length ? null : p.total;
    html += `<div class="nota"><span class="p">${esc(p.nombre_perfil)}</span>${rosco(v, p.semaforo)}<span class="chip ${p.semaforo}">${esc(p.veredicto)}</span></div>`;
  });
  html += `</div>`;
  bloqueos.forEach((b) => (html += `<div class="bloqueo">${esc(b)}</div>`));
  html += `<div class="acciones"><a href="/informe/${rc}${sufijo}" target="_blank" rel="noopener">Ver informe completo</a>
    <a class="sec" href="/informe/${rc}.pdf${sufijo}">Descargar PDF</a></div>`;
  html += `<p class="resumen">${esc(inf.resumen)}</p>`;
  html += `<div class="sec-tit">De un vistazo</div><div class="vistazo">`;
  inf.panorama.forEach((f) => (html += `<div class="fv e-${f.estado}"><div class="t">${esc(f.titulo)}</div><div class="v">${esc(f.valor)}</div><div class="d">${esc(f.detalle)}</div></div>`));
  html += `</div>`;
  html += `<div class="sec-tit">Competencia en 2 km</div>
    <div class="comp-filtros" id="comp-filtros">
      <button type="button" data-r="500" aria-pressed="false">500 m</button>
      <button type="button" data-r="1000" aria-pressed="false">1 km</button>
      <button type="button" data-r="2000" aria-pressed="true">2 km</button>
      <button type="button" data-g="marca" aria-pressed="true">Grandes marcas</button>
      <button type="button" data-g="independiente" aria-pressed="true">Independientes</button>
      <button type="button" data-g="supermercado" aria-pressed="true">Supermercados</button>
    </div>
    <ul class="comp-lista" id="comp-lista"></ul>`;
  $("resultado").innerHTML = html;
  $("resultado").hidden = false;
  prepararCompetencia(inf);
}

// ---------- Competencia en el mapa ----------
const COLOR_GRUPO = { marca: "#3f5f9e", independiente: "#1f8a70", supermercado: "#8a4b8f" };
function prepararCompetencia(inf) {
  const est = (inf.gasolineras && inf.gasolineras.estaciones) || [];
  est.forEach((e, i) => (e.n = i + 1));
  const precios = est.map((e) => e.gasoleo_a).filter(Boolean);
  const minimo = precios.length ? Math.min(...precios) : null;
  const centro = inf.parcela_geojson ? L.geoJSON(inf.parcela_geojson).getBounds().getCenter() : L.latLng(inf.lat, inf.lon);
  let radio = 2000;
  const grupos = new Set(["marca", "independiente", "supermercado"]);

  function pintar() {
    if (capaComp) mapa.removeLayer(capaComp);
    capaComp = L.layerGroup().addTo(mapa);
    [500, 1000, 2000].filter((r) => r <= radio).forEach((r) => {
      L.circle(centro, { radius: r, color: "#12355b", weight: 2, dashArray: "6 6", fill: false, interactive: false }).addTo(capaComp);
      L.tooltip({ permanent: true, direction: "top", className: "etq-radio" }).setLatLng(L.latLng(centro.lat + r / 111320, centro.lng)).setContent(r >= 1000 ? `${r / 1000} km` : `${r} m`).addTo(capaComp);
    });
    const visibles = est.filter((e) => e.distancia_m <= radio && grupos.has(e.grupo));
    visibles.forEach((e) => {
      const icono = L.divIcon({ className: "", html: `<div class="pin-comp" style="background:${COLOR_GRUPO[e.grupo] || "#1f8a70"}">${e.n}</div>`, iconSize: [26, 26], iconAnchor: [13, 13] });
      e.marcador = L.marker([e.lat, e.lon], { icon: icono }).addTo(capaComp)
        .bindPopup(`<b>${esc(e.marca)}</b><br>${esc(e.direccion)}<br>Gasóleo A: <b>${fmt(e.gasoleo_a, 3)} €/l</b> · Gasolina 95: ${fmt(e.gasolina_95, 3)} €/l<br>${fmt(e.distancia_m)} m · ${esc(e.horario)}`);
    });
    const ul = $("comp-lista");
    ul.innerHTML = visibles.length ? "" : `<li class="comp-vacia">No hay estaciones con estos filtros.</li>`;
    visibles.forEach((e) => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="n" style="background:${COLOR_GRUPO[e.grupo] || "#1f8a70"}">${e.n}</span>
        <span><span class="nom">${esc(e.marca)}</span><span class="dir">${esc(e.direccion)}</span></span>
        <span class="pr ${e.gasoleo_a === minimo ? "barato" : ""}">${fmt(e.gasoleo_a, 3)}<small>${fmt(e.distancia_m)} m</small></span>`;
      li.onclick = () => { mapa.setView([e.lat, e.lon], 17); e.marcador.openPopup(); };
      ul.appendChild(li);
    });
    mapa.stop();
    mapa.fitBounds(L.latLng(centro).toBounds(radio * 2.2), { animate: false });
  }

  document.querySelectorAll("#comp-filtros button").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.r) {
      radio = Number(b.dataset.r);
      document.querySelectorAll("#comp-filtros button[data-r]").forEach((o) => o.setAttribute("aria-pressed", String(o === b)));
    } else {
      const on = b.getAttribute("aria-pressed") !== "true";
      b.setAttribute("aria-pressed", String(on));
      on ? grupos.add(b.dataset.g) : grupos.delete(b.dataset.g);
    }
    pintar();
  }));
  pintar();
}
