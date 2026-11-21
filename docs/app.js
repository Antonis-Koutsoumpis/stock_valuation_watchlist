/* Rule #1 watchlist: web version of app.py (Stock page and Screener).
 * The data in data/ is built by rule1/export_web.py (GitHub Action pages.yml) with the same
 * code as the Streamlit app. Only the calculated value is done here (port of rule1/valuation.py),
 * so its sliders work in the browser. Charts: Plotly (vendor/).
 */
"use strict";

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const DAY = 86400000;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const TOUCH = window.matchMedia("(pointer: coarse)").matches;
const COLORS = ["#1f77b4", "#d62728", "#9467bd", "#ff7f0e"];
const COMPARE_COLORS = ["#2ca02c", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"];
const DCF_FILL = "rgba(46, 139, 87, 0.22)", DCF_LINE = "rgba(46, 139, 87, 0.9)";
const CALC_FILL = "rgba(255, 140, 0, 0.18)", CALC_LINE = "rgba(230, 120, 0, 0.95)";
const REAL = " real";
const NOT_PRICES = new Set(["VIX"]);
const BAR_GAP = 4 * DAY;
const PERIODS = ["1w", "1m", "6m", "1y", "3y", "5y", "10y", "20y", "All", "Custom"];
const ROW_LABELS = { roic: "ROIC (average)", net_debt_fcf: "Net Debt / FCF (average)", bvps: "BVPS growth",
  revenue: "Revenue growth", eps_diluted: "EPS (diluted) growth", fcf: "Free Cash Flow growth" };

let WATCH = [], G = {}, CPI = {}, SCREENER = null;
const CACHE = new Map();

/* ---------------- formatting ---------------- */
const nfCache = {};
const nf = (d) => (nfCache[d] ||= new Intl.NumberFormat("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));
const isNum = (v) => typeof v === "number" && Number.isFinite(v);
/** Same as fmt() in app.py */
function fmt(v, percent = false) {
  if (!isNum(v)) return "";
  if (percent) return nf(1).format(v * 100) + "%";
  if (Math.abs(v) >= 1e9) return nf(2).format(v / 1e9) + " B";
  if (Math.abs(v) >= 1e6) return nf(1).format(v / 1e6) + " M";
  return nf(2).format(v);
}
const signedPct = (v, d = 0) => (v >= 0 ? "+" : "") + nf(d).format(v * 100) + "%";
const dateLabel = (t) => { const d = new Date(t); return `${String(d.getUTCDate()).padStart(2, "0")} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`; };
const ymd = (t) => new Date(t).toISOString().slice(0, 10);
const addMonths = (t, n) => { const d = new Date(t); const y = d.getUTCFullYear(), m = d.getUTCMonth() + n, day = d.getUTCDate();
  const last = new Date(Date.UTC(y, m + 1, 0)).getUTCDate(); return Date.UTC(y, m, Math.min(day, last)); };
const OFFSETS = { "1w": (t) => t - 7 * DAY, "1m": (t) => addMonths(t, -1), "6m": (t) => addMonths(t, -6),
  ...Object.fromEntries([1, 3, 5, 10, 20].map((n) => [`${n}y`, (t) => addMonths(t, -12 * n)])) };

/* ---------------- quarters ---------------- */
const quarterStart = (label) => Date.UTC(+label.slice(0, 4), 3 * (+label.slice(-1) - 1), 1);
const quarterEnd = (label) => Date.UTC(+label.slice(0, 4), 3 * +label.slice(-1), 0);
const quarterMid = (label) => { const s = quarterStart(label); return s + (quarterEnd(label) - s) / 2; };
const quarterOf = (t) => { const d = new Date(t); return `${d.getUTCFullYear()}Q${Math.floor(d.getUTCMonth() / 3) + 1}`; };

/* ---------------- series: {t: [ms], v: [values]} ---------------- */
const mkSeries = (t, v) => { const T = [], V = []; t.forEach((x, i) => { if (isNum(v[i])) { T.push(x); V.push(v[i]); } }); return { t: T, v: V }; };
const emptyS = () => ({ t: [], v: [] });
const filterS = (s, f) => { const T = [], V = []; s.t.forEach((x, i) => { if (f(x, s.v[i])) { T.push(x); V.push(s.v[i]); } }); return { t: T, v: V }; };
const lastOf = (s) => (s.v.length ? s.v[s.v.length - 1] : NaN);
const meanOf = (a) => a.reduce((x, y) => x + y, 0) / a.length;

function realSeries(s) {
  const months = Object.keys(CPI).sort();
  if (!months.length || !s.t.length) return emptyS();
  const lastM = months[months.length - 1], lastCpi = CPI[lastM];
  const T = [], V = [];
  s.t.forEach((t, i) => {
    const m = ymd(t).slice(0, 7);
    const c = m > lastM ? lastCpi : CPI[m];
    if (isNum(c)) { T.push(t); V.push(s.v[i] * lastCpi / c); }
  });
  return { t: T, v: V };
}

/* ---------------- loading ---------------- */
async function loadJSON(url) { const r = await fetch(url); if (!r.ok) throw new Error(url); return r.json(); }
async function loadStock(ticker) {
  const base = ticker.replace(REAL, "");
  if (!CACHE.has(base)) CACHE.set(base, loadJSON(`data/stocks/${encodeURIComponent(base)}.json`).then(prepare));
  const st = await CACHE.get(base);
  if (!ticker.endsWith(REAL)) return st;
  const close = realSeries(st.close);
  const keep = new Set(close.t);
  const daily = {};
  for (const [k, s] of Object.entries(st.dailyS)) daily[k] = k === "close" ? close : filterS(s, (t) => keep.has(t));
  return { ...st, ticker, name: `${st.name} (inflation-adjusted)`, close, dailyS: daily };
}
function prepare(raw) {
  const st = { ...raw };
  const t = raw.daily ? raw.daily.d.map((d) => d * DAY) : [];
  st.dailyS = {};
  if (raw.daily) for (const [k, v] of Object.entries(raw.daily.cols)) st.dailyS[k] = mkSeries(t, v);
  st.close = st.dailyS.close || emptyS();
  st.q = raw.quarterly || { p: [], cols: {} };
  st.a = raw.annual || { p: [], cols: {} };
  return st;
}
async function loadClose(ticker) { return (await loadStock(ticker)).close; }

/* ---------------- valuation (port of rule1/valuation.py) ---------------- */
const SCEN = ["Conservative", "Middle", "Optimistic"];
const num = (v) => (isNum(v) ? v : NaN);
const clip = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
function percentile(vals, p) {   // numpy default (linear)
  const a = vals.slice().sort((x, y) => x - y), pos = (a.length - 1) * p / 100, lo = Math.floor(pos), hi = Math.ceil(pos);
  return a[lo] + (a[hi] - a[lo]) * (pos - lo);
}
function median(vals) { const a = vals.filter(isNum); return a.length ? percentile(a, 50) : NaN; }
function dcfPerShare(start, g, r, tg, years) {
  if (!(start > 0) || r <= tg) return NaN;
  let pv = 0, last = 0;
  for (let t = 1; t <= years; t++) { last = start * (1 + g) ** t; pv += last / (1 + r) ** t; }
  return pv + (last * (1 + tg) / (r - tg)) / (1 + r) ** years;
}
function exitMultiple(start, g, r, multiple, years) {
  if (!(start > 0) || !(multiple > 0)) return NaN;
  let pv = 0, last = 0;
  for (let t = 1; t <= years; t++) { last = start * (1 + g) ** t; pv += last / (1 + r) ** t; }
  return pv + last * multiple / (1 + r) ** years;
}
function valuate(src, A) {
  const inp = Object.fromEntries(Object.entries(src.inp).map(([k, v]) => [k, num(v)]));
  const cands = Object.fromEntries(Object.entries(src.cands).filter(([, v]) => isNum(v)));
  const vals = Object.values(cands);
  let growth = {};
  if (A.growth != null) growth = { Conservative: A.growth - 0.03, Middle: A.growth, Optimistic: A.growth + 0.03 };
  else if (vals.length) growth = { Conservative: percentile(vals, 25), Middle: percentile(vals, 50), Optimistic: percentile(vals, 75) };
  for (const s in growth) growth[s] = clip(growth[s], 0, A.growth_cap);
  const table = Object.fromEntries(G.methods.map((m) => [m, { Conservative: NaN, Middle: NaN, Optimistic: NaN }]));
  let mos = NaN;
  const { eps, fcf_per_share: fcf, avg_pe: avgPe, bvps } = inp;
  const multiple = avgPe > 0 ? clip(avgPe, 8, 25) : 15;
  if (Object.keys(growth).length) {
    const rates = { Conservative: [A.discount + A.spread, A.terminal - 0.01], Middle: [A.discount, A.terminal], Optimistic: [A.discount - A.spread, A.terminal] };
    for (const s of SCEN) {
      const [r, tg] = rates[s], g = growth[s];
      let sticker = NaN, m = NaN;
      if (eps > 0) {
        let fpe = 2 * g * 100; if (avgPe > 0) fpe = Math.min(fpe, avgPe); fpe = Math.min(fpe, A.max_pe);
        sticker = eps * (1 + g) ** A.horizon * fpe / (1 + A.marr) ** A.horizon; m = sticker / 2;
      }
      const v = {
        "FCF DCF": dcfPerShare(fcf, g, r, tg, A.horizon), "EPS DCF": dcfPerShare(eps, g, r, tg, A.horizon),
        "FCF exit multiple": exitMultiple(fcf, g, r, multiple, A.horizon), "EPS exit multiple": exitMultiple(eps, g, r, multiple, A.horizon),
        "Rule #1 Sticker Price": sticker,
        "Graham formula": eps > 0 ? eps * (8.5 + 2 * g * 100) * 0.044 / A.bond_yield : NaN,
        "Peter Lynch fair value": eps > 0 ? eps * clip(g * 100, 5, 25) : NaN,
        "Earnings power value": eps > 0 ? eps / r : NaN,
        "Graham number": eps > 0 && bvps > 0 ? Math.sqrt(22.5 * eps * bvps) : NaN,
      };
      for (const k of G.methods) table[k][s] = num(v[k]);
      if (s === "Middle") mos = m;
    }
  }
  const col = (s) => G.methods.map((k) => table[k][s]);
  return { table, range: { low: median(col("Conservative")), middle: median(col("Middle")), high: median(col("Optimistic")) },
    growth, candidates: cands, inputs: inp, mos };
}
function valuationHistory(st, A) {
  const out = [];
  for (const h of st.valuation.history) {
    const v = valuate(h, A);
    if (![v.range.low, v.range.middle, v.range.high].some(isNum)) continue;
    out.push({ q: h.q, low: v.range.low, middle: v.range.middle, high: v.range.high, mos: v.mos,
      ...Object.fromEntries(G.methods.map((m) => [m, v.table[m].Middle])) });
  }
  return out;
}

/* ---------------- trends (port of rule1/charts.py) ---------------- */
function polyfit(x, y, deg) {
  const lo = Math.min(...x), hi = Math.max(...x), c = (lo + hi) / 2, h = (hi - lo) / 2 || 1;
  const xs = x.map((v) => (v - c) / h), k = deg + 1;
  const A = Array.from({ length: k }, () => new Array(k + 1).fill(0));
  xs.forEach((v, r) => { const p = Array.from({ length: k }, (_, i) => v ** i); for (let i = 0; i < k; i++) { for (let j = 0; j < k; j++) A[i][j] += p[i] * p[j]; A[i][k] += p[i] * y[r]; } });
  for (let col = 0; col < k; col++) {
    let p = col; for (let r = col + 1; r < k; r++) if (Math.abs(A[r][col]) > Math.abs(A[p][col])) p = r;
    [A[col], A[p]] = [A[p], A[col]];
    for (let r = 0; r < k; r++) if (r !== col) { const f = A[r][col] / A[col][col]; for (let j = col; j <= k; j++) A[r][j] -= f * A[col][j]; }
  }
  const a = A.map((row, i) => row[k] / row[i]);
  const evalAt = (v) => { const z = (v - c) / h; return a.reduce((s, ai, i) => s + ai * z ** i, 0); };
  return { evalAt, slope: deg === 1 ? a[1] / h : NaN };
}
function trend(s, kind, degree) {
  let ser = kind === "Log" ? filterS(s, (t, v) => v > 0) : s;
  if (ser.t.length < Math.max(3, degree + 1)) return null;
  const x = ser.t.map((t) => (t - ser.t[0]) / DAY / 365.25);
  if (kind === "Linear") { const f = polyfit(x, ser.v, 1); return { t: ser.t, v: x.map(f.evalAt), label: `linear trend (${f.slope >= 0 ? "+" : ""}${nf(2).format(f.slope)}/yr)` }; }
  if (kind === "Polynomial") { const f = polyfit(x, ser.v, degree); return { t: ser.t, v: x.map(f.evalAt), label: `polynomial trend (degree ${degree})` }; }
  const f = polyfit(x, ser.v.map(Math.log), 1), growth = Math.exp(f.slope) - 1;
  return { t: ser.t, v: x.map((v) => Math.exp(f.evalAt(v))), label: `log trend (${growth >= 0 ? "+" : ""}${nf(1).format(growth * 100)}%/yr)` };
}
function trailingAverage(s, years) {
  if (!s.t.length) return null;
  const end = s.t[s.t.length - 1], start = addMonths(end, -12 * years);
  if (s.t[0] > addMonths(start, 6)) return null;
  return [start, end, meanOf(s.v.filter((_, i) => s.t[i] >= start))];
}

/* ---------------- state ---------------- */
const SP = {
  page: "stock", ticker: null, selected: ["close"], shownIdx: [], period: "5y", from: null, to: null,
  log: false, quarterly: false, barValues: false, trends: [], degree: 2, averages: [], avgFor: null,
  showDcf: false, compare: [], horizon: 10, discount: 10, ownGrowth: null, showCalc: false, perfLog: true, tab: "Yearly",
};
let ST = null;   // loaded stock
let CONDITIONS = null;

/* ---------------- Plotly ---------------- */
function themeLayout(extra = {}) {
  const cs = getComputedStyle(document.documentElement);
  const text = cs.getPropertyValue("--text").trim(), line = cs.getPropertyValue("--line").trim();
  const base = { paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: text, family: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", size: 12 } };
  const out = { ...base, ...extra };
  for (const k of Object.keys(out)) if (/^[xy]axis\d*$/.test(k)) out[k] = { gridcolor: line, zerolinecolor: line, ...out[k] };
  if (!out.xaxis) out.xaxis = { gridcolor: line };
  if (!out.yaxis) out.yaxis = { gridcolor: line };
  return out;
}
const PLOT_CONFIG = { displaylogo: false, responsive: true, displayModeBar: !TOUCH };
const X = (t) => ymd(t);

/* ---------------- stock page ---------------- */
function watchOptions() {
  const idx = WATCH.filter((w) => w.type === "index").sort((a, b) => (a.ticker !== "SPX") - (b.ticker !== "SPX"));
  const opts = [];
  for (const r of idx) {
    opts.push({ value: r.ticker, label: `${r.ticker} · ${r.name}` });
    if (Object.keys(CPI).length && !NOT_PRICES.has(r.ticker)) opts.push({ value: r.ticker + REAL, label: `${r.ticker}${REAL} · ${r.name} (inflation-adjusted)` });
  }
  for (const r of WATCH.filter((w) => w.type !== "index")) opts.push({ value: r.ticker, label: `${r.ticker} · ${r.name}` });
  return opts;
}
const nameOf = (t) => (WATCH.find((w) => w.ticker === t.replace(REAL, "")) || {}).name || t;
function indexNames() {
  const out = {};
  for (const r of WATCH.filter((w) => w.type === "index" && !NOT_PRICES.has(w.ticker))) {
    out[r.ticker] = r.name;
    if (Object.keys(CPI).length) out[r.ticker + REAL] = `${r.name} (inflation-adjusted)`;
  }
  for (const r of WATCH.filter((w) => NOT_PRICES.has(w.ticker))) out[r.ticker] = r.name;
  return out;
}

function availableMetrics(st) {
  const graph = { ...G.daily, ...G.quarterly, ...G.dcf };
  return Object.keys(graph).filter((m) =>
    (G.daily[m] && st.dailyS[m] && st.dailyS[m].v.length)
    || (G.quarterly[m] && st.q.cols[m] && st.q.cols[m].some(isNum))
    || (G.quarterly[m] && st.a.cols[m.replace(/_ttm$/, "")] && st.a.cols[m.replace(/_ttm$/, "")].some(isNum))
    || (G.dcf[m] && st.close.v.length));
}
const GRAPH = () => ({ ...G.daily, ...G.quarterly, ...G.dcf });

function checklist(boxId, items, selected, onChange, max) {
  const box = $(boxId); box.innerHTML = "";
  for (const it of items) {
    const l = document.createElement("label"); l.className = "check";
    l.innerHTML = `<input type="checkbox" value="${esc(it.value)}"> ${esc(it.label)}`;
    const cb = l.querySelector("input"); cb.checked = selected.includes(it.value);
    cb.onchange = () => onChange(it.value, cb.checked);
    box.appendChild(l);
  }
  if (max) {
    const full = selected.length >= max;
    box.querySelectorAll("input").forEach((cb) => { cb.disabled = full && !cb.checked; cb.parentElement.classList.toggle("disabled", cb.disabled); });
  }
}
function chips(id, values, isOn, toggle, label = (v) => v) {
  const box = $(id); box.innerHTML = "";
  for (const v of values) {
    const b = document.createElement("button"); b.type = "button"; b.className = "chip"; b.textContent = label(v);
    b.setAttribute("aria-pressed", isOn(v));
    b.onclick = () => { toggle(v); renderStockSidebar(); renderStock(); };
    box.appendChild(b);
  }
}

function renderStockSidebar() {
  const st = ST, g = GRAPH();
  const avail = availableMetrics(st);
  SP.selected = SP.selected.filter((m) => avail.includes(m));
  checklist("#vars", avail.map((m) => ({ value: m, label: g[m].label })), SP.selected, (m, on) => {
    SP.selected = on ? [...SP.selected, m] : SP.selected.filter((x) => x !== m);
    renderStockSidebar(); renderStock();
  }, 4);
  $("#varsSummary").textContent = `(${SP.selected.length} of 4)`;
  $("#varsHelp").innerHTML = variablesHelp(SP.ticker);
  const inames = indexNames();
  checklist("#shownIdx", Object.entries(inames).map(([v, l]) => ({ value: v, label: l })), SP.shownIdx, (t, on) => {
    SP.shownIdx = on ? [...SP.shownIdx, t] : SP.shownIdx.filter((x) => x !== t); renderStockSidebar(); renderStock();
  });
  $("#idxSummary").textContent = SP.shownIdx.length ? `(${SP.shownIdx.length})` : "";
  chips("#scale", ["Raw", "Logarithmic"], (v) => (v === "Logarithmic") === SP.log, (v) => { SP.log = v === "Logarithmic"; });
  chips("#freq", ["Daily", "Quarterly average"], (v) => (v === "Quarterly average") === SP.quarterly, (v) => { SP.quarterly = v === "Quarterly average"; });
  $("#freq").querySelectorAll(".chip").forEach((c) => { c.disabled = !SP.selected.some((m) => G.daily[m] && m !== "close"); });
  $("#barValues").checked = SP.barValues; $("#barValues").disabled = !SP.selected.some((m) => G.quarterly[m]);
  chips("#trends", ["Linear", "Polynomial", "Log"], (v) => SP.trends.includes(v), (v) => { SP.trends = SP.trends.includes(v) ? SP.trends.filter((x) => x !== v) : [...SP.trends, v]; });
  $("#degreeBox").hidden = !SP.trends.includes("Polynomial");
  chips("#averages", [5, 10], (v) => SP.averages.includes(v), (v) => { SP.averages = SP.averages.includes(v) ? SP.averages.filter((x) => x !== v) : [...SP.averages, v]; }, (y) => `${y}-year average`);
  if (SP.avgFor == null || SP.avgFor.some((m) => !SP.selected.includes(m))) {
    const def = SP.selected.filter((m) => m === "trailing_pe");
    SP.avgFor = SP.avgFor ? SP.avgFor.filter((m) => SP.selected.includes(m)) : (def.length ? def : SP.selected.slice(0, 1));
  }
  $("#avgForBox").hidden = !SP.averages.length;
  chips("#avgFor", SP.selected, (m) => SP.avgFor.includes(m), (m) => { SP.avgFor = SP.avgFor.includes(m) ? SP.avgFor.filter((x) => x !== m) : [...SP.avgFor, m]; }, (m) => g[m].label);
  $("#showDcf").checked = SP.showDcf; $("#showDcf").disabled = !st.dcf || !SP.selected.includes("close");
  // compare
  const base = SP.ticker.replace(REAL, "");
  const idxT = WATCH.filter((w) => w.type === "index" && !NOT_PRICES.has(w.ticker)).map((w) => w.ticker);
  const others = [...idxT, ...WATCH.filter((w) => w.type !== "index").map((w) => w.ticker)].filter((t) => t !== SP.ticker && t !== base || (SP.ticker.endsWith(REAL) && t === base));
  const f = normalize($("#cmpFilter").value);
  const items = others.filter((t) => !f || normalize(`${t} ${nameOf(t)}`).includes(f) || SP.compare.includes(t)).map((t) => ({ value: t, label: `${t} · ${nameOf(t)}` }));
  checklist("#compare", items, SP.compare, (t, on) => { SP.compare = on ? [...SP.compare, t] : SP.compare.filter((x) => x !== t); renderStockSidebar(); renderStock(); });
  $("#cmpSummary").textContent = SP.compare.length ? `(${SP.compare.join(", ")})` : "";
  $("#showCalc").checked = SP.showCalc;
}
const normalize = (s) => String(s).toLowerCase().normalize("NFKD").replace(/\p{M}/gu, "").trim();

function variablesHelp(ticker) {
  let text = "Up to 4, each with its own axis. What each variable means is explained under the graph.";
  const base = ticker.replace(REAL, "");
  if (G.market_tickers.includes(base)) {
    text += `<br><br><b>Valuation of the US market</b> (free sources, updated daily; compare today's value with its own history, e.g. with Average lines and the All time range)`;
    text += base !== "SPX" ? ": these describe the whole US market (S&amp;P 500), not this index itself: no free history of its own CAPE or P/E exists. Its own valuation is the Trailing P/E." : ".";
    text += ` Trailing P/E and Price/Book come from the ${esc(G.etf_names[base])} on Yahoo and are stored from November 2026 onwards.`;
  }
  return text;
}

function timeRange(st) {
  const first = st.close.t[0], last = st.close.t[st.close.t.length - 1];
  const defStart = Math.max(first, addMonths(last, -60));
  if (SP.period === "Custom") {
    let a = Date.parse(SP.from || ymd(defStart)), b = Date.parse(SP.to || ymd(last));
    if (!isNum(a) || !isNum(b)) { a = defStart; b = last; }
    if (a > b) [a, b] = [b, a];
    return [Math.max(a, first), Math.min(b, last), first, last];
  }
  const end = last;
  return [OFFSETS[SP.period] ? Math.max(first, OFFSETS[SP.period](end)) : first, end, first, last];
}

function tile(label, value, help) {
  return `<div class="tile"><div class="lab">${help ? `<abbr title="${esc(help)}">${esc(label)}</abbr>` : esc(label)}</div><div class="val">${esc(value || "—")}</div></div>`;
}

async function renderStock() {
  const st = ST, page = $("#page-stock"), g = GRAPH();
  document.title = `${st.name} (${SP.ticker}) · Rule #1 Watchlist`;
  $("#title").textContent = `${st.name} (${SP.ticker})`;
  if (!st.close.t.length) {
    page.innerHTML = `<h2 class="section">${esc(st.name)} (${esc(SP.ticker)})</h2><div class="notice warn-box">No data stored for this stock yet. It appears after the next daily update.</div>`;
    return;
  }
  const A = { ...G.assumptions, horizon: SP.horizon, discount: SP.discount / 100, growth: SP.ownGrowth == null ? null : SP.ownGrowth / 100 };
  const calc = st.valuation.now ? valuate(st.valuation.now, A) : null;
  const calcHist = valuationHistory(st, A);
  const [start, end] = timeRange(st);
  const inRange = (s, margin = 0) => filterS(s, (t) => t + margin >= start && t <= end + DAY);

  // ---- header numbers
  const lastI = st.close.t.length - 1, lastClose = st.close.v[lastI], lastDay = st.close.t[lastI];
  const lastD = (k) => (st.dailyS[k] ? lastOf(st.dailyS[k]) : NaN);
  const roicArr = (st.q.cols.roic_ttm || []).filter(isNum);
  const roic = roicArr.length ? roicArr[roicArr.length - 1] : NaN;
  const own = inRange(st.close);
  const total = own.v.length > 1 ? own.v[own.v.length - 1] / own.v[0] - 1 : null;
  const years = own.v.length > 1 ? (own.t[own.t.length - 1] - own.t[0]) / DAY / 365.25 : 0;
  const cagr = total != null && years >= 0.95 && total > -1 ? (1 + total) ** (1 / years) - 1 : null;
  const span = own.v.length > 1 ? `${dateLabel(own.t[0])} to ${dateLabel(own.t[own.t.length - 1])}` : "";
  const label = OFFSETS[SP.period] ? ` (${SP.period})` : years >= 0.95 ? ` (${Math.round(years)}y)` : "";
  const totalText = total != null && total >= 9 ? `×${nf(0).format(1 + total)}` : fmt(total, true);
  const cur = (WATCH.find((w) => w.ticker === SP.ticker.replace(REAL, "")) || {}).currency || "";

  let h = `<div class="tiles">
    ${tile(NOT_PRICES.has(SP.ticker) ? "Level" : `Price (${cur})`, fmt(lastClose), `${G.daily.close.help} Close on ${dateLabel(lastDay)}.`)}
    ${tile("Trailing P/E", fmt(lastD("trailing_pe")), G.daily.trailing_pe.help)}
    ${tile("Forward P/E", fmt(lastD("forward_pe")), G.daily.forward_pe.help)}
    ${tile("ROIC (TTM)", fmt(roic, true), G.quarterly.roic_ttm.help)}
    ${tile(`Price CAGR${cagr != null ? label : ""}`, fmt(cagr, true), `Average price growth per year over the chosen time range (${span}), without dividends. Shown for 1 year or longer.`)}
    ${tile(`Total growth${label}`, totalText, `Price change over the chosen time range (${span}), without dividends. Above +900% it shows how many times the price multiplied (×10 = +900%).`)}
  </div>
  <div class="field">Time range <div class="chips" id="period"></div>
    <div class="row2" id="customDates" ${SP.period === "Custom" ? "" : "hidden"}>
      <label class="field">From <input type="date" id="fromDate"></label><label class="field">To <input type="date" id="toDate"></label>
    </div></div>
  <div id="mainChart" class="chart main"></div>
  <p class="caption" id="axesNote"></p>
  <div id="perf"></div>
  <div class="legend-help" id="legendHelp"></div>
  <h2 class="section">Rule #1 numbers (latest year) <abbr class="caption" title="${esc(G.cagr_help)}">ⓘ</abbr></h2>
  <div id="rule1"></div>
  <div class="subtabs" id="subtabs"></div>
  <div id="subtab"></div>
  <p class="caption" id="currencyNote"></p>`;
  page.innerHTML = h;

  const pBox = $("#period");
  for (const p of PERIODS) {
    const b = document.createElement("button"); b.type = "button"; b.className = "chip"; b.textContent = p;
    b.setAttribute("aria-pressed", p === SP.period);
    b.onclick = () => { SP.period = p; renderStock(); };
    pBox.appendChild(b);
  }
  if (SP.period === "Custom") {
    const fd = $("#fromDate"), td = $("#toDate");
    fd.min = td.min = ymd(st.close.t[0]); fd.max = td.max = ymd(lastDay);
    fd.value = ymd(start); td.value = ymd(end);
    fd.onchange = () => { SP.from = fd.value; renderStock(); };
    td.onchange = () => { SP.to = td.value; renderStock(); };
  }

  // ---- graph
  const yearlyOnly = new Set();
  const seriesFor = (metric) => {
    if (G.dcf[metric]) {
      const key = metric.replace("dcf_", "");
      const src = st.dcf ? st.dcf.q.map((q, i) => [q, st.dcf[key][i]]) : calcHist.map((r) => [r.q, r[key]]);
      return mkSeries(src.map(([q]) => quarterMid(q)), src.map(([, v]) => v));
    }
    if (G.quarterly[metric]) {
      const vals = st.q.cols[metric] || [];
      let s = mkSeries(st.q.p.map(quarterMid), st.q.p.map((_, i) => vals[i]));
      if (!s.t.length) {
        const y = metric.replace(/_ttm$/, ""), av = st.a.cols[y] || [];
        s = mkSeries(st.a.p.map((p) => Date.UTC(+p, 6, 1)), st.a.p.map((_, i) => av[i]));
        yearlyOnly.add(metric);
        return inRange(s, 183 * DAY);
      }
      return inRange(s, 46 * DAY);
    }
    let s = st.dailyS[metric] || emptyS();
    if (SP.quarterly && metric !== "close") {
      const groups = new Map();
      s.t.forEach((t, i) => { const q = quarterOf(t); if (!groups.has(q)) groups.set(q, []); groups.get(q).push(s.v[i]); });
      s = { t: [...groups.keys()].map(quarterMid), v: [...groups.values()].map(meanOf) };
    }
    return inRange(s);
  };

  const levels = SP.shownIdx.filter((t) => NOT_PRICES.has(t));
  const overlays = [...new Set([...SP.shownIdx, ...SP.compare].filter((t) => !NOT_PRICES.has(t)))];
  const traces = [], layout = {};
  const slots = [["left", 0.0], ["right", 1.0], ["left", 0.06], ["right", 0.94]];
  let priceAxis = null;
  const firstDates = [];
  const bars = SP.selected.filter((m) => G.quarterly[m]);
  const order = [...bars, ...SP.selected.filter((m) => !bars.includes(m))];
  order.forEach((metric, i) => {
    const meta = g[metric], color = COLORS[SP.selected.indexOf(metric)];
    let name = meta.label;
    const s = seriesFor(metric);
    const r = inRange(s); if (r.t.length) firstDates.push(r.t[0]);
    const axis = i === 0 ? "y" : `y${i + 1}`;
    if (metric === "close") {
      priceAxis = axis;
      const o = inRange(st.close);
      if (overlays.length && o.v.length > 1) name = `${meta.label} (${signedPct(o.v[o.v.length - 1] / o.v[0] - 1)} in the time range)`;
    }
    if (G.quarterly[metric]) {
      const yearly = yearlyOnly.has(metric), n = bars.length, k = bars.indexOf(metric);
      const left = s.t.map((t) => { const d = new Date(t); return yearly ? Date.UTC(d.getUTCFullYear(), 0, 1) : quarterStart(quarterOf(t)); });
      const right = s.t.map((t) => { const d = new Date(t); return yearly ? Date.UTC(d.getUTCFullYear() + 1, 0, 1) : quarterStart(quarterOf(addMonths(t, 3))); });
      const spans = left.map((l, j) => right[j] - l);
      const ylab = metric.replace(/_ttm$/, "");
      traces.push({ type: "bar", x: left.map(X), y: s.v, yaxis: axis, width: spans.map((w) => w / n - BAR_GAP / n),
        offset: spans.map((w) => BAR_GAP / 2 + k * (w / n)),
        name: yearly && G.yearly[ylab] ? `${G.yearly[ylab].label} (yearly; no quarterly data)` : name,
        marker: { color }, opacity: 0.45, cliponaxis: false,
        text: SP.barValues ? s.v.map((v) => fmt(v, meta.percent)) : undefined, textposition: "outside" });
    } else {
      const points = G.dcf[metric] || (SP.quarterly && metric !== "close");
      traces.push({ type: "scatter", x: s.t.map(X), y: s.v, name, yaxis: axis, mode: points || s.t.length < 30 ? "lines+markers" : "lines",
        line: { color, width: metric === "close" ? 2 : 1.5 } });
    }
    for (const kind of SP.trends) {
      const f = trend(inRange(s), kind, SP.degree);
      if (f) traces.push({ type: "scatter", x: f.t.map(X), y: f.v, name: `${meta.label}: ${f.label}`, yaxis: axis, mode: "lines", line: { color, dash: "dash", width: 1.5 } });
    }
    for (const yrs of SP.avgFor.includes(metric) ? SP.averages : []) {
      const avg = trailingAverage(inRange(s), yrs);
      if (avg) traces.push({ type: "scatter", x: [X(avg[0]), X(avg[1])], y: [avg[2], avg[2]], yaxis: axis, mode: "lines",
        name: `${meta.label}: ${yrs}-yr average (${fmt(avg[2], meta.percent)})`, line: { color, dash: "dot", width: 2 } });
    }
    const [side, pos] = slots[i];
    const spec = { title: { text: meta.label }, side, type: SP.log ? "log" : "linear", tickformat: meta.percent ? ".0%" : undefined, showgrid: i === 0 };
    if (i) Object.assign(spec, { overlaying: "y", anchor: "free", position: pos, autoshift: true });
    layout[i === 0 ? "yaxis" : `yaxis${i + 1}`] = spec;
  });

  const addBoxes = (rows, name, fill, line) => {
    const bx = [], by = [], mx = [], my = [], mt = [];
    for (const r of rows) {
      const q0 = quarterStart(r.q), q1 = quarterEnd(r.q);
      if (q1 < start || q0 > end || !isNum(r.low) || !isNum(r.high)) continue;
      bx.push(X(q0), X(q1), X(q1), X(q0), X(q0), null); by.push(r.low, r.low, r.high, r.high, r.low, null);
      if (isNum(r.middle)) { const text = `${name} ${r.q}: ${fmt(r.low)} to ${fmt(r.high)}, middle ${fmt(r.middle)}`; mx.push(X(q0), X(q1), null); my.push(r.middle, r.middle, null); mt.push(text, text, null); }
    }
    traces.push({ type: "scatter", x: bx, y: by, yaxis: priceAxis, fill: "toself", fillcolor: fill, line: { color: line, width: 0.5 }, mode: "lines", name: `${name} (low to high)`, hoverinfo: "skip", legendgroup: name });
    traces.push({ type: "scatter", x: mx, y: my, yaxis: priceAxis, mode: "lines", name: `${name} middle`, line: { color: line, width: 2 }, text: mt, hovertemplate: "%{text}<extra></extra>", legendgroup: name });
  };
  if (SP.showDcf && st.dcf && priceAxis) addBoxes(st.dcf.q.map((q, i) => ({ q, low: st.dcf.low[i], middle: st.dcf.middle[i], high: st.dcf.high[i] })), "DCF sites", DCF_FILL, DCF_LINE);
  if (SP.showCalc && calcHist.length && priceAxis) addBoxes(calcHist, "Calculated value", CALC_FILL, CALC_LINE);

  let note = "";
  if (overlays.length && !priceAxis) note = "Add Price to the variables to see the index or compared stocks on the graph.";
  if (overlays.length && priceAxis) {
    const own2 = inRange(st.close), ownMap = new Map(own2.t.map((t, i) => [t, own2.v[i]]));
    const inames = indexNames();
    for (const [j, t] of overlays.entries()) {
      let other = await loadClose(t);
      other = filterS(other, (x) => x >= st.close.t[0]);
      const common = other.t.filter((x) => ownMap.has(x));
      if (!common.length) continue;
      const firstDay = common[0], factor = ownMap.get(firstDay) / other.v[other.t.indexOf(firstDay)];
      const shown = inRange(filterS(other, (x) => x >= firstDay));
      const change = shown.v[shown.v.length - 1] / shown.v[0] - 1;
      const o = inRange(other), lab = inames[t] || nameOf(t);
      traces.push({ type: "scatter", x: o.t.map(X), y: o.v.map((v) => v * factor), yaxis: priceAxis, mode: "lines", customdata: o.v,
        name: `${lab} (scaled to the stock on ${dateLabel(firstDay)}; ${signedPct(change)} in the time range)`,
        hovertemplate: `${lab}: %{customdata:,.2f} (scaled %{y:,.2f})<extra></extra>`,
        line: { color: COMPARE_COLORS[j % COMPARE_COLORS.length], width: 1.8, dash: "dash" } });
    }
  }
  for (const [j, t] of levels.entries()) {
    const id = 9 + j, lv = inRange(await loadClose(t));
    traces.push({ type: "scatter", x: lv.t.map(X), y: lv.v, yaxis: `y${id}`, mode: "lines", name: `${indexNames()[t]} (right axis)`,
      line: { color: COMPARE_COLORS[(overlays.length + j) % COMPARE_COLORS.length], width: 1.2 } });
    layout[`yaxis${id}`] = { title: { text: t }, side: "right", overlaying: "y", anchor: "free", position: 1.0, autoshift: true, showgrid: false, type: SP.log ? "log" : "linear" };
  }
  const xStart = firstDates.length ? Math.max(start, Math.min(...firstDates) - 45 * DAY) : start;
  const narrow = window.innerWidth < 700;
  Plotly.react("mainChart", traces, themeLayout({
    ...layout, hovermode: "x unified", margin: { l: narrow ? 45 : 60, r: narrow ? 45 : 60, t: 20, b: 30 }, barmode: "overlay",
    legend: { orientation: "h", y: narrow ? -0.35 : -0.28 },
    xaxis: { type: "date", domain: SP.selected.length + levels.length > 2 ? [0.12, 0.88] : [0.08, 0.92], range: [X(xStart), X(end + DAY)] },
  }), PLOT_CONFIG);
  $("#axesNote").textContent = note || (SP.selected.length + levels.length > 1
    ? "Each variable has its own axis (left or right), scaled to fill the graph, so the axes are not comparable: a line drawn above or below another means nothing. Read each line against its own axis and its own history (e.g. with Average lines), and compare how the lines move. Indices drawn as dashed lines are scaled to the Price and do share its axis." : "");

  if (SP.compare.length) await perfChart(st, start, end); else $("#perf").innerHTML = "";
  $("#legendHelp").innerHTML = SP.selected.map((m) => `<details><summary>${esc(g[m].label)}</summary><p class="caption">${esc(g[m].help)} Updated: ${esc(g[m].frequency.toLowerCase())}.</p></details>`).join("");

  // ---- Rule #1 table
  const gr = st.growth;
  if (!gr) $("#rule1").innerHTML = `<div class="notice">Not enough yearly data yet.</div>`;
  else {
    const ok = (m, v) => isNum(v) && (m === "net_debt_fcf" ? v <= 3 : v >= 0.1);
    $("#rule1").innerHTML = `<div class="table-wrap"><table><tr><th></th>${gr.cols.map((c) => `<th><abbr title="Over the last ${c.slice(0, -1)} year(s).">${c}</abbr></th>`).join("")}</tr>
      ${gr.rows.map((m, i) => `<tr><td>${esc(ROW_LABELS[m] || m)}</td>${gr.values[i].map((v) => `<td class="${ok(m, v) ? "green" : ""}">${fmt(v, m !== "net_debt_fcf")}</td>`).join("")}</tr>`).join("")}</table></div>
      <p class="caption">Green = meets Rule #1: ROIC and growth 10% or more a year; debt payable from 3 years of free cash flow or less (Net Debt / FCF ≤ 3, negative = more cash than debt). ROIC and Net Debt / FCF are averages over the period; the others are growth per year (CAGR). Empty cells: not enough history yet, or a start/end value that is zero or negative.</p>`;
  }

  // ---- tabs
  const tabs = ["Yearly", "Quarterly", "Calculated value", "DCF estimates"];
  const tb = $("#subtabs");
  for (const t of tabs) {
    const b = document.createElement("button"); b.className = "chip"; b.textContent = t; b.setAttribute("aria-pressed", t === SP.tab);
    b.onclick = () => { SP.tab = t; tb.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", c.textContent === t)); renderSubtab(st, calc, calcHist, cur); };
    tb.appendChild(b);
  }
  renderSubtab(st, calc, calcHist, cur);
  const fin = st.financial_currency || st.currency;
  $("#currencyNote").textContent = `${fin !== st.currency ? `Prices in ${st.currency}; financial statements in ${fin} (converted to ${st.currency} for P/E and similar ratios).` : `All values in ${st.currency}.`} Sources: SEC EDGAR (US), Yahoo Finance, and manual entries (manual values always win). TTM = trailing 12 months. Quarters are calendar quarters.`;
}

function dataTable(head, rows, helps = {}) {
  return `<div class="table-wrap"><table><tr>${head.map((c) => `<th>${helps[c] ? `<abbr title="${esc(helps[c])}">${esc(c)}</abbr>` : esc(c)}</th>`).join("")}</tr>${
    rows.map((r) => `<tr>${r.map((v) => `<td>${esc(v)}</td>`).join("")}</tr>`).join("")}</table></div>`;
}
function statementTable(block, glossary) {
  const cols = Object.keys(glossary).filter((c) => block.cols[c] && block.cols[c].some(isNum));
  const rows = block.p.map((p, i) => [p, ...cols.map((c) => fmt(block.cols[c][i], glossary[c].percent))]).reverse();
  return dataTable(["", ...cols.map((c) => glossary[c].label)], rows, Object.fromEntries(cols.map((c) => [glossary[c].label, `${glossary[c].help} Updated: ${glossary[c].frequency.toLowerCase()}.`])));
}
function renderSubtab(st, calc, calcHist, cur) {
  const box = $("#subtab");
  if (SP.tab === "Yearly") box.innerHTML = st.a.p.length ? statementTable(st.a, G.yearly) : `<p class="caption">No yearly data.</p>`;
  else if (SP.tab === "Quarterly") box.innerHTML = st.q.p.length ? statementTable(st.q, { ...G.quarterly, cash: { label: "Cash", help: "Cash and cash equivalents at quarter end.", frequency: "Quarterly", percent: false } }) : `<p class="caption">No quarterly data.</p>`;
  else if (SP.tab === "Calculated value") box.innerHTML = calcTab(calc, st.currency);
  else {
    if (!st.dcf) {
      const head = ["", "Low (conservative)", "Middle", "High (optimistic)", "Margin of Safety", ...G.methods];
      const rows = calcHist.slice().reverse().map((r) => [r.q, fmt(r.low), fmt(r.middle), fmt(r.high), fmt(r.mos), ...G.methods.map((m) => fmt(r[m]))]);
      box.innerHTML = `<div class="notice">No DCF estimates typed in yet, so this shows the calculated estimates of every method (middle scenario) at the end of each quarter, with the data published by then. Typed-in estimates (manual-entry sheet, tab 'dcf') will replace them.</div>`
        + dataTable(head, rows, { "Low (conservative)": "Median of all methods, conservative scenario.", Middle: "Median of all methods, middle scenario.", "High (optimistic)": "Median of all methods, optimistic scenario.", "Margin of Safety": "Half the Rule #1 Sticker Price.", ...G.method_help });
    } else {
      const cols = Object.keys(st.dcf).filter((c) => c !== "q");
      box.innerHTML = dataTable(["quarter", ...cols], st.dcf.q.map((q, i) => [q, ...cols.map((c) => (typeof st.dcf[c][i] === "string" ? st.dcf[c][i] : fmt(st.dcf[c][i])))]).reverse());
    }
  }
}
function calcTab(calc, currency) {
  let h = `<p class="prose">${esc(G.valuation_help)}</p><details class="panel"><summary>How each method works</summary><ul class="prose">${G.methods.map((m) => `<li><b>${esc(m)}</b>: ${esc(G.method_help[m])}</li>`).join("")}</ul></details>`;
  if (!calc || !Object.keys(calc.growth).length) return h + `<div class="notice">No value: the stock has no positive growth history or analyst estimate yet.</div>`;
  const inp = calc.inputs;
  const rows = G.methods.map((m) => [m, ...SCEN.map((s) => calc.table[m][s])]);
  const med = SCEN.map((s) => median(G.methods.map((m) => calc.table[m][s])));
  rows.push(["Median of all methods", ...med]);
  h += dataTable(["", ...SCEN, "Price / middle"], rows.map((r) => [r[0], fmt(r[1]), fmt(r[2]), fmt(r[3]), fmt(inp.price / r[2])]),
    { Conservative: "Lowest growth rates, discount rate + 2%, final growth 2%.", Middle: "Middle growth rate, your discount rate, final growth 3%.",
      Optimistic: "Highest growth rates, discount rate − 2%, final growth 3%.", "Price / middle": "Below 1: the price is below the calculated value.", ...G.method_help });
  h += `<p class="caption">Values per share in ${esc(currency)}. Rule #1 Margin of Safety price (half the middle Sticker Price): ${fmt(calc.mos)}. Empty cells: the starting value (EPS or FCF) is zero or negative.</p>`;
  h += `<div class="row2" style="align-items:start"><div><p><b>Growth rate used</b></p>${dataTable(["", "per year"], SCEN.map((s) => [s, fmt(calc.growth[s], true)]))}
    <p><b>Starting values</b></p>${dataTable(["", "value"], [["Price", fmt(inp.price)], ["EPS (diluted, last 12 months)", fmt(inp.eps)], ["FCF per share (last 12 months)", fmt(inp.fcf_per_share)],
      ["Average P/E (10 years)", fmt(inp.avg_pe)], ["Growth years", String(SP.horizon)], ["Discount rate", fmt(SP.discount / 100, true)]])}</div>
    <div><p><b>Growth rates found</b></p>${dataTable(["", "per year"], Object.entries(calc.candidates).map(([k, v]) => [k, fmt(v, true)]))}
    <p class="caption">Yearly growth (CAGR) over 5 and 10 years from the statements, and the analysts' 5-year estimate (Yahoo's P/E ÷ PEG). Conservative = 25th percentile, middle = median, optimistic = 75th percentile; between 0% and 20% a year.</p></div></div>`;
  return h;
}

async function perfChart(st, start, end) {
  const box = $("#perf");
  box.innerHTML = `<div class="field">Comparison scale <div class="chips" id="perfScale"></div></div><div id="perfChart" class="chart"></div><p class="caption">Price change only, without dividends. Starts on the first date all chosen series have data, within the time range.</p>`;
  const sc = $("#perfScale");
  for (const v of ["Logarithmic", "Raw"]) {
    const b = document.createElement("button"); b.className = "chip"; b.textContent = v; b.setAttribute("aria-pressed", (v === "Logarithmic") === SP.perfLog);
    b.onclick = () => { SP.perfLog = v === "Logarithmic"; perfChart(st, start, end); };
    sc.appendChild(b);
  }
  const series = [];
  for (const t of [SP.ticker, ...SP.compare]) {
    const s = filterS(t === SP.ticker ? st.close : await loadClose(t), (x) => x >= start && x <= end + DAY);
    if (s.t.length) series.push([t, s]);
  }
  if (series.length < 2) { box.innerHTML = `<div class="notice">Not enough overlapping price history to compare.</div>`; return; }
  const common = Math.max(...series.map(([, s]) => s.t[0]));
  const traces = series.map(([t, s0], i) => {
    const s = filterS(s0, (x) => x >= common), ch = s.v.map((v) => v / s.v[0] - 1), last = ch[ch.length - 1];
    const yrs = (s.t[s.t.length - 1] - s.t[0]) / DAY / 365.25;
    const py = yrs >= 1 && last > -1 ? (1 + last) ** (1 / yrs) - 1 : null;
    return { type: "scatter", x: s.t.map(X), y: SP.perfLog ? ch.map((c) => 1 + c) : ch, mode: "lines",
      name: `${t} · ${nameOf(t)} (${signedPct(last)}${py != null ? `, ${py >= 0 ? "+" : ""}${nf(1).format(py * 100)}%/yr` : ""})`,
      line: { width: t === SP.ticker ? 2.5 : 1.5, color: t === SP.ticker ? COLORS[0] : undefined },
      hovertemplate: SP.perfLog ? `%{y:.2f}×<extra>${t}</extra>` : `%{y:.1%}<extra>${t}</extra>` };
  });
  const narrow = window.innerWidth < 700;
  Plotly.react("perfChart", traces, themeLayout({
    title: { text: `Performance since ${dateLabel(common)}`, font: { size: 14 } }, hovermode: "x unified",
    margin: { l: 60, r: 20, t: 50, b: 30 }, legend: { orientation: "h", y: narrow ? -0.3 : -0.15 },
    xaxis: { type: "date" }, yaxis: { title: { text: SP.perfLog ? "Growth of 1 (×)" : "Change since start" }, type: SP.perfLog ? "log" : "linear", tickformat: SP.perfLog ? undefined : ".0%" },
  }), PLOT_CONFIG);
}

async function selectStock(ticker) {
  SP.ticker = ticker;
  $("#stock").value = ticker;
  try { history.replaceState(null, "", `#stock=${encodeURIComponent(ticker)}`); } catch (e) { /* ignore */ }
  $("#page-stock").innerHTML = `<div class="loading">Loading ${esc(ticker)}…</div>`;
  ST = await loadStock(ticker);
  SP.compare = SP.compare.filter((t) => t !== ticker);
  renderStockSidebar();
  await renderStock();
}

/* ---------------- screener ---------------- */
function renderScreener() {
  const page = $("#page-screener"), F = G.screener.filters;
  if (!CONDITIONS) CONDITIONS = G.screener.default_conditions.map((c) => ({ ...c }));
  const table = SCREENER.rows.map((r) => Object.fromEntries(SCREENER.columns.map((c, i) => [c, r[i]])));
  page.innerHTML = `<h2 class="section">Screener</h2>
    <p class="prose">Find watchlist stocks that meet all your conditions. The default conditions are Phil Town's Big 5: ROIC, and growth of BVPS, EPS, Revenue and Free Cash Flow, each 10% or more a year. Change the period (1 to 10 years), remove a row, or add your own. Percent metrics take percent values (type 10 for 10%).</p>
    <div id="conds"></div><button class="btn" id="addCond">➕ Add condition</button> <button class="btn ghost" id="resetCond">Reset to the Big 5</button>
    <div id="condWarn"></div><p class="caption" id="scrCount"></p><div id="scrTable"></div><p class="caption">Values are recalculated with every daily update.</p>`;
  const resolve = (metric, period) => {
    const f = F[metric]; if (!f) return null;
    const ps = Object.keys(f.periods);
    if (!ps.includes(period)) period = ps.length === 1 ? ps[0] : null;
    return period ? { col: f.periods[period], label: `${metric} (${period})`, f } : null;
  };
  const draw = () => {
    const box = $("#conds"); box.innerHTML = "";
    CONDITIONS.forEach((c, i) => {
      const row = document.createElement("div"); row.className = "cond";
      row.innerHTML = `<select class="metric" aria-label="Metric">${Object.keys(F).map((m) => `<option ${m === c.metric ? "selected" : ""}>${esc(m)}</option>`).join("")}</select>
        <select aria-label="Period">${G.screener.periods.map((p) => `<option ${p === c.period ? "selected" : ""}>${p}</option>`).join("")}</select>
        <select aria-label="Condition">${G.screener.operators.map((o) => `<option ${o === c.operator ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>
        <input type="number" step="any" aria-label="Value" value="${c.value}">
        <button class="btn ghost" aria-label="Remove condition">✕</button>`;
      const [m, p, o] = row.querySelectorAll("select"), v = row.querySelector("input");
      m.onchange = () => { c.metric = m.value; apply(); };
      p.onchange = () => { c.period = p.value; apply(); };
      o.onchange = () => { c.operator = o.value; apply(); };
      v.onchange = () => { c.value = parseFloat(v.value); apply(); };
      row.querySelector("button").onclick = () => { CONDITIONS.splice(i, 1); draw(); apply(); };
      box.appendChild(row);
    });
  };
  const OPS = { ">": (a, b) => a > b, ">=": (a, b) => a >= b, "<": (a, b) => a < b, "<=": (a, b) => a <= b, "=": (a, b) => a === b };
  const apply = () => {
    const warn = [], resolved = [];
    for (const c of CONDITIONS) {
      const r = resolve(c.metric, c.period);
      if (!r) warn.push(`'${c.metric}' needs one of these periods: ${Object.keys(F[c.metric].periods).join(", ")}`);
      resolved.push(r);
    }
    $("#condWarn").innerHTML = warn.map((w) => `<div class="notice warn-box">${esc(w)}</div>`).join("");
    const result = table.filter((row) => CONDITIONS.every((c, i) => {
      const r = resolved[i]; if (!r || !OPS[c.operator] || !isNum(c.value) || !(r.col in row)) return true;
      const val = r.f.percent ? c.value / 100 : c.value, x = row[r.col];
      return isNum(x) && OPS[c.operator](x, val);
    }));
    $("#scrCount").textContent = `${result.length} of ${table.length} stocks meet all conditions. Stocks without enough history for a condition don't pass it (most non-US stocks have 4 years until older data is added).`;
    const cols = new Map([["close", ["Price", F.Price]], ["trailing_pe", ["Trailing P/E", F["Trailing P/E"]]],
      ["calc_middle", ["Calculated value", { help: G.valuation_help, percent: false }]], ["price_to_calc", ["Price / calculated value", F["Price / calculated value"]]]]);
    for (const r of resolved) if (r) cols.set(r.col, [r.label, r.f]);
    const shown = [...cols.entries()].filter(([c]) => SCREENER.columns.includes(c));
    const head = ["Ticker", "Name", "Currency", ...shown.map(([, [l]]) => l)];
    const helps = Object.fromEntries(shown.map(([, [l, f]]) => [l, f.help]));
    const body = result.map((row) => [row.ticker, row.name, row.currency, ...shown.map(([c, [, f]]) => (isNum(row[c]) ? (f.percent ? nf(1).format(row[c] * 100) + "%" : nf(2).format(row[c])) : ""))]);
    $("#scrTable").innerHTML = dataTable(head, body, helps);
    $("#scrTable").querySelectorAll("tr").forEach((tr, i) => { if (i === 0) return; const t = body[i - 1][0]; tr.style.cursor = "pointer"; tr.title = `Open ${t}`; tr.onclick = () => { showPage("stock"); selectStock(t); }; });
  };
  $("#addCond").onclick = () => { CONDITIONS.push({ metric: "ROIC", period: "5y", operator: ">=", value: 10 }); draw(); apply(); };
  $("#resetCond").onclick = () => { CONDITIONS = G.screener.default_conditions.map((c) => ({ ...c })); draw(); apply(); };
  draw(); apply();
}

/* ---------------- navigation ---------------- */
function showPage(page) {
  SP.page = page;
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.page === page));
  $("#page-stock").hidden = page !== "stock"; $("#page-screener").hidden = page !== "screener";
  $("#settings").hidden = page !== "stock"; $("#menuBtn").style.visibility = page === "stock" ? "" : "hidden";
  if (page === "screener") {
    $("#title").textContent = "Screener";
    try { history.replaceState(null, "", "#screener"); } catch (e) { /* ignore */ }
    renderScreener();
  } else if (ST) { $("#title").textContent = `${ST.name} (${SP.ticker})`; try { history.replaceState(null, "", `#stock=${encodeURIComponent(SP.ticker)}`); } catch (e) { /* ignore */ } }
}
function openSettings(open) {
  $("#settings").classList.toggle("open", open);
  $("#backdrop").hidden = !open;
  $("#menuBtn").setAttribute("aria-expanded", open);
}

function fillStockSelect() {
  const f = normalize($("#stockFilter").value), sel = $("#stock");
  const opts = watchOptions().filter((o) => !f || normalize(o.label).includes(f) || o.value === SP.ticker);
  sel.innerHTML = opts.map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join("");
  sel.value = SP.ticker;
}

async function init() {
  [WATCH, G, CPI, SCREENER] = await Promise.all([loadJSON("data/watchlist.json"), loadJSON("data/glossary.json"),
    loadJSON("data/cpi.json").catch(() => ({})), loadJSON("data/screener.json")]);
  const hash = decodeURIComponent(location.hash.slice(1));
  const opts = watchOptions();
  let ticker = hash.startsWith("stock=") ? hash.slice(6) : opts[0].value;
  if (!opts.some((o) => o.value === ticker)) ticker = opts[0].value;
  SP.ticker = ticker;
  fillStockSelect();
  $("#stockFilter").oninput = () => {
    fillStockSelect();
    const sel = $("#stock");
    if (sel.options.length === 1 && sel.value !== SP.ticker) selectStock(sel.value);
  };
  $("#stock").onchange = (e) => selectStock(e.target.value);
  $("#cmpFilter").oninput = () => renderStockSidebar();
  $("#barValues").onchange = (e) => { SP.barValues = e.target.checked; renderStock(); };
  $("#showDcf").onchange = (e) => { SP.showDcf = e.target.checked; renderStock(); };
  $("#showCalc").onchange = (e) => { SP.showCalc = e.target.checked; renderStock(); };
  $("#degree").oninput = (e) => { SP.degree = +e.target.value; $("#degreeVal").textContent = SP.degree; };
  $("#degree").onchange = () => renderStock();
  $("#horizon").oninput = (e) => { SP.horizon = +e.target.value; $("#horizonVal").textContent = SP.horizon; };
  $("#horizon").onchange = () => renderStock();
  $("#discount").oninput = (e) => { SP.discount = +e.target.value; $("#discountVal").textContent = SP.discount.toFixed(1); };
  $("#discount").onchange = () => renderStock();
  $("#ownGrowth").onchange = (e) => { const v = parseFloat(e.target.value); SP.ownGrowth = Number.isFinite(v) ? Math.max(0, Math.min(30, v)) : null; renderStock(); };
  document.querySelectorAll(".tabs button").forEach((b) => { b.onclick = () => showPage(b.dataset.page); });
  $("#menuBtn").onclick = () => openSettings(true);
  $("#closeSettings").onclick = $("#backdrop").onclick = $("#applySettings").onclick = () => openSettings(false);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") openSettings(false); });
  $("#loading").hidden = true;
  showPage(hash === "screener" ? "screener" : "stock");
  await selectStock(ticker);
  if (hash === "screener") showPage("screener");
}
init().catch((e) => { console.error(e); $("#loading").textContent = "Could not load the data. Check your connection and reload the page."; });

if ("serviceWorker" in navigator) {
  // When a new version of the app is installed, reload once so it shows right away.
  const hadController = !!navigator.serviceWorker.controller;
  let reloaded = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (hadController && !reloaded) { reloaded = true; location.reload(); }
  });
  window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").then((r) => r.update()).catch(() => {}));
}
