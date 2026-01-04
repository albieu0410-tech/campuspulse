async function api(path, opts) {
  const res = await fetch(path, opts);
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch { data = text; }
  if (!res.ok) throw new Error(typeof data === "string" ? data : JSON.stringify(data));
  return data;
}

function fmt(dtString) {
  if (!dtString) return "";
  try {
    const d = new Date(dtString);
    return d.toLocaleString();
  } catch {
    return dtString;
  }
}

async function loadClasses() {
  const tbody = document.getElementById("classesTbody");
  tbody.innerHTML = `<tr><td class="py-2" colspan="3">Loading...</td></tr>`;
  try {
    const data = await api("/api/classes");
    const items = data.items || [];
    if (!items.length) {
      tbody.innerHTML = `<tr><td class="py-2 text-slate-600" colspan="3">No classes yet.</td></tr>`;
      return;
    }
    tbody.innerHTML = items.map(c => `
      <tr class="border-b last:border-b-0">
        <td class="py-2 pr-2 font-medium">
          <span class="inline-flex items-center gap-2">
            ${c.is_recurring ? '<svg viewBox="0 0 24 24" class="h-4 w-4 text-slate-500" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/></svg>' : ""}
            ${escapeHtml(c.course_name)}
          </span>
        </td>
        <td class="py-2 pr-2 text-slate-700">${fmt(c.start_time)}</td>
        <td class="py-2 pr-2 text-slate-700">${c.end_time ? fmt(c.end_time) : "-"}</td>
        <td class="py-2 pr-2 text-slate-700">${escapeHtml(c.location)}</td>
        <td class="py-2 text-right">
          <div class="inline-flex items-center gap-2">
            <button data-class-id="${c.id}" class="btnEditClass px-2 py-1 rounded-lg border text-xs hover:bg-slate-50">
              Edit
            </button>
            <button data-class-id="${c.id}" class="btnDeleteClass px-2 py-1 rounded-lg border text-xs hover:bg-slate-50">
              Delete
            </button>
          </div>
        </td>
      </tr>
    `).join("");
    document.querySelectorAll(".btnDeleteClass").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-class-id");
        if (!id) return;
        if (!confirm("Delete this class?")) return;
        try {
          await api(`/api/classes/${id}`, { method: "DELETE" });
          await loadClasses();
        } catch (e) {
          alert(e.message);
        }
      });
    });
    document.querySelectorAll(".btnEditClass").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-class-id");
        const row = items.find((x) => String(x.id) === String(id));
        if (!row) return;
        startEdit(row);
      });
    });
  } catch (e) {
    tbody.innerHTML = `<tr><td class="py-2 text-red-600" colspan="5">${escapeHtml(e.message)}</td></tr>`;
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (m) => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  }[m]));
}

document.getElementById("btnDbTest").addEventListener("click", async () => {
  const out = document.getElementById("dbOut");
  out.textContent = "Running...";
  try {
    const data = await api("/api/db-test");
    out.textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    out.textContent = e.message;
  }
});

const notifyBtn = document.getElementById("btnNotifyTest");
if (notifyBtn) {
  notifyBtn.addEventListener("click", async () => {
    const out = document.getElementById("notifyOut");
    out.textContent = "Sending...";
    console.log("notify: sending test email");
    try {
      await api("/api/notify/test", { method: "POST" });
      console.log("notify: success");
      out.textContent = "Sent test email to your account.";
    } catch (e) {
      console.error("notify: failed", e);
      out.textContent = e.message;
    }
  });
}

const notifyDailyBtn = document.getElementById("btnNotifyDailyTest");
if (notifyDailyBtn) {
  notifyDailyBtn.addEventListener("click", async () => {
    const out = document.getElementById("notifyOut");
    out.textContent = "Sending daily reminder...";
    console.log("notify: sending daily reminder");
    try {
      await api("/api/notify/daily-test", { method: "POST" });
      console.log("notify: daily reminder success");
      out.textContent = "Sent daily reminder email.";
    } catch (e) {
      console.error("notify: daily reminder failed", e);
      out.textContent = e.message;
    }
  });
}

document.getElementById("btnRefresh").addEventListener("click", loadClasses);

let editingClassId = null;
const classForm = document.getElementById("classForm");
classForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const course_name = document.getElementById("courseName").value.trim();
  const start_time_local = document.getElementById("startTime").value;
  const end_time_local = document.getElementById("endTime").value;
  const location = document.getElementById("location").value.trim();
  const is_recurring = document.getElementById("repeatWeekly").checked;

  // datetime-local returns "YYYY-MM-DDTHH:mm" (no timezone).
  // We'll send it as ISO string with seconds for Postgres parsing.
  const start_time = start_time_local.length === 16 ? start_time_local + ":00" : start_time_local;
  const end_time = end_time_local.length === 16 ? end_time_local + ":00" : end_time_local;

  try {
    const method = editingClassId ? "PUT" : "POST";
    const path = editingClassId ? `/api/classes/${editingClassId}` : "/api/classes";
    await api(path, {
      method,
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ course_name, start_time, end_time, location, is_recurring })
    });
    resetEditForm();
    await loadClasses();
  } catch (e) {
    alert(e.message);
  }
});

const cancelEditBtn = document.getElementById("btnCancelEdit");
if (cancelEditBtn) {
  cancelEditBtn.addEventListener("click", () => {
    resetEditForm();
  });
}

function startEdit(row) {
  editingClassId = row.id;
  document.getElementById("courseName").value = row.course_name || "";
  document.getElementById("startTime").value = toLocalInput(row.start_time);
  document.getElementById("endTime").value = toLocalInput(row.end_time);
  document.getElementById("location").value = row.location || "";
  document.getElementById("repeatWeekly").checked = !!row.is_recurring;
  const saveBtn = document.getElementById("btnSaveClass");
  if (saveBtn) saveBtn.textContent = "Update class";
  if (cancelEditBtn) cancelEditBtn.classList.remove("hidden");
}

function resetEditForm() {
  editingClassId = null;
  classForm.reset();
  const repeat = document.getElementById("repeatWeekly");
  if (repeat) repeat.checked = false;
  const saveBtn = document.getElementById("btnSaveClass");
  if (saveBtn) saveBtn.textContent = "Save class";
  if (cancelEditBtn) cancelEditBtn.classList.add("hidden");
}

function toLocalInput(value) {
  if (!value) return "";
  const d = new Date(value);
  if (isNaN(d.getTime())) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function loadMe() {
  try {
    const me = await api("/api/auth/me");
    const name = [me.first_name, me.last_name].filter(Boolean).join(" ");
    const link = document.getElementById("userProfileLink");
    if (link) link.textContent = name || me.email;
  } catch {
    const loginLink = document.getElementById("loginLink");
    const logoutBtn = document.getElementById("btnLogout");
    if (loginLink) loginLink.classList.remove("hidden");
    if (logoutBtn) logoutBtn.classList.add("hidden");
  }
}

async function loadPreferences() {
  try {
    const prefs = await api("/api/preferences");
    document.getElementById("prefUbahn").checked = prefs.allow_ubahn;
    document.getElementById("prefSbahn").checked = prefs.allow_sbahn;
    document.getElementById("prefRegional").checked = prefs.allow_regional;
    document.getElementById("prefTram").checked = prefs.allow_tram;
    document.getElementById("prefBus").checked = prefs.allow_bus;
    document.getElementById("arrivalPref").value = prefs.timing_pref || "earlier";
    document.getElementById("arrivalTime").value = prefs.arrival_time || "";
    const from = document.getElementById("fromInput");
    userHomeLocation = prefs.home_location || "";
    if (from && !from.value && prefs.home_location) {
      from.value = prefs.home_location;
    }
    updateArrivalTimeState();
    updateRouteModeUI();
  } catch {}
}

async function savePreferences() {
  const payload = {
    allow_ubahn: document.getElementById("prefUbahn").checked,
    allow_sbahn: document.getElementById("prefSbahn").checked,
    allow_regional: document.getElementById("prefRegional").checked,
    allow_tram: document.getElementById("prefTram").checked,
    allow_bus: document.getElementById("prefBus").checked,
    timing_pref: document.getElementById("arrivalPref").value,
    arrival_time: document.getElementById("arrivalTime").value,
  };
  try {
    await api("/api/preferences", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {}
}

function updateArrivalTimeState() {
  const pref = document.getElementById("arrivalPref");
  const timeInput = document.getElementById("arrivalTime");
  if (!pref || !timeInput) return;
  if (pref.value === "now") {
    timeInput.value = "";
    timeInput.disabled = true;
  } else {
    timeInput.disabled = false;
  }
}

const logoutBtn = document.getElementById("btnLogout");
if (logoutBtn) {
  logoutBtn.addEventListener("click", async () => {
    await api("/api/auth/logout", { method: "POST" });
    window.location.href = "/login";
  });
}

function decodePolyline(str) {
  let index = 0;
  let lat = 0;
  let lng = 0;
  const coords = [];
  while (index < str.length) {
    let b = 0;
    let shift = 0;
    let result = 0;
    do {
      b = str.charCodeAt(index++) - 63;
      result |= (b & 0x1f) << shift;
      shift += 5;
    } while (b >= 0x20);
    const dlat = (result & 1) ? ~(result >> 1) : (result >> 1);
    lat += dlat;

    shift = 0;
    result = 0;
    do {
      b = str.charCodeAt(index++) - 63;
      result |= (b & 0x1f) << shift;
      shift += 5;
    } while (b >= 0x20);
    const dlng = (result & 1) ? ~(result >> 1) : (result >> 1);
    lng += dlng;
    coords.push([lat / 1e5, lng / 1e5]);
  }
  return coords;
}

let map;
let routeLayers = [];
let startMarker;
let endMarker;
let transferMarkers = [];
let routeMode = "toCampus";
let userHomeLocation = "";
let lastFromValue = "";
function initMap() {
  const el = document.getElementById("map");
  if (!el || !window.L) return;
  map = L.map(el).setView([52.52, 13.405], 12);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(map);
}

function clearRouteLayers() {
  if (!map) return;
  routeLayers.forEach((layer) => layer.remove());
  routeLayers = [];
}

function clearTransferMarkers() {
  if (!map) return;
  transferMarkers.forEach((m) => m.remove());
  transferMarkers = [];
}

function setRouteSegments(legs) {
  if (!map) return;
  clearRouteLayers();
  clearTransferMarkers();
  const bounds = [];
  legs.forEach((leg) => {
    const coords = legCoords(leg);
    if (!coords.length) return;
    const color = productColor(legProduct(leg));
    const layer = L.polyline(coords, { color, weight: 5 }).addTo(map);
    routeLayers.push(layer);
    coords.forEach((c) => bounds.push(c));
  });
  if (bounds.length) {
    map.fitBounds(bounds, { padding: [20, 20] });
  }
}

function setMarkers(start, end) {
  if (!map) return;
  if (startMarker) startMarker.remove();
  if (endMarker) endMarker.remove();
  const startLabel = routeMode === "return" ? "Campus" : "Start";
  const endLabel = routeMode === "return" ? "Home" : "Campus";
  const startIcon = L.divIcon({
    className: "start-marker",
    html: `<div style="background:#0f172a;color:#fff;font-size:11px;padding:4px 6px;border-radius:10px;">${startLabel}</div>`,
    iconSize: [50, 20],
    iconAnchor: [12, 10],
  });
  const endIcon = L.divIcon({
    className: "end-marker",
    html: `<div style="background:#10b981;color:#fff;font-size:11px;padding:4px 6px;border-radius:10px;">${endLabel}</div>`,
    iconSize: [60, 20],
    iconAnchor: [12, 10],
  });
  if (start) {
    startMarker = L.marker(start, { icon: startIcon }).addTo(map);
  }
  if (end) {
    endMarker = L.marker(end, { icon: endIcon }).addTo(map);
  }
}

function normalizeStopId(stop) {
  if (!stop) return null;
  const pickId = (val) => {
    if (!val || typeof val !== "string") return null;
    const last = val.includes(":") ? val.split(":").pop() : val;
    return last || null;
  };
  const ibnr = pickId(stop.ibnr);
  if (ibnr && /^[0-9]+$/.test(ibnr)) return ibnr;
  const id = pickId(stop.id);
  if (id && /^[0-9]+$/.test(id)) return id;
  if (stop.station && stop.station.id) {
    const sid = pickId(stop.station.id);
    if (sid && /^[0-9]+$/.test(sid)) return sid;
  }
  return null;
}

function extractCoords(item) {
  if (!item) return null;
  if (item.latitude && item.longitude) {
    return [item.latitude, item.longitude];
  }
  if (item.location && item.location.latitude && item.location.longitude) {
    return [item.location.latitude, item.location.longitude];
  }
  return null;
}

function legTitle(leg) {
  const mode = leg.mode || "Travel";
  const line = leg.line && leg.line.name ? ` ${leg.line.name}` : "";
  const from = leg.origin && leg.origin.name ? leg.origin.name : "Start";
  const to = leg.destination && leg.destination.name ? leg.destination.name : "End";
  return `${mode}${line}: ${from} -> ${to}`;
}

function timeShort(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

function legProduct(leg) {
  if (leg.line && leg.line.product) return leg.line.product;
  if (leg.mode) return leg.mode;
  return "walk";
}

function productMeta(product) {
  const map = {
    subway: { label: "U-Bahn", logo: "/static/img/U-Bahn.svg.png" },
    suburban: { label: "S-Bahn", logo: "/static/img/S-Bahn-Logo.svg.png" },
    regional: { label: "Regional", logo: "/static/img/DB Logo.png" },
    tram: { label: "Tram", logo: "/static/img/Tram-Logo.svg" },
    bus: { label: "Bus", logo: "/static/img/BUS-Logo-BVG.svg.png" },
    walk: { label: "Walk", logo: "/static/img/Walk Logo.webp" },
  };
  return map[product] || { label: product || "Travel", logo: "" };
}

function productColor(product) {
  const colors = {
    subway: "#2563eb",
    suburban: "#16a34a",
    regional: "#dc2626",
    tram: "#9333ea",
    bus: "#f97316",
    walk: "#64748b",
  };
  return colors[product] || "#10b981";
}

function addTransferMarkers(legs) {
  if (!map) return;
  for (let i = 0; i < legs.length - 1; i++) {
    const curr = legs[i];
    const next = legs[i + 1];
    const currProduct = legProduct(curr);
    const nextProduct = legProduct(next);
    if (currProduct === nextProduct) continue;
    const loc = curr.destination && curr.destination.location;
    if (!loc) continue;
    const lat = loc.latitude || loc.lat;
    const lon = loc.longitude || loc.lon;
    if (lat == null || lon == null) continue;
    const color = productColor(nextProduct);
    const marker = L.circleMarker([lat, lon], {
      radius: 6,
      color,
      fillColor: color,
      fillOpacity: 0.9,
      weight: 2,
    }).addTo(map);
    transferMarkers.push(marker);
  }
}

function legCoords(leg) {
  const coords = [];
  if (leg.polyline) {
    if (typeof leg.polyline === "string") {
      coords.push(...decodePolyline(leg.polyline));
    } else if (leg.polyline.points) {
      coords.push(...decodePolyline(leg.polyline.points));
    } else if (Array.isArray(leg.polyline)) {
      leg.polyline.forEach((p) => coords.push([p.latitude || p.lat, p.longitude || p.lon]));
    }
  }
  if (!coords.length) {
    const o = leg.origin && leg.origin.location;
    const d = leg.destination && leg.destination.location;
    if (o && d) {
      coords.push([o.latitude || o.lat, o.longitude || o.lon]);
      coords.push([d.latitude || d.lat, d.longitude || d.lon]);
    }
  }
  return coords;
}

function renderLegCard(leg) {
  const from = leg.origin && leg.origin.name ? leg.origin.name : "Start";
  const to = leg.destination && leg.destination.name ? leg.destination.name : "End";
  const dep = timeShort(leg.departure);
  const arr = timeShort(leg.arrival);
  const rawLine = (leg.line && leg.line.name) || leg.mode || "Walk";
  const lineName = rawLine.toLowerCase() === "walk" ? "Walk" : rawLine;
  const product = legProduct(leg);
  const meta = productMeta(product);
  const color = productColor(product);
  const logo = meta.logo
    ? `<img src="${meta.logo}" alt="${escapeHtml(meta.label)}" class="h-4 w-auto" onerror="this.style.display='none'" />`
    : "";
  const showMeta = product !== "walk";
  const metaSpan = showMeta
    ? `<span class="text-slate-500">${escapeHtml(meta.label)}</span>`
    : "";
  const timeSpan = showMeta
    ? `<div class="text-slate-600">${escapeHtml(dep)}${arr ? " - " + escapeHtml(arr) : ""}</div>`
    : "";
  return `
    <div class="rounded-xl border p-3" style="border-color:${color}66;background:linear-gradient(180deg, ${color}33, #f8fafc);">
      <div class="flex items-center justify-between text-sm">
        <div class="flex items-center gap-2">
          ${logo}
          <span class="font-semibold">${escapeHtml(lineName)}</span>
          ${metaSpan}
        </div>
        ${timeSpan}
      </div>
      <div class="mt-1 text-sm text-slate-700">${escapeHtml(from)} -> ${escapeHtml(to)}</div>
    </div>
  `;
}

async function loadRoute() {
  const fromInput = document.getElementById("fromInput");
  const toInput = document.getElementById("toInput");
  const from = routeMode === "return" ? "Campus Jungfernsee" : (fromInput.value || "").trim();
  const to = routeMode === "return" ? (userHomeLocation || "").trim() : "Campus Jungfernsee";
  const list = document.getElementById("routeSteps");
  list.innerHTML = "";
  if (!from) {
    list.innerHTML = `<div class="text-sm text-slate-600">Please enter your start location.</div>`;
    return;
  }
  if (routeMode === "return" && !to) {
    list.innerHTML = `<div class="text-sm text-slate-600">Please set your home address in signup.</div>`;
    return;
  }
  try {
    let fromStop = await resolveLocation(from);
    let toStop = await resolveLocation(to);
    fromStop = await normalizeToNearestStop(fromStop);
    toStop = await normalizeToNearestStop(toStop);
    const params = new URLSearchParams();
    if (fromStop.id && toStop.id) {
      params.set("from", fromStop.id);
      params.set("to", toStop.id);
    } else {
      if (!fromStop.coords || !toStop.coords) {
        throw new Error("Please pick a valid stop or address.");
      }
      params.set("from.latitude", String(fromStop.coords[0]));
      params.set("from.longitude", String(fromStop.coords[1]));
      params.set("from.name", fromStop.name || "Start");
      params.set("to.latitude", String(toStop.coords[0]));
      params.set("to.longitude", String(toStop.coords[1]));
      params.set("to.name", toStop.name || "Destination");
    }
    params.set("results", "1");
    params.set("polylines", "true");

    const allowU = document.getElementById("prefUbahn").checked;
    const allowS = document.getElementById("prefSbahn").checked;
    const allowR = document.getElementById("prefRegional").checked;
    const allowT = document.getElementById("prefTram").checked;
    const allowB = document.getElementById("prefBus").checked;
    params.set("products[subway]", String(allowU));
    params.set("products[suburban]", String(allowS));
    params.set("products[regional]", String(allowR));
    params.set("products[tram]", String(allowT));
    params.set("products[bus]", String(allowB));

    const pref = document.getElementById("arrivalPref").value;
    const time = document.getElementById("arrivalTime").value;
    if (pref !== "now" && time) {
      const now = new Date();
      const [hh, mm] = time.split(":").map((v) => parseInt(v, 10));
      const target = new Date(now.getFullYear(), now.getMonth(), now.getDate(), hh, mm, 0, 0);
      const offset = pref === "later" ? 10 : -10;
      target.setMinutes(target.getMinutes() + offset);
      params.set("arrival", target.toISOString());
    }

    if (pref !== "now") {
      await savePreferences();
    }
    const data = await api(`/api/bvg/journeys?${params.toString()}`);
    const journey = data.journeys && data.journeys[0];
    if (!journey || !journey.legs) {
      list.innerHTML = `<div class="text-sm text-slate-600">No route found.</div>`;
      clearRouteLayers();
      return;
    }
    setRouteSegments(journey.legs);
    addTransferMarkers(journey.legs);
    const firstLeg = journey.legs[0];
    const lastLeg = journey.legs[journey.legs.length - 1];
    const startLoc = firstLeg && firstLeg.origin && firstLeg.origin.location;
    const endLoc = lastLeg && lastLeg.destination && lastLeg.destination.location;
    if (startLoc && endLoc) {
      setMarkers(
        [startLoc.latitude || startLoc.lat, startLoc.longitude || startLoc.lon],
        [endLoc.latitude || endLoc.lat, endLoc.longitude || endLoc.lon]
      );
    }
    list.innerHTML = journey.legs.map(renderLegCard).join("");
    if (fromInput && toInput) {
      if (routeMode === "return") {
        fromInput.value = "Campus Jungfernsee";
        toInput.value = userHomeLocation || "Home";
      } else {
        if (fromStop && fromStop.name) {
          fromInput.value = fromStop.name;
        }
        toInput.value = "Campus Jungfernsee";
      }
    }
  } catch (e) {
    list.innerHTML = `<div class="text-sm text-red-600">${escapeHtml(e.message)}</div>`;
  }
}

const routeBtn = document.getElementById("btnRoute");
if (routeBtn) {
  routeBtn.addEventListener("click", loadRoute);
}

const arrivalPref = document.getElementById("arrivalPref");
if (arrivalPref) {
  arrivalPref.addEventListener("change", () => {
    updateArrivalTimeState();
  });
}

function updateRouteModeUI() {
  const fromInput = document.getElementById("fromInput");
  const toInput = document.getElementById("toInput");
  if (!fromInput || !toInput) return;
  if (routeMode === "return") {
    lastFromValue = fromInput.value || lastFromValue;
    fromInput.value = "Campus Jungfernsee";
    fromInput.readOnly = true;
    toInput.value = userHomeLocation || "Home";
    toInput.readOnly = true;
  } else {
    fromInput.readOnly = false;
    fromInput.value = lastFromValue || userHomeLocation || "";
    toInput.value = "Campus Jungfernsee";
    toInput.readOnly = true;
  }
}

const swapBtn = document.getElementById("btnSwapRoute");
if (swapBtn) {
  swapBtn.addEventListener("click", () => {
    routeMode = routeMode === "toCampus" ? "return" : "toCampus";
    updateRouteModeUI();
  });
}

const fromInputEl = document.getElementById("fromInput");
if (fromInputEl) {
  fromInputEl.addEventListener("blur", async () => {
    if (routeMode !== "toCampus") return;
    const value = (fromInputEl.value || "").trim();
    if (!value) return;
    try {
      let loc = await resolveLocation(value);
      loc = await normalizeToNearestStop(loc);
      if (loc && loc.name) {
        fromInputEl.value = loc.name;
      }
    } catch {}
  });
}


async function resolveLocation(query) {
  const data = await api(`/api/bvg/locations?query=${encodeURIComponent(query)}&results=5`);
  const candidates = Array.isArray(data) ? data : data.items || [];
  const stop = candidates.find((c) => c && normalizeStopId(c));
  if (stop) {
    const coords = extractCoords(stop);
    return {
      id: normalizeStopId(stop),
      name: stop.name || query,
      coords: coords || null,
    };
  }
  const fallback = candidates.find((c) => extractCoords(c));
  if (fallback) {
    return {
      id: null,
      name: fallback.name || query,
      coords: extractCoords(fallback),
    };
  }
  try {
    const geo = await api(`/api/geocode?query=${encodeURIComponent(query)}`);
    return {
      id: null,
      name: geo.name || query,
      coords: [geo.latitude, geo.longitude],
    };
  } catch {}
  if (!candidates.length) {
    throw new Error(`No stop found for "${query}".`);
  }
  throw new Error(`No stop or address found for "${query}".`);
}

async function resolveStopByCoords(lat, lon) {
  const params = new URLSearchParams();
  params.set("latitude", String(lat));
  params.set("longitude", String(lon));
  params.set("results", "5");
  params.set("stops", "true");
  params.set("addresses", "false");
  params.set("poi", "false");
  const data = await api(`/api/bvg/locations/nearby?${params.toString()}`);
  const candidates = Array.isArray(data) ? data : data.items || [];
  const stop = candidates.find(
    (c) =>
      c &&
      c.id &&
      (c.type === "stop" || c.type === "station" || !c.type) &&
      normalizeStopId(c)
  );
  if (!stop) {
    throw new Error("No nearby stop found.");
  }
  return {
    id: normalizeStopId(stop),
    name: stop.name || "Nearby stop",
    coords: extractCoords(stop),
  };
}

async function normalizeToNearestStop(loc) {
  if (!loc || loc.id) return loc;
  if (!loc.coords) return loc;
  try {
    const stop = await resolveStopByCoords(loc.coords[0], loc.coords[1]);
    return {
      id: stop.id,
      name: stop.name || loc.name,
      coords: stop.coords || loc.coords,
    };
  } catch {
    return loc;
  }
}

const useLocationBtn = document.getElementById("btnUseLocation");
if (useLocationBtn) {
  useLocationBtn.addEventListener("click", async () => {
    const list = document.getElementById("routeSteps");
    list.innerHTML = "";
    if (!navigator.geolocation) {
      list.innerHTML = `<li class="text-red-600">Geolocation is not supported.</li>`;
      return;
    }
    useLocationBtn.disabled = true;
    useLocationBtn.textContent = "Locating...";
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          const stop = await resolveStopByCoords(pos.coords.latitude, pos.coords.longitude);
          document.getElementById("fromInput").value = stop.name || stop.id;
        } catch (e) {
          list.innerHTML = `<li class="text-red-600">${escapeHtml(e.message)}</li>`;
        } finally {
          useLocationBtn.disabled = false;
          useLocationBtn.textContent = "Use my location";
        }
      },
      (err) => {
        list.innerHTML = `<li class="text-red-600">${escapeHtml(err.message)}</li>`;
        useLocationBtn.disabled = false;
        useLocationBtn.textContent = "Use my location";
      },
      { enableHighAccuracy: true, timeout: 8000 }
    );
  });
}

initMap();
loadMe();
loadPreferences();
loadClasses();
