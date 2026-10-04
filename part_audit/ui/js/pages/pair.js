// Two parts compared: side by side, deviation heat map (where exactly they differ) and an aligned overlay.
import { get, binary } from "../api.js";
import { esc, pct, datetime, pnChip, sysBadge, catPill, confBar, uidLink, DECISION } from "../util.js";
import { decisionBar } from "../ui.js";
import { compare3d } from "../compare3d.js";
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
        ${both ? '<div class="seg" id="mode"></div>' : ""}</div>
      <div class="panel-b stack" id="c3">
        ${both ? ""
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

  const near = p.category === "near_identical" || p.category === "mirror";
  return compare3d(el.querySelector("#c3"), {
    labelA: `<span class="small muted">א</span> ${pnChip(a.pn)} ${sysBadge(a.source_kind, "")}`,
    labelB: `<span class="small muted">ב</span> ${pnChip(b.pn)} ${sysBadge(b.source_kind, "")}`,
    overlayLabel: `<span class="pill neutral plain">אפור = א</span> <span class="pill brass plain">זהב שקוף = ב, מיושר על א</span>`,
    seg: el.querySelector("#mode"), initial: near ? "heat" : "side",
    load: {
      meshA: () => binary(`/api/mesh/latest/${encodeURIComponent(a.uid)}`),
      meshB: () => binary(`/api/mesh/latest/${encodeURIComponent(b.uid)}`),
      align: () => get("/api/align/latest", { a: a.uid, b: b.uid }),
      compare: () => binary("/api/compare/latest", { a: a.uid, b: b.uid }),
    },
  });
}
