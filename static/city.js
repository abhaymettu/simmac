"use strict";
// SimMac renderer. Draws a 640x360 pixel buffer and scales it up without smoothing.
// Buildings are apps (height from memory, lit windows from CPU), cars are processes,
// arcs are network bytes, the sky follows the local clock, the roads pulse with load.

const W = 640, H = 360, N = 20, TW = 24, TH = 12;
const OX = W / 2, OY = 84;
const params = new URLSearchParams(location.search);
const RECORD_SECONDS = Number(params.get("record") || 0);
const HOUR_OVERRIDE = params.has("hour") ? Number(params.get("hour")) : null;
const CYCLE_SECONDS = Number(params.get("cycle") || 0);

const view = document.getElementById("view");
const vctx = view.getContext("2d");
const buf = document.createElement("canvas");
buf.width = W; buf.height = H;
const ctx = buf.getContext("2d");

// ---------- small helpers ----------
function hash(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}
function rng(seed) {
  let s = seed >>> 0 || 1;
  return () => { s ^= s << 13; s >>>= 0; s ^= s >> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; };
}
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, t) => a + (b - a) * t;
function hex(c) { return [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)]; }
function mix(a, b, t) { return [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)]; }
function rgb(c, k = 1) { return `rgb(${clamp(c[0] * k, 0, 255) | 0},${clamp(c[1] * k, 0, 255) | 0},${clamp(c[2] * k, 0, 255) | 0})`; }
function iso(x, y) { return [OX + (x - y) * TW / 2, OY + (x + y) * TH / 2]; }

// ---------- time of day ----------
const SKY = [ // hour, top, horizon
  [0, "#0a0f2e", "#1e2a5c"], [5, "#141a44", "#3a3570"], [6.2, "#3b4a8c", "#f09a7a"],
  [7.5, "#5aa7e6", "#cfe8f2"], [12, "#3f92dd", "#b8e0f5"], [16.5, "#5d9fdc", "#f3d7a6"],
  [18.3, "#5a4a8a", "#f08a5c"], [19.6, "#26285e", "#7a4a7a"], [21, "#0e1436", "#22305e"], [24, "#0a0f2e", "#1e2a5c"],
];
function skyAt(h) {
  for (let i = 0; i < SKY.length - 1; i++) {
    const [h0, t0, b0] = SKY[i], [h1, t1, b1] = SKY[i + 1];
    if (h >= h0 && h <= h1) { const t = (h - h0) / (h1 - h0); return [mix(hex(t0), hex(t1), t), mix(hex(b0), hex(b1), t)]; }
  }
  return [hex(SKY[0][1]), hex(SKY[0][2])];
}
function nightAt(h) { // 0 at midday, 1 at deep night
  const d = Math.cos(((h - 13) / 24) * Math.PI * 2); // 1 at 13:00, -1 at 01:00
  return clamp(0.5 - d * 0.9, 0, 1);
}

// ---------- city layout ----------
const isRoad = (x, y) => x % 4 === 0 || y % 4 === 0;
const LOTS = [];
for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) if (!isRoad(x, y)) LOTS.push({ x, y, owner: null });
const LOT_AT = new Map(LOTS.map(l => [l.x + "," + l.y, l]));
const DISTRICT_CENTER = { apps: [6, 6], workshop: [14, 6], system: [10, 15] };
const lotOrder = {};
for (const d of Object.keys(DISTRICT_CENTER)) {
  const [cx, cy] = DISTRICT_CENTER[d];
  lotOrder[d] = LOTS.slice().sort((a, b) => Math.hypot(a.x - cx, a.y - cy) - Math.hypot(b.x - cx, b.y - cy));
}
const TOWER_LOT = LOTS.find(l => l.x === 19 && l.y === 1);
TOWER_LOT.owner = "__tower__";

const PALETTES = {
  apps: ["#c8735a", "#d9a05b", "#6fa38f", "#8c7bb8", "#d48aa0", "#5f8fbf"],
  workshop: ["#7d8f6a", "#a3875f", "#6e7f99", "#9a6f5a", "#5f8f86"],
  system: ["#8a8f9c", "#9c968a", "#7a8696", "#a0a4ab"],
};
const AGENT_RE = /claude|codex|agent|intent/i;

const buildings = new Map(); // name -> building
function placeBuilding(app) {
  const order = lotOrder[app.district] || lotOrder.workshop;
  const lot = order.find(l => l.owner === null) || LOTS.find(l => l.owner === null);
  if (!lot) return null;
  lot.owner = app.name;
  const h = hash(app.name), pal = PALETTES[app.district] || PALETTES.workshop;
  const b = {
    name: app.name, district: app.district, lot, color: hex(pal[h % pal.length]),
    seed: h, height: 0, target: 6, cpu: 0, mem: 0, procs: 0, lastSeen: 0,
    agent: AGENT_RE.test(app.name), smoke: [],
  };
  buildings.set(app.name, b);
  return b;
}

const trees = LOTS.filter((l, i) => hash("tree" + l.x + "," + l.y) % 3 === 0);

// ---------- live data ----------
let snap = null, snapAt = 0, fetchError = "";
async function poll() {
  try {
    const r = await fetch("/api/snapshot", { cache: "no-store" });
    if (!r.ok) throw new Error("snapshot returned " + r.status);
    snap = await r.json(); snapAt = performance.now(); fetchError = "";
    const now = performance.now();
    for (const app of snap.apps) {
      const b = buildings.get(app.name) || placeBuilding(app);
      if (!b) continue;
      b.cpu = app.cpu; b.mem = app.mem_mb; b.procs = app.procs; b.lastSeen = now;
      b.target = clamp(6 + 16 * Math.log2(1 + app.mem_mb / 40), 6, 120);
    }
    for (const [name, b] of buildings) {
      if (now - b.lastSeen > 10000) { b.target = 0; if (b.height < 0.5) { b.lot.owner = null; buildings.delete(name); } }
    }
  } catch (e) {
    fetchError = "Can't reach the SimMac server. Start it with: python3 -m simmac.server";
  }
  document.getElementById("err").textContent = fetchError;
}
poll(); setInterval(poll, 1000);

// ---------- cars (processes) ----------
const cars = [];
function spawnCar(r) {
  const axis = r() < 0.5 ? "x" : "y";
  const line = 4 * Math.floor(r() * 5 + 0.0001) + (r() < 0.5 ? 0 : 0);
  const dir = r() < 0.5 ? 1 : -1;
  const palette = ["#e8d44d", "#e05a47", "#5ab0e0", "#f2f2f2", "#7ad07a", "#e08a3a"];
  cars.push({ axis, line: clamp(line, 0, 16), pos: r() * N, dir, lane: dir > 0 ? 0.28 : -0.28,
    color: hex(palette[Math.floor(r() * palette.length)]), speed: 0.7 + r() * 0.6, turn: r() });
}
const carRng = rng(12345);

// ---------- network arcs ----------
const arcs = [];
let rxCarry = 0, txCarry = 0;
function rateFor(bps) { return bps <= 0 ? 0 : clamp(Math.log2(1 + bps / 20000) * 1.6, 0, 24); }

// ---------- pixel font (3x5) ----------
const GLYPHS = {
  A:"010101111101101",B:"110101110101110",C:"011100100100011",D:"110101101101110",E:"111100110100111",
  F:"111100110100100",G:"011100101101011",H:"101101111101101",I:"111010010010111",J:"001001001101010",
  K:"101101110101101",L:"100100100100111",M:"101111111101101",N:"110101101101101",O:"010101101101010",
  P:"110101110100100",Q:"010101101110011",R:"110101110101101",S:"011100010001110",T:"111010010010010",
  U:"101101101101111",V:"101101101101010",W:"101101111111101",X:"101101010101101",Y:"101101010010010",
  Z:"111001010100111","0":"111101101101111","1":"010110010010111","2":"110001010100111","3":"110001010001110",
  "4":"101101111001001","5":"111100110001110","6":"011100111101111","7":"111001010010010","8":"111101111101111",
  "9":"111101111001110",".":"000000000000010",":":"000010000010000","%":"101001010100101","/":"001001010100100",
  "-":"000000111000000","+":"000010111010000","(":"010100100100010",")":"010001001001010"," ":"000000000000000",
  "'":"010010000000000","_":"000000000000111","&":"010101010101011","@":"010101111100011",
};
function textWidth(s) { return s.length * 4 - 1; }
function drawText(s, x, y, color) {
  ctx.fillStyle = color;
  s = s.toUpperCase();
  for (let i = 0; i < s.length; i++) {
    const g = GLYPHS[s[i]] || GLYPHS["-"];
    for (let p = 0; p < 15; p++) if (g[p] === "1") ctx.fillRect(x + i * 4 + (p % 3), y + ((p / 3) | 0), 1, 1);
  }
}
function fmtBytes(bps) {
  if (bps >= 1e6) return (bps / 1e6).toFixed(1) + "MB/S";
  if (bps >= 1e3) return (bps / 1e3).toFixed(0) + "KB/S";
  return (bps | 0) + "B/S";
}

// ---------- drawing ----------
function poly(pts, fill) {
  ctx.fillStyle = fill; ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
  for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
  ctx.closePath(); ctx.fill();
}
function tile(x, y, fill) {
  const [sx, sy] = iso(x, y);
  poly([[sx, sy], [sx + TW / 2, sy + TH / 2], [sx, sy + TH], [sx - TW / 2, sy + TH / 2]], fill);
}

let light = 1, night = 0, tSec = 0, frame = 0, drawnFrames = 0, drawnBuildings = 0;
function shade(c, k) { return rgb(mix(c, [40, 50, 110], night * 0.45), k * light); }

function drawSky(hour) {
  const [top, bot] = skyAt(hour);
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, rgb(top)); g.addColorStop(0.62, rgb(bot)); g.addColorStop(1, rgb(bot, 0.8));
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  if (night > 0.35) {
    const r = rng(99);
    for (let i = 0; i < 90; i++) {
      const x = (r() * W) | 0, y = (r() * 150) | 0, tw = 0.5 + 0.5 * Math.sin(tSec * (1 + r() * 2) + i);
      ctx.fillStyle = `rgba(255,248,220,${(night - 0.35) * 1.4 * tw})`; ctx.fillRect(x, y, 1, 1);
    }
  }
  // sun by day, moon by night, on an arc across the sky
  const dayT = (hour - 6) / 12, nightT = ((hour + 6) % 24) / 12;
  const body = dayT >= 0 && dayT <= 1 ? { t: dayT, c: "#ffe9a8", r: 7 } : { t: nightT, c: "#f2f0e6", r: 5 };
  const bx = lerp(60, W - 60, body.t), by = 120 - Math.sin(body.t * Math.PI) * 95;
  ctx.fillStyle = body.c; ctx.beginPath(); ctx.arc(bx | 0, by | 0, body.r, 0, Math.PI * 2); ctx.fill();
}

function drawGround(load) {
  const grass = hex("#5d8a4a"), road = hex("#3d3c48"), plaza = hex("#7d7a70");
  const pulseR = (tSec * (2 + load * 6)) % 18;
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    if (isRoad(x, y)) {
      const d = Math.hypot(x - 10, y - 10);
      const glow = Math.max(0, 1 - Math.abs(d - pulseR) / 1.5) * clamp(load, 0, 1) * 0.6;
      tile(x, y, shade(mix(road, [120, 200, 255], glow), 1));
    } else {
      const lot = LOT_AT.get(x + "," + y);
      tile(x, y, shade(lot && lot.owner ? plaza : grass, 1 - ((x + y) % 2) * 0.04));
    }
  }
  // lane dashes
  ctx.fillStyle = shade([220, 210, 150], 0.9);
  for (let i = 0; i < N; i += 2) for (let l = 0; l <= 16; l += 4) {
    const [ax, ay] = iso(l + 0.5, i + 0.5); ctx.fillRect(ax | 0, (ay + 0) | 0, 1, 1);
    const [bx, by] = iso(i + 0.5, l + 0.5); ctx.fillRect(bx | 0, by | 0, 1, 1);
  }
}

function drawBuilding(b) {
  const [sx, sy0] = iso(b.lot.x, b.lot.y);
  const cx = sx, cy = sy0 + TH / 2; // center of the tile
  const hw = 9, hh = 4.5, h = Math.round(b.height);
  if (h < 1) return;
  const L = [cx - hw, cy], R = [cx + hw, cy], F = [cx, cy + hh], B = [cx, cy - hh];
  const up = (p) => [p[0], p[1] - h];
  poly([L, F, up(F), up(L)], shade(b.color, 0.72));
  poly([F, R, up(R), up(F)], shade(b.color, 0.9));
  poly([up(L), up(F), up(R), up(B)], shade(b.color, 1.15));
  // windows: more of them lit at night and when the app is busy
  const busy = clamp(b.cpu / 60, 0, 1);
  const litP = clamp(0.08 + night * 0.45 + busy * 0.6, 0, 0.97);
  const r = rng(b.seed ^ Math.floor(tSec / (busy > 0.5 ? 0.4 : 3)));
  for (let row = 4; row < h - 2; row += 4) {
    for (const [ux, face] of [[2, 0], [5, 0], [8, 0], [2, 1], [5, 1], [8, 1]]) {
      const lit = r() < litP;
      const px = face === 0 ? cx - hw + ux : cx + ux;
      const py = face === 0 ? cy + ux * hh / hw - row : cy + hh - ux * hh / hw - row;
      ctx.fillStyle = lit ? (busy > 0.6 ? "#fff2b0" : "#ffd27a") : shade([40, 52, 70], 1);
      ctx.fillRect(px | 0, (py - 1) | 0, 1, 2);
    }
  }
  const roofX = cx, roofY = cy - h;
  if (b.agent) { // agent processes get a blinking beacon
    ctx.fillStyle = shade([90, 90, 100], 1); ctx.fillRect(roofX, roofY - 5, 1, 4);
    if (Math.sin(tSec * 4 + b.seed) > 0) { ctx.fillStyle = "#ff5a5a"; ctx.fillRect(roofX - 1, roofY - 6, 3, 2); }
  }
  if (b.cpu > 25 && Math.random() < 0.08 + b.cpu / 1500) b.smoke.push({ x: roofX + 3, y: roofY - 1, a: 1 });
  for (const s of b.smoke) {
    s.y -= 0.25; s.x += 0.08; s.a -= 0.012;
    ctx.fillStyle = `rgba(210,210,215,${Math.max(0, s.a) * 0.7})`; ctx.fillRect(s.x | 0, s.y | 0, 2, 2);
  }
  b.smoke = b.smoke.filter(s => s.a > 0);
  b.roof = [roofX, roofY];
  drawnBuildings++;
}

function drawTree(l) {
  const [sx, sy] = iso(l.x, l.y);
  const cx = sx, cy = sy + TH / 2;
  ctx.fillStyle = shade([95, 70, 50], 1); ctx.fillRect(cx, cy - 3, 1, 3);
  ctx.fillStyle = shade([60, 120, 60], 1); ctx.fillRect(cx - 2, cy - 7, 5, 4);
  ctx.fillStyle = shade([80, 150, 75], 1); ctx.fillRect(cx - 1, cy - 8, 3, 2);
}

function drawTower(net) {
  const [sx, sy] = iso(TOWER_LOT.x, TOWER_LOT.y);
  const cx = sx, base = sy + TH / 2;
  ctx.fillStyle = shade([150, 150, 160], 1);
  for (let i = 0; i < 26; i++) ctx.fillRect(cx - ((26 - i) / 9 | 0), base - i, 1 + 2 * ((26 - i) / 9 | 0), 1);
  const top = [cx, base - 27];
  const strength = clamp(Math.log10(1 + (net.rx_bps + net.tx_bps) / 1000) / 5, 0, 1);
  for (let k = 0; k < 3; k++) {
    const rr = ((tSec * 14 + k * 9) % 27);
    ctx.strokeStyle = `rgba(140,230,255,${(1 - rr / 27) * strength})`;
    ctx.beginPath(); ctx.arc(top[0], top[1], rr, Math.PI * 1.05, Math.PI * 1.95); ctx.stroke();
  }
  ctx.fillStyle = Math.sin(tSec * 3) > 0 ? "#ffef7a" : "#c9b04a"; ctx.fillRect(top[0] - 1, top[1] - 1, 3, 2);
  return top;
}

function drawCar(c) {
  const gx = c.axis === "x" ? c.pos : c.line + 0.5 + c.lane;
  const gy = c.axis === "x" ? c.line + 0.5 + c.lane : c.pos;
  const [sx, sy] = iso(gx, gy);
  ctx.fillStyle = shade(c.color, 1); ctx.fillRect((sx - 1) | 0, (sy - 2) | 0, 3, 2);
  ctx.fillStyle = shade([30, 30, 40], 1); ctx.fillRect((sx - 1) | 0, sy | 0, 3, 1);
  if (night > 0.4) {
    const fx = c.axis === "x" ? c.dir : -c.dir;
    ctx.fillStyle = "#fff6c8"; ctx.fillRect((sx + fx * 2) | 0, (sy - 1) | 0, 1, 1);
  }
}

function update(dt, s) {
  // building heights ease toward their targets; new apps rise from the ground
  for (const b of buildings.values()) b.height += (b.target - b.height) * Math.min(1, dt * 1.8);
  const want = clamp(Math.round(s.procs / 12), 6, 90);
  while (cars.length < want) spawnCar(carRng);
  if (cars.length > want) cars.length = want;
  const speed = 0.8 + 3 * s.cpu;
  for (const c of cars) {
    c.pos += c.dir * c.speed * speed * dt;
    if (c.pos < -0.5 || c.pos > N + 0.5) { c.pos = c.dir > 0 ? -0.5 : N + 0.5; c.line = 4 * Math.floor(carRng() * 5); }
  }
  rxCarry += rateFor(s.net.rx_bps) * dt; txCarry += rateFor(s.net.tx_bps) * dt;
  const targets = [...buildings.values()].filter(b => b.roof);
  while (rxCarry >= 1 && targets.length) { rxCarry--; arcs.push({ to: targets[(carRng() * targets.length) | 0], t: 0, inbound: true }); }
  while (txCarry >= 1 && targets.length) { txCarry--; arcs.push({ to: targets[(carRng() * targets.length) | 0], t: 0, inbound: false }); }
  for (const a of arcs) a.t += dt * 1.4;
  for (let i = arcs.length - 1; i >= 0; i--) if (arcs[i].t >= 1) arcs.splice(i, 1);
}

function drawArcs(top) {
  for (const a of arcs) {
    if (!a.to.roof) continue;
    const [x0, y0] = a.inbound ? top : a.to.roof, [x1, y1] = a.inbound ? a.to.roof : top;
    for (let k = 0; k < 4; k++) {
      const t = clamp(a.t - k * 0.04, 0, 1);
      const x = lerp(x0, x1, t), y = lerp(y0, y1, t) - Math.sin(t * Math.PI) * 30;
      ctx.fillStyle = a.inbound ? `rgba(120,230,255,${1 - k * 0.25})` : `rgba(255,140,220,${1 - k * 0.25})`;
      ctx.fillRect(x | 0, y | 0, k === 0 ? 2 : 1, k === 0 ? 2 : 1);
    }
  }
}

function drawLabels() {
  const top = [...buildings.values()].filter(b => b.roof && b.height > 4)
    .sort((a, b) => b.cpu - a.cpu).slice(0, 3);
  const placed = [];
  for (const b of top) {
    const s = b.name.slice(0, 18), w = textWidth(s);
    const x = clamp((b.roof[0] - w / 2) | 0, 2, W - w - 2);
    let y = (b.roof[1] - 14) | 0;
    while (placed.some(p => x < p[0] + p[2] + 4 && p[0] < x + w + 4 && Math.abs(p[1] - y) < 11)) y -= 11;
    placed.push([x, y, w]);
    ctx.fillStyle = "rgba(246,231,193,0.5)"; ctx.fillRect(b.roof[0] | 0, y + 7, 1, Math.max(0, (b.roof[1] - y - 9) | 0));
    ctx.fillStyle = "rgba(14,18,40,0.82)"; ctx.fillRect(x - 2, y - 2, w + 4, 9);
    drawText(s, x, y, "#f6e7c1");
  }
}

function drawHud(s, hour) {
  const hh = String(Math.floor(hour)).padStart(2, "0"), mm = String(Math.floor((hour % 1) * 60)).padStart(2, "0");
  const lines = [
    `THIS MAC  ${hh}:${mm}`,
    `CPU ${Math.round(s.cpu * 100)}%  MEMORY ${Math.round(s.mem.used * 100)}% OF ${s.mem.total_gb}GB  LOAD ${s.load[0].toFixed(1)}`,
    `NET IN ${fmtBytes(s.net.rx_bps)}  OUT ${fmtBytes(s.net.tx_bps)}`,
    `${s.procs} PROCESSES  ${buildings.size} BUILDINGS`,
  ];
  const w = Math.max(...lines.map(textWidth));
  ctx.fillStyle = "rgba(14,18,40,0.78)"; ctx.fillRect(8, H - 12 - lines.length * 8, w + 10, lines.length * 8 + 6);
  lines.forEach((l, i) => drawText(l, 13, H - 9 - (lines.length - i) * 8 + 3, i === 0 ? "#ffd27a" : "#f6e7c1"));
}

function fitView() {
  const w = RECORD_SECONDS ? 1280 : innerWidth, h = RECORD_SECONDS ? 720 : innerHeight;
  const scale = Math.max(1, Math.min(w / W, h / H));
  const s = scale >= 2 ? Math.floor(scale) : scale;
  view.width = Math.round(W * s); view.height = Math.round(H * s);
  view.style.marginTop = RECORD_SECONDS ? "0" : Math.max(0, (innerHeight - view.height) / 2) + "px";
  vctx.imageSmoothingEnabled = false;
}
addEventListener("resize", fitView); fitView();

let last = performance.now();
function loop(now) {
  const dt = Math.min(0.1, (now - last) / 1000); last = now; tSec += dt; frame++;
  if (snap) {
    let hour = HOUR_OVERRIDE !== null ? HOUR_OVERRIDE : snap.hour + (now - snapAt) / 3.6e6;
    if (CYCLE_SECONDS) hour = (hour + (tSec / CYCLE_SECONDS) * 24) % 24;
    night = nightAt(hour); light = lerp(1, 0.62, night);
    update(dt, snap);
    drawSky(hour);
    const loadFrac = snap.load[0] / snap.ncpu;
    drawGround(loadFrac);
    drawnBuildings = 0;
    const items = [];
    for (const b of buildings.values()) items.push({ d: b.lot.x + b.lot.y, f: () => drawBuilding(b) });
    for (const t of trees) if (!t.owner) items.push({ d: t.x + t.y, f: () => drawTree(t) });
    for (const c of cars) items.push({ d: (c.axis === "x" ? c.pos + c.line : c.line + c.pos) + 0.6, f: () => drawCar(c) });
    let top = null;
    items.push({ d: TOWER_LOT.x + TOWER_LOT.y, f: () => { top = drawTower(snap.net); } });
    items.sort((a, b) => a.d - b.d);
    for (const it of items) it.f();
    if (top) drawArcs(top);
    drawLabels();
    drawHud(snap, hour);
    vctx.drawImage(buf, 0, 0, view.width, view.height);
    if (++drawnFrames === 60) report();
  }
  requestAnimationFrame(loop);
}
requestAnimationFrame(loop);

function report() {
  const px = ctx.getImageData(0, 0, W, H).data, colors = new Set();
  for (let i = 0; i < px.length; i += 4 * 37) colors.add((px[i] << 16) | (px[i + 1] << 8) | px[i + 2]);
  const body = { frame: drawnFrames, buildings: drawnBuildings, apps: snap.apps.length, cars: cars.length, arcs: arcs.length,
    colors: colors.size, night: Number(night.toFixed(2)) };
  window.simmacReport = body;
  fetch("/api/rendered", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

// Record mode: capture the scaled canvas for N seconds and hand the clip to the server.
if (RECORD_SECONDS) {
  setTimeout(() => {
    const stream = view.captureStream(30);
    const mime = MediaRecorder.isTypeSupported("video/webm;codecs=vp9") ? "video/webm;codecs=vp9" : "video/webm";
    const rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 8e6 });
    const chunks = [];
    rec.ondataavailable = e => e.data.size && chunks.push(e.data);
    rec.onstop = () => fetch("/api/clip", { method: "POST", body: new Blob(chunks, { type: "video/webm" }) });
    rec.start(1000);
    setTimeout(() => rec.stop(), RECORD_SECONDS * 1000);
  }, 4000);
}
