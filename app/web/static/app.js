/* Plataforma de Ubicaciones · mapa, búsqueda y generación de informes */
const $ = (id) => document.getElementById(id);
const fmt = (n, d = 0) => n == null ? "—" : Number(n).toLocaleString("es-ES", { maximumFractionDigits: d, minimumFractionDigits: d });

// ---------- Mapa ----------
const mapa = L.map("mapa", { zoomControl: true }).setView([41.7, 1.8], 8);
const baseMapa = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 20, maxNativeZoom: 19, attribution: "© OpenStreetMap",
}).addTo(mapa);
const baseOrto = L.tileLayer.wms("https://geoserveis.icgc.cat/servei/catalunya/orto-territorial/wms", {
  layers: "ortofoto_color_vigent", format: "image/jpeg", maxZoom: 21, attribution: "© ICGC",
});
const capaCatastro = L.tileLayer.wms("https://ovc.catastro.meh.es/cartografia/INSPIRE/spadgcwms.aspx", {
  layers: "CP.CadastralParcel", format: "image/png", transparent: true, minZoom: 15, maxZoom: 21, attribution: "© Catastro",
}).addTo(mapa);
let capaParcela = null;
let marcador = null;

document.querySelectorAll("input[name=base]").forEach((r) =>
  r.addEventListener("change", () => {
    if (r.value === "orto" && r.checked) { mapa.removeLayer(baseMapa); baseOrto.addTo(mapa).bringToBack(); }
    if (r.value === "mapa" && r.checked) { mapa.removeLayer(baseOrto); baseMapa.addTo(mapa).bringToBack(); }
  }));
$("capa-catastro").addEventListener("change", (e) => e.target.checked ? capaCatastro.addTo(mapa) : mapa.removeLayer(capaCatastro));

// Población del municipio al detener el ratón sobre el mapa
let tPob = null, ultimoMuni = null;
const tooltip = L.tooltip({ className: "tooltip-pob", direction: "top", offset: [0, -8] });
mapa.on("mousemove", (e) => {
  clearTimeout(tPob);
  tPob = setTimeout(async () => {
    if (mapa.getZoom() < 11) return;
    try {
      const r = await fetch(`/api/municipio?lon=${e.latlng.lng}&lat=${e.latlng.lat}`).then((r) => r.json());
      if (!r.nombre) return;
      ultimoMuni = r;
      tooltip.setLatLng(e.latlng).setContent(`${r.nombre}${r.poblacion ? " · " + fmt(r.poblacion) + " hab." : ""}`).addTo(mapa);
    } catch (_) {}
  }, 700);
});
mapa.on("mouseout", () => { clearTimeout(tPob); mapa.removeLayer(tooltip); });

// ---------- Utilidades UI ----------
function mostrarMensaje(txt) { $("mensaje").textContent = txt; $("mensaje").hidden = !txt; }
function limpiarResultado() { $("resultado").hidden = true; $("resultado").innerHTML = ""; }

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
$("buscador").addEventListener("submit", async (e) => {
  e.preventDefault();
  mostrarMensaje("");
  $("resultados").innerHTML = "<li>Buscando…</li>";
  try {
    const { resultados } = await pedir(`/api/buscar?q=${encodeURIComponent($("q").value)}`);
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
});

mapa.on("click", (e) => elegirPunto({ lon: e.latlng.lng, lat: e.latlng.lat }));

async function elegirPunto(p) {
  mostrarMensaje("");
  limpiarResultado();
  mapa.setView([p.lat, p.lon], Math.max(mapa.getZoom(), 18));
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
    capaParcela = L.geoJSON(parc.geojson, { style: { color: "#e11d48", weight: 3, fillOpacity: 0.12 } }).addTo(mapa);
    mapa.fitBounds(capaParcela.getBounds(), { maxZoom: 19, padding: [40, 40] });
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

// ---------- Perfiles ----------
pedir("/api/perfiles").then((perfiles) => {
  Object.entries(perfiles).forEach(([k, v]) => $("perfil").add(new Option(v, k)));
});

// ---------- Informe ----------
function parametros() {
  const q = new URLSearchParams();
  if ($("potencia").value) q.set("potencia_mw", $("potencia").value);
  if ($("supmin").value) q.set("sup_minima", $("supmin").value);
  return q.toString();
}

$("generar").addEventListener("submit", async (e) => {
  e.preventDefault();
  const rc = $("ficha").dataset.rc;
  if (!rc) return;
  $("btn-generar").disabled = true;
  $("progreso").hidden = false;
  limpiarResultado();
  try {
    const qs = parametros();
    const inf = await pedir(`/api/informe/${rc}${qs ? "?" + qs : ""}`);
    pintarResultado(inf, rc, qs);
  } catch (err) {
    mostrarMensaje(`No se pudo generar el informe: ${err.message}`);
  } finally {
    $("btn-generar").disabled = false;
    $("progreso").hidden = true;
  }
});

function pintarResultado(inf, rc, qs) {
  const perfil = $("perfil").value;
  const p = inf.puntuaciones[perfil];
  const sufijo = qs ? "?" + qs : "";
  let html = `<div><small>${p.nombre_perfil}</small></div>
    <div class="nota-grande">${p.bloqueos.length ? "—" : (p.total ?? "—")}</div>
    <span class="chip ${p.semaforo}">${p.veredicto}</span> <small>Confianza ${p.confianza}</small>`;
  p.bloqueos.forEach((b) => (html += `<div class="bloqueo">⛔ ${b}</div>`));
  html += `<div class="otros-perfiles">`;
  Object.values(inf.puntuaciones).filter((o) => o.perfil !== perfil).forEach((o) => {
    html += `<span>${o.nombre_perfil}</span><span class="chip ${o.semaforo}">${o.bloqueos.length ? "No apta" : (o.total ?? "—")}</span>`;
  });
  html += `</div><p style="font-size:13px">${inf.resumen}</p>
    <div class="acciones"><a href="/informe/${rc}${sufijo}" target="_blank" rel="noopener">Ver informe</a>
    <a class="sec" href="/informe/${rc}.pdf${sufijo}">Descargar PDF</a></div>`;
  $("resultado").innerHTML = html;
  $("resultado").hidden = false;
}
