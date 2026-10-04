// Two models compared in 3D: side by side, deviation heat map (where exactly they differ) and an aligned overlay.
// Used by the pair page and by the pre-release check (a new file against an existing part).
import { esc, mm } from "./util.js";
import { Viewer, parseMesh, parseCompare, linkViewers } from "./viewer3d.js";

/** el: where the viewers go; seg: where the mode buttons go (default: a bar above the viewers).
 *  load = { meshA(), meshB(), align(), compare() } return promises (ArrayBuffer / {matrix}); labels are HTML. */
export function compare3d(el, { labelA, labelB, overlayLabel, load, seg = null, initial = "side" }) {
  el.innerHTML = `${seg ? "" : '<div class="row c3-bar"><div class="seg c3-seg"></div></div>'}
    <div class="viewers c3-two"><div class="c3-a"></div><div class="c3-b"></div></div>
    <div class="c3-one" hidden><div class="c3-o" style="aspect-ratio:16/9"></div></div>
    <div class="small c3-stats"></div>`;
  const segEl = seg || el.querySelector(".c3-seg");
  segEl.innerHTML = '<button data-v="side" class="on">זה לצד זה</button><button data-v="heat">מפת סטיות</button><button data-v="overlay">חפיפה</button>';
  const va = new Viewer(el.querySelector(".c3-a"), { label: labelA });
  const vb = new Viewer(el.querySelector(".c3-b"), { label: labelB });
  linkViewers([va, vb]);
  const stats = el.querySelector(".c3-stats");
  let vo = null, ma = null, mb = null, cmp = null, alive = true;
  const ready = Promise.all([
    load.meshA().then(parseMesh).catch((e) => { va.msg.textContent = e.message; return null; }),
    load.meshB().then(parseMesh).catch((e) => { vb.msg.textContent = e.message; return null; }),
  ]).then(([a, b]) => {
    ma = a; mb = b;
    if (!alive) return;
    if (ma) va.setMesh(ma);
    if (mb) vb.setMesh(mb);
    if (ma && mb) load.align().then((al) => alive && vb.orient(al.matrix)).catch(() => {});
  });
  const loadCompare = async () => {
    if (cmp) return cmp;
    stats.innerHTML = '<span class="muted">מיישר את החלקים ומחשב מרחקים…</span>';
    cmp = parseCompare(await load.compare());
    return cmp;
  };
  const diag = (m) => Math.hypot(m.bbox[3] - m.bbox[0], m.bbox[4] - m.bbox[1], m.bbox[5] - m.bbox[2]);
  const setMode = async (mode) => {
    await ready;
    if (!alive) return;
    el.querySelector(".c3-two").hidden = mode === "overlay";
    el.querySelector(".c3-one").hidden = mode !== "overlay";
    if (mode === "side") {
      if (ma) { va.setSurface(ma.pos, ma.idx); va.plain(); }
      if (mb) { vb.setSurface(mb.pos, mb.idx); vb.plain(); }
      stats.innerHTML = ""; return;
    }
    if (!ma || !mb) return;
    let c;
    try { c = await loadCompare(); } catch (e) { stats.innerHTML = `<div class="callout warn">${esc(e.message)}</div>`; return; }
    if (!alive) return;
    // small distances are the faceting of the display mesh, not a real difference: below max(3 x median distance,
    // 0.05% of the part size, 0.01 mm) the surface is shown as matching
    const floor = Math.max(3 * c.median, 0.0005 * Math.max(diag(ma), diag(mb)), 0.01);
    const scale = Math.max(c.max, floor * 4);
    if (mode === "heat") {
      const adj = (dev) => Float32Array.from(dev, (x) => Math.max(0, x - floor));
      va.setSurface(c.A.pos, c.A.idx); va.heatmap(adj(c.A.dev), scale - floor);
      vb.setSurface(c.B.pos, c.B.idx); vb.heatmap(adj(c.B.dev), scale - floor);
    } else if (!vo) {
      vo = new Viewer(el.querySelector(".c3-o"), { label: overlayLabel });
      vo.setMesh(ma); vo.addOverlay(mb, c.matrix);
    } else vo.resize();
    const same = c.max <= floor * 1.5;
    stats.innerHTML = `<div class="row" style="gap:18px">
      ${mode === "heat" ? `<div class="legend"><span>0</span><span class="bar"></span><span class="ltr">${mm(scale)}</span></div>` : ""}
      <span>סטייה מקסימלית <b class="num">${mm(c.max)}</b></span><span>95% מהשטח בתוך <b class="num">${mm(c.p95)}</b></span>
      <span>חציון <b class="num">${mm(c.median)}</b></span>${c.mirror ? '<span class="pill info">יושר כתמונת ראי</span>' : ""}</div>
      <p class="muted" style="margin-top:6px">${same ? "לא נמצא הבדל מעבר לדיוק התצוגה – הצורות זהות." : "האזורים האדומים הם המקומות שבהם החלקים שונים."}
        הבדלים קטנים מ-${mm(floor)} לא נצבעים, כי זה דיוק רשת התצוגה. המנוע עצמו משווה את המודל המדויק.</p>`;
  };
  segEl.querySelectorAll("button").forEach((btn) => (btn.onclick = () => {
    segEl.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === btn));
    setMode(btn.dataset.v);
  }));
  if (initial !== "side") segEl.querySelector(`[data-v="${initial}"]`)?.click();
  return () => { alive = false; va.dispose(); vb.dispose(); if (vo) vo.dispose(); };
}
