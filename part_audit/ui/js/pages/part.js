// Everything known about one record: model, attributes, ERP, where it is used, history and findings.
import { get } from "../api.js";
import { esc, n0, kg, money, date, sysBadge, statePill, pnChip, rev, mb, cm3, dims, catPill, sevPill, uidLink, confBar } from "../util.js";
import { Viewer } from "../viewer3d.js";

export async function render({ el, param, setTitle }) {
  const p = await get(`/api/runs/latest/parts/${encodeURIComponent(param)}`);
  setTitle(p.name || p.pn || "חלק", `<a href="#/parts">חיפוש חלקים</a> / ${esc(p.pn || p.uid)}`);
  const kv = (label, v) => (v == null || v === "" ? "" : `<dt>${label}</dt><dd>${v}</dd>`);
  const e = p.erp;
  const flags = [
    p.group_id ? `<a class="pill dye plain" href="#/group/${p.group_id}">בקבוצת כפילות – לקבוצה</a>` : "",
    p.near_count ? `<span class="pill brass plain">${n0(p.near_count)} חלקים כמעט זהים</span>` : "",
    p.issues?.length ? `<span class="pill warn plain">${n0(p.issues.length)} ממצאים</span>` : "",
  ].filter(Boolean).join(" ");

  el.innerHTML = `
    <section class="split">
      <div class="panel"><div class="panel-h"><h2>${pnChip(p.pn)} ${rev(p.revision)}</h2>${sysBadge(p.source_kind, p.source)}<span style="flex:1"></span>${statePill(p.state_class, p.state)}</div>
        <div class="panel-b">${p.has_step ? '<div id="v3d"></div>' : `<div class="empty">${p.kind === "assembly" ? "למכלול אין קובץ STEP בתוכנה – אפשר לפתוח כל רכיב ולראות אותו בתלת-ממד"
          : `אין קובץ STEP לרשומה הזו${p.step_note ? ` – ${esc(p.step_note)}` : ""}`}</div>`}
          ${flags ? `<div class="row" style="margin-top:12px">${flags}</div>` : ""}</div></div>
      <div class="panel"><div class="panel-h"><h2>נתונים הנדסיים</h2><span class="sub">כפי שנקראו מהמערכת</span></div>
        <div class="panel-b"><dl class="kv">
          ${kv("שם", esc(p.name))}${kv("תיאור", esc(p.description))}${kv("סוג", p.kind === "assembly" ? "מכלול" : "חלק")}
          ${kv("רוויזיה / גרסה", `${esc(p.revision || "—")}${p.version ? ` / ${esc(p.version)}` : ""}`)}${kv("מצב", `${statePill(p.state_class, p.state)} <span class="small muted">${esc(p.state)}</span>`)}
          ${kv("מפרט תקני", p.spec ? `<span class="mono">${esc(p.spec)}</span>` : "")}${kv("חומר", esc(p.material))}${kv("גימור", esc(p.finish))}
          ${kv("משקל רשום", p.mass_kg != null ? kg(p.mass_kg) : "")}${kv("ייצור / קנייה", p.make_buy ? mb(p.make_buy) : "")}
          ${kv("נפח (מחושב מהמודל)", p.volume_mm3 != null ? cm3(p.volume_mm3) : "")}${kv("מידות מעטפת", p.bbox ? dims(p.bbox) : "")}
          ${kv("פאות במודל", p.n_faces != null ? n0(p.n_faces) : "")}${kv("יחידות בקובץ STEP", esc(p.unit))}
          ${kv("קובץ", p.native_file ? `<span class="mono small ltr">${esc(p.native_file)}</span>` : "")}${kv("קובץ STEP", p.step_name ? `<span class="mono small ltr">${esc(p.step_name)}</span>` : "")}
          ${kv("תיקייה", p.folder ? `<span class="small ltr">${esc(p.folder)}</span>` : "")}${kv("תוכנת CAD", esc(p.cad_app))}
          ${kv("יוצר", esc(p.author))}${kv("נוצר", p.created ? date(p.created) : "")}${kv("עודכן", p.modified ? date(p.modified) : "")}
        </dl></div></div>
    </section>

    <section class="grid grid-2">
      <div class="panel"><div class="panel-h"><h2>ERP</h2>${e ? `<span class="sub">${pnChip(e.pn)}</span>` : ""}</div>
        <div class="panel-b">${e ? `<dl class="kv">${kv("תיאור", esc(e.description))}${kv("מלאי", `${n0(e.stock)} ${esc(e.uom || "")}`)}
          ${kv("עלות יחידה", money(e.unit_cost, e.currency || "ILS"))}${kv("שווי מלאי", e.unit_cost != null ? money(e.stock * e.unit_cost, e.currency || "ILS") : "")}
          ${kv("סטטוס", esc(e.status))}${kv("ספק", esc(e.supplier))}${kv("משפחה", esc(e.family))}</dl>`
          : '<div class="empty">לא נמצא פריט ERP עם המק"ט הזה</div>'}</div></div>
      <div class="panel"><div class="panel-h"><h2>איפה בשימוש</h2><span class="sub">${n0(p.parents.length + p.erp_parents.length)} שורות בעצי מוצר</span></div>
        <div class="table-wrap" style="max-height:320px"><table class="t"><thead><tr><th>מכלול</th><th>מערכת</th><th class="n">כמות</th></tr></thead><tbody>
          ${p.parents.map((x) => `<tr><td>${uidLink(x.uid, pnChip(x.pn))} <span class="small">${esc(x.name)}</span></td><td class="small">${esc(x.source)}</td><td class="n">${n0(x.qty)}</td></tr>`).join("")}
          ${p.erp_parents.map((x) => `<tr><td>${pnChip(x.parent)}</td><td>${sysBadge("ERP", "עץ מוצר ב-ERP")}</td><td class="n">${n0(x.qty)}</td></tr>`).join("")}
          ${p.parents.length + p.erp_parents.length ? "" : '<tr><td colspan="3" class="muted">לא נמצא בשימוש באף מכלול</td></tr>'}
        </tbody></table></div>
        ${p.products?.length ? `<div class="panel-b small"><b>מוצרים:</b> ${p.products.map((x) => uidLink(x.uid, `<span class="chip">${esc(x.pn || x.name)}</span>`)).join(" ")}</div>` : ""}</div>
    </section>

    ${p.children?.length ? `<section class="panel"><div class="panel-h"><h2>רכיבים</h2><span class="sub">${n0(p.children.length)} שורות</span></div>
      <div class="table-wrap"><table class="t"><thead><tr><th>מק"ט</th><th>שם</th><th>מצב</th><th class="n">כמות</th></tr></thead><tbody>
      ${p.children.map((c) => `<tr><td>${uidLink(c.uid, pnChip(c.pn))}</td><td>${esc(c.name)}${c.kind === "assembly" ? ' <span class="pill neutral plain">מכלול</span>' : ""}</td>
        <td>${statePill(c.state_class, c.state)}</td><td class="n">${n0(c.qty)}</td></tr>`).join("")}</tbody></table></div></section>` : ""}

    ${p.pairs?.length ? `<section class="panel"><div class="panel-h"><h2>רשומות קשורות</h2><span class="sub">חלקים שנמצאו דומים לחלק הזה</span></div>
      <div class="table-wrap"><table class="t"><thead><tr><th>חלק</th><th>מערכת</th><th>סוג</th><th>פירוט</th><th class="n">ביטחון</th><th></th></tr></thead><tbody>
      ${p.pairs.map((x) => `<tr><td>${uidLink(x.other.uid, pnChip(x.other.pn))} <span class="small">${esc(x.other.name)}</span></td><td>${sysBadge(x.other.source_kind, "")}</td>
        <td>${catPill(x.category)}</td><td class="small">${esc(x.reason_he)}</td><td class="n">${confBar(x.confidence)}</td>
        <td>${p.has_step && x.other.has_step ? `<a class="small nowrap" href="#/pair/${x.id}">השוואה</a>` : ""}</td></tr>`).join("")}</tbody></table></div></section>` : ""}

    ${p.issues?.length ? `<section class="panel"><div class="panel-h"><h2>ממצאים</h2></div>
      <div class="table-wrap"><table class="t"><thead><tr><th>חומרה</th><th>סוג</th><th>פירוט</th></tr></thead><tbody>
      ${p.issues.map((q) => `<tr><td>${sevPill(q.severity)}</td><td class="small">${esc(q.type_he)}</td><td>${esc(q.message)}</td></tr>`).join("")}</tbody></table></div></section>` : ""}

    <section class="grid grid-2">
      <div class="panel"><div class="panel-h"><h2>היסטוריית גרסאות</h2></div>
        ${p.history?.length ? `<div class="table-wrap"><table class="t"><thead><tr><th>גרסה</th><th>רוויזיה</th><th>תאריך</th><th>הערה</th></tr></thead><tbody>
          ${p.history.map((h) => `<tr><td class="num">${esc(h.version ?? "")}</td><td>${rev(h.revision)}</td><td>${date(h.date)}</td><td>${esc(h.comment || "")}</td></tr>`).join("")}</tbody></table></div>`
          : '<div class="panel-b muted small">המערכת לא החזירה היסטוריית גרסאות לרשומה הזו.</div>'}</div>
      <div class="panel"><div class="panel-h"><h2>כל המאפיינים מהמערכת</h2><span class="sub">כמו שהם, בלי עיבוד</span></div>
        ${Object.keys(p.props || {}).length ? `<div class="table-wrap" style="max-height:340px"><table class="t"><tbody>
          ${Object.entries(p.props).map(([k, v]) => `<tr><td class="mono small ltr">${esc(k)}</td><td class="small">${esc(typeof v === "object" && v ? (v.Display ?? JSON.stringify(v)) : v)}</td></tr>`).join("")}</tbody></table></div>`
          : '<div class="panel-b muted small">אין מאפיינים נוספים (למשל קובץ מתיקייה).</div>'}</div>
    </section>`;

  let v = null;
  const box = el.querySelector("#v3d");
  if (box) {
    v = new Viewer(box, { label: `${pnChip(p.pn)} ${sysBadge(p.source_kind, "")}` });
    v.loadUrl(`/api/mesh/latest/${encodeURIComponent(p.uid)}`);
  }
  return () => v && v.dispose();
}
