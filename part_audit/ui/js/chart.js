// Small SVG charts drawn in the app's own tokens (no chart library): a one-series line over time with a crosshair,
// and diverging bars (what was created above the baseline, what was resolved below it). Time runs left to right.
const NS = "http://www.w3.org/2000/svg";
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function el(tag, attrs = {}, parent = null) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}

// clean tick values that cover [lo, hi]; whole steps only when the data is whole numbers (counts)
export function ticks(lo, hi, count = 4, whole = false) {
  if (lo === hi) { lo -= 1; hi += 1; }
  const raw = (hi - lo) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const steps = (whole && mag < 10 ? [1, 2, 5, 10] : [1, 2, 2.5, 5, 10]).map((m) => m * mag);
  let step = steps.find((s) => s >= raw) || 10 * mag;
  if (whole) step = Math.max(1, step);
  const start = Math.floor(lo / step + 1e-9) * step, end = Math.ceil(hi / step - 1e-9) * step;
  const out = [];
  for (let v = start; v <= end + step * 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

const dateShort = (d) => d.toLocaleDateString("he-IL", { day: "2-digit", month: "2-digit" });

// rendered width of a label (falls back to an estimate while the chart is not laid out)
function textWidth(svg, s, size = 11, weight = 400) {
  const t = el("text", { x: -9999, y: -9999, "font-size": size, "font-weight": weight }, svg);
  t.textContent = s;
  const w = t.getComputedTextLength ? t.getComputedTextLength() : 0;
  t.remove();
  return w || String(s).length * size * 0.62;
}

function frame(box, height) {
  box.classList.add("chart");
  box.innerHTML = "";
  box.setAttribute("dir", "ltr");
  const w = Math.max(260, box.clientWidth || 320);
  const svg = el("svg", { width: w, height, viewBox: `0 0 ${w} ${height}`, role: "img" }, box);
  const tip = document.createElement("div");
  tip.className = "chart-tip";
  tip.hidden = true;
  box.appendChild(tip);
  return { svg, tip, w };
}

function showTip(tip, box, x, y, rows) {
  tip.replaceChildren(...rows.map(([strong, rest, key]) => {
    const line = document.createElement("div");
    if (key) { const k = document.createElement("i"); k.style.background = key; line.appendChild(k); }
    const b = document.createElement("b");
    b.textContent = strong;
    line.appendChild(b);
    if (rest) line.appendChild(document.createTextNode(` ${rest}`));
    return line;
  }));
  tip.hidden = false;
  const bw = box.clientWidth;
  tip.style.left = `${Math.min(Math.max(4, x + 12), bw - tip.offsetWidth - 4)}px`;
  tip.style.top = `${Math.max(0, y - tip.offsetHeight - 10)}px`;
}

/** One series over time. points: [{t: Date, v: number}] (oldest first); fmt: number -> text. */
export function lineChart(box, { points, fmt = String, label = "", height = 168 }) {
  const draw = () => {
    const { svg, tip, w } = frame(box, height);
    svg.setAttribute("aria-label", label);
    if (!points.length) return;
    const vals = points.map((p) => p.v);
    const ys = ticks(Math.min(...vals), Math.max(...vals), 4, vals.every(Number.isInteger));
    const y0 = ys[0], y1 = ys[ys.length - 1];
    const last = points.at(-1);
    // the value axis on the left, the latest value labelled to the right of the line's end
    const P = { l: Math.ceil(Math.max(...ys.map((v) => textWidth(svg, fmt(v))))) + 14, r: Math.ceil(textWidth(svg, fmt(last.v), 12, 600)) + 16, t: 12, b: 26 };
    const t0 = +points[0].t, t1 = +last.t;
    const X = (t) => (t1 === t0 ? (P.l + w - P.r) / 2 : P.l + ((+t - t0) / (t1 - t0)) * (w - P.l - P.r));
    const Y = (v) => P.t + (1 - (v - y0) / (y1 - y0 || 1)) * (height - P.t - P.b);
    const ink = css("--muted"), line = css("--line"), dye = css("--chart-a") || css("--dye"), surf = css("--surface");
    for (const v of ys) {
      el("line", { x1: P.l, x2: w - P.r, y1: Y(v), y2: Y(v), stroke: line, "stroke-width": 1 }, svg);
      const t = el("text", { x: P.l - 8, y: Y(v) + 4, "text-anchor": "end", fill: ink, "font-size": 11 }, svg);
      t.textContent = fmt(v);
    }
    const lab = [0, points.length - 1];
    if (points.length > 4) lab.splice(1, 0, Math.floor((points.length - 1) / 2));
    for (const i of new Set(lab)) {
      const t = el("text", { x: X(points[i].t), y: height - 8, "text-anchor": i === 0 ? "start" : i === points.length - 1 ? "end" : "middle", fill: ink, "font-size": 11 }, svg);
      t.textContent = dateShort(points[i].t);
    }
    const path = points.map((p, i) => `${i ? "L" : "M"}${X(p.t).toFixed(1)},${Y(p.v).toFixed(1)}`).join("");
    // a wash under the line only when the axis starts at zero; on a zoomed axis it would exaggerate the change
    if (y0 === 0) el("path", { d: `${path}L${X(last.t)},${Y(y0)}L${X(points[0].t)},${Y(y0)}Z`, fill: dye, "fill-opacity": 0.1 }, svg);
    el("path", { d: path, fill: "none", stroke: dye, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
    // each scan is a point; with many scans only the latest is marked
    for (const p of points.length <= 16 ? points : [last]) {
      el("circle", { cx: X(p.t), cy: Y(p.v), r: p === last ? 4 : 3, fill: dye, stroke: surf, "stroke-width": 2 }, svg);
    }
    const end = el("text", { x: X(last.t) + 9, y: Y(last.v) + 4, "text-anchor": "start", fill: css("--ink"), "font-size": 12, "font-weight": 600 }, svg);
    end.textContent = fmt(last.v);
    // crosshair: snaps to the nearest scan; the arrow keys move it too
    const cross = el("line", { y1: P.t, y2: height - P.b, stroke: css("--line-strong"), "stroke-width": 1, visibility: "hidden" }, svg);
    const dot = el("circle", { r: 5, fill: dye, stroke: surf, "stroke-width": 2, visibility: "hidden" }, svg);
    const hit = el("rect", { x: 0, y: 0, width: w, height, fill: "transparent" }, svg);
    let at = -1;
    const pick = (i) => {
      at = Math.max(0, Math.min(points.length - 1, i));
      const p = points[at], x = X(p.t), y = Y(p.v);
      cross.setAttribute("x1", x); cross.setAttribute("x2", x); cross.setAttribute("visibility", "visible");
      dot.setAttribute("cx", x); dot.setAttribute("cy", y); dot.setAttribute("visibility", "visible");
      const prev = at ? points[at - 1].v : null;
      const d = prev == null ? "" : p.v - prev;
      showTip(tip, box, x, y, [[fmt(p.v), label], [p.t.toLocaleString("he-IL", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }),
        d === "" ? "הסריקה הראשונה" : d ? `${d > 0 ? "+" : "−"}${fmt(Math.abs(d))} מהסריקה הקודמת` : "ללא שינוי מהסריקה הקודמת"]]);
    };
    const hide = () => { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); tip.hidden = true; };
    hit.addEventListener("pointermove", (e) => {
      const r = svg.getBoundingClientRect(), x = e.clientX - r.left;
      let best = 0;
      points.forEach((p, i) => { if (Math.abs(X(p.t) - x) < Math.abs(X(points[best].t) - x)) best = i; });
      pick(best);
    });
    hit.addEventListener("pointerleave", hide);
    svg.setAttribute("tabindex", "0");
    svg.addEventListener("focus", () => pick(points.length - 1));
    svg.addEventListener("blur", hide);
    svg.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); pick(at + (e.key === "ArrowRight" ? 1 : -1)); }
    });
  };
  draw();
  return observe(box, draw);
}

/** Per scan: what was created (above the baseline) and what was resolved (below). rows: [{t, up, down, detail}] */
export function divergingBars(box, { rows, upLabel, downLabel, height = 200 }) {
  const draw = () => {
    const { svg, tip, w } = frame(box, height);
    svg.setAttribute("aria-label", `${upLabel} ו${downLabel} בכל סריקה`);
    if (!rows.length) return;
    const max = Math.max(1, ...rows.map((r) => Math.max(r.up, r.down)));
    const ys = ticks(0, max, 2, true).filter((v) => v > 0);
    // room above and below for the value labels, and under them for the dates
    const P = { l: Math.ceil(Math.max(...ys.map((v) => textWidth(svg, String(v))))) + 16, r: 14, t: 22, b: 42 };
    const mid = P.t + (height - P.t - P.b) / 2, half = (height - P.t - P.b) / 2;
    const Y = (v) => mid - (v / ys.at(-1)) * half;
    const ink = css("--muted"), line = css("--line"), up = css("--chart-b"), down = css("--chart-a");
    for (const v of ys) {
      for (const s of [1, -1]) {
        el("line", { x1: P.l, x2: w - P.r, y1: Y(s * v), y2: Y(s * v), stroke: line, "stroke-width": 1 }, svg);
        const t = el("text", { x: P.l - 8, y: Y(s * v) + 4, "text-anchor": "end", fill: ink, "font-size": 11 }, svg);
        t.textContent = String(v);
      }
    }
    el("line", { x1: P.l, x2: w - P.r, y1: mid, y2: mid, stroke: css("--line-strong"), "stroke-width": 1 }, svg);
    const slot = (w - P.l - P.r) / rows.length, bw = Math.min(24, slot * 0.55);
    const every = Math.ceil(rows.length / 8);           // date labels: the latest always, then evenly back in time
    rows.forEach((r, i) => {
      const cx = P.l + slot * (i + 0.5);
      const g = el("g", { tabindex: 0, class: "bar" }, svg);
      if (r.up) el("path", { d: bar(cx, mid - 1, bw, Y(r.up) - (mid - 1)), fill: up }, g);
      if (r.down) el("path", { d: bar(cx, mid + 1, bw, Y(-r.down) - (mid + 1)), fill: down }, g);
      for (const [v, y] of [[r.up, Y(r.up) - 5], [r.down, Y(-r.down) + 14]]) {
        if (!v) continue;
        const t = el("text", { x: cx, y, "text-anchor": "middle", fill: css("--ink-2"), "font-size": 11 }, g);
        t.textContent = String(v);
      }
      if ((rows.length - 1 - i) % every === 0) {
        const t = el("text", { x: cx, y: height - 8, "text-anchor": "middle", fill: ink, "font-size": 11 }, svg);
        t.textContent = dateShort(r.t);
      }
      el("rect", { x: cx - slot / 2, y: 0, width: slot, height, fill: "transparent" }, g);
      const show = () => showTip(tip, box, cx, Math.min(Y(r.up), mid), [[String(r.up), upLabel, up], [String(r.down), downLabel, down],
        [r.t.toLocaleDateString("he-IL", { day: "2-digit", month: "2-digit", year: "numeric" }), r.detail || ""]]);
      g.addEventListener("pointerenter", show);
      g.addEventListener("focus", show);
      g.addEventListener("pointerleave", () => (tip.hidden = true));
      g.addEventListener("blur", () => (tip.hidden = true));
    });
  };
  draw();
  return observe(box, draw);
}

// a bar from the baseline y0 with height h (negative = upward); 4px rounded at the data end, square at the baseline
function bar(cx, y0, w, h) {
  const x = cx - w / 2, r = Math.min(4, Math.abs(h) / 2, w / 2), s = Math.sign(h) || 1, y1 = y0 + h;
  return `M${x},${y0}L${x},${y1 - s * r}Q${x},${y1} ${x + r},${y1}L${x + w - r},${y1}Q${x + w},${y1} ${x + w},${y1 - s * r}L${x + w},${y0}Z`;
}

function observe(box, draw) {
  let last = box.clientWidth;
  const ro = new ResizeObserver(() => { if (Math.abs(box.clientWidth - last) > 4) { last = box.clientWidth; draw(); } });
  ro.observe(box);
  const onTheme = () => draw();
  window.addEventListener("pa-theme", onTheme);
  return () => { ro.disconnect(); window.removeEventListener("pa-theme", onTheme); };
}
