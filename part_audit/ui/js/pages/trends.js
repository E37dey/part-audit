// Trends: the numbers of every scan over time, and per scan what was created and what was resolved. All measured by
// the scans themselves; a missing scan is a gap, never an interpolated value.
import { get } from "../api.js";
import { esc, n0, money, datetime, date } from "../util.js";
import { lineChart, divergingBars } from "../chart.js";

const TRIGGER = { manual: "ידנית", schedule: "מתוזמנת", cli: "משימה של המחשב" };

export async function render({ el, setTitle }) {
  setTitle("מגמות", "איך המספרים השתנו מסריקה לסריקה");
  const { runs } = await get("/api/trends");
  if (runs.length < 2) {
    el.innerHTML = `<section class="panel"><div class="empty stack" style="align-items:center">
      <p>מגמה צריכה לפחות שתי סריקות. אחרי כל סריקה נוספת יופיעו כאן קבוצות הכפילות, המלאי על מק"טים כפולים ובעיות הנתונים לאורך זמן.</p>
      <a class="btn" href="#/settings">להגדרת סריקה אוטומטית</a></div></section>`;
    return null;
  }
  const cur = runs.at(-1).summary.currency || "ILS";
  const first = runs[0], last = runs.at(-1);
  const pts = (key, sameCurrency = false) => runs.filter((r) => r.summary[key] != null && (!sameCurrency || (r.summary.currency || "ILS") === cur))
    .map((r) => ({ t: new Date(r.created), v: r.summary[key] }));
  const SERIES = [
    ["groups", "קבוצות כפילות", n0, "#/groups"], ["redundant_pns", "מק\"טים שאפשר לבטל", n0, "#/mapping"],
    ["redundant_stock_value", "מלאי על מק\"טים כפולים", (x) => money(x, cur), "#/groups"], ["quality_issues", "בעיות איכות נתונים", n0, "#/quality"],
    ["erp_issues", "פערים מול ה-ERP", n0, "#/erp"], ["parts", "חלקים שנסרקו", n0, "#/parts"],
  ];
  const flows = runs.slice(1).filter((r) => r.changes).map((r) => ({ t: new Date(r.created), up: r.changes.new_groups + r.changes.grown_groups,
    down: r.changes.resolved_groups, detail: r.changes.unread.length ? `${r.changes.unread.join(", ")} לא נקרא` : "" }));
  const created = flows.reduce((t, f) => t + f.up, 0), resolved = flows.reduce((t, f) => t + f.down, 0);
  const approvedAny = runs.some((r) => r.approved_groups);
  const delta = (k, fmt) => {
    const a = first.summary[k], b = last.summary[k];
    if (a == null || b == null || (k === "redundant_stock_value" && (first.summary.currency || "ILS") !== cur)) return "";
    const d = b - a;
    return d ? `${d > 0 ? "+" : "−"}${fmt(Math.abs(d))} מאז ${date(first.created)}` : `ללא שינוי מאז ${date(first.created)}`;
  };
  el.innerHTML = `
    <p class="muted">${n0(runs.length)} סריקות, מ-${datetime(first.created)} עד ${datetime(last.created)}. כל נקודה על הקו היא סריקה אחת; הקו רק מחבר בין הסריקות.</p>
    <section class="panel"><div class="panel-h"><h2>כפילויות שנוצרו ושנפתרו בכל סריקה</h2>
        <span class="sub">${n0(created)} נוצרו (חדשות, או רשומה נוספת לקבוצה קיימת) · ${n0(resolved)} נפתרו</span></div>
      <div class="panel-b">
        <div class="legend" style="margin-bottom:6px"><span><span class="swatch" style="background:var(--chart-b)"></span> נוצרו – מעל הקו</span><span><span class="swatch" style="background:var(--chart-a)"></span> נפתרו – מתחת לקו</span></div>
        <div id="flow"></div></div></section>
    <section class="grid grid-2" id="multiples">${SERIES.map(([k, label, fmt, href], i) => `
      <div class="panel"><div class="panel-h"><h2><a href="${href}" style="color:inherit">${label}</a></h2><span class="sub">${esc(delta(k, fmt))}</span></div>
        <div class="panel-b"><div data-c="${i}"></div></div></div>`).join("")}
      ${approvedAny ? `<div class="panel"><div class="panel-h"><h2>קבוצות שאושרו</h2><span class="sub">החלטות שהיו בתוקף בזמן כל סריקה</span></div><div class="panel-b"><div id="approved"></div></div></div>` : ""}
    </section>
    <section class="panel"><div class="panel-h"><h2>כל הסריקות</h2><span class="sub">אותם נתונים כטבלה</span></div>
      <div class="table-wrap"><table class="t"><thead><tr><th>מתי</th><th>סוג</th><th class="n">חלקים</th><th class="n">קבוצות כפילות</th><th class="n">מק"טים לביטול</th>
        <th class="n">מלאי על הכפולים</th><th class="n">בעיות איכות</th><th class="n">פערים מול ERP</th><th class="n">נוצרו</th><th class="n">נפתרו</th></tr></thead>
        <tbody>${[...runs].reverse().map((r) => `<tr><td class="nowrap">${datetime(r.created)}</td><td class="small">${TRIGGER[r.trigger] || "ידנית"}</td>
          <td class="n">${n0(r.summary.parts)}</td><td class="n">${n0(r.summary.groups)}</td><td class="n">${n0(r.summary.redundant_pns)}</td>
          <td class="n">${money(r.summary.redundant_stock_value, r.summary.currency || cur)}</td><td class="n">${n0(r.summary.quality_issues)}</td><td class="n">${n0(r.summary.erp_issues)}</td>
          <td class="n">${r.changes ? n0(r.changes.new_groups + r.changes.grown_groups) : "—"}</td><td class="n">${r.changes ? n0(r.changes.resolved_groups) : "—"}</td></tr>`).join("")}</tbody></table></div></section>`;
  const stops = [];
  stops.push(divergingBars(el.querySelector("#flow"), { rows: flows, upLabel: "נוצרו", downLabel: "נפתרו" }));
  SERIES.forEach(([k, label, fmt], i) => stops.push(lineChart(el.querySelector(`[data-c="${i}"]`), { points: pts(k, k === "redundant_stock_value"), fmt, label })));
  if (approvedAny) stops.push(lineChart(el.querySelector("#approved"), { points: runs.map((r) => ({ t: new Date(r.created), v: r.approved_groups })), fmt: n0, label: "קבוצות שאושרו" }));
  return () => stops.forEach((s) => s && s());
}
