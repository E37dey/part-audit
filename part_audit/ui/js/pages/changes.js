// What changed since the scan before: new duplicates first (someone just created another copy of a part), then what
// was fixed, data findings that appeared or went away, and the records added, removed or edited in the systems.
import { get } from "../api.js";
import { esc, n0, money, date, datetime, pnChip, sysBadge, catPill } from "../util.js";

const KIND_HE = { manual: "ידנית", schedule: "מתוזמנת", cli: "משימה מתוזמנת של המחשב" };

function delta(d, fmt = n0, goodWhenDown = true) {
  if (!d || d.delta == null || d.delta === 0) return '<span class="muted">ללא שינוי</span>';
  const up = d.delta > 0;
  const tone = up === goodWhenDown ? "bad" : "ok";
  return `<span class="d-${tone} ltr">${up ? "+" : "−"}${fmt(Math.abs(d.delta))}</span> <span class="muted">מאז הסריקה הקודמת</span>`;
}

function cell(label, d, fmt = n0, goodWhenDown = true, href = "") {
  const tag = href ? "a" : "div";
  return `<${tag} class="cell"${href ? ` href="${href}"` : ""}><span class="r-label">${label}</span>
    <span class="r-value">${d && d.after != null ? fmt(d.after) : "—"}</span><span class="r-note">${delta(d, fmt, goodWhenDown)}</span></${tag}>`;
}

const show = (v) => (v === "" || v == null ? '<span class="muted">—</span>' : v === true ? "יש" : v === false ? "אין" : esc(String(v)));

function rec(p, extra = "") {
  return `<span class="nowrap">${pnChip(p.pn)}</span> ${esc(p.name || "")} ${sysBadge(p.source_kind, "")}${extra}`;
}

function groupRows(rows, what) {
  if (!rows.length) return "";
  return rows.map((g) => `<tr${what !== "resolved" ? ` class="click" data-h="#/group/${esc(g.id)}"` : ""}>
    <td>${esc(g.name)}${g.spec ? ` <span class="small muted mono">${esc(g.spec)}</span>` : ""}<div class="small muted">${g.pns.map((x) => esc(x)).join(" · ")}</div></td>
    <td class="small">${(g.joined || []).map((p) => `<div>${rec(p, p.new_record ? ' <span class="pill bad plain">רשומה חדשה</span>' : ' <span class="pill neutral plain">הצטרפה לקבוצה</span>')}</div>`).join("")
      || (g.left || []).map((p) => `<div>${rec(p, p.removed ? ' <span class="pill ok plain">הוסרה</span>' : ' <span class="pill neutral plain">כבר לא תואמת</span>')}</div>`).join("")
      || (g.members_then || []).map((p) => `<div>${rec(p, p.removed ? ' <span class="pill ok plain">הוסרה</span>' : "")}</div>`).join("")}</td>
    <td class="nowrap">${g.sources.map((s) => esc(s)).join("<br>")}</td>
    <td class="n">${n0(g.members)}</td></tr>`).join("");
}

function findingRows(list, kind) {
  return list.map((q) => `<li><span class="pill ${kind === "new" ? "warn" : "ok"} plain">${esc(q.type_he || q.category_he || q.type)}</span>
    ${q.parts ? q.parts.slice(0, 2).map((p) => `${pnChip(p.pn)} ${esc(p.name || "")}`).join(" · ") : ""}
    ${q.a ? `${pnChip(q.a.pn)} ↔ ${pnChip(q.b?.pn)}` : ""} <span class="small muted">${esc((q.message || q.reason_he || "").slice(0, 140))}</span></li>`).join("");
}

export async function render({ el, setTitle, state }) {
  const runs = (await get("/api/runs")).filter((r) => r.status === "done");
  const latest = runs[0];
  setTitle("מה השתנה", latest ? `הסריקה של ${datetime(latest.created)} מול סריקה קודמת` : "");
  if (runs.length < 2) {
    el.innerHTML = `<section class="panel"><div class="empty stack" style="align-items:center">
      <p>כדי לראות מה השתנה צריך לפחות שתי סריקות. הסריקה הבאה תושווה לזו, ויוצג מה נוסף, מה נפתר ואיזו כפילות חדשה נוצרה.</p>
      <p class="small">אפשר לקבוע סריקה אוטומטית קבועה (למשל כל יום ראשון בבוקר) במסך ההגדרות.</p>
      <a class="btn" href="#/settings">להגדרת סריקה אוטומטית</a></div></section>`;
    return null;
  }
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const base = params.get("base") || "";
  const c = await get(`/api/runs/${latest.id}/changes`, base ? { base } : {});
  const older = runs.slice(1);
  const g = c.groups, f = c.findings, r = c.records, s = c.summary, cur = c.currency || "ILS";
  const m = (x) => money(x, cur);
  const nNew = f.quality.n_new + f.erp_issues.n_new + f.names.n_new + f.pairs.n_new;
  const nFixed = f.quality.n_resolved + f.erp_issues.n_resolved + f.names.n_resolved + f.pairs.n_resolved;
  el.innerHTML = `
    <div class="toolbar"><label class="small muted" for="base">להשוות את הסריקה האחרונה (${datetime(latest.created)}) מול הסריקה של</label>
      <select id="base">${older.map((x, i) => `<option value="${esc(x.id)}" ${(base ? x.id === base : i === 0) ? "selected" : ""}>${datetime(x.created)} · ${KIND_HE[x.trigger] || "ידנית"}</option>`).join("")}</select></div>

    <section class="verdict ${c.alert ? "warn" : "ok"} slim" aria-live="polite"><div class="v-body">
      <h2>${esc(c.headline)}</h2>
      <p class="small">${g.new.length + g.grown.length ? "כפילות חדשה היא חלק שנפתח שוב תחת מק\"ט חדש, במקום להשתמש במק\"ט הקיים. כדאי לטפל בה לפני שהיא נכנסת לעצי מוצר ולמלאי." : "השוואה של כל הרשומות, הקבוצות והממצאים בין שתי הסריקות."}</p>
      ${c.notify ? `<div class="v-note ${c.notify.sent ? "ok" : "bad"}">${c.notify.sent ? `נשלח מייל ל-${esc(c.notify.to)} (${datetime(c.notify.at)})` : `שליחת המייל נכשלה: ${esc(c.notify.error)}`}</div>` : ""}
      ${c.unread_sources?.length ? `<div class="v-note bad">${esc(c.unread_sources.join(", "))} לא נקרא בסריקה הזו. הרשומות שלו לא נספרו כ"הוסרו".</div>` : ""}
    </div></section>

    <section class="readout" style="--cells:4">
      ${cell("קבוצות כפילות", s.groups, n0, true, "#/groups")}
      ${cell("מק\"טים שאפשר לבטל", s.redundant_pns, n0, true, "#/mapping")}
      ${cell("מלאי במק\"טים הכפולים", s.redundant_stock_value, m, true, "#/groups")}
      ${cell("בעיות איכות", s.quality_issues, n0, true, "#/quality")}
    </section>

    <section class="panel"><div class="panel-h"><h2>כפילויות חדשות</h2><span class="sub">${g.new.length ? `${n0(g.new.length)} קבוצות שלא היו בסריקה הקודמת` : ""}</span></div>
      ${g.new.length ? `<div class="table-wrap"><table class="t"><thead><tr><th>חלק</th><th>הרשומות</th><th>מערכות</th><th class="n">רשומות</th></tr></thead><tbody>${groupRows(g.new, "new")}</tbody></table></div>`
        : '<div class="empty">לא נוצרה כפילות חדשה.</div>'}</section>

    ${g.grown.length ? `<section class="panel"><div class="panel-h"><h2>קבוצות שקיבלו רשומה נוספת</h2><span class="sub">עוד עותק של חלק שכבר היה כפול</span></div>
      <div class="table-wrap"><table class="t"><thead><tr><th>חלק</th><th>מה נוסף</th><th>מערכות</th><th class="n">רשומות</th></tr></thead><tbody>${groupRows(g.grown, "grown")}</tbody></table></div></section>` : ""}

    <section class="panel"><div class="panel-h"><h2>מה נפתר</h2><span class="sub">${n0(g.resolved.length)} קבוצות נפתרו לגמרי, ${n0(g.shrunk.length)} הצטמצמו</span></div>
      ${g.resolved.length + g.shrunk.length ? `<div class="table-wrap"><table class="t"><thead><tr><th>חלק</th><th>מה השתנה</th><th>מערכות</th><th class="n">רשומות</th></tr></thead><tbody>
        ${groupRows(g.resolved, "resolved")}${groupRows(g.shrunk, "shrunk")}</tbody></table></div>`
        : '<div class="empty">אף קבוצת כפילות לא נפתרה מאז הסריקה הקודמת.</div>'}
      ${g.unknown ? `<div class="panel-b small muted">${n0(g.unknown)} קבוצות לא נבדקו, כי מקור הנתונים שלהן לא נקרא בסריקה הזו.</div>` : ""}</section>

    <section class="grid grid-2">
      <div class="panel"><div class="panel-h"><h2>ממצאים חדשים</h2><span class="sub">${n0(nNew)}</span></div>
        <div class="panel-b">${nNew ? `<ul class="evidence">${findingRows([...f.quality.new, ...f.erp_issues.new, ...f.pairs.new, ...f.names.new].slice(0, 40), "new")}</ul>` : '<p class="muted">אין ממצאים חדשים.</p>'}</div></div>
      <div class="panel"><div class="panel-h"><h2>ממצאים שתוקנו</h2><span class="sub">${n0(nFixed)}</span></div>
        <div class="panel-b">${nFixed ? `<ul class="evidence">${findingRows([...f.quality.resolved, ...f.erp_issues.resolved, ...f.pairs.resolved, ...f.names.resolved].slice(0, 40), "fixed")}</ul>` : '<p class="muted">אין ממצאים שתוקנו.</p>'}</div></div>
    </section>

    <section class="panel"><div class="panel-h"><h2>רשומות במערכות</h2>
      <span class="sub">${n0(r.n_added)} נוספו · ${n0(r.n_removed)} הוסרו · ${n0(r.n_changed)} השתנו${r.n_not_read ? ` · ${n0(r.n_not_read)} לא נקראו` : ""}</span></div>
      <div class="panel-b grid grid-2">
        <div><h3 class="small muted" style="margin-bottom:6px">נוספו</h3>${r.added.length ? `<ul class="evidence small">${r.added.slice(0, 30).map((p) => `<li>${rec(p)} <span class="muted">${p.created ? date(p.created) : ""}</span></li>`).join("")}</ul>` : '<p class="muted small">אין</p>'}
          <h3 class="small muted" style="margin:12px 0 6px">הוסרו</h3>${r.removed.length ? `<ul class="evidence small">${r.removed.slice(0, 30).map((p) => `<li>${rec(p)}</li>`).join("")}</ul>` : '<p class="muted small">אין</p>'}</div>
        <div><h3 class="small muted" style="margin-bottom:6px">השתנו</h3>${r.changed.length ? `<div class="table-wrap"><table class="t"><thead><tr><th>רשומה</th><th>שדה</th><th>לפני</th><th>אחרי</th></tr></thead><tbody>
          ${r.changed.slice(0, 40).flatMap((p) => p.changes.map((x, i) => `<tr>${i ? "<td></td>" : `<td>${rec(p)}</td>`}<td>${esc(x.field_he)}</td><td class="small">${show(x.before)}</td><td class="small">${show(x.after)}</td></tr>`)).join("")}
          </tbody></table></div>` : '<p class="muted small">אין</p>'}</div>
      </div></section>`;
  el.querySelectorAll("tr[data-h]").forEach((tr) => (tr.onclick = () => (location.hash = tr.dataset.h)));
  el.querySelector("#base").onchange = (e) => {
    const v = e.target.value;
    location.hash = v === older[0].id ? "#/changes" : `#/changes?base=${encodeURIComponent(v)}`;
  };
  return null;
}
