// Findings lists: names & part numbers, data quality, ERP vs PDM. Each row can be marked for fixing or dismissed.
import { get, send, can } from "../api.js";
import { esc, n0, sevPill, uidLink, pnChip, debounce } from "../util.js";
import { tabs, toast } from "../ui.js";

const KIND = {
  names: { api: "names", title: "שמות ומק\"טים", sub: "אותו מק\"ט עם שמות שונים, שמות דומים תחת מק\"טים שונים, מק\"טים בפורמט חריג", sev: false },
  quality: { api: "quality", title: "איכות נתונים", sub: "משקל, חומר, יחידות, קבצים ומצבי שחרור", sev: true },
  erp: { api: "erp_issues", title: "ERP מול PDM", sub: "פערים בין הרשומה ההנדסית לפריט ב-ERP", sev: true },
};
const GEO = { identical: "זהה", near: "כמעט זהה", different: "שונה", unknown: "לא נבדקה (אין STEP)", unit_scaled: "זהה, ביחידות אחרות", mirror: "תמונת ראי" };
const ACTIONS = [["", "ממתין"], ["approve", "לתקן"], ["reject", "לא בעיה"], ["review", "לבדיקה"], ["ignore", "להתעלם"]];
const PAGE = 200;

export async function render({ el, page, param, setTitle }) {
  const k = KIND[page];
  setTitle(k.title, k.sub);
  const rows = await get(`/api/runs/latest/findings/${k.api}`);
  const types = [...new Map(rows.map((r) => [r.type, r.type_he])).entries()].map(([key, label]) => ({ key, label, count: rows.filter((r) => r.type === key).length }))
    .sort((x, y) => y.count - x.count);
  const f = { type: types.some((t) => t.key === param) ? param : "", sev: k.sev ? "noinfo" : "", q: "", shown: PAGE };

  el.innerHTML = `<div class="panel">
    <div class="tabs" id="tabs" style="padding:0 12px"></div>
    <div class="panel-h toolbar">
      <input type="search" id="q" placeholder='חיפוש לפי מק"ט, שם או תיאור' aria-label="חיפוש">
      ${k.sev ? `<div class="seg" id="sev"><button data-v="noinfo" class="on">בלי הערות מידע</button><button data-v="high">גבוהה</button>
        <button data-v="medium">בינונית</button><button data-v="low">נמוכה</button><button data-v="info">מידע</button><button data-v="">הכול</button></div>` : ""}
    </div>
    <div class="table-wrap"><table class="t"><thead><tr>${k.sev ? "<th>חומרה</th>" : ""}<th>סוג</th><th>פירוט</th><th>חלקים</th><th>טיפול</th></tr></thead>
      <tbody id="tb"></tbody></table></div>
    <div class="panel-b small muted row" id="foot"></div></div>`;

  const SEV = { high: 0, medium: 1, low: 2, info: 3 };
  rows.sort((a, b) => (SEV[a.severity] ?? 1) - (SEV[b.severity] ?? 1) || a.type_he.localeCompare(b.type_he, "he"));
  const filtered = () => {
    const q = f.q.trim().toLowerCase();
    return rows.filter((r) => (!f.type || r.type === f.type)
      && (!f.sev || (f.sev === "noinfo" ? r.severity !== "info" : r.severity === f.sev))
      && (!q || [r.message, r.pn, ...(r.names || []), ...r.parts.flatMap((p) => [p.pn, p.name])].some((x) => (x || "").toLowerCase().includes(q))));
  };
  const detail = (r) => {
    if (r.message) return esc(r.message);
    const names = (r.names || []).map((n) => `<span class="chip">${esc(n)}</span>`).join(' <span class="muted">≠</span> ');
    const extra = [r.similarity != null ? `דמיון שמות ${Math.round(r.similarity * 100)}%` : "", r.geo_relation ? `גיאומטריה: ${GEO[r.geo_relation] || r.geo_relation}` : ""]
      .filter(Boolean).join(" · ");
    return `${r.pn ? `${pnChip(r.pn)} ` : ""}${names}${extra ? `<div class="small muted" style="margin-top:4px">${extra}</div>` : ""}
      ${/^P[0-9a-f]+$/.test(r.id) ? `<div style="margin-top:4px"><a class="small" href="#/pair/${r.id}">להשוואת הזוג</a></div>` : ""}`;
  };
  const draw = () => {
    const r = filtered();
    el.querySelector("#tb").innerHTML = r.slice(0, f.shown).map((x) => `<tr>${k.sev ? `<td>${sevPill(x.severity)}</td>` : ""}
      <td class="small">${esc(x.type_he)}</td><td style="max-width:560px">${detail(x)}</td>
      <td class="small">${x.parts.map((p) => `<div class="nowrap">${uidLink(p.uid, pnChip(p.pn))} <span class="muted">${esc(p.source)}</span></div>`).join("")}</td>
      <td>${can("engineer") ? `<select data-id="${x.id}" aria-label="טיפול">${ACTIONS.map(([v, l]) => `<option value="${v}" ${v === (x.decision || "") ? "selected" : ""}>${l}</option>`).join("")}</select>`
        : `<span class="small">${(ACTIONS.find(([v]) => v === (x.decision || "")) || ACTIONS[0])[1]}</span>`}
        ${x.decision_by ? `<div class="small muted">${esc(x.decision_by)}</div>` : ""}</td></tr>`).join("")
      || '<tr><td colspan="5"><div class="empty">אין ממצאים שמתאימים לסינון</div></td></tr>';
    el.querySelector("#foot").innerHTML = `מוצגים ${n0(Math.min(f.shown, r.length))} מתוך ${n0(r.length)}
      ${r.length > f.shown ? '<button class="btn small" id="more">הצג עוד</button>' : ""}`;
    const more = el.querySelector("#more");
    if (more) more.onclick = () => { f.shown += PAGE; draw(); };
  };
  tabs(el.querySelector("#tabs"), [{ key: "", label: "הכול", count: rows.length }, ...types], (t) => {
    f.type = t; f.shown = PAGE; history.replaceState(null, "", `#/${page}${t ? "/" + t : ""}`); draw();
  }, f.type);
  el.querySelector("#q").oninput = debounce((e) => { f.q = e.target.value; f.shown = PAGE; draw(); }, 150);
  const sev = el.querySelector("#sev");
  if (sev) sev.querySelectorAll("button").forEach((b) => (b.onclick = () => {
    sev.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b)); f.sev = b.dataset.v; f.shown = PAGE; draw();
  }));
  el.querySelector("#tb").addEventListener("change", async (e) => {
    const s = e.target.closest("select[data-id]");
    if (!s) return;
    try {
      await send("POST", "/api/decisions", { target_type: "issue", target_id: s.dataset.id, decision: s.value });
      const row = rows.find((r) => r.id === s.dataset.id);
      if (row) row.decision = s.value;
      toast(`נשמר: ${(ACTIONS.find((a) => a[0] === s.value) || ACTIONS[0])[1]}`);
    } catch (err) { toast(err.message, true); }
  });
  draw();
}
