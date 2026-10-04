// Change package: what to change in each system to carry out the approved decisions - BOM lines to replace, part
// numbers to retire, stock to move - and every affected BOM before and after. PartAudit prepares; people execute.
import { get, isStatic } from "../api.js";
import { esc, n0, money, pnChip, sysBadge, ICON } from "../util.js";
import { term } from "../learn.js";
import { art } from "../art.js";
import { toast } from "../ui.js";

const KIND = {
  replace_line: { he: "שורות בעץ מוצר", icon: ICON.tree, one: "החלפת שורה" },
  supersede: { he: "ביטול מק\"טים", icon: ICON.stop, one: "ביטול" },
  move_stock: { he: "העברות מלאי", icon: ICON.erp, one: "מלאי" },
};
const sysKind = (s) => (s.kind === "ERP" ? "ERP" : s.kind);
const arrow = '<span class="pk-arrow" aria-hidden="true">←</span>';

function actionRow(a, cur) {
  if (a.kind === "replace_line") {
    return `<li class="pk-a"><span class="pk-ic">${KIND.replace_line.icon}</span><div>
      <div>בעץ המוצר של ${pnChip(a.assembly_pn)} <span class="small">${esc(a.assembly_name || "")}</span>${a.assembly_state ? ` <span class="small muted">(${esc(a.assembly_state)})</span>` : ""}</div>
      <div class="pk-swap"><span class="old">${pnChip(a.old_pn)}</span>${arrow}${pnChip(a.new_pn, true)}<span class="qty">×${n0(a.qty)}</span></div></div></li>`;
  }
  if (a.kind === "supersede") {
    return `<li class="pk-a"><span class="pk-ic">${KIND.supersede.icon}</span><div>
      <div class="pk-swap"><span class="old">${pnChip(a.pn)}</span><span class="small">${esc(a.name || "")}</span></div>
      <div class="small muted">לסמן כמבוטל, ולהפנות ל-${pnChip(a.new_pn, true)}${a.state ? ` · מצב עכשיו: ${esc(a.state)}` : ""}</div></div></li>`;
  }
  return `<li class="pk-a"><span class="pk-ic">${KIND.move_stock.icon}</span><div>
    <div class="pk-swap"><span class="old">${pnChip(a.pn)}</span>${arrow}${pnChip(a.to_pn, true)}
      <b class="num">${n0(a.stock)} ${esc(a.uom || "")}</b>${a.value != null ? `<span class="small muted">${money(a.value, a.currency || cur)}</span>` : ""}</div>
    <div class="small muted">להעביר את המלאי, ולסגור את ${esc(a.pn)} לרכש חדש</div></div></li>`;
}

function systemCard(s, cur) {
  const groups = Object.keys(KIND).filter((k) => s.counts[k]);
  return `<section class="panel pk-sys"><div class="panel-h"><h2>${sysBadge(sysKind(s), s.name)}</h2>
      <span class="sub">${groups.map((k) => `${n0(s.counts[k])} ${KIND[k].he}`).join(" · ")}</span></div>
    <div class="panel-b">${groups.map((k) => `<h3 class="pk-k">${KIND[k].icon}${KIND[k].he}</h3>
      <ol class="pk-list">${s.actions.filter((a) => a.kind === k).map((a) => actionRow(a, cur)).join("")}</ol>`).join("")}</div></section>`;
}

function beforeAfter(a) {
  const rows = a.before.map((b) => {
    const key = b.pn;
    const x = a.after.find((y) => y.was === key) || a.after.find((y) => y.pn === key);
    return { b, x };
  });
  const same = rows.filter(({ x }) => !x || x.change === "same").length;
  return `<div class="ba"><div class="ba-h"><span class="kind">${ICON.asm}</span>${pnChip(a.pn)}<b>${esc(a.name)}</b>
      <span class="small muted">${sysBadge(a.system_kind, a.system)}</span><span class="pill warn plain">${n0(a.changes)} ${a.changes === 1 ? "שינוי" : "שינויים"}</span></div>
    <table class="t ba-t"><thead><tr><th>לפני</th><th class="n">כמות</th><th aria-hidden="true"></th><th>אחרי</th><th class="n">כמות</th></tr></thead><tbody>
    ${rows.map(({ b, x }) => {
      const ch = x && x.change !== "same";
      return `<tr class="${ch ? `ch-${x.change}` : "same"}" ${ch ? "" : "hidden"}><td>${pnChip(b.pn)} <span class="small">${esc(b.name || "")}</span></td><td class="n">${n0(b.qty)}</td>
        <td class="ba-arrow">${ch ? "←" : ""}</td><td>${x ? `${pnChip(x.pn, ch)} ${ch ? `<span class="small">${x.change === "merged" ? "מאוחד – הכמויות חוברו" : "מוחלף"}</span>` : ""}` : ""}</td>
        <td class="n">${x ? n0(x.qty) : ""}</td></tr>`;
    }).join("")}</tbody></table>
    ${same ? `<button type="button" class="btn ghost small" data-all>הצגת כל ${n0(rows.length)} השורות</button>` : ""}</div>`;
}

export async function render({ el, setTitle, state }) {
  setTitle("חבילת שינוי", "מה לשנות בכל מערכת כדי לבצע את ההחלטות שאושרו");
  const rid = state.status.latest_run;
  const pkg = await get(`/api/runs/${rid}/package`);
  const t = pkg.totals, cur = t.currency || "ILS";
  if (!t.groups) {
    el.innerHTML = `<section class="panel"><div class="panel-b pk-empty">
      <div class="pk-art">${art("eco")}</div>
      <div><h2>עוד אין מה לבצע</h2>
        <p>${term("eco", "חבילת השינוי")} נבנית מההחלטות שלכם: כל קבוצת כפילות שאישרתם נכנסת אליה – אילו שורות להחליף בעצי המוצר, אילו מק"טים לבטל ואיזה מלאי להעביר, לכל מערכת בנפרד.</p>
        <p class="muted">עדיין לא אושרה אף קבוצה.</p>
        <a class="btn primary" href="#/groups">לקבוצות הכפילות</a></div></div></section>`;
    return null;
  }
  el.innerHTML = `
    <section class="readout" style="--cells:4">
      <div class="cell"><span class="r-label">קבוצות שאושרו</span><span class="r-value">${n0(t.groups)}</span><span class="r-note">${n0(t.old_pns)} מק"טים יוחלפו</span></div>
      <div class="cell"><span class="r-label">שורות בעצי מוצר</span><span class="r-value">${n0(t.bom_lines)}</span><span class="r-note">ב-${n0(t.assemblies)} מכלולים</span></div>
      <div class="cell"><span class="r-label">רשומות לביטול</span><span class="r-value">${n0(t.supersede)}</span><span class="r-note">ב-${n0(t.systems)} מערכות</span></div>
      <div class="cell"><span class="r-label">מלאי שעובר</span><span class="r-value">${money(t.stock_value, cur)}</span><span class="r-note">מ-${n0(t.stock_items)} פריטי ERP</span></div>
    </section>
    <div class="row pk-bar"><span class="callout small" style="flex:1">${ICON.lock} PartAudit לא כותב לשום מערכת. זו רשימת עבודה: מעבירים אותה לאחראי של כל מערכת, והוא מבצע לפי הנהלים שלכם.</span>
      <button class="btn" id="pk-xls">${ICON.xls}Excel לביצוע</button><button class="btn ghost" id="pk-csv">CSV</button></div>
    <div class="seg pk-tabs" role="tablist"><button type="button" role="tab" data-t="sys" aria-selected="true">${ICON.eco}לפי מערכת</button>
      <button type="button" role="tab" data-t="ba" aria-selected="false">${ICON.tree}לפני ואחרי (${n0(pkg.assemblies.length)})</button>
      <button type="button" role="tab" data-t="grp" aria-selected="false">${ICON.copy}הקבוצות (${n0(pkg.groups.length)})</button></div>
    <div id="pk-sys" class="pk-grid">${pkg.systems.map((s) => systemCard(s, cur)).join("")}</div>
    <div id="pk-ba" hidden>${pkg.assemblies.length ? `<p class="small muted">כל ${term("assembly", "מכלול")} ש${term("bom", "עץ המוצר")} שלו משתנה. שורה שהמק"ט שלה כבר נמצא במכלול מתאחדת איתו, והכמויות מתחברות.</p>
      <div class="pk-grid">${pkg.assemblies.map(beforeAfter).join("")}</div>` : '<div class="empty">אף עץ מוצר לא משתנה – לחלקים בקבוצות שאושרו אין שימושים במק"טים שיוחלפו.</div>'}</div>
    <div id="pk-grp" hidden><section class="panel"><div class="table-wrap"><table class="t"><thead><tr><th>חלק</th><th>${term("target", "המק\"ט שנשאר")}</th><th>מק"טים שיוחלפו</th></tr></thead><tbody>
      ${pkg.groups.map((g) => `<tr class="click" data-h="#/group/${esc(g.id)}"><td>${esc(g.name)}${g.spec ? ` <span class="mono small muted">${esc(g.spec)}</span>` : ""}</td>
        <td>${pnChip(g.target_pn, true)}</td><td>${g.old_pns.map((x) => pnChip(x)).join(" ")}</td></tr>`).join("")}</tbody></table></div></section></div>`;
  el.querySelectorAll("[data-t]").forEach((b) => (b.onclick = () => {
    el.querySelectorAll("[data-t]").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    ["sys", "ba", "grp"].forEach((k) => (el.querySelector(`#pk-${k}`).hidden = k !== b.dataset.t));
  }));
  el.querySelectorAll("tr[data-h]").forEach((tr) => (tr.onclick = () => (location.hash = tr.dataset.h)));
  el.querySelectorAll("[data-all]").forEach((b) => (b.onclick = () => {
    const box = b.closest(".ba"), open = b.dataset.open === "1";
    box.querySelectorAll("tr.same").forEach((tr) => (tr.hidden = open));
    b.dataset.open = open ? "" : "1";
    b.textContent = open ? `הצגת כל ${box.querySelectorAll("tbody tr").length} השורות` : "רק השורות שמשתנות";
  }));
  const dl = (fmt) => () => {
    if (isStatic) { toast("הורדת הקובץ זמינה באפליקציה; בהדגמה המקוונת החבילה מוצגת כאן"); return; }
    location.href = `/api/runs/${rid}/package.${fmt}`;
  };
  el.querySelector("#pk-xls").onclick = dl("xlsx");
  el.querySelector("#pk-csv").onclick = dl("csv");
  return null;
}
