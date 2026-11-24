"use strict";
/* Nexus Grid UI. Behaviour and motion follow docs/design/DESIGN.md. No framework. */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const sleep = ms => new Promise(r => setTimeout(r, ms));
const LS = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };
const PALETTE = ["#22D3EE", "#A78BFA", "#34D399", "#FBBF24", "#F472B6", "#60A5FA"];
const HIST = 120, SPARK = 60;
const RMQ = matchMedia("(prefers-reduced-motion: reduce)");
let RM = RMQ.matches;
const applyRM = () => { RM = RMQ.matches; document.body.classList.toggle("rm", RM); };
RMQ.addEventListener?.("change", applyRM); applyRM();

const S = {
  base: (new URLSearchParams(location.search).get("server") || LS.get("nexus.server") || "").replace(/\/$/, ""),
  key: LS.get("nexus.key") || "", keyShown: false, desktop: null, mode: "observer", loaded: false,
  workers: new Map(), job: null, tiles: [], assigned: new Map(), colorOf: new Map(),
  m: { tps: 0, lat: 0, alive: 0, total: 0, queue: 0, jobs: 0 }, lastLat: [], spark: { tps: [], lat: [], alive: [], queue: [], jobs: [] },
  queueNow: 0, memMode: "mem", hidden: new Set(), diag: [], lastEvent: 0,
};
const diag = m => { S.diag.push(`${new Date().toISOString()} ${m}`); if (S.diag.length > 300) S.diag.shift(); };
const hhmmss = d => d.toTimeString().slice(0, 8);
const wsBase = () => S.base ? S.base.replace(/^http/, "ws") : (location.protocol === "https:" ? "wss://" : "ws://") + location.host;
const apiUrl = p => S.base + p;
async function api(path, opt = {}) {
  const headers = { ...(opt.headers || {}) };
  if (S.key) headers["X-API-Key"] = S.key;
  if (opt.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const r = await fetch(apiUrl(path), { ...opt, headers });
  if (r.status === 401) { setError("AUTH_401", "Invalid API Key"); }
  return r;
}
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("on"); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("on"), 2600); }
async function copyText(txt) {
  try { await navigator.clipboard.writeText(txt); } catch (e) { const a = document.createElement("textarea"); a.value = txt; document.body.append(a); a.select(); document.execCommand("copy"); a.remove(); }
  toast("Copied");
}

/* ---------- worker model ---------- */
function colorFor(id) {
  if (S.colorOf.has(id)) return S.colorOf.get(id);
  let h = 0; for (const c of id) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  const used = new Set([...S.workers.values()].filter(w => w.alive).map(w => w.color));
  let i = h % PALETTE.length;
  for (let k = 0; k < PALETTE.length && used.has(PALETTE[i]); k++) i = (i + 1) % PALETTE.length;
  S.colorOf.set(id, PALETTE[i]); return PALETTE[i];
}
function upsertWorker(w) {
  let v = S.workers.get(w.id);
  if (!v) {
    v = { id: w.id, color: colorFor(w.id), hist: { cpu: [], mem: [], temp: [], tp: [], lat: [] }, doneTimes: [], lat: 0, lastSeen: performance.now(), lostAt: 0, lostAfter: 0 };
    S.workers.set(w.id, v);
  }
  Object.assign(v, { name: w.name, alive: w.alive, busy: w.busy, demo: !!w.demo, done: w.done || v.done || 0, metrics: w.metrics || v.metrics || {} });
  return v;
}
const aliveWorkers = () => [...S.workers.values()].filter(w => w.alive);

/* ---------- connection state ---------- */
const C = { state: "init", gen: 0, attempt: 0, ws: null, t0: 0, wantDemo: false, sleepTimer: null };
function setConn(state, extra = "") {
  C.state = state;
  const el = $("#conn"), txt = $("#conn-text");
  el.className = state === "online" ? "" : state === "reconnecting" ? "reconnecting" : state === "error" ? "error" : "waking";
  const t = { online: "Connected", reconnecting: `Reconnecting · Attempt ${C.attempt}/5`, error: extra || "Disconnected", probing: "Connecting", sleeping: "Waking up server" }[state];
  txt.textContent = t;
  $("#conn-micro").textContent = state === "online" ? "ONLINE" : state === "reconnecting" ? "RECONNECTING" : state === "error" ? "OFFLINE" : "WAKING";
  $("#retry").hidden = !(state === "reconnecting" || state === "error");
  $("#bar-amber").hidden = state !== "reconnecting";
  $("#hud").classList.toggle("frozen", state === "reconnecting");
  document.body.classList.toggle("err-state", state === "error");
  diag(`state ${state}${state === "reconnecting" ? " attempt " + C.attempt : ""}`);
  updateEmpty();
}
async function probe() {
  const ctl = new AbortController(), to = setTimeout(() => ctl.abort(), 4000);
  try { const r = await fetch(apiUrl("/api/health"), { signal: ctl.signal, cache: "no-store" }); return { ok: r.ok, any: true }; }
  catch (e) { return { ok: false, any: false }; } finally { clearTimeout(to); }
}
const fmtMS = s => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
function showSleep(on) {
  $("#sleep").hidden = !on;
  clearInterval(C.sleepTimer);
  if (!on) return;
  const tick = () => { const s = (performance.now() - C.t0) / 1000; $("#sl-t").textContent = fmtMS(s); if (RM) $("#sl-t").textContent = fmtMS(s); };
  tick(); C.sleepTimer = setInterval(tick, 1000);
}
function setStep(n) { ["st1", "st2", "st3"].forEach((id, i) => $("#" + id).className = i + 1 < n ? "ok" : i + 1 === n ? "now" : ""); }
async function startConn() {
  const g = ++C.gen; C.t0 = performance.now();
  try { C.ws && C.ws.close(); } catch (e) {}
  clearBanner("WS_1006");
  setConn("probing"); setStep(1);
  let shown = false, gotAny = false;
  const skel = setTimeout(() => { if (!S.loaded) document.body.classList.add("loading"); }, 150);
  for (;;) {
    const r = await probe();
    if (g !== C.gen) return;
    gotAny = gotAny || r.any;
    if (r.ok) break;
    const el = (performance.now() - C.t0) / 1000;
    if (!shown && el > 1.5) { shown = true; showSleep(true); setConn("sleeping"); }
    setStep(gotAny || el > 15 ? 2 : 1);
    await sleep(1000);
  }
  clearTimeout(skel);
  if (shown) setStep(3);
  const ok = await openWs(g);
  if (g !== C.gen) return;
  if (!ok) return startConnRetry(g);
  showSleep(false);
  if (C.wantDemo) { C.wantDemo = false; launchDemo(); }
}
async function startConnRetry(g) { await sleep(1000); if (g === C.gen) startConn(); }
function openWs(g) {
  return new Promise(res => {
    let opened = false;
    let ws; try { ws = new WebSocket(wsBase() + "/ws/events"); } catch (e) { res(false); return; }
    C.ws = ws;
    const to = setTimeout(() => { if (!opened) ws.close(); }, 8000);
    ws.onopen = () => { opened = true; clearTimeout(to); C.attempt = 0; clearBanner("WS_1006"); setConn("online"); res(true); };
    ws.onmessage = m => { try { onEvent(JSON.parse(m.data)); } catch (e) { console.warn(e); } };
    ws.onclose = () => { clearTimeout(to); if (g !== C.gen) { res(false); return; } if (!opened) res(false); else reconnect(g); };
    ws.onerror = () => {};
  });
}
async function reconnect(g) {
  const delays = [1, 2, 4, 8, 15];
  for (let n = 1; n <= 5; n++) {
    C.attempt = n; setConn("reconnecting");
    await sleep(delays[n - 1] * 1000);
    if (g !== C.gen) return;
    if (await openWs(g)) return;
    if (g !== C.gen) return;
  }
  setConn("error", "Cluster Unreachable");
  setError("WS_1006", "Cluster Unreachable");
}

/* ---------- error banner ---------- */
function setError(code, msg) {
  if (!$("#banner").hidden && $("#banner-code").textContent === code) return;
  $("#banner").hidden = false; $("#banner-code").textContent = code; $("#banner-msg").textContent = msg;
  $("#b-key").hidden = code !== "AUTH_401"; $("#b-reconnect").hidden = code === "AUTH_401" && C.state === "online";
  $$("#hud, #mosaic-panel, #graph-panel").forEach(e => e.classList.add("err"));
  diag(`error ${code} ${msg}`); document.body.classList.add("has-banner");
}
function clearBanner(code) {
  if ($("#banner").hidden || (code && $("#banner-code").textContent !== code)) return;
  $("#banner").hidden = true; $$(".err").forEach(e => e.classList.remove("err")); document.body.classList.remove("has-banner");
}

/* ---------- odometer + sparkline ---------- */
function odo(el, text) {
  const prev = el.dataset.v;
  if (prev === text) return;
  el.dataset.v = text;
  if (prev === undefined || RM) { el.textContent = text; return; }
  const cur = [...text], old = [...prev], off = old.length - cur.length;
  el.textContent = "";
  cur.forEach((c, i) => {
    const slot = document.createElement("span"); slot.className = "od-ch";
    const o = old[i + off], now = document.createElement("span"); now.textContent = c; slot.append(now);
    if (o !== undefined && o !== c && /\d/.test(c) && /\d/.test(o)) {
      const was = document.createElement("span"); was.className = "old"; was.textContent = o; slot.append(was);
      const opt = { duration: 260, easing: "cubic-bezier(.2,.8,.2,1)", fill: "both" };
      now.animate([{ transform: "translateY(100%)" }, { transform: "none" }], opt);
      was.animate([{ transform: "none" }, { transform: "translateY(-100%)" }], opt).onfinish = () => was.remove();
    }
    el.append(slot);
  });
}
function drawSpark(svg, data, color, first) {
  if (!svg.firstChild) svg.innerHTML = `<defs><linearGradient id="sg-${svg.parentNode.dataset.k}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".35"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs><g><path class="a" fill="url(#sg-${svg.parentNode.dataset.k})"/><path class="l" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke" pathLength="1"/></g>`;
  const max = Math.max(1e-6, ...data) * 1.15, n = data.length, step = 100 / (SPARK - 1);
  const pts = data.map((v, i) => [100 - (n - 1 - i) * step, 28 - 26 * v / max]);
  const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join("");
  const l = svg.querySelector(".l"), a = svg.querySelector(".a"), g = svg.querySelector("g");
  l.setAttribute("d", d); a.setAttribute("d", pts.length ? d + `L100 30L${pts[0][0].toFixed(1)} 30Z` : "");
  if (RM) return;
  if (first) { l.style.strokeDasharray = 1; l.animate([{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], { duration: 550, easing: "cubic-bezier(.25,1,.5,1)" }); }
  else g.animate([{ transform: `translateX(${step}px)` }, { transform: "none" }], { duration: 300, easing: "linear" });
}
const SPARK_COLOR = { tps: "#22D3EE", lat: "#60A5FA", alive: "#10B981", queue: "#22D3EE", jobs: "#10B981" };
const sparkMounted = {};
function sampleHud() {
  if (C.state === "reconnecting") return;                       // frozen while reconnecting
  const m = S.m, vals = { tps: m.tps, lat: m.lat, alive: m.alive, queue: m.queue, jobs: m.jobs };
  for (const k in vals) {
    const arr = S.spark[k]; arr.push(vals[k]); if (arr.length > SPARK) arr.shift();
    const svg = $(`.card[data-k=${k}] .spark`);
    if (svg) { drawSpark(svg, arr, k === "alive" && m.alive < m.total ? "#F59E0B" : SPARK_COLOR[k], !sparkMounted[k] && arr.length > 1); if (arr.length > 1) sparkMounted[k] = true; }
  }
}
function renderHud() {
  if (C.state === "reconnecting") return;
  const m = S.m;
  odo($("#v-tps"), m.tps.toFixed(1)); odo($("#v-lat"), m.lat ? String(Math.round(m.lat)) : "-");
  odo($("#v-alive"), `${m.alive}/${m.total}`); odo($("#v-queue"), String(m.queue)); odo($("#v-jobs"), String(m.jobs));
  $("#card-alive").classList.toggle("fail", m.total > 0 && m.alive < m.total);
}
async function pollMetrics() {
  if (C.state !== "online") return;
  try {
    const m = await (await fetch(apiUrl("/api/metrics"), { cache: "no-store" })).json();
    const l = S.lastLat.slice(-10);
    Object.assign(S.m, { tps: m.tasks_per_s, alive: m.workers_alive, total: m.workers_total, queue: m.queue_depth, jobs: m.jobs_done || 0,
      lat: l.length ? l.reduce((a, b) => a + b) / l.length : 0 });
    S.queueNow = m.queue_depth; renderHud(); updateEmpty();
  } catch (e) {}
}

/* ---------- mosaic ---------- */
const mosaic = $("#mosaic");
function jobGeometry(j) {
  if (j.type === "image") { const n = j.params.count || j.total, cols = Math.ceil(Math.sqrt(n * 4 / 3)); return { cols, rows: Math.ceil(n / cols), n, tile: 0 }; }
  const p = j.params, cols = Math.ceil(p.width / p.tile), rows = Math.ceil(p.height / p.tile);
  return { cols, rows, n: cols * rows, tile: p.tile, w: p.width, h: p.height, max: p.max_iter };
}
function buildMosaic(job) {
  mosaic.innerHTML = ""; S.tiles = []; S.assigned.clear();
  const wire = !job, g = job ? jobGeometry(job) : { cols: 16, rows: 12, n: 192 };
  document.body.classList.toggle("wire", wire);
  mosaic.style.gridTemplateColumns = `repeat(${g.cols}, 1fr)`; mosaic.style.gridTemplateRows = `repeat(${g.rows}, 1fr)`; mosaic.style.setProperty("--ar", `${g.cols} / ${g.rows}`);
  const frag = document.createDocumentFragment();
  for (let i = 0; i < g.n; i++) {
    const el = document.createElement("div"); el.className = "tile"; el.dataset.i = i;
    el.innerHTML = `<i class="ring"></i>`;
    if (job && job.type === "image") { const s = document.createElement("span"); s.className = "idx"; s.textContent = i + 1; el.append(s); }
    frag.append(el); S.tiles.push({ el, state: "pending", worker: null, ms: 0, canvas: null });
  }
  mosaic.append(frag);
  S.geo = g; updateMosaicTitle(); updateFoot();
}
function updateFoot() {
  const j = S.job, c = { pending: 0, active: 0, done: 0, orphan: 0 }; S.tiles.forEach(t => c[t.state] = (c[t.state] || 0) + 1);
  $("#mosaic-foot").innerHTML = `<span><i style="--c:#0B1120;outline:1px solid #334155"></i>Pending ${c.pending}</span><span><i style="--c:#22D3EE"></i>Computing ${c.active}</span><span><i style="--c:#10B981"></i>Done ${c.done}</span><span><i style="--c:#EF4444"></i>Reassigning ${c.orphan}</span><span class="sp">${j ? `job #${j.id} · ${j.done}/${j.total}` : "no job"}</span>`;
}
function updateMosaicTitle() {
  const j = S.job, pct = j ? Math.round(100 * j.done / Math.max(j.total, 1)) : 0;
  const base = !j ? "Mandelbrot Mosaic (192 Tiles)" : j.type === "image" ? `Image Batch (${j.total} Files)` : `Mandelbrot Mosaic (${j.total} Tiles)`;
  $("#mosaic-title").textContent = compact() && j ? `${j.type === "image" ? "Image Batch" : "Mandelbrot Mosaic"} — ${pct}%` : base;
}
function tileIndex(job, tile) { return job.type === "image" ? tile[0] : tile[1] * S.geo.cols + tile[0]; }
function setTile(i, state, w) {
  const t = S.tiles[i]; if (!t) return;
  clearTimeout(setTile.f); setTile.f = setTimeout(updateFoot, 150);
  const prev = t.state; t.state = state; if (w) t.worker = w;
  const el = t.el, wk = t.worker && S.workers.get(t.worker);
  if (wk) el.style.setProperty("--wc", wk.color);
  el.classList.toggle("active", state === "active");
  el.classList.toggle("orphan", state === "orphan");
  el.classList.toggle("done", state === "done");
  if (state === "done" && prev !== "done" && !RM) { el.classList.remove("fill"); void el.offsetWidth; el.classList.add("fill"); }
  if (state === "done" && RM) { el.classList.add("fill"); }
}
const decodeCache = new Map();
async function decodeTile(buf, max) {
  const dv = new DataView(buf), w = dv.getUint16(5), h = dv.getUint16(7);
  const raw = await new Response(new Blob([buf.slice(9)]).stream().pipeThrough(new DecompressionStream("deflate"))).arrayBuffer();
  const it = new Uint16Array(raw), img = new ImageData(w, h);
  for (let i = 0; i < it.length; i++) {
    const v = it[i], o = i * 4; img.data[o + 3] = 255;
    if (v >= max) continue;
    const c = ((v * 255 / 64) | 0) & 255; img.data[o] = LUT[c * 3]; img.data[o + 1] = LUT[c * 3 + 1]; img.data[o + 2] = LUT[c * 3 + 2];
  }
  return img;
}
const LUT = (() => { const a = new Uint8ClampedArray(768); for (let i = 0; i < 256; i++) for (let k = 0; k < 3; k++) a[i * 3 + k] = 255 * (0.5 + 0.5 * Math.sin(6.28 * (i / 255 * 3 + k * 0.33))); return a; })();
async function loadTile(taskId, i, job) {
  if (job.type !== "mandelbrot") return;
  const t0 = S.tiles[i]; if (t0) { t0.taskId = taskId; t0.tries = (t0.tries || 0) + 1; t0.doneAt = performance.now(); }
  try {
    const r = await fetch(apiUrl(`/api/tiles/${taskId}`)); if (!r.ok) return;
    const img = await decodeTile(await r.arrayBuffer(), S.geo.max);
    if (S.job !== job) return;
    const t = S.tiles[i]; if (!t) return;
    if (!t.canvas) { t.canvas = document.createElement("canvas"); t.el.prepend(t.canvas); }
    t.canvas.width = img.width; t.canvas.height = img.height; t.canvas.getContext("2d").putImageData(img, 0, 0);
  } catch (e) { console.warn("tile", e); }
}
/* Idempotent repair: the picture is always derived from state, so a skipped event or a view switch cannot leave it stale. */
function reconcileTiles() {
  const j = S.job; if (!j) return;
  S.tiles.forEach(t => {
    const el = t.el;
    for (const c of ["active", "orphan", "done"]) { const on = t.state === c; if (el.classList.contains(c) !== on) el.classList.toggle(c, on); }
    const wk = t.worker && S.workers.get(t.worker); if (wk) el.style.setProperty("--wc", wk.color);
    if (t.state === "done" && !t.canvas && t.taskId && j.type === "mandelbrot" && t.tries < 4 && performance.now() - t.doneAt > 1500) loadTile(t.taskId, +el.dataset.i, j);
  });
  updateMosaicTitle();
}
function newJob(j) {
  S.job = { id: j.id, type: j.type, total: j.total, done: j.done, state: j.state, priority: j.priority || 0, params: j.params, lastDec: 0 };
  S.job.lastDec = Math.floor(10 * j.done / Math.max(j.total, 1));
  buildMosaic(S.job); renderJob();
}
async function followJob(id) {
  S.switching = true;
  try { const r = await fetch(apiUrl(`/api/jobs/${id}`)); if (r.ok) await restoreJob(await r.json()); } catch (e) {} finally { S.switching = false; }
}
async function restoreJob(j) {
  newJob(j);
  try {
    const list = await (await fetch(apiUrl(`/api/jobs/${j.id}/tiles`))).json();
    for (const t of list) { const i = S.job.type === "image" ? t.tx : t.ty * S.geo.cols + t.tx; setTile(i, "done", t.worker_id); loadTile(t.task_id, i, S.job); }
  } catch (e) {}
}
mosaic.addEventListener("mousemove", ev => {
  const el = ev.target.closest(".tile"), tip = $("#tip");
  if (!el) { tip.classList.remove("on"); return; }
  const t = S.tiles[+el.dataset.i], w = t.worker && S.workers.get(t.worker), n = +el.dataset.i + 1;
  tip.textContent = t.state === "done" ? `${w ? w.name : "worker"} · ${t.ms ? t.ms + "ms" : "done"}` : t.state === "active" ? `Computing · ${w ? w.name : ""}` :
    t.state === "orphan" ? "Reassigning…" : `Tile #${n} · pending`;
  tip.style.left = Math.min(ev.clientX + 14, innerWidth - 180) + "px"; tip.style.top = ev.clientY + 14 + "px"; tip.classList.add("on");
});
mosaic.addEventListener("mouseleave", () => $("#tip").classList.remove("on"));
const blobB64 = b => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result.split(",")[1]); r.onerror = () => rej(r.error); r.readAsDataURL(b); });
async function saveBlob(name, blob) {
  if (S.desktop) {                                        // pywebview blocks anchor downloads: native save dialog via Python
    try {
      const r = await S.desktop.save_file(name, await blobB64(blob));
      toast(r.ok ? `Saved ${r.path}` : r.cancelled ? "Save cancelled" : `Save failed: ${r.error}`);
    } catch (e) { toast("Save failed: " + e); }
    return;
  }
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000); toast(`Downloading ${name}`);
}
function composePNG() {
  const j = S.job; if (!j || j.type !== "mandelbrot" || !S.geo.w) return toast("Nothing to save yet");
  const c = document.createElement("canvas"); c.width = S.geo.w; c.height = S.geo.h; const x = c.getContext("2d");
  x.fillStyle = "#050811"; x.fillRect(0, 0, c.width, c.height);
  S.tiles.forEach((t, i) => { if (t.canvas) x.drawImage(t.canvas, (i % S.geo.cols) * S.geo.tile, Math.floor(i / S.geo.cols) * S.geo.tile); });
  c.toBlob(b => b ? saveBlob(`mandelbrot-job${j.id}.png`, b) : toast("Could not create the image"));
}
async function downloadZip() {
  const j = S.job; const url = apiUrl(`/api/jobs/${j.id}/download`);
  if (!S.desktop) { location.href = url; toast(`Downloading job${j.id}.zip`); return; }
  try { const r = await fetch(url); if (!r.ok) throw new Error("HTTP " + r.status); await saveBlob(`job${j.id}.zip`, await r.blob()); }
  catch (e) { toast("Download failed: " + e.message); }
}

/* ---------- fly helper (WAAPI, transform only) ---------- */
const qb = (a, c, b, t) => ({ x: (1 - t) * (1 - t) * a.x + 2 * (1 - t) * t * c.x + t * t * b.x, y: (1 - t) * (1 - t) * a.y + 2 * (1 - t) * t * c.y + t * t * b.y });
function fly(parent, fn, dur, color, size, { delay = 0, easing = "linear", scale = null, glow = 12 } = {}) {
  if (RM || parent.childElementCount > 60) return;
  const d = document.createElement("i"); d.className = "fx-dot";
  Object.assign(d.style, { width: size + "px", height: size + "px", background: color, boxShadow: `0 0 ${glow}px ${color}` });
  parent.append(d);
  const kf = []; for (let k = 0; k <= 20; k++) { const t = k / 20, p = fn(t), s = scale ? scale(t) : 1; kf.push({ transform: `translate(${p.x - size / 2}px,${p.y - size / 2}px) scale(${s})`, opacity: 1 }); }
  const a = d.animate(kf, { duration: dur, delay, easing, fill: "both" });
  let gone = false; const rm = () => { if (!gone) { gone = true; d.remove(); } };
  a.onfinish = rm; a.oncancel = rm; setTimeout(rm, dur + delay + 200);      // timer fallback: never leak dots
}

/* ---------- graph ---------- */
const graph = $("#graph"), nodes = $("#nodes"), links = $("#links");
const G = { w: 0, h: 0, pos: new Map(), server: { x: 0, y: 0 } };
function ensureServerNode() {
  if ($("#n-server")) return;
  const n = document.createElement("div"); n.className = "node"; n.id = "n-server"; n.innerHTML = `<div class="pill server">SERVER</div>`; nodes.append(n);
}
function graphLayout() {
  const r = graph.getBoundingClientRect(); G.w = r.width; G.h = r.height;
  G.server = { x: G.w / 2, y: G.h / 2 };
  const ws = [...S.workers.values()], n = ws.length;
  ensureServerNode();
  const sn = $("#n-server"); sn.style.left = G.server.x + "px"; sn.style.top = G.server.y + "px";
  const rx = Math.max(60, G.w / 2 - 70), ry = Math.max(50, G.h / 2 - 38);
  ws.forEach((w, i) => {
    const a = -Math.PI / 2 - Math.PI / n + i * 2 * Math.PI / n;
    G.pos.set(w.id, { x: G.w / 2 + rx * Math.cos(a) * (n === 1 ? 0.9 : 1), y: G.h / 2 + ry * Math.sin(a) });
  });
}
function edge(c, o, hw, hh) { const dx = o.x - c.x, dy = o.y - c.y, k = Math.min(hw / Math.abs(dx || 1e-6), hh / Math.abs(dy || 1e-6)); return { x: c.x + dx * k, y: c.y + dy * k }; }
function linkGeom(w, dir) {                      // dir "out": server -> worker, "in": worker -> server
  const p = G.pos.get(w.id), s = G.server, el = $(`#n-${CSS.escape(w.id)} .pill`), hw = (el ? el.offsetWidth : 90) / 2 + 4, hh = (el ? el.offsetHeight : 28) / 2 + 4;
  const len = Math.hypot(p.x - s.x, p.y - s.y) || 1, nx = -(p.y - s.y) / len, ny = (p.x - s.x) / len, off = dir === "out" ? 5 : -5, cv = dir === "out" ? 10 : -10;
  const a = edge(s, p, 48, 18), b = edge(p, s, hw, hh);
  const A = { x: a.x + nx * off, y: a.y + ny * off }, B = { x: b.x + nx * off, y: b.y + ny * off };
  const C0 = { x: (A.x + B.x) / 2 + nx * cv, y: (A.y + B.y) / 2 + ny * cv };
  return dir === "out" ? { A, C: C0, B } : { A: B, C: C0, B: A };
}
const qd = g => `M${g.A.x.toFixed(1)} ${g.A.y.toFixed(1)} Q${g.C.x.toFixed(1)} ${g.C.y.toFixed(1)} ${g.B.x.toFixed(1)} ${g.B.y.toFixed(1)}`;
function renderGraph() {
  if (!graph.clientWidth) return;
  graphLayout();
  const seen = new Set();
  for (const w of S.workers.values()) {
    seen.add(w.id);
    let n = $(`#n-${CSS.escape(w.id)}`);
    if (!n) { n = document.createElement("div"); n.className = "node"; n.id = "n-" + w.id; n.innerHTML = `<div class="pill"><i></i><span class="nm"></span><span class="pct">0%</span><span class="offline">OFFLINE</span></div>`; nodes.append(n); }
    const p = G.pos.get(w.id); n.style.left = p.x + "px"; n.style.top = p.y + "px"; n.style.setProperty("--wc", w.color);
    $(".nm", n).textContent = w.name; n.classList.toggle("dead", !w.alive); n.classList.toggle("demo", !!w.demo && w.alive);
    $(".pct", n).textContent = Math.round((w.metrics && w.metrics.cpu) || 0) + "%";
  }
  $$(".node", nodes).forEach(n => { if (n.id !== "n-server" && !seen.has(n.id.slice(2))) n.remove(); });
  links.innerHTML = "";
  for (const w of S.workers.values()) {
    if (!w.alive) { const g = linkGeom(w, "out"); links.insertAdjacentHTML("beforeend", `<path class="link dead" d="${qd(g)}"/>`); continue; }
    const o = linkGeom(w, "out"), i = linkGeom(w, "in");
    links.insertAdjacentHTML("beforeend", `<path class="link out" data-w="${w.id}" marker-end="url(#ah-out)" d="${qd(o)}"/><path class="link in" data-w="${w.id}" marker-end="url(#ah-in)" d="${qd(i)}"/>`);
  }
  $("#idle-rings").hidden = S.workers.size > 0 && aliveWorkers().length > 0;
}
new ResizeObserver(() => renderGraph()).observe(graph);
function linkMs(w, base = 450) { return Math.min(700, Math.max(450, base + (w.lat || 0) / 6)); }
function pulse(w, dir, color) {
  if (!G.pos.has(w.id)) return;
  const g = linkGeom(w, dir);
  fly(graph, t => qb(g.A, g.C, g.B, t), linkMs(w), color, 6, { glow: 12 });
}
function setNodeDead(w) {
  renderGraph();
  const n = $(`#n-${CSS.escape(w.id)}`); if (!n) return;
  if (!RM) { n.classList.remove("shake"); void n.offsetWidth; n.classList.add("shake"); }
}
function reassignFx(deadW, tileIdx) {
  const alive = aliveWorkers(), gr = graph.getBoundingClientRect(), srv = { x: gr.left + G.server.x, y: gr.top + G.server.y };
  // glowing arcs in the graph: dead worker -> SERVER -> healthy workers
  if (G.pos.has(deadW.id)) alive.slice(0, 6).forEach((w, i) => {
    const from = G.pos.get(deadW.id), to = G.pos.get(w.id), s = G.server;
    fly(graph, t => t < .5 ? qb(from, { x: (from.x + s.x) / 2, y: (from.y + s.y) / 2 - 14 }, s, t * 2) : qb(s, { x: (s.x + to.x) / 2, y: (s.y + to.y) / 2 - 14 }, to, (t - .5) * 2), 650, i % 2 ? "#F59E0B" : "#EF4444", 7, { delay: i * 40, glow: 14 });
  });
  // 10x10 chips: orphaned tiles -> SERVER -> receiving workers, quadratic arcs, max 8
  tileIdx.slice(0, 8).forEach((idx, i) => {
    const el = S.tiles[idx] && S.tiles[idx].el; if (!el) return;
    const r = el.getBoundingClientRect(), from = { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    const w = alive.length ? alive[i % alive.length] : null, wp = w && G.pos.get(w.id), to = wp ? { x: gr.left + wp.x, y: gr.top + wp.y } : srv;
    const c1 = { x: (from.x + srv.x) / 2, y: Math.min(from.y, srv.y) - 50 }, c2 = { x: (srv.x + to.x) / 2, y: Math.min(srv.y, to.y) - 40 };
    fly($("#fx"), t => t < .5 ? qb(from, c1, srv, t * 2) : qb(srv, c2, to, (t - .5) * 2), 650, i % 2 ? "#F59E0B" : "#EF4444", 10,
      { delay: i * 40, easing: "cubic-bezier(.22,1,.36,1)", glow: 12, scale: t => t < .5 ? 1 + .3 * t : 1.15 - .55 * ((t - .5) * 2) });
  });
}

/* ---------- kill a demo worker (graph node or list row) ---------- */
async function killWorker(id) {
  const w = S.workers.get(id); if (!w || !w.alive) return;
  if (!w.demo) { toast(`${w.name} is a real worker and cannot be killed here`); return; }
  try {
    const r = await fetch(apiUrl(`/api/workers/${encodeURIComponent(id)}/kill`), { method: "POST" });
    toast(r.ok ? `Killed ${w.name} (demo)` : `Could not kill ${w.name}: ${r.status}`);
  } catch (e) { toast("Kill failed: " + e.message); }
}
function killTarget(ev) {
  const el = ev.target.closest(".node.demo, .wrow.kill"); if (!el) return null;
  return el.classList.contains("node") ? el.id.slice(2) : el.dataset.id;
}
for (const root of [$("#nodes"), $("#wlist")]) {
  root.addEventListener("click", ev => { const id = killTarget(ev); if (id) killWorker(id); });
  root.addEventListener("mousemove", ev => { const id = killTarget(ev), tip = $("#tip"); if (!id) { if (tip.dataset.k) { tip.classList.remove("on"); tip.dataset.k = ""; } return; }
    tip.textContent = "Click to kill (demo)"; tip.dataset.k = "1"; tip.style.left = Math.min(ev.clientX + 14, innerWidth - 190) + "px"; tip.style.top = ev.clientY + 14 + "px"; tip.classList.add("on"); });
  root.addEventListener("mouseleave", () => { $("#tip").classList.remove("on"); $("#tip").dataset.k = ""; });
}

/* ---------- workers list, feed, ticker ---------- */
const HB_SVG = `<svg viewBox="0 0 24 24"><use href="#i-bolt"/></svg>`;
function renderWorkers() {
  const l = $("#wlist"); let h = `<div class="h">Status</div><div class="h">Load</div><div class="h">Tasks</div><div class="h">Heartbeat</div>`;
  for (const w of S.workers.values()) {
    const cpu = Math.min(100, Math.round((w.metrics && w.metrics.cpu) || 0));
    h += `<div class="wrow ${w.alive ? "" : "dead"} ${w.alive && w.demo ? "kill" : ""}" style="--wc:${w.color}" data-id="${esc(w.id)}"><div class="nm"><i></i><span>${esc(w.name)}</span></div><div><div class="bar"><b style="width:${cpu}%"></b></div></div><div class="num">${w.done || 0}</div><div class="hb">${w.alive ? HB_SVG + `<span class="mono-xs">-</span>` : `${WARN_SVG}<span class="mono-xs">Lost · ${w.lostAfter.toFixed(1)}s</span>`}</div></div>`;
  }
  l.innerHTML = h;
}
const WARN_SVG = `<svg viewBox="0 0 24 24" style="width:12px;height:12px;stroke:currentColor;fill:none;stroke-width:2.4"><path d="M12 3 2 21h20z"/><path d="M12 10v5"/></svg>`;
function tickHeartbeat() {
  const now = performance.now();
  for (const row of $$(".wrow:not(.dead)")) {
    const w = S.workers.get(row.dataset.id); if (!w) continue;
    const s = $(".hb span", row); if (s) s.textContent = ((now - w.lastSeen) / 1000).toFixed(1) + "s";
  }
}
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
function feed(kind, text, ticker) {
  const el = document.createElement("div"); el.className = `ev ${kind} fresh`;
  el.innerHTML = `<span class="ic">${kind === "fault" ? "!" : kind === "warn" ? "↻" : kind === "ok" ? "✓" : ""}</span><span class="tm">${hhmmss(new Date())}</span><span class="tx">${text}</span>`;
  const f = $("#feed"); f.prepend(el); while (f.children.length > 40) f.lastChild.remove();
  setTimeout(() => el.classList.remove("fresh"), 900);
  if (kind === "fault" || kind === "warn") { if (RM) { el.animate([{ background: "rgba(255,255,255,.18)" }, {}], { duration: 150 }); } }
  const tk = $("#ticker"); if (ticker !== false) tk.innerHTML = `<span class="t">${hhmmss(new Date())}</span> · ${ticker || text}`;
  diag(`feed ${kind} ${el.textContent}`);
}

/* ---------- telemetry ---------- */
const CHARTS = [["cpu", "CPU", v => v, "%"], ["mem", "Memory", v => v, "%"], ["tp", "Throughput", v => v, ""], ["lat", "Latency", v => v, "ms"]];
function buildCharts() {
  $("#charts").innerHTML = CHARTS.map(([k, t]) => `<div class="chart" data-k="${k}"><div class="ct"><span>${t}</span>${k === "mem" ? `<button id="memtoggle" hidden>Temp</button>` : ""}</div><div class="body"><div class="y"><span></span><span></span><span></span></div><svg viewBox="0 0 300 64" preserveAspectRatio="none"></svg></div></div>`).join("");
  $("#memtoggle").onclick = () => { S.memMode = S.memMode === "mem" ? "temp" : "mem"; $("#memtoggle").textContent = S.memMode === "mem" ? "Temp" : "Mem"; $(".chart[data-k=mem] .ct span").textContent = S.memMode === "mem" ? "Memory" : "Temperature"; drawCharts(); };
}
function niceMax(v) { if (v <= 5) return Math.max(1, Math.ceil(v)); const p = Math.pow(10, Math.floor(Math.log10(v))); return Math.ceil(v / p * 2) / 2 * p; }
function drawCharts() {
  const anyTemp = [...S.workers.values()].some(w => w.metrics && w.metrics.temp != null);
  $("#memtoggle").hidden = !anyTemp;
  for (const c of $$(".chart")) {
    const k = c.dataset.k === "mem" ? S.memMode : c.dataset.k, svg = $("svg", c);
    let max = 1; for (const w of S.workers.values()) if (!S.hidden.has(w.id)) for (const v of w.hist[k]) if (v > max) max = v;
    if (k === "cpu" || k === "mem") max = Math.max(max, 100); else max = niceMax(max * 1.1);
    const ys = $$(".y span", c); ys.forEach((s, i) => s.textContent = String(Math.round(max * (2 - i) / 2 * (max < 5 ? 10 : 1)) / (max < 5 ? 10 : 1)));
    let h = "";
    for (const w of S.workers.values()) {
      if (S.hidden.has(w.id) || w.hist[k].length < 2) continue;
      const n = w.hist[k].length, pts = w.hist[k].map((v, i) => `${(300 - (n - 1 - i) * 300 / (HIST - 1)).toFixed(1)},${(62 - 60 * v / max).toFixed(1)}`).join(" ");
      h += `<polyline points="${pts}" stroke="${w.alive ? w.color : "#EF4444"}"/>`;
    }
    svg.innerHTML = h;
  }
}
function renderChips() {
  $("#chips").innerHTML = [...S.workers.values()].map(w => `<button class="chip ${S.hidden.has(w.id) ? "off" : ""} ${w.alive ? "" : "dead"}" style="--wc:${w.color}" data-id="${w.id}">${esc(w.name)}${w.alive ? "" : " <i></i>"}</button>`).join("");
}
$("#chips").addEventListener("click", e => { const b = e.target.closest(".chip"); if (!b) return; S.hidden.has(b.dataset.id) ? S.hidden.delete(b.dataset.id) : S.hidden.add(b.dataset.id); renderChips(); drawCharts(); });
function sampleWorkers() {
  const now = performance.now();
  for (const w of S.workers.values()) {
    if (!w.alive) continue;
    w.doneTimes = w.doneTimes.filter(t => now - t < 5000);
    const push = (k, v) => { w.hist[k].push(v); if (w.hist[k].length > HIST) w.hist[k].shift(); };
    const m = w.metrics || {}; push("cpu", m.cpu || 0); push("mem", m.mem || 0); push("temp", m.temp || 0); push("tp", w.doneTimes.length / 5); push("lat", w.lat || 0);
  }
  drawCharts(); renderWorkers(); renderGraph();
  if (RM) { const mx = Math.max(1, ...[...S.workers.values()].map(w => w.doneTimes.length)); $$(".link").forEach(l => { const w = S.workers.get(l.dataset.w); if (w) l.style.opacity = (0.25 + 0.7 * w.doneTimes.length / mx).toFixed(2); }); }
}
async function prefill() {
  try {
    const rows = await (await fetch(apiUrl("/api/metrics/history?seconds=120"), { cache: "no-store" })).json();
    for (const w of S.workers.values()) for (const k in w.hist) w.hist[k] = [];
    for (const r of rows) for (const [id, m] of Object.entries(r.workers)) {
      const w = S.workers.get(id); if (!w) continue;
      w.hist.cpu.push(m.cpu); w.hist.mem.push(0); w.hist.temp.push(m.temp); w.hist.tp.push(m.tp); w.hist.lat.push(m.lat);
    }
    const tail = rows.slice(-SPARK);
    S.spark.tps = tail.map(r => r.tasks_per_s); S.spark.queue = tail.map(r => r.queue); S.spark.alive = tail.map(r => r.workers_alive); S.spark.lat = tail.map(r => r.latency_ms || 0);
    drawCharts();
  } catch (e) {}
}

/* ---------- job panel ---------- */
function renderJob() {
  const j = S.job, pct = j ? Math.round(100 * j.done / Math.max(j.total, 1)) : 0, run = j && j.state === "running";
  for (const id of ["prog", "prog-inline"]) { const p = $("#" + id); $("i", p).style.width = pct + "%"; p.classList.toggle("run", !!run); }
  $("#job-pct").textContent = pct + "%";
  $("#job-prio b").textContent = !j ? "-" : j.priority > 0 ? "High" : j.priority < 0 ? "Low" : "Normal";
  $("#job-type").value = j ? j.type : $("#job-type").value;
  $("#cancel").disabled = $("#cancel-inline").disabled = !run;
  $("#download").disabled = !(j && j.state === "done");
  $("#mosaic-save").disabled = !(j && j.type === "mandelbrot" && j.done > 0);
  updateMosaicTitle();
}
$("#download").onclick = () => { const j = S.job; if (!j) return; if (j.type === "image") downloadZip(); else composePNG(); };
$("#mosaic-save").onclick = composePNG;
async function cancelJob() { if (!S.job) return; const r = await api(`/api/jobs/${S.job.id}`, { method: "DELETE" }); if (r.ok) toast("Job cancelled"); }
$("#cancel").onclick = $("#cancel-inline").onclick = cancelJob;
const SPOTS = [{ cx: -0.7436, cy: 0.1318, view_w: 0.02 }, { cx: -0.5, cy: 0, view_w: 3 }, { cx: -0.1011, cy: 0.9563, view_w: 0.05 }, { cx: -1.7497, cy: 0, view_w: 0.04 }];
async function newJobAction() {
  const type = $("#job-type").value;
  if (type === "image") { $("#files").click(); return; }
  const sp = SPOTS[Math.floor(Math.random() * SPOTS.length)];
  const r = await api("/api/jobs", { method: "POST", body: JSON.stringify({ type: "mandelbrot", params: { width: 640, height: 480, tile: 40, max_iter: 200, ...sp } }) });
  if (!r.ok && r.status !== 401) toast("Could not start job: " + r.status);
}
$("#new-job").onclick = $("#new-inline").onclick = newJobAction;
$("#job-type").onchange = () => { if ($("#job-type").value === "image") toast("Press + New and choose image files"); };
$("#files").onchange = async e => {
  const files = [...e.target.files]; e.target.value = ""; if (!files.length) return;
  const b64 = f => new Promise(res => { const r = new FileReader(); r.onload = () => res(r.result.split(",")[1]); r.readAsDataURL(f); });
  const images = []; for (const f of files.slice(0, 50)) images.push({ name: f.name, data: await b64(f) });
  const r = await api("/api/jobs", { method: "POST", body: JSON.stringify({ type: "image", params: { images, max_side: 1024, format: "WEBP", quality: 80 } }) });
  if (!r.ok && r.status !== 401) toast(`Could not start job: ${r.status} ${(await r.json().catch(() => ({}))).detail || ""}`);
};
async function launchDemo() {
  const b = $("#demo-btn"); b.classList.remove("breathe"); b.disabled = true; setTimeout(() => { b.disabled = false; updateEmpty(); }, 3200);
  const r = await fetch(apiUrl("/api/demo?workers=4"), { method: "POST" });
  toast(r.ok ? "Demo Mode started" : r.status === 429 ? "Demo was just started" : "Demo failed: " + r.status);
}
$("#demo-btn").onclick = $("#e-demo").onclick = launchDemo;
$("#sl-demo").onclick = () => { C.wantDemo = true; $("#sl-demo").textContent = "Demo Mode queued"; $("#sl-demo").disabled = true; };
$("#e-worker").onclick = () => setMode("worker");
$("#retry").onclick = $("#b-reconnect").onclick = () => startConn();
function updateEmpty() {
  const empty = C.state === "online" && S.loaded && S.m.alive === 0 && aliveWorkers().length === 0 && S.mode === "observer";
  $("#empty").hidden = !empty;
  $("#demo-btn").classList.toggle("breathe", C.state === "online" && S.m.alive === 0 && aliveWorkers().length === 0 && !$("#demo-btn").disabled && !RM);
}

/* ---------- events ---------- */
function onEvent(e) {
  try { handleEvent(e); } catch (err) { diag(`event ${e && e.e} failed: ${err && err.message}`); console.error("event", e && e.e, err); }
}
function handleEvent(e) {
  S.lastEvent = performance.now();
  switch (e.e) {
    case "snapshot": {
      const first = !S.loaded;
      S.workers.forEach(w => { w.alive = false; });
      e.workers.forEach(w => { const v = upsertWorker(w); v.lastSeen = performance.now(); });
      for (const [id, w] of [...S.workers]) if (!e.workers.some(x => x.id === id)) S.workers.delete(id);
      S.loaded = true; document.body.classList.remove("loading");
      if (first) buildCharts();
      renderChips(); renderWorkers(); renderGraph(); prefill(); pollMetrics();
      const js = e.jobs; const latest = js.length ? js[js.length - 1] : null;
      if (latest && (!S.job || S.job.id !== latest.id)) restoreJob(latest); else if (!S.job) { buildMosaic(null); renderJob(); }
      else { S.job.done = latest ? latest.done : S.job.done; renderJob(); }
      if (first) feed("conn", "Connected to cluster", "Connected to cluster");
      break; }
    case "job_created": if (!S.job || S.job.state !== "running") newJob(e.job); feed("prog", `Job #${e.job.id} started (${e.job.total} ${e.job.type === "image" ? "files" : "tiles"})`); break;
    case "worker_joined": { const w = upsertWorker(e.worker); w.lastSeen = performance.now(); renderChips(); renderWorkers(); renderGraph(); feed("conn", `${esc(w.name)} connected`, `<b>${esc(w.name)}</b> connected`); updateEmpty(); break; }
    case "worker_lost": {
      const w = S.workers.get(e.worker_id); if (!w) break;
      w.alive = false; w.busy = false; w.lostAt = performance.now(); w.lostAfter = (w.lostAt - w.lastSeen) / 1000;
      w.hist.mem.push(0); w.hist.cpu.push(0);
      S.m.alive = aliveWorkers().length; renderHud(); renderChips(); renderWorkers(); setNodeDead(w);
      const idxs = [];
      for (const id of e.requeued) { const a = S.assigned.get(id); if (a && S.tiles[a.idx]) { idxs.push(a.idx); setTile(a.idx, "orphan", a.worker); } }
      feed("fault", `${esc(w.name)} lost — ${esc(e.reason)}`, `<b style="color:#fca5a5">${esc(w.name)}</b> lost — ${esc(e.reason)}`);
      if (e.requeued.length) { feed("warn", `${e.requeued.length} tile${e.requeued.length > 1 ? "s" : ""} reassigned to active workers`, `${e.requeued.length} tiles reassigned to active workers`); reassignFx(w, idxs); }
      updateEmpty(); break; }
    case "worker_removed": S.workers.delete(e.worker_id); renderChips(); renderWorkers(); renderGraph(); break;
    case "task_assigned": {
      const w = S.workers.get(e.worker_id); if (w) { w.busy = true; pulse(w, "out", "#22D3EE"); }
      if ((!S.job || e.job_id !== S.job.id) && !S.switching) followJob(e.job_id);          // show the job the cluster is actually working on
      if (S.job && e.job_id === S.job.id) {
        const idx = tileIndex(S.job, e.tile), was = S.tiles[idx] && S.tiles[idx].state;
        S.assigned.set(e.task_id, { idx, worker: e.worker_id }); setTile(idx, "active", e.worker_id);
        if (was === "orphan" && RM) { const el = S.tiles[idx].el; el.classList.add("reassigned"); setTimeout(() => el.classList.remove("reassigned"), 1200); }
      }
      break; }
    case "task_done": {
      const w = S.workers.get(e.worker_id);
      if (w) { w.busy = false; w.done = (w.done || 0) + 1; w.doneTimes.push(performance.now()); w.lat = e.latency_ms; pulse(w, "in", w.color); }
      S.lastLat.push(e.latency_ms); if (S.lastLat.length > 50) S.lastLat.shift();
      if (S.job && e.job_id === S.job.id) {
        const idx = tileIndex(S.job, e.tile), t = S.tiles[idx];
        if (t) { t.ms = e.latency_ms; setTile(idx, "done", e.worker_id); }
        S.job.done = e.done; renderJob(); loadTile(e.task_id, idx, S.job);
        const dec = Math.floor(10 * e.done / e.total);
        if (dec > S.job.lastDec && dec < 10) { S.job.lastDec = dec; feed("prog", `Job #${S.job.id} progress ${dec * 10}%`, `Job #${S.job.id} progress ${dec * 10}%`); }
        const tk = $("#ticker"); if (performance.now() - (tk._t || 0) > 250) { tk._t = performance.now(); tk.innerHTML = `<span class="t">${hhmmss(new Date())}</span> · <b>${esc(w ? w.name : "")}</b> completed ${S.job.type === "image" ? "file" : "Tile"} #${idx + 1} (${e.latency_ms}ms)`; }
      }
      break; }
    case "job_done": if (S.job && e.job.id === S.job.id) { S.job.state = "done"; S.job.done = S.job.total; renderJob(); feed("ok", `Job #${S.job.id} complete`); toast(`Job #${S.job.id} finished`); } break;
    case "job_failed": if (S.job && e.job.id === S.job.id) { S.job.state = "failed"; renderJob(); feed("fault", `Job #${S.job.id} failed: ${esc(e.job.error || "")}`); } break;
    case "job_deleted": if (S.job && e.job_id === S.job.id) { S.job.state = "cancelled"; renderJob(); feed("info", `Job #${S.job.id} cancelled`); } break;
    case "metrics": { const w = S.workers.get(e.worker_id); if (w) { w.metrics = e.metrics; w.lastSeen = performance.now(); } S.queueNow = e.queue; break; }
  }
}

/* ---------- layout: wide / compact ---------- */
const MQ = matchMedia("(max-width: 959px)");
const compact = () => MQ.matches;
const TABMAP = { graph: "graph-panel", workers: "workers-panel", charts: "tele-panel", feed: "feed-panel" };
let curTab = "graph";
function setTab(t) {
  curTab = t; $$("#tabs .tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === t));
  for (const [k, id] of Object.entries(TABMAP)) { const p = $("#" + id); if (compact()) p.hidden = k !== t; }
  requestAnimationFrame(renderGraph); drawCharts();
}
function applyLayout() {
  const c = compact();
  if (c) { for (const id of Object.values(TABMAP)) $("#tab-body").append($("#" + id)); setTab(curTab); }
  else {
    $("#midcol").append($("#graph-panel"), $("#tele-panel")); $("#right").append($("#workers-panel"), $("#feed-panel"));
    Object.values(TABMAP).forEach(id => $("#" + id).hidden = false);
  }
  $("#t-alive").textContent = c ? "Alive" : "Alive Workers"; graph.classList.toggle("pcts", c);
  updateMosaicTitle(); requestAnimationFrame(renderGraph);
}
MQ.addEventListener("change", applyLayout);
$("#tabs .tabs").addEventListener("click", e => { const b = e.target.closest("button"); if (b) setTab(b.dataset.tab); });

/* ---------- modes ---------- */
function restagger(root) { $$(".stg", root).forEach(e => { e.classList.remove("stg"); void e.offsetWidth; e.classList.add("stg"); }); }
function setMode(m) {
  S.mode = m; $$("#seg button").forEach(b => { b.classList.toggle("on", b.dataset.mode === m); b.setAttribute("aria-selected", b.dataset.mode === m); });
  $("#observer").classList.toggle("view-off", m !== "observer"); $("#myworker").classList.toggle("view-off", m !== "worker");
  restagger($(m === "observer" ? "#observer" : "#myworker")); updateEmpty();
  if (m === "observer") { renderGraph(); renderWorkers(); renderChips(); drawCharts(); reconcileTiles(); requestAnimationFrame(renderGraph); }
}
$("#seg").addEventListener("click", e => { const b = e.target.closest("button"); if (b) setMode(b.dataset.mode); });

/* ---------- key, settings ---------- */
const maskKey = k => k ? "•".repeat(7) + k.slice(-4) : "none";
function renderKey() { $("#key-mask").textContent = S.keyShown ? (S.key || "none") : maskKey(S.key); $("#c-key").value = S.key; }
$("#key-eye").onclick = () => { S.keyShown = !S.keyShown; renderKey(); };
$("#key-copy").onclick = () => S.key ? copyText(S.key) : toast("No API key set (not needed on an open server)");
const openModal = () => { $("#m-url").value = S.base; $("#m-key").value = S.key; $("#modal").hidden = false; $("#m-key").focus(); };
$("#settings-btn").onclick = $("#b-key").onclick = openModal;
$("#m-cancel").onclick = () => $("#modal").hidden = true;
$("#m-diag").onclick = $("#b-diag").onclick = () => copyText(S.diag.join("\n"));
$("#m-save").onclick = () => {
  const url = $("#m-url").value.trim().replace(/\/$/, ""), key = $("#m-key").value.trim();
  const changed = url !== S.base;
  S.key = key; LS.set("nexus.key", key); if (!S.desktop) LS.set("nexus.server", url); S.base = url;
  renderKey(); $("#modal").hidden = true; clearBanner("AUTH_401"); if (changed) startConn();
};
document.addEventListener("keydown", e => { if (e.key === "Escape") { $("#modal").hidden = true; $("#ask").hidden = true; } });

/* ---------- Ask the cluster ---------- */
const SRC = { model: "Free model", cache: "Cached answer", recorded: "Recorded model answer", rules: "Rule-based answer (no model reachable)" };
async function openAsk() {
  $("#ask").hidden = false; $("#ask-q").focus();
  if (!$("#ask-chips").children.length) {
    let list = ["Is the cluster healthy?", "Which worker is slowest?", "Why is the queue growing?", "What happened to the last job?"];
    try { list = await (await fetch(apiUrl("/api/ask/suggestions"))).json(); } catch (e) {}
    $("#ask-chips").innerHTML = list.map(q => `<button class="chip" style="--wc:#22D3EE">${esc(q)}</button>`).join("");
  }
}
async function doAsk(q) {
  q = (q || $("#ask-q").value).trim(); if (!q) return;
  $("#ask-q").value = q; $("#ask-go").disabled = true; $("#ask-out").innerHTML = `<span style="color:var(--text-secondary)">Thinking…</span>`;
  try {
    const r = await fetch(apiUrl("/api/ask"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q }) });
    if (!r.ok) throw new Error(r.status === 429 ? "Too many questions, try again in a minute." : "Request failed: " + r.status);
    const a = await r.json();
    $("#ask-out").innerHTML = `<div>${esc(a.answer)}</div><div class="mono-xs" style="margin-top:6px;color:var(--text-muted)">${SRC[a.source] || a.source}${a.model ? " · " + esc(a.model) : ""}</div>`;
  } catch (e) { $("#ask-out").innerHTML = `<span style="color:#fca5a5">${esc(e.message)}</span>`; }
  finally { $("#ask-go").disabled = false; }
}
$("#ask-btn").onclick = openAsk; $("#ask-close").onclick = () => $("#ask").hidden = true; $("#ask-go").onclick = () => doAsk();
$("#ask-q").onkeydown = e => { if (e.key === "Enter") doAsk(); };
$("#ask-chips").addEventListener("click", e => { const b = e.target.closest(".chip"); if (b) doAsk(b.textContent); });

/* ---------- My Worker (desktop only) ---------- */
const MW = { since: 0, shown: -1, prevPrev: "" };
async function initDesktop() {
  const a = window.pywebview && window.pywebview.api; if (!a) return;
  const cfg = await a.get_config();
  S.desktop = a; $("#winctl").hidden = false; $("#no-desktop").hidden = true;
  S.key = cfg.key || S.key; renderKey();
  $("#c-url").value = cfg.url; $("#c-name").value = cfg.name; setSwitch(cfg.auto_reconnect);
  $$("#c-url,#c-key,#c-name,#c-btn,#ar").forEach(e => e.disabled = false);
  if (cfg.url && cfg.url !== S.base) { S.base = cfg.url.replace(/\/$/, ""); startConn(); }
  $("#w-min").onclick = () => a.minimize(); $("#w-max").onclick = () => a.toggle_maximize(); $("#w-close").onclick = () => a.close();
  setInterval(pollWorker, 500);
}
function setSwitch(on) { $("#ar").setAttribute("aria-checked", on); $("#ar-lbl").textContent = on ? "ON" : "OFF"; }
$("#ar").onclick = () => { const on = $("#ar").getAttribute("aria-checked") !== "true"; setSwitch(on); S.desktop && S.desktop.set_auto_reconnect(on); };
$("#c-eye").onclick = () => { const i = $("#c-key"); i.type = i.type === "password" ? "text" : "password"; };
$("#c-key").oninput = () => { S.key = $("#c-key").value.trim(); LS.set("nexus.key", S.key); renderKey(); };
$("#c-btn").onclick = async () => {
  if (!S.desktop) return;
  const st = await S.desktop.state(0);
  if (["online", "connecting", "reconnecting"].includes(st.state)) { S.desktop.disconnect(); return; }
  const url = $("#c-url").value.trim(); S.key = $("#c-key").value.trim(); LS.set("nexus.key", S.key); renderKey();
  clearBanner("AUTH_401");
  await S.desktop.connect(url, S.key, $("#c-name").value.trim());
  if (url.replace(/\/$/, "") !== S.base) { S.base = url.replace(/\/$/, ""); startConn(); }
};
const BADGE = { online: ["ok", "Online · "], connecting: ["warn", "Connecting…"], reconnecting: ["warn", "Reconnecting"], rejected: ["bad", "Rejected · AUTH_401"], offline: ["idle", "Offline"], stopped: ["idle", "Offline"] };
function logLine(en) { return `<div class="li k-${en.kind}"><span class="tm">${esc(en.t)}</span><i></i><span>${esc(en.msg)}</span></div>`; }
async function pollWorker() {
  if (!S.desktop) return;
  let st; try { st = await S.desktop.state(MW.since); } catch (e) { return; }
  MW.since = st.log_len;
  if (st.log.length) for (const en of st.log) { $("#log-a").insertAdjacentHTML("afterbegin", logLine(en)); $("#log-b").insertAdjacentHTML("afterbegin", logLine(en)); }
  const [cls, txt] = BADGE[st.state] || BADGE.offline;
  $("#c-badge").className = "badge " + cls; $("#c-badge").textContent = st.state === "online" ? txt + (st.task ? "Computing" : "Idle") : txt;
  const live = ["online", "connecting", "reconnecting"].includes(st.state);
  $("#c-btn").textContent = live ? "Disconnect" : "Connect"; $("#c-btn").className = "btn " + (live ? "danger" : "primary");
  if (st.state === "rejected") setError("AUTH_401", "Invalid API Key");
  const cpu = Math.round((st.metrics && st.metrics.cpu) || 0);
  $("#g-val").textContent = (st.state === "online" ? cpu : 0) + "%"; $("#g-arc").style.strokeDashoffset = 1 - (st.state === "online" ? cpu : 0) / 100;
  const tk = st.task;
  $("#t-label").textContent = tk ? (tk.type === "mandelbrot" ? `Mandelbrot Tile #${tk.n} (Row ${tk.row}, Col ${tk.col})` : tk.label) : (st.state === "online" ? "Idle · waiting for tasks" : "Not connected");
  const pct = tk ? Math.min(95, Math.round(100 * (Date.now() / 1000 - tk.started) * 1000 / Math.max(tk.est_ms, 50))) : 0;
  $("#t-prog i").style.width = pct + "%"; $("#t-pct").textContent = pct + "%"; $("#t-prog").classList.toggle("run", !!tk);
  if (st.preview && MW.prev !== st.done) { MW.prev = st.done; const c = $("#t-prev"), x = c.getContext("2d"), bin = atob(st.preview.rgba), a = new Uint8ClampedArray(bin.length); for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i); c.width = st.preview.w; c.height = st.preview.h; x.putImageData(new ImageData(a, st.preview.w, st.preview.h), 0, 0); }
  $("#s-done").textContent = st.done || 0; $("#s-avg").textContent = st.avg_ms ? st.avg_ms + "ms" : "-";
  const u = st.uptime_s || 0; $("#s-up").textContent = [Math.floor(u / 3600), Math.floor(u / 60) % 60, u % 60].map(n => String(n).padStart(2, "0")).join(":");
  const mine = (S.workers.get(st.wid) || {}).done || 0, tot = [...S.workers.values()].reduce((s, w) => s + (w.done || 0), 0);
  $("#s-share").textContent = tot && st.wid ? (100 * mine / tot).toFixed(1) + "%" : "-";
}

/* ---------- boot ---------- */
function boot() {
  $("#c-url").value = S.base || location.origin; $("#c-name").value = "My worker"; renderKey();
  if (!(window.pywebview && window.pywebview.api)) { $("#no-desktop").hidden = false; $$("#c-url,#c-key,#c-name,#c-btn,#ar").forEach(e => e.disabled = true); }
  buildMosaic(null); buildCharts(); renderJob(); applyLayout(); renderGraph(); renderWorkers(); renderHud();
  window.addEventListener("pywebviewready", initDesktop);
  if (window.pywebview && window.pywebview.api) initDesktop();
  setInterval(reconcileTiles, 500); setInterval(pollMetrics, 500); setInterval(sampleHud, 1000); setInterval(sampleWorkers, 1000); setInterval(tickHeartbeat, 200);
  startConn();
}
window.__probe = () => ({ base: S.base, conn: $("#conn-text").textContent, mode: S.mode, compact: compact(), banner: $("#banner").hidden ? null : $("#banner-code").textContent,
  sleeping: !$("#sleep").hidden, empty: !$("#empty").hidden, workers: S.workers.size, alive: aliveWorkers().length, job: S.job && { id: S.job.id, done: S.job.done, total: S.job.total },
  tilesDone: S.tiles.filter(t => t.state === "done").length, hud: { ...S.m }, badge: $("#c-badge").textContent, desktop: !!S.desktop, feed: $$("#feed .tx").slice(0, 4).map(e => e.textContent) });
boot();
