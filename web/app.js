/* Post-fire debris flow hazard map.
 *
 * Reads data/fires.json, then whichever GeoJSON that manifest points at. It has
 * no knowledge of where those files came from, which is what lets the same page
 * later show a result generated on demand for an uploaded shape.
 */

const THRESHOLD_STOPS = [
  { max: 14,       color: "#ff4f2b", label: "under 14"  },
  { max: 18,       color: "#ff8a3d", label: "14 to 18"  },
  { max: 24,       color: "#ffc857", label: "18 to 24"  },
  { max: 40,       color: "#6d93a8", label: "24 to 40"  },
  { max: Infinity, color: "#3a5567", label: "over 40"   },
];

const STABILITY_COLORS = {
  always:    { color: "#ff4f2b", label: "High whatever we assume" },
  sometimes: { color: "#b07cc6", label: "Depends on the assumptions" },
  never:     { color: "#3a5567", label: "Not high under any assumption" },
};

const VIEW_NOTES = {
  threshold:
    "Rain over 15 minutes that gives this basin a 50% chance of a debris flow. " +
    "Lower means more dangerous.",
  stability:
    "Whether the basin is rated high hazard at 24 mm/hr across all six " +
    "combinations of severity threshold and soil rule.",
};

// The two views answer different questions at different probabilities, so each
// legend states its own. Rainfall needed is the 50% point; Certainty asks
// whether a basin clears 60% in a fixed 24 mm/hr storm. A basin can therefore
// need under 24 mm/hr on one map and still not be High on the other: the
// crossover sits at 24 / 1.11 = 21.6 mm/hr. See m1.hazard_class for the ratio.
const LEGEND_CAPTIONS = {
  threshold:
    "<b>The question:</b> how hard does it have to rain, for 15 minutes, to " +
    "make a debris flow a coin flip (50%)? Red basins slide with very little " +
    "rain. Blue basins need a downpour. For scale, 24 mm/hr for 15 minutes is " +
    "6 mm of rain, about a quarter inch.",
  stability:
    "<b>The question:</b> in a 24 mm/hr storm lasting 15 minutes, is a debris " +
    "flow at least 60% likely? Red, yes, however we set our assumptions. " +
    "Purple, only under some. Grey, never. 60% is where the top two of USGS's " +
    "five likelihood classes begin.",
};

const state = { view: "threshold", manifest: null, fire: null,
                hovered: null, locked: null };

const map = new maplibregl.Map({
  container: "map",
  style: {
    version: 8,
    // Esri's ArcGIS Online basemaps need no key. The dark canvas keeps the
    // hazard ramp as the only saturated thing on the page, and the hillshade
    // under it shows the terrain the whole model is about.
    sources: {
      base: {
        type: "raster",
        tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"],
        tileSize: 256,
        maxzoom: 16,
        attribution: 'Basemap &copy; <a href="https://www.esri.com/">Esri</a>',
      },
      hillshade: {
        type: "raster",
        tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}"],
        tileSize: 256,
        maxzoom: 16,
      },
      labels: {
        type: "raster",
        tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}"],
        tileSize: 256,
        maxzoom: 16,
      },
    },
    layers: [
      { id: "base", type: "raster", source: "base" },
      { id: "hillshade", type: "raster", source: "hillshade",
        paint: { "raster-opacity": 0.4 } },
    ],
  },
  center: [-117.71, 34.3],
  zoom: 10,
  attributionControl: { compact: true },
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
map.addControl(new maplibregl.ScaleControl({ maxWidth: 90, unit: "metric" }), "bottom-left");

/* ---- Paint expressions --------------------------------------------------- */

function thresholdPaint() {
  // step() needs ascending breaks; nulls fall through to the last colour.
  return [
    "case",
    ["==", ["get", "threshold_mm_hr"], null], "#2a3b48",
    ["step", ["get", "threshold_mm_hr"],
      THRESHOLD_STOPS[0].color,
      14, THRESHOLD_STOPS[1].color,
      18, THRESHOLD_STOPS[2].color,
      24, THRESHOLD_STOPS[3].color,
      40, THRESHOLD_STOPS[4].color],
  ];
}

function stabilityPaint() {
  return [
    "match", ["get", "stability"],
    "always", STABILITY_COLORS.always.color,
    "sometimes", STABILITY_COLORS.sometimes.color,
    "never", STABILITY_COLORS.never.color,
    "#2a3b48",
  ];
}

function applyView() {
  if (!map.getLayer("basins-fill")) return;
  const paint = state.view === "threshold" ? thresholdPaint() : stabilityPaint();
  map.setPaintProperty("basins-fill", "fill-color", paint);
  document.getElementById("viewNote").textContent = VIEW_NOTES[state.view];
  drawLegend();
}

/* ---- Legend -------------------------------------------------------------- */

function drawLegend() {
  const el = document.getElementById("legend");
  if (state.view === "threshold") {
    el.innerHTML =
      THRESHOLD_STOPS.map(
        (s) => `<div class="legend-row"><i style="background:${s.color}"></i>${s.label} mm/hr</div>`
      ).join("") +
      `<p class="legend-caption">${LEGEND_CAPTIONS.threshold}</p>`;
  } else {
    el.innerHTML =
      Object.values(STABILITY_COLORS)
        .map((s) => `<div class="legend-row"><i style="background:${s.color}"></i>${s.label}</div>`)
        .join("") +
      `<p class="legend-caption">${LEGEND_CAPTIONS.stability}</p>`;
  }
}

/* ---- Basin readout ------------------------------------------------------- */

const fmt = (v, d = 1) =>
  v === null || v === undefined || Number.isNaN(v) ? "n/a" : Number(v).toFixed(d);

function showBasin(props, locked = false) {
  const el = document.getElementById("readout");
  if (!props) {
    el.innerHTML = `<p class="empty">Point at a basin to see its numbers. ` +
      `Click to keep it on screen.</p>`;
    return;
  }
  const thr = props.threshold_mm_hr;
  const range =
    props.thr_min != null && props.thr_max != null
      ? `${fmt(props.thr_min)} to ${fmt(props.thr_max)} depending on assumptions`
      : "";
  const baer =
    props.baer_threshold != null
      ? `<dt>Field-checked severity</dt><dd>${fmt(props.baer_threshold)} mm/hr</dd>`
      : "";

  el.innerHTML = `
    <h2>
      Basin ${props.id}
      ${locked
        ? `<button class="unlock" id="unlockBtn" title="Press Escape to release">pinned, release</button>`
        : `<span class="hint">click to pin</span>`}
    </h2>
    <div class="big">${fmt(thr)}<span>mm/hr</span></div>
    <p class="range">${range}</p>
    <dl class="rows">
      <dt>Area</dt><dd>${fmt(props.area_km2, 2)} km2</dd>
      <dt>Steep and badly burned</dt><dd>${fmt(props.T * 100, 0)}%</dd>
      <dt>Burn severity</dt><dd>${fmt(props.F, 2)}</dd>
      <dt>Soil erodibility</dt><dd>${fmt(props.S, 3)}</dd>
      <dt>Chance at 24 mm/hr</dt><dd>${fmt(props.p_24 * 100, 0)}%</dd>
      <dt>Certainty</dt><dd>${props.stability ?? "n/a"}</dd>
      ${baer}
    </dl>`;
}

/* ---- Data loading -------------------------------------------------------- */

async function loadFire(fire) {
  state.fire = fire;
  state.locked = null;
  state.hovered = null;

  const res = await fetch(fire.data);
  if (!res.ok) throw new Error(`Could not load ${fire.data} (${res.status})`);
  const data = await res.json();

  if (map.getSource("basins")) {
    map.getSource("basins").setData(data);
  } else {
    map.addSource("basins", { type: "geojson", data, promoteId: "id" });
    map.addLayer({
      id: "basins-fill", type: "fill", source: "basins",
      paint: {
        "fill-color": thresholdPaint(),
        "fill-opacity": [
          "case", ["boolean", ["feature-state", "hover"], false], 0.92, 0.68,
        ],
      },
    });
    map.addLayer({
      id: "basins-line", type: "line", source: "basins",
      paint: { "line-color": "#0e151b", "line-width": 0.6, "line-opacity": 0.7 },
    });
    map.addLayer({
      id: "labels", type: "raster", source: "labels",
      paint: { "raster-opacity": 0.85 },
    });
    wireInteraction();
  }

  map.fitBounds(fire.bounds, { padding: { top: 110, bottom: 60, left: 370, right: 60 } });

  const s = fire.stability || {};
  document.getElementById("fireMeta").textContent =
    `${fire.basins} basins, ${fire.area_km2} km2 burned. ` +
    `Typical basin needs ${fire.median_threshold_mm_hr} mm/hr. ` +
    (s.always ? `${s.always} basins are high hazard whatever we assume.` : "");

  applyView();
}

function setHover(id) {
  if (state.hovered !== null && state.hovered !== state.locked) {
    map.setFeatureState({ source: "basins", id: state.hovered }, { hover: false });
  }
  state.hovered = id;
  if (id !== null) {
    map.setFeatureState({ source: "basins", id }, { hover: true });
  }
}

function unpin() {
  if (state.locked !== null) {
    map.setFeatureState({ source: "basins", id: state.locked }, { hover: false });
  }
  state.locked = null;
  showBasin(null);
}

function wireInteraction() {
  // Hover is a preview. A click pins the basin so the panel can be read and
  // scrolled without the pointer wandering onto a neighbour and swapping it out.
  map.on("mousemove", "basins-fill", (e) => {
    if (state.locked !== null || !e.features.length) return;
    const f = e.features[0];
    setHover(f.id);
    showBasin(f.properties);
    map.getCanvas().style.cursor = "pointer";
  });

  map.on("mouseleave", "basins-fill", () => {
    if (state.locked !== null) return;
    setHover(null);
    map.getCanvas().style.cursor = "";
  });

  map.on("click", "basins-fill", (e) => {
    if (!e.features.length) return;
    const f = e.features[0];
    if (state.locked === f.id) { unpin(); return; }   // click again to release
    if (state.locked !== null) {
      map.setFeatureState({ source: "basins", id: state.locked }, { hover: false });
    }
    state.locked = f.id;
    setHover(f.id);
    showBasin(f.properties, true);
  });

  // Clicking bare map releases the pin, as does Escape.
  map.on("click", (e) => {
    const hits = map.queryRenderedFeatures(e.point, { layers: ["basins-fill"] });
    if (!hits.length) unpin();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") unpin();
  });
  document.getElementById("readout").addEventListener("click", (e) => {
    if (e.target.id === "unlockBtn") unpin();
  });
}

/* ---- Boot ---------------------------------------------------------------- */

async function boot() {
  const res = await fetch("data/fires.json");
  if (!res.ok) throw new Error(`Could not load the fire list (${res.status})`);
  state.manifest = await res.json();

  const sel = document.getElementById("fireSelect");
  state.manifest.fires.forEach((f, i) => {
    const opt = document.createElement("option");
    opt.value = String(i);
    opt.textContent = `${f.name}, ${f.year}`;
    sel.appendChild(opt);
  });
  sel.disabled = state.manifest.fires.length < 2;
  sel.addEventListener("change", () =>
    loadFire(state.manifest.fires[Number(sel.value)]).catch(fail)
  );

  await loadFire(state.manifest.fires[0]);
}

function fail(err) {
  console.error(err);
  document.getElementById("readout").innerHTML =
    `<p class="empty">${err.message}. Check that the files in data/ are present.</p>`;
}

map.on("load", () => boot().catch(fail));

document.querySelectorAll(".segmented button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".segmented button").forEach((b) => {
      b.classList.toggle("on", b === btn);
      b.setAttribute("aria-checked", String(b === btn));
    });
    state.view = btn.dataset.view;
    applyView();
  });
});

const panel = document.getElementById("panel");
document.getElementById("panelToggle").addEventListener("click", (e) => {
  const collapsed = panel.classList.toggle("collapsed");
  e.currentTarget.setAttribute("aria-expanded", String(!collapsed));
  document.getElementById("panelToggleLabel").textContent = collapsed ? "Show" : "Hide";
});
