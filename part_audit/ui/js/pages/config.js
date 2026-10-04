// Configuration control: pick a product, walk its BOM tree. Every item carries its identity (part number,
// revision, state) and the marks of what was found on it; clicking an item explains, in plain words, what the
// problem is, why it matters and what to do. The ERP view puts the assembly's BOM next to the ERP's, line by line.
import { get, isStatic } from "../api.js";
import { esc, n0, money, pnChip, sysBadge, statePill, rev, ICON, debounce } from "../util.js";
import { term } from "../learn.js";

const FLAG = {
  duplicate: { he: "כפילות", icon: ICON.copy, cls: "f-dup",
    why: "שני מק\"טים לאותו חלק: קונים אותו פעמיים, המלאי מתפצל, ובכל עץ מוצר הוא רשום אחרת.",
    todo: "בקבוצת הכפילות בוחרים איזה מק\"ט נשאר ומאשרים. אחרי האישור השורה הזו נכנסת לחבילת השינוי." },
  state: { he: "מצב / שחרור", icon: ICON.clock, cls: "f-state",
    why: "רכיב שלא שוחרר, או שבוטל, בתוך מכלול פעיל: אי אפשר לייצר או לקנות לפי עץ המוצר הזה בלי לבדוק אותו.",
    todo: "לשחרר את הרכיב במערכת ה-PDM / PLM, או להחליף אותו ברכיב משוחרר." },
  erp: { he: "פער מול ERP", icon: ICON.erp, cls: "f-erp",
    why: "הרכש והייצור עובדים לפי ה-ERP. כשהוא לא מסכים עם ההנדסה – קונים או מרכיבים את הדבר הלא נכון.",
    todo: "לבדוק איזו מערכת צודקת ולתקן את השנייה." },
  quality: { he: "בעיית נתונים", icon: ICON.check, cls: "f-qual",
    why: "מידע חסר או סותר ברשומה גורם לטעויות ברכש, בייצור ובחישובי משקל ועלות.",
    todo: "לתקן את הרשומה במערכת המקור; הסריקה הבאה תראה שזה נפתר." },
  near: { he: "כמעט זהים", icon: ICON.near, cls: "f-near",
    why: "קיים כבר חלק כמעט זהה. אולי אפשר להשתמש בחלק אחד ולחסוך מק\"ט, מלאי ושרטוט.",
    todo: "להשוות במפת הצבעים ולהחליט אם ההבדל חשוב." },
};
const ORDER = ["duplicate", "state", "erp", "quality", "near"];
const ERP_STATUS = { same: ["זהה", "ok"], qty: ["כמות שונה", "warn"], pdm_only: ["חסר ב-ERP", "bad"], erp_only: ["רק ב-ERP", "bad"] };

const open = (f) => !(f.type === "duplicate" && f.stays);            // the part number that stays is not a problem
const kindIcon = (n) => (n.kind === "assembly" ? ICON.asm : n.standard ? ICON.bolt : ICON.part);
const kindHe = (n) => (n.kind === "assembly" ? "מכלול" : n.standard ? "חלק תקני" : "חלק");
const qtyTxt = (q) => (q == null ? "" : `×${Number.isInteger(q) ? q : q.toFixed(2)}`);

function ring(ok, total, size = 46) {
  const r = (size - 6) / 2, c = 2 * Math.PI * r, f = total ? ok / total : 0;
  return `<svg class="ring" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img" aria-label="${n0(ok)} מתוך ${n0(total)} רכיבים בלי ממצא">
    <circle cx="${size / 2}" cy="${size / 2}" r="${r}" class="ring-bg"/>
    <circle cx="${size / 2}" cy="${size / 2}" r="${r}" class="ring-fg" stroke-dasharray="${(c * f).toFixed(1)} ${c.toFixed(1)}" transform="rotate(-90 ${size / 2} ${size / 2})"/>
    <text x="50%" y="50%" dy="4" text-anchor="middle">${Math.round(100 * f)}%</text></svg>`;
}

function flagDots(flags) {
  const kinds = [...new Set(flags.filter(open).map((f) => f.type))];
  const stays = flags.some((f) => f.type === "duplicate" && f.stays);
  return `${stays ? `<span class="fdot f-stays" title="זה המק&quot;ט שנשאר">${ICON.anchor}</span>` : ""}${kinds.map((k) =>
    `<span class="fdot ${FLAG[k].cls}" title="${FLAG[k].he}">${FLAG[k].icon}</span>`).join("")}`;
}

function productCard(p, on) {
  const h = p.health;
  return `<button type="button" class="prod ${on ? "on" : ""}" data-p="${esc(p.uid)}" aria-pressed="${on}">
    ${ring(h.ok, h.items)}
    <span class="prod-t"><b dir="auto">${esc(p.name)}</b><span class="prod-sub">${pnChip(p.pn)} ${sysBadge(p.source_kind, "")}</span>
      <span class="prod-n">${n0(h.items)} רכיבים · <b>${n0(h.attention)}</b> לטיפול</span></span></button>`;
}

function treeHtml(n, depth, path, ui) {
  const key = path ? `${path}>${n.uid}` : n.uid;
  const kids = n.children || [];
  const showKids = kids.filter((c) => ui.visible(c, `${key}>${c.uid}`));
  const exp = kids.length && ui.expanded.has(key);
  const flagged = n.flags.some(open);
  const match = ui.matches(n);
  const sev = n.flags.filter(open).some((f) => f.severity === "high") ? "att-high" : flagged ? "att" : "";
  return `<li role="treeitem" aria-level="${depth + 1}" ${kids.length ? `aria-expanded="${!!exp}"` : ""} aria-selected="${ui.sel === key}" data-key="${esc(key)}">
    <div class="trow ${sev} ${ui.sel === key ? "sel" : ""} ${ui.filtering && !match ? "dim" : ""}" tabindex="${ui.sel === key ? 0 : -1}">
      <span class="caret" aria-hidden="true">${kids.length ? (exp ? "▾" : "◂") : ""}</span>
      <span class="kind" title="${kindHe(n)}">${kindIcon(n)}</span>
      ${pnChip(n.pn, n.flags.some((f) => f.type === "duplicate" && f.stays))}
      <span class="tname">${esc(n.name)}</span>
      <span class="tmeta">${rev(n.revision)}<span class="sdot s-${n.state_class || "x"}" title="${esc(n.state || "")}"></span>
        <span class="qty">${qtyTxt(n.qty)}</span></span>
      <span class="tflags">${flagDots(n.flags)}</span></div>
    ${exp ? `<ul role="group">${showKids.map((c) => treeHtml(c, depth + 1, key, ui)).join("")}</ul>` : ""}</li>`;
}

function detailHtml(n, parentName, product) {
  const flags = n.flags;
  const e = n.erp;
  return `<div class="det-head">
      <span class="kind big">${kindIcon(n)}</span>
      <div><div class="row">${pnChip(n.pn, flags.some((f) => f.type === "duplicate" && f.stays))}${rev(n.revision)}${statePill(n.state_class, n.state)}</div>
        <h3>${esc(n.name)}</h3>
        <div class="small muted">${kindHe(n)}${n.spec ? ` · <span class="mono">${esc(n.spec)}</span>` : ""}${n.make_buy ? ` · ${n.make_buy === "buy" ? "נקנה מספק" : "מיוצר אצלכם"}` : ""}
          ${parentName ? ` · ${n.qty != null ? `${qtyTxt(n.qty)} ` : ""}בתוך ${esc(parentName)}` : ` · המוצר עצמו`}</div>
        <div class="small">${sysBadge(n.source_kind, n.source)}</div></div></div>
    <div class="det-erp">${e ? `<span class="small muted">${term("erp", "ב-ERP")}</span>${pnChip(e.pn)}
        <span>מלאי <b class="num">${n0(e.stock)}</b> ${esc(e.uom || "")}</span>${e.unit_cost != null ? `<span>עלות <b class="num">${money(e.unit_cost, e.currency || "ILS")}</b></span>` : ""}
        ${e.status ? `<span class="small muted">${esc(e.status)}</span>` : ""}`
      : `<span class="small muted">לא נמצא פריט ${term("erp", "ERP")} עם המק"ט הזה</span>`}</div>
    ${flags.length ? `<div class="det-flags">${flags.map((f) => flagCard(f, n)).join("")}</div>`
      : `<div class="det-ok">${ICON.check}<div><b>לא נמצא כאן שום דבר לטפל בו.</b><span>אין לרכיב הזה מק"ט נוסף, הנתונים שלו שלמים, והוא מתאים ל-ERP.</span></div></div>`}
    ${n.erp_bom ? `<button type="button" class="btn small" data-erpview>השוואת עץ המוצר של המכלול ל-ERP${n.erp_bom.has_erp_bom && n.erp_bom.differences ? ` (${n0(n.erp_bom.differences)} הבדלים)` : ""}</button>` : ""}
    <div class="det-more"><a class="btn ghost small" href="#/part/${encodeURIComponent(n.uid)}">לכרטיס החלק המלא</a>
      <span class="small muted" data-used>…</span></div>`;
}

// the product itself: how much of it is fine, what kinds of findings it has, and where to start
function summaryHtml(data, byKey) {
  const h = data.health, by = h.by_flag, max = Math.max(1, ...ORDER.map((k) => by[k]));
  const seen = new Set(), start = [];
  for (const [key, { n }] of byKey) {
    if (seen.has(n.uid) || key === data.tree.uid) continue;
    seen.add(n.uid);
    const hi = n.flags.filter(open).filter((f) => f.severity === "high");
    if (hi.length) start.push({ key, n, f: hi[0] });
  }
  return `<div class="det-sum">
    <div class="row" style="gap:14px">${ring(h.ok, h.items, 64)}<div><b>${n0(h.ok)} מתוך ${n0(h.items)} רכיבים תקינים</b>
      <div class="small muted">${n0(h.attention)} רכיבים צריכים טיפול. רכיב שמופיע בכמה מכלולים נספר פעם אחת.</div></div></div>
    <div class="sum-bars">${ORDER.map((k) => `<button type="button" class="sum-bar ${FLAG[k].cls}" data-f="${k}" ${by[k] ? "" : "disabled"}>
        <span class="fdot ${FLAG[k].cls}">${FLAG[k].icon}</span><span class="sb-l">${FLAG[k].he}</span>
        <span class="sb-t"><i style="width:${(100 * by[k]) / max}%"></i></span><b class="num">${n0(by[k])}</b></button>`).join("")}</div>
    ${h.erp_bom_differs || h.erp_bom_missing ? `<p class="small">${term("bom", "עצי מוצר")} מול ה-ERP: ${h.erp_bom_differs ? `<b>${n0(h.erp_bom_differs)}</b> מכלולים עם הבדלים` : ""}${h.erp_bom_differs && h.erp_bom_missing ? ", " : ""}${h.erp_bom_missing ? `<b>${n0(h.erp_bom_missing)}</b> בלי עץ מוצר ב-ERP` : ""}.</p>` : ""}
    ${start.length ? `<div class="sum-start"><b>מאיפה להתחיל</b>${start.slice(0, 4).map((x) => `<button type="button" class="link" data-go="${esc(x.key)}">
        <span class="fdot ${FLAG[x.f.type].cls}">${FLAG[x.f.type].icon}</span>${pnChip(x.n.pn)}<span>${esc(x.f.title)}</span></button>`).join("")}</div>` : ""}
  </div>`;
}

function flagCard(f, n) {
  if (f.type === "duplicate" && f.stays) {
    return `<div class="fcard f-stays"><div class="fc-h">${ICON.anchor}<b>${term("target", "זה המק\"ט שנשאר")}</b></div>
      <p>${esc(f.text)}</p><a class="small" href="#/group/${esc(f.group_id)}">לקבוצת הכפילות</a></div>`;
  }
  const F = FLAG[f.type];
  const link = f.type === "duplicate" ? `<a class="btn small" href="#/group/${esc(f.group_id)}">לקבוצת הכפילות ולהחלטה</a>`
    : f.type === "near" ? `<a class="btn small" href="#/part/${encodeURIComponent(n.uid)}">להשוואה עם החלקים הדומים</a>`
    : `<a class="btn small" href="#/${f.type === "erp" ? "erp" : "quality"}">לרשימת הממצאים</a>`;
  const termKey = { duplicate: "duplicate", state: "state", erp: "erpgap", quality: "quality", near: "near" }[f.type];
  return `<div class="fcard ${F.cls} sev-${f.severity}"><div class="fc-h">${F.icon}<b>${esc(f.title)}</b><span class="small muted">${term(termKey, F.he)}</span></div>
    <p>${esc(f.text)}</p>
    <dl><dt>למה זה חשוב</dt><dd>${F.why}</dd><dt>מה עושים</dt><dd>${F.todo}</dd></dl>${link}</div>`;
}

function erpHtml(n) {
  const cmp = n.erp_bom;
  if (!cmp) return '<div class="empty">לרכיב הזה אין עץ מוצר – הוא לא מכלול.</div>';
  const head = `<div class="row" style="margin-bottom:10px"><span class="kind">${ICON.asm}</span>${pnChip(n.pn)}<b>${esc(n.name)}</b>
    ${cmp.has_erp_bom ? `<span class="pill ${cmp.differences ? "warn" : "ok"}">${cmp.differences ? `${n0(cmp.differences)} הבדלים` : "זהה ל-ERP"}</span>` : ""}</div>`;
  if (!cmp.has_erp_bom) {
    return `${head}<div class="callout warn small"><b>למכלול הזה אין ${term("bom", "עץ מוצר")} ב-ERP${cmp.erp_parent ? ` (פריט ${esc(cmp.erp_parent)})` : ""}.</b>
      אם המכלול מיוצר או נקנה, הייצור לא יודע ממה להרכיב אותו. ${n.state_class === "released" ? "המכלול משוחרר בהנדסה – כדאי להקים לו עץ מוצר ב-ERP." : "המכלול עוד לא שוחרר, אז זה יכול להיות בסדר."}</div>
      <table class="t cmp"><thead><tr><th>רכיב ב-PDM</th><th class="n">כמות</th></tr></thead><tbody>
      ${cmp.rows.map((r) => `<tr><td>${pnChip(r.pn)} <span class="small">${esc(r.name)}</span></td><td class="n">${n0(r.pdm_qty)}</td></tr>`).join("")}</tbody></table>`;
  }
  return `${head}<div class="table-wrap"><table class="t cmp"><thead><tr><th>רכיב</th><th class="n">כמות ב-PDM</th><th class="n">כמות ב-ERP</th><th>מצב</th></tr></thead><tbody>
    ${cmp.rows.map((r) => {
      const [he, tone] = ERP_STATUS[r.status];
      return `<tr class="cmp-${r.status}"><td>${r.pn ? pnChip(r.pn) : ""}${r.erp_pn && r.erp_pn !== r.pn ? ` <span class="small muted">ב-ERP:</span> ${pnChip(r.erp_pn)}` : ""}
        <div class="small">${esc(r.name || "")}</div></td>
        <td class="n">${r.pdm_qty == null ? '<span class="muted">—</span>' : n0(r.pdm_qty)}</td>
        <td class="n">${r.erp_qty == null ? '<span class="muted">—</span>' : n0(r.erp_qty)}</td>
        <td><span class="pill ${tone}">${he}</span></td></tr>`;
    }).join("")}</tbody></table></div>
    <p class="small muted">השורות מותאמות לפי המק"ט (גם כשה-ERP כותב אותו עם נקודה במקום מקף). הייצור עובד לפי עץ המוצר של ה-ERP.</p>`;
}

export async function render({ el, setTitle, param, state }) {
  setTitle("בקרת תצורה", "ממה בנוי כל מוצר, ומה בו צריך טיפול");
  const rid = state.status.latest_run;
  const { products } = await get(`/api/runs/${rid}/products`);
  if (!products.length) {
    el.innerHTML = `<section class="panel"><div class="empty">בסריקה האחרונה לא נמצאו מוצרים עם ${term("bom", "עץ מוצר")}. בקרת תצורה צריכה מערכת PDM או PLM עם עצי מוצר.</div></section>`;
    return null;
  }
  const want = new URLSearchParams((location.hash.split("?")[1] || ""));
  let pid = param && products.some((p) => p.uid === param) ? param : products[0].uid;
  const ui = { expanded: new Set(), sel: null, filter: want.get("f") || "", q: "", view: "tree", filtering: false,
    visible: () => true, matches: () => true };
  let data = null;
  const byKey = new Map();

  el.innerHTML = `
    <section class="prods" role="group" aria-label="בחירת מוצר">${products.map((p) => productCard(p, p.uid === pid)).join("")}</section>
    <section class="cfg">
      <div class="panel cfg-main"><div class="panel-h"><h2 id="cfg-title"></h2><span class="sub" id="cfg-sub"></span></div>
        <div class="cfg-tools">
          <div class="seg" role="tablist" aria-label="תצוגה"><button type="button" role="tab" data-view="tree" aria-selected="true">${ICON.tree}${term("bom", "עץ המוצר")}</button>
            <button type="button" role="tab" data-view="erp" aria-selected="false">${ICON.erp}השוואה ל-ERP</button></div>
          <div class="fchips" id="fchips" role="group" aria-label="סינון לפי ממצא"></div>
          <input type="search" id="cfg-q" placeholder='חיפוש מק"ט או שם בעץ' aria-label="חיפוש בעץ המוצר">
          <button type="button" class="btn ghost small" id="cfg-exp">פתיחת הכול</button>
        </div>
        <div class="panel-b" id="cfg-body"></div></div>
      <aside class="panel cfg-det" id="cfg-det" aria-live="polite"></aside>
    </section>`;
  const body = el.querySelector("#cfg-body"), det = el.querySelector("#cfg-det");

  const walk = (n, key, parent, f) => { f(n, key, parent); (n.children || []).forEach((c) => walk(c, `${key}>${c.uid}`, n, f)); };
  const matchFn = () => {
    const q = ui.q.trim().toLowerCase();
    return (n) => (!ui.filter || (ui.filter === "any" ? n.flags.some(open) : n.flags.some((f) => f.type === ui.filter && open(f))))
      && (!q || (n.pn || "").toLowerCase().includes(q) || (n.name || "").toLowerCase().includes(q));
  };
  function applyFilter() {
    ui.filtering = !!(ui.filter || ui.q.trim());
    ui.matches = matchFn();
    if (!ui.filtering) { ui.visible = () => true; return; }
    const keep = new Set();
    walk(data.tree, data.tree.uid, null, (n, key) => {
      if (ui.matches(n)) {
        const parts = key.split(">");
        for (let i = 1; i <= parts.length; i++) keep.add(parts.slice(0, i).join(">"));
      }
    });
    ui.visible = (n, key) => keep.has(key);
    keep.forEach((k) => ui.expanded.add(k));                      // show every match
  }
  function chips() {
    const h = data.health, by = h.by_flag;
    el.querySelector("#fchips").innerHTML = [["", "הכול", null], ["any", "צריך טיפול", h.attention], ...ORDER.map((k) => [k, FLAG[k].he, by[k]])]
      .map(([k, l, c]) => `<button type="button" class="fchip ${k && k !== "any" ? FLAG[k].cls : ""}" data-f="${k}" aria-pressed="${ui.filter === k}" ${c === 0 ? "disabled" : ""}>
        ${k && k !== "any" ? FLAG[k].icon : ""}${l}${c != null ? `<span class="n">${n0(c)}</span>` : ""}</button>`).join("");
  }
  function paint() {
    if (ui.view === "tree") {
      const none = ui.filtering && ![...byKey.values()].some(({ n }) => ui.matches(n));
      body.innerHTML = `${none ? '<div class="empty">לא נמצאו רכיבים מתאימים בעץ הזה</div>' : `<ul class="tree" role="tree" aria-label="עץ המוצר">${treeHtml(data.tree, 0, "", ui)}</ul>`}
        <div class="legend tlegend"><span><span class="sdot s-released"></span>משוחרר</span><span><span class="sdot s-in_work"></span>בעבודה</span>
          <span><span class="sdot s-review"></span>בבדיקה</span><span><span class="sdot s-obsolete"></span>מבוטל</span>
          <span><span class="fdot f-stays">${ICON.anchor}</span>המק"ט שנשאר</span>${ORDER.map((k) => `<span><span class="fdot ${FLAG[k].cls}">${FLAG[k].icon}</span>${FLAG[k].he}</span>`).join("")}</div>`;
    } else {
      const k = ui.sel && byKey.get(ui.sel)?.n.erp_bom ? ui.sel : data.tree.uid;
      const asms = [];
      walk(data.tree, data.tree.uid, null, (n, key) => { if (n.erp_bom && !asms.some((a) => a.n.uid === n.uid)) asms.push({ n, key }); });
      body.innerHTML = `<div class="asm-pick" role="group" aria-label="בחירת מכלול">${asms.map(({ n, key }) => {
        const c = n.erp_bom, tone = !c.has_erp_bom ? "bad" : c.differences ? "warn" : "ok";
        return `<button type="button" class="asm-chip ${key === k ? "on" : ""}" data-k="${esc(key)}"><span class="sdot t-${tone}"></span>${esc(n.pn)}<span class="small">${esc(n.name)}</span></button>`;
      }).join("")}</div>${erpHtml(byKey.get(k).n)}`;
    }
  }
  function select(key, focus = false) {
    if (!byKey.has(key)) return;
    ui.sel = key;
    const { n, parent } = byKey.get(key);
    det.innerHTML = `<div class="panel-b">${key === data.tree.uid ? summaryHtml(data, byKey) : ""}${detailHtml(n, parent?.name, data.tree)}</div>`;
    det.querySelectorAll(".sum-bar").forEach((b) => (b.onclick = () => { ui.view = "tree"; ui.filter = b.dataset.f; chips(); applyFilter(); setView(); }));
    det.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => {
      b.dataset.go.split(">").forEach((_, i, a) => ui.expanded.add(a.slice(0, i).join(">") || a[0]));
      ui.view = "tree"; setView(); select(b.dataset.go, true);
    }));
    const eb = det.querySelector("[data-erpview]");
    if (eb) eb.onclick = () => { ui.view = "erp"; setView(); };
    usedElsewhere(n);
    paint();
    if (focus) body.querySelector(`li[data-key="${CSS.escape(key)}"] > .trow`)?.focus();
  }
  async function usedElsewhere(n) {
    const box = det.querySelector("[data-used]");
    try {
      const p = await get(`/api/runs/${rid}/parts/${encodeURIComponent(n.uid)}`);
      const others = (p.products || []).filter((x) => x.uid !== data.tree.uid);
      if (box && ui.sel && byKey.get(ui.sel)?.n.uid === n.uid) {
        box.innerHTML = n.uid === data.tree.uid ? "" : others.length
          ? `${term("whereused", "בשימוש")} גם ב: ${others.map((x) => `<a href="#/config/${encodeURIComponent(x.uid)}">${esc(x.name)}</a>`).join(", ")}`
          : `${term("whereused", "בשימוש")} רק במוצר הזה`;
      }
    } catch { if (box) box.textContent = ""; }
  }
  function setView() {
    el.querySelectorAll("[data-view]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.view === ui.view)));
    el.querySelector("#fchips").hidden = ui.view !== "tree";
    el.querySelector("#cfg-q").hidden = ui.view !== "tree";
    el.querySelector("#cfg-exp").hidden = ui.view !== "tree";
    paint();
  }
  async function load(uid) {
    pid = uid;
    el.querySelectorAll(".prod").forEach((b) => { b.classList.toggle("on", b.dataset.p === uid); b.setAttribute("aria-pressed", String(b.dataset.p === uid)); });
    body.innerHTML = '<div class="skeleton"><i></i><i></i></div>';
    data = await get(`/api/runs/${rid}/products/${encodeURIComponent(uid)}`);
    byKey.clear();
    walk(data.tree, data.tree.uid, null, (n, key, parent) => byKey.set(key, { n, parent }));
    ui.expanded = new Set([data.tree.uid]);
    (data.tree.children || []).forEach((c) => ui.expanded.add(`${data.tree.uid}>${c.uid}`));
    const h = data.health;
    el.querySelector("#cfg-title").innerHTML = `${esc(data.tree.name)} ${pnChip(data.tree.pn)}`;
    el.querySelector("#cfg-sub").innerHTML = `${n0(h.items)} רכיבים שונים ב-${n0(h.lines)} שורות · ${n0(h.ok)} תקינים · <b>${n0(h.attention)}</b> לטיפול`
      + (h.erp_bom_differs ? ` · ${n0(h.erp_bom_differs)} מכלולים שונים מה-ERP` : "") + (h.erp_bom_missing ? ` · ${n0(h.erp_bom_missing)} בלי עץ ב-ERP` : "");
    if (!isStatic) history.replaceState(null, "", `#/config/${encodeURIComponent(uid)}`);
    chips();
    applyFilter();
    const item = want.get("item");
    const first = item ? [...byKey.keys()].find((k) => byKey.get(k).n.uid === item) : null;
    if (first) first.split(">").forEach((_, i, a) => ui.expanded.add(a.slice(0, i + 1).join(">")));
    select(first || data.tree.uid);
    setView();
  }

  el.querySelector(".prods").addEventListener("click", (e) => { const b = e.target.closest(".prod"); if (b && b.dataset.p !== pid) load(b.dataset.p); });
  el.querySelectorAll("[data-view]").forEach((b) => (b.onclick = () => { ui.view = b.dataset.view; setView(); }));
  el.querySelector("#fchips").addEventListener("click", (e) => {
    const b = e.target.closest("[data-f]");
    if (!b || b.disabled) return;
    ui.filter = ui.filter === b.dataset.f ? "" : b.dataset.f;
    chips(); applyFilter(); paint();
  });
  el.querySelector("#cfg-q").addEventListener("input", debounce((e) => { ui.q = e.target.value; applyFilter(); paint(); }, 160));
  el.querySelector("#cfg-exp").onclick = (e) => {
    const all = ui.expanded.size >= byKey.size - 1;
    ui.expanded = all ? new Set([data.tree.uid]) : new Set(byKey.keys());
    e.target.textContent = all ? "פתיחת הכול" : "סגירת הכול";
    paint();
  };
  body.addEventListener("click", (e) => {
    const chip = e.target.closest(".asm-chip");
    if (chip) { select(chip.dataset.k); return; }
    if (e.target.closest(".term")) return;
    const li = e.target.closest("li[data-key]");
    if (!li) return;
    const key = li.dataset.key;
    if (e.target.closest(".caret")) { toggle(key); return; }
    if (ui.sel === key && byKey.get(key).n.children) toggle(key); else select(key);
  });
  const toggle = (key, refocus = false) => {
    if (ui.expanded.has(key)) ui.expanded.delete(key); else ui.expanded.add(key);
    paint();
    if (refocus) body.querySelector(`li[data-key="${CSS.escape(key)}"] > .trow`)?.focus();
  };
  // keyboard (the tree reads right to left): up / down move; left opens a closed item or steps into it, right closes
  // an open one or steps out to its parent; Enter or space opens and closes
  body.addEventListener("keydown", (e) => {
    const row = e.target.closest(".trow");
    if (!row) return;
    const rows = [...body.querySelectorAll(".trow")];
    const i = rows.indexOf(row), key = row.parentElement.dataset.key, kids = byKey.get(key).n.children;
    const move = (j) => { const r = rows[Math.max(0, Math.min(rows.length - 1, j))]; if (r) select(r.parentElement.dataset.key, true); };
    if (e.key === "ArrowDown") { e.preventDefault(); move(i + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); move(i - 1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); if (kids && !ui.expanded.has(key)) toggle(key, true); else if (kids) move(i + 1); }
    else if (e.key === "ArrowRight") {
      e.preventDefault();
      if (kids && ui.expanded.has(key)) toggle(key, true);
      else { const p = key.split(">").slice(0, -1).join(">"); if (p) select(p, true); }
    } else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); if (kids) toggle(key, true); }
  });
  await load(pid);
  return null;
}
