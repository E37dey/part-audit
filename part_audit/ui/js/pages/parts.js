// Search across every record that was read from every source.
import { get } from "../api.js";
import { esc, n0, kg, pnChip, rev, sysBadge, statePill, debounce } from "../util.js";

const LIMIT = 100;

export async function render({ el, setTitle, param }) {
  setTitle("חיפוש חלקים", "כל הרשומות מכל המערכות במקום אחד");
  const summary = await get("/api/runs/latest/summary");
  const f = { q: param || "", source: "", kind: "", flag: "", offset: 0 };
  el.innerHTML = `<div class="panel">
    <div class="panel-h toolbar">
      <input type="search" id="q" placeholder='מק"ט, שם, תיאור או שם קובץ' value="${esc(f.q)}" aria-label="חיפוש" style="width:min(380px,100%)">
      <select id="src" aria-label="מערכת"><option value="">כל המערכות</option>${summary.sources.filter((s) => s.role !== "erp")
        .map((s) => `<option value="${esc(s.name)}">${esc(s.name)}</option>`).join("")}</select>
      <select id="kind" aria-label="סוג"><option value="">חלקים ומכלולים</option><option value="part">רק חלקים</option><option value="assembly">רק מכלולים</option></select>
      <div class="seg" id="flag"><button data-v="" class="on">הכול</button><button data-v="group">בקבוצת כפילות</button>
        <button data-v="near">כמעט זהים</button><button data-v="issues">עם ממצאים</button><button data-v="nostep">בלי STEP</button></div>
    </div>
    <div class="table-wrap"><table class="t"><thead><tr><th>מק"ט</th><th>שם</th><th>מערכת</th><th>מצב</th><th>חומר</th><th class="n">משקל</th>
      <th class="n">מלאי ERP</th><th class="n">שימושים</th><th>סימונים</th></tr></thead><tbody id="tb"></tbody></table></div>
    <div class="panel-b small muted row" id="foot"></div></div>`;
  const tb = el.querySelector("#tb");
  let total = 0, rows = [];
  const load = async (append = false) => {
    const r = await get("/api/runs/latest/parts", { q: f.q, source: f.source, kind: f.kind, flag: f.flag, limit: LIMIT, offset: f.offset });
    total = r.total;
    rows = append ? rows.concat(r.rows) : r.rows;
    tb.innerHTML = rows.map((p) => `<tr class="click" data-uid="${esc(p.uid)}">
      <td class="nowrap">${pnChip(p.pn)} ${rev(p.revision)}</td>
      <td>${esc(p.name)}${p.kind === "assembly" ? ' <span class="pill neutral plain">מכלול</span>' : ""}${p.spec ? `<div class="small muted mono">${esc(p.spec)}</div>` : ""}</td>
      <td>${sysBadge(p.source_kind, p.source)}</td><td>${statePill(p.state_class, p.state)}</td><td class="small">${esc(p.material || "")}</td>
      <td class="n">${kg(p.mass_kg)}</td><td class="n">${p.erp ? n0(p.erp.stock) : '<span class="muted">—</span>'}</td><td class="n">${n0(p.used_in)}</td>
      <td>${p.group_id ? '<span class="pill dye plain">כפילות</span> ' : ""}${p.near_count ? '<span class="pill brass plain">כמעט זהה</span> ' : ""}
        ${p.issues ? `<span class="pill warn plain">${n0(p.issues)} ממצאים</span> ` : ""}${p.kind === "part" && !p.has_step ? '<span class="pill neutral plain">בלי STEP</span>' : ""}</td></tr>`).join("")
      || '<tr><td colspan="9"><div class="empty">לא נמצאו חלקים</div></td></tr>';
    el.querySelector("#foot").innerHTML = `מוצגים ${n0(rows.length)} מתוך ${n0(total)} ${rows.length < total ? '<button class="btn small" id="more">הצג עוד</button>' : ""}`;
    const more = el.querySelector("#more");
    if (more) more.onclick = () => { f.offset = rows.length; load(true); };
  };
  const reload = () => { f.offset = 0; load(); };
  el.querySelector("#q").oninput = debounce((e) => { f.q = e.target.value; reload(); }, 250);
  el.querySelector("#src").onchange = (e) => { f.source = e.target.value; reload(); };
  el.querySelector("#kind").onchange = (e) => { f.kind = e.target.value; reload(); };
  const seg = el.querySelector("#flag");
  seg.querySelectorAll("button").forEach((b) => (b.onclick = () => { seg.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b)); f.flag = b.dataset.v; reload(); }));
  tb.onclick = (e) => { const tr = e.target.closest("tr[data-uid]"); if (tr) location.hash = `#/part/${encodeURIComponent(tr.dataset.uid)}`; };
  await load();
  el.querySelector("#q").focus();
}
