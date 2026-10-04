import { get } from "../api.js";
import { esc, n0, money, pnChip, sysBadge, decisionPill, datetime } from "../util.js";
import { bars } from "../ui.js";

export async function render({ el, setTitle, state }) {
  setTitle("לוח בקרה", "תמונת מצב של הסריקה האחרונה");
  const d = await get(`/api/runs/${state.status.latest_run}/summary`);
  const s = d.summary;
  const cur = s.currency || "ILS";
  const kindOf = Object.fromEntries(d.sources.map((x) => [x.name, x.kind]));
  const share = (a, b) => (b ? Math.round((100 * a) / b) : 0);
  el.innerHTML = `
  <section class="readout" aria-label="הממצאים העיקריים">
    ${cell("קבוצות כפילות", n0(s.groups), `${n0(s.parts_in_groups)} רשומות, ${n0(s.groups_cross_source)} מהן חוצות מערכות`, "#/groups")}
    ${cell("מק\"טים שאפשר לבטל", n0(s.redundant_pns), "אחרי אישור נשאר מק\"ט אחד בכל קבוצה", "#/mapping")}
    ${cell("מלאי במק\"טים הכפולים", money(s.redundant_stock_value, cur), "כמות × עלות מה-ERP, בלי המק\"ט שנשאר", "#/groups")}
    ${cell("ממתינים לאישור", n0(d.decisions.pending_groups), `${n0(d.decisions.approved_groups)} קבוצות כבר אושרו`, "#/groups", "act")}
  </section>
  <section class="readout sub" aria-label="ממצאים נוספים">
    ${cell("חלקים שנסרקו", n0(s.parts), `ועוד ${n0(s.assemblies)} מכלולים מ-${n0(s.sources)} מקורות`, "#/parts")}
    ${cell("כמעט זהים", n0(s.near_pairs), "זוגות שאולי אפשר לתקנן לחלק אחד", "#/near")}
    ${cell("בעיות איכות", n0(s.quality_high + s.quality_medium), `${n0(s.quality_high)} בחומרה גבוהה`, "#/quality")}
    ${cell("פערים בין PDM ל-ERP", n0(s.erp_issues), "חסרים, תיאור, חומר, סטטוס, עץ מוצר", "#/erp")}
  </section>
  <section class="panel"><div class="panel-h"><h2>כיסוי הנתונים</h2><span class="sub">על מה מבוססות ההשוואות</span></div>
    <div class="panel-b gauges">
      ${gauge("חלקים עם מודל STEP", s.with_step, s.parts, `${share(s.with_step, s.parts)}% נבדקו גם לפי גיאומטריה; השאר לפי שם, מק"ט ומפרט`)}
      ${gauge("חלקים שמקושרים לפריט ERP", s.erp_linked, s.parts, `${share(s.erp_linked, s.parts)}% עם מלאי, עלות ועץ מוצר מה-ERP`)}
      ${gauge("חלקים בקבוצת כפילות", s.parts_in_groups, s.parts, `${share(s.parts_in_groups, s.parts)}% מהחלקים רשומים יותר מפעם אחת`)}
    </div></section>
  <section class="panel"><div class="panel-h"><h2>הקבוצות עם ההשפעה הגדולה</h2><span class="sub">לפי שווי המלאי במק"טים הכפולים</span><span class="spacer"></span><a href="#/groups" class="small">לכל ${n0(s.groups)} הקבוצות</a></div>
    <div class="table-wrap"><table class="t"><thead><tr><th>חלק</th><th>מק"ט שנשאר</th><th>מק"טים כפולים</th><th>מערכות</th><th class="n">שימושים</th><th class="n">מלאי במק"טים הכפולים</th><th>החלטה</th></tr></thead><tbody>
    ${d.top_groups.map((g) => `<tr class="click" data-h="#/group/${g.id}"><td>${esc(g.name)}${g.spec ? ` <span class="small muted mono">${esc(g.spec)}</span>` : ""}</td>
      <td class="nowrap">${pnChip(g.final_master_pn || g.master_pn, true)}</td>
      <td>${g.pns.filter((p) => p !== (g.final_master_pn || g.master_pn)).map((p) => pnChip(p)).join(" ")}</td>
      <td class="nowrap">${g.sources.map((x) => sysBadge(kindOf[x], "")).join("")}</td><td class="n">${n0(g.where_used?.length ?? g.n_used)}</td>
      <td class="n">${money(g.redundant_stock_value, cur)}</td><td>${decisionPill(g.decision)}</td></tr>`).join("")}
    </tbody></table></div></section>
  <section class="grid grid-2">
    <div class="panel"><div class="panel-h"><h2>כפילויות לפי מערכת</h2><span class="sub">רשומות שנמצאו בקבוצת כפילות מתוך כל החלקים</span></div>
      <div class="panel-b">${bars(Object.entries(d.by_source).map(([name, v]) => ({ label: name, html: sysBadge(v.kind, name), value: v.parts,
        parts: [{ value: v.in_groups, alt: false }, { value: v.parts - v.in_groups, alt: true }] })), { fmt: (x) => n0(x) })}
        <div class="legend" style="margin-top:10px"><span><span class="swatch" style="background:var(--dye)"></span> בקבוצת כפילות</span><span><span class="swatch" style="background:var(--brass)"></span> ייחודי</span></div></div></div>
    <div class="panel"><div class="panel-h"><h2>כפילויות שחוצות מערכות</h2><span class="sub">מספר הקבוצות שיש להן רשומות בשתי המערכות</span></div>
      <div class="panel-b table-wrap">${matrix(d.cross_source, kindOf)}</div></div>
  </section>
  <section class="grid grid-2">
    <div class="panel"><div class="panel-h"><h2>ממצאי איכות ו-ERP לפי סוג</h2><span class="spacer"></span><a class="small" href="#/quality">לפירוט</a></div>
      <div class="panel-b">${bars(Object.entries(d.issues_by_type).slice(0, 10).map(([k, v]) => ({ label: k, value: v })), { fmt: n0 })}</div></div>
    <div class="panel"><div class="panel-h"><h2>מקורות הנתונים בסריקה</h2><span class="spacer"></span><a class="small" href="#/sources">ניהול מקורות</a></div>
      <div class="table-wrap"><table class="t"><thead><tr><th>מקור</th><th class="n">רשומות</th><th class="n">זמן קריאה</th><th>מצב</th></tr></thead><tbody>
      ${d.sources.map((x) => `<tr><td>${sysBadge(x.kind, x.name)}${x.simulated ? ' <span class="pill neutral plain">סימולטור</span>' : ""}</td>
        <td class="n">${n0(x.stats.records || x.stats.erp_items || 0)}</td><td class="n">${x.stats.seconds != null ? x.stats.seconds + " ש'" : "—"}</td>
        <td>${x.errors.length ? `<span class="pill bad">${esc(x.errors[0]).slice(0, 80)}</span>` : '<span class="pill ok">נקרא</span>'}</td></tr>`).join("")}
      </tbody></table></div>
      <div class="panel-b small muted">משך הסריקה: ${Math.round(d.timings.total_s)} שניות לניתוח (${n0(d.timings.geometry_computed ?? 0)} קבצים חושבו, ${n0(d.timings.geometry_cached ?? 0)} מהמטמון) · ${datetime(d.created)}</div></div>
  </section>
  <section class="panel"><div class="panel-h"><h2>מה עושים עכשיו</h2></div><div class="next-steps">
    ${next("1", "לאשר כפילויות", `${n0(d.decisions.pending_groups)} קבוצות ממתינות. כל קבוצה מציגה את החלקים זה לצד זה בתלת-ממד, עם מלאי ושימושים.`, "#/groups")}
    ${next("2", "לבדוק חלקים כמעט זהים", `${n0(s.near_pairs)} זוגות עם הבדל קטן. מפת צבעים מראה בדיוק איפה הם שונים.`, "#/near")}
    ${next("3", "לתקן את הנתונים", `${n0(s.quality_high)} בעיות בחומרה גבוהה ו-${n0(s.erp_issues)} פערים מול ה-ERP.`, "#/quality")}
  </div></section>`;
  el.querySelectorAll("tr[data-h]").forEach((tr) => (tr.onclick = () => (location.hash = tr.dataset.h)));
}

function cell(label, value, note, href, tone = "") {
  return `<a class="cell ${tone}" href="${href}"><span class="r-label">${label}</span><span class="r-value">${value}</span><span class="r-note">${note}</span></a>`;
}
function gauge(label, part, whole, note) {
  const p = whole ? Math.min(100, (100 * part) / whole) : 0;
  return `<div class="gauge"><div class="g-top"><span>${label}</span><b>${n0(part)} <span class="muted">מתוך</span> ${n0(whole)}</b></div>
    <div class="g-bar" role="meter" aria-valuemin="0" aria-valuemax="${whole}" aria-valuenow="${part}" aria-label="${label}"><i style="width:${p.toFixed(1)}%"></i></div>
    <div class="g-note">${note}</div></div>`;
}
function next(n, title, text, href) {
  return `<a class="next-step" href="${href}"><span class="n">${n}</span><b>${title}</b><span>${text}</span></a>`;
}
function matrix(cross, kindOf) {
  const names = [...new Set(Object.keys(cross).flatMap((k) => k.split("|")))];
  if (!names.length) return '<div class="empty">אין כפילויות חוצות מערכות</div>';
  const max = Math.max(1, ...Object.values(cross));
  const cell = (a, b) => {
    if (a === b) return '<td class="cell muted">—</td>';
    const v = cross[`${a}|${b}`] ?? cross[`${b}|${a}`] ?? 0;
    const alpha = v ? 0.12 + 0.6 * (v / max) : 0;
    return `<td class="cell" style="background:color-mix(in srgb, var(--dye) ${Math.round(alpha * 100)}%, transparent);color:${alpha > 0.45 ? "var(--dye-ink)" : "inherit"}">${v || ""}</td>`;
  };
  return `<table class="t matrix"><thead><tr><th></th>${names.map((n) => `<th title="${esc(n)}">${sysBadge(kindOf[n], "")}</th>`).join("")}</tr></thead>
    <tbody>${names.map((a) => `<tr><th style="position:static">${sysBadge(kindOf[a], a)}</th>${names.map((b) => cell(a, b)).join("")}</tr>`).join("")}</tbody></table>`;
}
