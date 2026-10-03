// Two parts compared: side by side, deviation heat map (where exactly they differ) and an aligned overlay.
import { get, binary } from "../api.js";
import { esc, pct, mm, datetime, pnChip, sysBadge, catPill, confBar, uidLink, DECISION } from "../util.js";
import { decisionBar } from "../ui.js";
import { Viewer, parseMesh, parseCompare, linkViewers } from "../viewer3d.js";
import { attrTable } from "../compare.js";

const LABELS = {
  near_identical: { approve: "לתקנן לחלק אחד", reject: "חלקים שונים – להשאיר", review: "לבדיקה" },
  identical_attr_conflict: { approve: "טעות רישום – לתקן", reject: "חלקים שונים באמת", review: "לבדיקה" },
  mirror: { approve: "תקין – ימין ושמאל", reject: "יש טעות בסימון", review: "לבדיקה" },
  conflict: { approve: "לתקן את המק\"ט", reject: "תקין", review: "לבדיקה" },
  conflict_unverified: { approve: "לתקן את המק\"ט", reject: "תקין", review: "לבדיקה" },
};

export async function render({ el, param, setTitle, refreshStatus }) {
  const p = await get(`/api/runs/latest/pairs/${encodeURIComponent(param)}`);
  const a = p.part_a, b = p.part_b;
  const back = ["near_identical", "identical_attr_conflict", "mirror"].includes(p.category) ? `<a href="#/near/${p.category}">כמעט זהים</a>`
    : a.group_id ? `<a href="#/group/${a.group_id}">קבוצת הכפילות</a>` : `<a href="#/names">שמות ומק"טים</a>`;
  setTitle(`${a.pn || a.name} ↔ ${b.pn || b.name}`, `${back} / השוואת זוג`);
  const m = p.metrics || {};
  const both = a.has_step && b.has_step;

  el.innerHTML = `
    <section class="panel"><div class="panel-b stack" style="gap:10px">
      <div class="row">${catPill(p.category)}${p.cross_source ? '<span class="pill info">חוצה מערכות</span>' : ""}
        <span class="small muted">ציון ביטחון ${confBar(p.confidence)}</span><span style="flex:1"></span><span id="dec-pill"></span></div>
      <p><b>מה נמצא:</b> ${esc(p.reason_he)}</p>
      ${p.hint_he ? `<p class="muted">${esc(p.hint_he)}</p>` : ""}
      ${p.spec_note ? `<p><b>מפרט:</b> ${esc(p.spec_note)}</p>` : ""}
      <div class="row small muted">
        ${m.d_volume != null ? `<span>הפרש נפח <b class="num">${pct(m.d_volume, 3)}</b></span>` : ""}
        ${m.d_area != null ? `<span>· הפרש שטח פנים <b class="num">${pct(m.d_area, 3)}</b></span>` : ""}
        ${m.scale && Math.abs(m.scale - 1) > 1e-6 ? `<span>· יחס גודל <b class="num">${m.scale.toPrecision(4)}</b> ${esc(m.unit_note || "")}</span>` : ""}
      </div>
    </div></section>

    <section class="panel"><div class="panel-h"><h2>השוואה בתלת-ממד</h2><span class="spacer"></span>
        <div class="seg" id="mode"><button data-v="side" class="on">זה לצד זה</button><button data-v="heat">מפת סטיות</button><button data-v="overlay">חפיפה</button></div></div>
      <div class="panel-b stack">
        ${both ? `<div class="viewers" id="two"><div id="va"></div><div id="vb"></div></div>
          <div id="one" hidden><div id="vo" style="aspect-ratio:16/9"></div></div>
          <div id="stats" class="small"></div>`
          : `<div class="empty">${!a.has_step && !b.has_step ? "לשני החלקים" : !a.has_step ? "לחלק א" : "לחלק ב"} אין קובץ STEP – אין השוואה תלת-ממדית.</div>`}
      </div></section>

    <section class="panel"><div class="panel-h"><h2>החלטה</h2></div><div class="panel-b stack"><div id="decision"></div><div id="history"></div></div></section>

    <section class="panel"><div class="panel-h"><h2>השוואת נתונים</h2></div>
      <div class="panel-b">${attrTable([a, b], (x, i) => `<span class="small muted">${i ? "חלק ב" : "חלק א"}</span> ${pnChip(x.pn)}<div style="margin-top:4px">${sysBadge(x.source_kind, "")} ${uidLink(x.uid, "לכרטיס החלק")}</div>`)}</div></section>`;

  const paint = (d) => {
    const [he, tone] = DECISION[d.decision || ""] || DECISION[""];
    el.querySelector("#dec-pill").innerHTML = `<span class="pill ${tone}">${he}</span>`;
    decisionBar(el.querySelector("#decision"), { type: "pair", id: p.id, current: d.decision, note: d.decision_note, by: d.decision_by,
      at: d.decision_at, labels: LABELS[p.category] || {},
      onSaved: async () => { paint(await get(`/api/runs/latest/pairs/${encodeURIComponent(p.id)}`)); refreshStatus(); } });
    el.querySelector("#history").innerHTML = d.history?.length ? `<details><summary class="small">היסטוריית החלטות (${d.history.length})</summary>
      <ul class="small">${d.history.map((h) => `<li>${datetime(h.created)} · ${esc(h.user)} · ${(DECISION[h.decision] || [h.decision])[0]}${h.note ? ` – ${esc(h.note)}` : ""}</li>`).join("")}</ul></details>` : "";
  };
  paint(p);
  if (!both) return null;

  const va = new Viewer(el.querySelector("#va"), { label: `<span class="small muted">א</span> ${pnChip(a.pn)} ${sysBadge(a.source_kind, "")}` });
  const vb = new Viewer(el.querySelector("#vb"), { label: `<span class="small muted">ב</span> ${pnChip(b.pn)} ${sysBadge(b.source_kind, "")}` });
  linkViewers([va, vb]);
  let vo = null;
  const [ma, mb] = await Promise.all([
    binary(`/api/mesh/latest/${encodeURIComponent(a.uid)}`).then(parseMesh).catch((e) => { va.msg.textContent = e.message; return null; }),
    binary(`/api/mesh/latest/${encodeURIComponent(b.uid)}`).then(parseMesh).catch((e) => { vb.msg.textContent = e.message; return null; }),
  ]);
  if (ma) va.setMesh(ma);
  if (mb) vb.setMesh(mb);
  if (ma && mb) get("/api/align/latest", { a: a.uid, b: b.uid }).then((al) => vb.orient(al.matrix)).catch(() => {});
  let cmp = null;
  const loadCompare = async () => {
    if (cmp) return cmp;
    el.querySelector("#stats").innerHTML = '<span class="muted">מיישר את החלקים ומחשב מרחקים…</span>';
    cmp = parseCompare(await binary("/api/compare/latest", { a: a.uid, b: b.uid }));
    return cmp;
  };
  const diag = (mesh) => Math.hypot(mesh.bbox[3] - mesh.bbox[0], mesh.bbox[4] - mesh.bbox[1], mesh.bbox[5] - mesh.bbox[2]);
  const setMode = async (mode) => {
    el.querySelector("#two").hidden = mode === "overlay";
    el.querySelector("#one").hidden = mode !== "overlay";
    const stats = el.querySelector("#stats");
    if (mode === "side") {
      if (ma) { va.setSurface(ma.pos, ma.idx); va.plain(); }
      if (mb) { vb.setSurface(mb.pos, mb.idx); vb.plain(); }
      stats.innerHTML = ""; return;
    }
    if (!ma || !mb) return;
    let c;
    try { c = await loadCompare(); } catch (e) { stats.innerHTML = `<div class="callout warn">${esc(e.message)}</div>`; return; }
    // small distances are the faceting of the display mesh, not a real difference: below max(3 x median distance,
    // 0.05% of the part size, 0.01 mm) the surface is shown as matching
    const floor = Math.max(3 * c.median, 0.0005 * Math.max(diag(ma), diag(mb)), 0.01);
    const scale = Math.max(c.max, floor * 4);
    if (mode === "heat") {
      const adj = (dev) => Float32Array.from(dev, (x) => Math.max(0, x - floor));
      va.setSurface(c.A.pos, c.A.idx); va.heatmap(adj(c.A.dev), scale - floor);
      vb.setSurface(c.B.pos, c.B.idx); vb.heatmap(adj(c.B.dev), scale - floor);
    } else {
      if (!vo) { vo = new Viewer(el.querySelector("#vo"), { label: `<span class="pill neutral plain">אפור = א</span> <span class="pill brass plain">זהב שקוף = ב, מיושר על א</span>` }); vo.setMesh(ma); vo.addOverlay(mb, c.matrix); }
      else vo.resize();
    }
    const same = c.max <= floor * 1.5;
    stats.innerHTML = `<div class="row" style="gap:18px">
      ${mode === "heat" ? `<div class="legend"><span>0</span><span class="bar"></span><span class="ltr">${mm(scale)}</span></div>` : ""}
      <span>סטייה מקסימלית <b class="num">${mm(c.max)}</b></span><span>95% מהשטח בתוך <b class="num">${mm(c.p95)}</b></span>
      <span>חציון <b class="num">${mm(c.median)}</b></span>${c.mirror ? '<span class="pill info">יושר כתמונת ראי</span>' : ""}</div>
      <p class="muted" style="margin-top:6px">${same ? "לא נמצא הבדל מעבר לדיוק התצוגה – הצורות זהות." : "האזורים האדומים הם המקומות שבהם החלקים שונים."}
        הבדלים קטנים מ-${mm(floor)} לא נצבעים, כי זה דיוק רשת התצוגה. המנוע עצמו משווה את המודל המדויק.</p>`;
  };
  const seg = el.querySelector("#mode");
  seg.querySelectorAll("button").forEach((btn) => (btn.onclick = () => {
    seg.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === btn));
    setMode(btn.dataset.v);
  }));
  if (p.category === "near_identical" || p.category === "mirror") seg.querySelector('[data-v="heat"]').click();
  return () => { va.dispose(); vb.dispose(); if (vo) vo.dispose(); };
}
