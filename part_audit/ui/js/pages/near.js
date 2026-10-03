// Pairs that need an engineer's eye: nearly identical shapes, same shape with a different spec, left/right versions.
import { get } from "../api.js";
import { esc, n0, pct, pnChip, sysBadge, decisionPill, confBar, debounce } from "../util.js";
import { tabs } from "../ui.js";

const KINDS = [
  { key: "near_identical", label: "כמעט זהים", text: "שני חלקים עם הבדל גיאומטרי קטן (חור, אורך, רדיוס). אולי אפשר לתקנן לחלק אחד – כדאי לבדוק במפת הסטיות איפה בדיוק הם שונים." },
  { key: "identical_attr_conflict", label: "אותה צורה – מפרט שונה", text: "הגיאומטריה זהה אבל החומר, הדרגה או מידה תקנית שונים. בדרך כלל אלה חלקים שונים באמת (למשל בורג 8.8 מול 12.9), ולפעמים זו טעות רישום." },
  { key: "mirror", label: "ימין / שמאל", text: "חלקים שהם תמונת ראי זה של זה. הם לא כפילות, אבל כדאי לוודא שהשמות והמק\"טים מסמנים נכון ימין ושמאל." },
];

export async function render({ el, setTitle, param }) {
  setTitle("כמעט זהים", "זוגות שצריכים החלטה הנדסית – לא מאוחדים אוטומטית");
  const rows = await get("/api/runs/latest/pairs", { category: KINDS.map((k) => k.key).join(",") });
  let active = KINDS.find((k) => k.key === param) ? param : KINDS[0].key;
  let q = "";
  el.innerHTML = `<div class="panel"><div class="tabs" id="tabs" style="padding:0 12px"></div>
    <div class="panel-b stack"><p class="small muted" id="explain"></p>
      <div class="toolbar"><input type="search" id="q" placeholder='חיפוש לפי מק"ט או שם' aria-label="חיפוש"></div></div>
    <div class="table-wrap"><table class="t"><thead><tr><th>חלק א</th><th>חלק ב</th><th>מה שונה</th><th class="n">הפרש נפח</th>
      <th class="n">ביטחון</th><th>החלטה</th><th></th></tr></thead><tbody id="tb"></tbody></table></div></div>`;
  const draw = () => {
    const k = KINDS.find((x) => x.key === active);
    el.querySelector("#explain").textContent = k.text;
    const ql = q.trim().toLowerCase();
    const r = rows.filter((p) => p.category === active && (!ql || [p.a_pn, p.b_pn, p.a_name, p.b_name].some((x) => (x || "").toLowerCase().includes(ql))));
    el.querySelector("#tb").innerHTML = r.map((p) => `<tr class="click" data-id="${p.id}">
      <td>${pnChip(p.a_pn)} <div class="small">${esc(p.a_name)}</div><div class="small muted">${esc(p.a_source)}</div></td>
      <td>${pnChip(p.b_pn)} <div class="small">${esc(p.b_name)}</div><div class="small muted">${esc(p.b_source)}</div></td>
      <td class="small" style="max-width:420px">${esc(p.reason_he)}${p.spec_note ? `<div class="muted">${esc(p.spec_note)}</div>` : ""}</td>
      <td class="n">${p.metrics?.d_volume != null ? pct(p.metrics.d_volume, 2) : "—"}</td><td class="n">${confBar(p.confidence)}</td>
      <td>${decisionPill(p.decision)}</td><td>${p.has_step ? '<span class="small nowrap">מפת סטיות ←</span>' : ""}</td></tr>`).join("")
      || '<tr><td colspan="7"><div class="empty">אין זוגות בקטגוריה הזו</div></td></tr>';
  };
  const tabEl = el.querySelector("#tabs");
  tabs(tabEl, KINDS.map((k) => ({ key: k.key, label: k.label, count: rows.filter((p) => p.category === k.key).length })), (k) => {
    active = k; history.replaceState(null, "", `#/near/${k}`); draw();
  }, active);
  el.querySelector("#q").oninput = debounce((e) => { q = e.target.value; draw(); }, 150);
  el.querySelector("#tb").onclick = (e) => { const tr = e.target.closest("tr[data-id]"); if (tr) location.hash = `#/pair/${tr.dataset.id}`; };
  draw();
}
