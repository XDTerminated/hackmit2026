// Freezing of Gait Monitor page. Polls /api/state four times a second and draws everything
// from the answer. No libraries, so it works on a board with no internet access.

const POLL_MS = 250;
const SAMPLE_RATE = 64, FRAME_SECONDS = 0.5;
const MAG_SECONDS = 10, FI_FRAMES = 240, FI_AXIS_MAX = 4;

const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

let samples = [];          // [sample number, |acc| mg]
let frames = [];           // {n, fi, power, positive, cue, state}
let lastSample = 0, lastFrame = 0;
let status = null, recording = { active: false, label: "" };
let failures = 0;

const STATES = {
  warming_up:      { icon: "…", label: "Warming up", detail: "The detector needs 4 seconds of data" },
  still:           { icon: "■", label: "Still", detail: "Too little movement to be walking or freezing" },
  moving:          { icon: "◆", label: "Moving", detail: "Some movement, below walking level" },
  walking:         { icon: "▶", label: "Walking", detail: "Steady stepping rhythm" },
  freeze_detected: { icon: "▲", label: "Freeze detected", detail: "Cue is playing" },
  offline:         { icon: "!", label: "No data from the sensor", detail: "Check that the app is running and the sensor is wired" },
};

// ---- polling --------------------------------------------------------------------------------

async function poll() {
  try {
    const response = await fetch(`/api/state?since_sample=${lastSample}&since_frame=${lastFrame}`);
    const data = await response.json();
    failures = 0;
    status = data.status;
    recording = data.recording;

    // A restarted server counts from zero again: start over.
    if (data.status.samples < lastSample) { samples = []; frames = []; lastSample = 0; lastFrame = 0; }
    for (const s of data.samples) { samples.push(s); lastSample = s[0]; }
    for (const f of data.frames) { frames.push(f); lastFrame = f.n; }
    samples = samples.slice(-MAG_SECONDS * SAMPLE_RATE);
    frames = frames.slice(-FI_FRAMES);

    renderStatus(data);
    renderEvents(data.events);
    renderFramesTable();
  } catch (error) {
    failures += 1;
    if (failures > 3) renderOffline("page cannot reach the board");
  }
  drawMagnitude();
  drawFreezeIndex();
}

// ---- status, tiles, tables ------------------------------------------------------------------

function setTile(id, value, note, level) {
  $(id).textContent = value;
  const noteEl = $(id + "-note");
  noteEl.textContent = note;
  if (level) noteEl.dataset.level = level; else delete noteEl.dataset.level;
}

function renderOffline(reason) {
  $("link").textContent = reason;
  $("link").dataset.ok = "false";
  showState("offline");
}

function showState(name) {
  const s = STATES[name] || STATES.warming_up;
  $("hero").dataset.state = name;
  $("hero-icon").textContent = s.icon;
  $("hero-label").textContent = s.label;
  $("hero-detail").textContent = s.detail;
}

function renderStatus(data) {
  const st = data.status;
  if (!st.receiving) {
    renderOffline(st.samples ? "sensor data stopped" : "no sensor data yet");
  } else {
    $("link").textContent = "receiving data";
    $("link").dataset.ok = "true";
    showState(st.state);
    if (st.state === "walking" || st.state === "still" || st.state === "moving") {
      $("hero-detail").textContent = STATES[st.state].detail + (st.armed ? ". Detector armed." : ". Detector not armed: no recent walking.");
    }
  }

  const counted = st.total_power !== null && st.total_power > 178;
  setTile("t-fi", st.freeze_index === null ? "–" : st.freeze_index.toFixed(2),
          st.freeze_index === null ? " " : counted ? `freeze above ${st.fi_threshold}` : "ignored while still");
  setTile("t-power", st.total_power === null ? "–" : st.total_power.toLocaleString(), "mg², walking is above 10,000");
  const rateOk = st.sample_rate_hz !== null && Math.abs(st.sample_rate_hz - 64) < 0.5;
  setTile("t-rate", st.sample_rate_hz === null ? "–" : st.sample_rate_hz.toFixed(1) + " Hz",
          st.sample_rate_hz === null ? " " : rateOk ? "on target (64)" : "detector assumes 64", st.sample_rate_hz === null ? "" : rateOk ? "ok" : "bad");
  const lostShare = st.samples ? st.lost_samples / (st.samples + st.lost_samples) : 0;
  setTile("t-lost", st.lost_samples.toLocaleString(), `of ${(st.samples + st.lost_samples).toLocaleString()} (${(100 * lostShare).toFixed(2)}%)`,
          st.samples ? (lostShare < 0.001 ? "ok" : "bad") : "");

  for (const button of document.querySelectorAll("#response button")) {
    button.setAttribute("aria-pressed", String(button.dataset.response === st.response));
  }

  $("rec-toggle").textContent = data.recording.active ? "Stop recording" : "Start recording";
  $("rec-name").disabled = data.recording.active;
  $("rec-info").textContent = data.recording.active
    ? `${data.recording.name}: ${(data.recording.rows / SAMPLE_RATE).toFixed(0)} s recorded` : "";
  for (const button of document.querySelectorAll("#labels button")) {
    button.disabled = !data.recording.active;
    button.setAttribute("aria-pressed", String(data.recording.active && button.dataset.label === data.recording.label));
  }
}

function renderEvents(events) {
  const body = $("events-table").tBodies[0];
  if (!events.length) return;
  body.replaceChildren(...events.map((e) => {
    const row = document.createElement("tr");
    const started = new Date(e.start).toLocaleTimeString();
    for (const text of [e.id, started, e.duration_s.toFixed(1) + " s" + (e.ongoing ? " (ongoing)" : ""), e.peak_freeze_index.toFixed(2)]) {
      const cell = document.createElement("td");
      cell.textContent = text;
      row.append(cell);
    }
    return row;
  }));
}

function renderFramesTable() {
  if (!$("frames-table").closest("details").open) return;
  const newest = frames.length ? frames[frames.length - 1].n : 0;
  $("frames-table").tBodies[0].replaceChildren(...frames.slice(-40).reverse().map((f) => {
    const row = document.createElement("tr");
    for (const text of [((newest - f.n) * FRAME_SECONDS).toFixed(1), f.fi.toFixed(2), f.power.toLocaleString(), STATES[f.state].label, f.cue ? "playing" : ""]) {
      const cell = document.createElement("td");
      cell.textContent = text;
      row.append(cell);
    }
    return row;
  }));
}

// ---- charts ---------------------------------------------------------------------------------

const PAD = { left: 46, right: 10, top: 10, bottom: 22 };
const hover = { "c-mag": null, "c-fi": null };   // pointer x in CSS pixels, or null

function setupCanvas(canvas) {
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth, height = Number(canvas.getAttribute("height"));
  if (canvas.width !== Math.round(width * ratio)) { canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio); }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.font = "11px system-ui, sans-serif";
  return { ctx, width, height, plotW: width - PAD.left - PAD.right, plotH: height - PAD.top - PAD.bottom };
}

function drawAxes(g, yMin, yMax, yTicks, xLabels) {
  const { ctx, width, height, plotH } = g;
  ctx.lineWidth = 1;
  ctx.fillStyle = css("--muted");
  ctx.textAlign = "right"; ctx.textBaseline = "middle";
  for (const tick of yTicks) {
    const y = PAD.top + plotH * (1 - (tick - yMin) / (yMax - yMin));
    ctx.strokeStyle = css("--grid");
    ctx.beginPath(); ctx.moveTo(PAD.left, y + 0.5); ctx.lineTo(width - PAD.right, y + 0.5); ctx.stroke();
    ctx.fillText(tick.toLocaleString(), PAD.left - 6, y);
  }
  ctx.strokeStyle = css("--axis");
  ctx.beginPath(); ctx.moveTo(PAD.left, height - PAD.bottom + 0.5); ctx.lineTo(width - PAD.right, height - PAD.bottom + 0.5); ctx.stroke();
  ctx.textBaseline = "top";
  for (const [fraction, text, align] of xLabels) {
    ctx.textAlign = align;
    ctx.fillText(text, PAD.left + g.plotW * fraction, height - PAD.bottom + 6);
  }
}

function niceTicks(min, max, count) {
  const raw = (max - min) / count, power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * power).find((s) => s >= raw);
  const ticks = [];
  for (let t = Math.ceil(min / step) * step; t <= max + 1e-9; t += step) ticks.push(Math.round(t * 1000) / 1000);
  return ticks;
}

function showTip(canvas, x, strongText, restText) {
  const tip = canvas.parentElement.querySelector(".tip");
  if (x === null) { tip.hidden = true; return; }
  tip.replaceChildren(Object.assign(document.createElement("strong"), { textContent: strongText }), document.createTextNode(restText));
  tip.hidden = false;
  const left = Math.min(Math.max(x + 10, PAD.left), canvas.clientWidth - tip.offsetWidth - 4);
  tip.style.left = left + "px";
}

function crosshair(g, x) {
  g.ctx.strokeStyle = css("--muted"); g.ctx.lineWidth = 1;
  g.ctx.beginPath(); g.ctx.moveTo(x + 0.5, PAD.top); g.ctx.lineTo(x + 0.5, g.height - PAD.bottom); g.ctx.stroke();
}

function drawMagnitude() {
  const canvas = $("c-mag"), g = setupCanvas(canvas), span = MAG_SECONDS * SAMPLE_RATE;
  let lo = 800, hi = 1200;
  for (const [, v] of samples) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  const margin = (hi - lo) * 0.06; lo = Math.max(0, lo - margin); hi += margin;
  drawAxes(g, lo, hi, niceTicks(lo, hi, 4), [[0, `${MAG_SECONDS} s ago`, "left"], [1, "now", "right"]]);
  if (!samples.length) { showTip(canvas, null); return; }

  const newest = samples[samples.length - 1][0];
  const xOf = (n) => PAD.left + g.plotW * (1 - (newest - n) / span);
  const yOf = (v) => PAD.top + g.plotH * (1 - (v - lo) / (hi - lo));
  g.ctx.strokeStyle = css("--series-1"); g.ctx.lineWidth = 2; g.ctx.lineJoin = "round";
  g.ctx.beginPath();
  samples.forEach(([n, v], i) => (i ? g.ctx.lineTo(xOf(n), yOf(v)) : g.ctx.moveTo(xOf(n), yOf(v))));
  g.ctx.stroke();

  const px = hover["c-mag"];
  if (px === null) { showTip(canvas, null); return; }
  const nearest = samples.reduce((a, b) => (Math.abs(xOf(b[0]) - px) < Math.abs(xOf(a[0]) - px) ? b : a));
  crosshair(g, xOf(nearest[0]));
  showTip(canvas, xOf(nearest[0]), `${Math.round(nearest[1]).toLocaleString()} mg`, `${((newest - nearest[0]) / SAMPLE_RATE).toFixed(1)} s ago`);
}

function drawFreezeIndex() {
  const canvas = $("c-fi"), g = setupCanvas(canvas);
  drawAxes(g, 0, FI_AXIS_MAX, [0, 1, 2, 3, 4], [[0, "2 min ago", "left"], [1, "now", "right"]]);
  if (!frames.length) { showTip(canvas, null); return; }

  const { ctx } = g, newest = frames[frames.length - 1].n;
  const xOf = (n) => PAD.left + g.plotW * (1 - (newest - n) / FI_FRAMES);
  const yOf = (v) => PAD.top + g.plotH * (1 - Math.min(v, FI_AXIS_MAX) / FI_AXIS_MAX);
  const frameW = g.plotW / FI_FRAMES;

  // Shade each run of cue-on frames as one rectangle (per-frame rectangles overlap into stripes).
  ctx.fillStyle = css("--cue-band");
  let runStart = null;
  frames.forEach((f, i) => {
    if (f.cue && runStart === null) runStart = f.n;
    const runEnds = runStart !== null && (!f.cue || i === frames.length - 1);
    if (runEnds) {
      const end = f.cue ? f.n : frames[i - 1].n;
      const x0 = Math.max(xOf(runStart) - frameW, PAD.left);
      ctx.fillRect(x0, PAD.top, xOf(end) - x0, g.plotH);
      runStart = null;
    }
  });

  // Threshold: a labelled dashed hairline, not a series.
  const threshold = status ? status.fi_threshold : 1.056, ty = yOf(threshold);
  ctx.strokeStyle = css("--text-secondary"); ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
  ctx.beginPath(); ctx.moveTo(PAD.left, ty + 0.5); ctx.lineTo(g.width - PAD.right, ty + 0.5); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = css("--text-secondary"); ctx.textAlign = "left"; ctx.textBaseline = "bottom";
  ctx.fillText(`freeze threshold ${threshold}`, PAD.left + 4, ty - 2);

  // One line; segments where there is too little movement to count are drawn recessive.
  ctx.lineWidth = 2; ctx.lineJoin = "round";
  for (let i = 1; i < frames.length; i++) {
    const a = frames[i - 1], b = frames[i];
    if (b.n - a.n !== 1) continue;
    ctx.strokeStyle = b.power > 178 ? css("--series-1") : css("--axis");
    ctx.beginPath(); ctx.moveTo(xOf(a.n), yOf(a.fi)); ctx.lineTo(xOf(b.n), yOf(b.fi)); ctx.stroke();
  }

  const px = hover["c-fi"];
  if (px === null) { showTip(canvas, null); return; }
  const f = frames.reduce((a, b) => (Math.abs(xOf(b.n) - px) < Math.abs(xOf(a.n) - px) ? b : a));
  crosshair(g, xOf(f.n));
  const note = f.cue ? "cue playing" : f.power > 178 ? STATES[f.state].label.toLowerCase() : "ignored, too little movement";
  showTip(canvas, xOf(f.n), f.fi.toFixed(2), `${((newest - f.n) * FRAME_SECONDS).toFixed(1)} s ago, ${note}`);
}

for (const id of Object.keys(hover)) {
  const canvas = $(id);
  canvas.addEventListener("pointermove", (e) => { hover[id] = e.offsetX; id === "c-mag" ? drawMagnitude() : drawFreezeIndex(); });
  canvas.addEventListener("pointerleave", () => { hover[id] = null; id === "c-mag" ? drawMagnitude() : drawFreezeIndex(); });
}

// ---- recording controls ---------------------------------------------------------------------

async function post(path) {
  try { return await (await fetch(path, { method: "POST" })).json(); } catch (error) { return { ok: false }; }
}

async function refreshRecordings() {
  try {
    const list = await (await fetch("/api/recordings")).json();
    $("rec-list").replaceChildren(...list.slice(0, 12).map((r) => {
      const item = document.createElement("li"), link = document.createElement("a");
      link.href = "/api/recording?name=" + encodeURIComponent(r.name);
      link.textContent = r.name;
      item.append(link, document.createTextNode(`  ${r.kb.toLocaleString()} KB`));
      return item;
    }));
  } catch (error) { /* list stays as it was */ }
}

$("rec-toggle").addEventListener("click", async () => {
  if (recording.active) await post("/api/record/stop");
  else await post("/api/record/start?name=" + encodeURIComponent($("rec-name").value));
  refreshRecordings();
});

for (const button of document.querySelectorAll("#response button")) {
  button.addEventListener("click", () => post("/api/response?response=" + button.dataset.response));
}

function setLabel(label) { if (recording.active) post("/api/label?label=" + encodeURIComponent(label)); }
for (const button of document.querySelectorAll("#labels button")) button.addEventListener("click", () => setLabel(button.dataset.label));
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.ctrlKey || e.metaKey || e.altKey) return;
  const label = { w: "walking", s: "standing", f: "freezing", n: "" }[e.key.toLowerCase()];
  if (label !== undefined) setLabel(label);
});

window.addEventListener("resize", () => { drawMagnitude(); drawFreezeIndex(); });
refreshRecordings();
poll();
setInterval(poll, POLL_MS);
