// Everything known about one record: model, attributes, ERP, where it is used, history and findings.
import { get, binary } from "../api.js";
import { esc, n0, kg, money, date, sysBadge, statePill, pnChip, rev, mb, cm3, dims, catPill, sevPill, uidLink, confBar, shapeRows, ICON } from "../util.js";
import { term } from "../learn.js";
import { Viewer } from "../viewer3d.js";
import { modal } from "../ui.js";
import { compare3d } from "../compare3d.js";

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
      <div class="panel"><div class="panel-h"><h2>${term("erp", "ERP")}</h2>${e ? `<span class="sub">${pnChip(e.pn)}</span>` : ""}</div>
        <div class="panel-b">${e ? `<dl class="kv">${kv("תיאור", esc(e.description))}${kv("מלאי", `${n0(e.stock)} ${esc(e.uom || "")}`)}
          ${kv("עלות יחידה", money(e.unit_cost, e.currency || "ILS"))}${kv("שווי מלאי", e.unit_cost != null ? money(e.stock * e.unit_cost, e.currency || "ILS") : "")}
          ${kv("סטטוס", esc(e.status))}${kv("ספק", esc(e.supplier))}${kv("משפחה", esc(e.family))}</dl>`
          : '<div class="empty">לא נמצא פריט ERP עם המק"ט הזה</div>'}</div></div>
      <div class="panel"><div class="panel-h"><h2>${term("whereused", "איפה בשימוש")}</h2><span class="sub">${n0(p.parents.length + p.erp_parents.length)} שורות בעצי מוצר</span></div>
        <div class="table-wrap" style="max-height:320px"><table class="t"><thead><tr><th>מכלול</th><th>מערכת</th><th class="n">כמות</th></tr></thead><tbody>
          ${p.parents.map((x) => `<tr><td>${uidLink(x.uid, pnChip(x.pn))} <span class="small">${esc(x.name)}</span></td><td class="small">${esc(x.source)}</td><td class="n">${n0(x.qty)}</td></tr>`).join("")}
          ${p.erp_parents.map((x) => `<tr><td>${pnChip(x.parent)}</td><td>${sysBadge("ERP", "עץ מוצר ב-ERP")}</td><td class="n">${n0(x.qty)}</td></tr>`).join("")}
          ${p.parents.length + p.erp_parents.length ? "" : '<tr><td colspan="3" class="muted">לא נמצא בשימוש באף מכלול</td></tr>'}
        </tbody></table></div>
        ${p.products?.length ? `<div class="panel-b small"><b>מוצרים:</b> ${p.products.map((x) => uidLink(x.uid, `<span class="chip">${esc(x.pn || x.name)}</span>`)).join(" ")}
          <div style="margin-top:6px">${p.products.map((x) => `<a href="#/config/${encodeURIComponent(x.uid)}?item=${encodeURIComponent(p.uid)}"><span class="ic">${ICON.tree}</span> לראות את החלק בעץ של ${esc(x.name)}</a>`).join("<br>")}</div></div>` : ""}</div>
    </section>

    ${p.children?.length ? `<section class="panel"><div class="panel-h"><h2>${term("bom", "רכיבים")}</h2><span class="sub">${n0(p.children.length)} שורות</span></div>
      <div class="table-wrap"><table class="t"><thead><tr><th>מק"ט</th><th>שם</th><th>מצב</th><th class="n">כמות</th></tr></thead><tbody>
      ${p.children.map((c) => `<tr><td>${uidLink(c.uid, pnChip(c.pn))}</td><td>${esc(c.name)}${c.kind === "assembly" ? ' <span class="pill neutral plain">מכלול</span>' : ""}</td>
        <td>${statePill(c.state_class, c.state)}</td><td class="n">${n0(c.qty)}</td></tr>`).join("")}</tbody></table></div></section>` : ""}

    ${p.pairs?.length ? `<section class="panel"><div class="panel-h"><h2>רשומות קשורות</h2><span class="sub">חלקים שנמצאו דומים לחלק הזה</span></div>
      <div class="table-wrap"><table class="t"><thead><tr><th>חלק</th><th>מערכת</th><th>סוג</th><th>פירוט</th><th class="n">ביטחון</th><th></th></tr></thead><tbody>
      ${p.pairs.map((x) => `<tr><td>${uidLink(x.other.uid, pnChip(x.other.pn))} <span class="small">${esc(x.other.name)}</span></td><td>${sysBadge(x.other.source_kind, "")}</td>
        <td>${catPill(x.category)}</td><td class="small">${esc(x.reason_he)}</td><td class="n">${confBar(x.confidence)}</td>
        <td>${p.has_step && x.other.has_step ? `<a class="small nowrap" href="#/pair/${x.id}">השוואה</a>` : ""}</td></tr>`).join("")}</tbody></table></div></section>` : ""}

    ${p.has_step ? `<section class="panel" id="similar"><div class="panel-h"><h2>חלקים בצורה דומה</h2><span class="sub">חיפוש לפי צורה בכל המערכות, בלי קשר לשם או למק"ט</span></div>
      <div class="panel-b muted small">מחפש…</div></section>` : ""}

    ${p.issues?.length ? `<section class="panel"><div class="panel-h"><h2>ממצאים</h2></div>
      <div class="table-wrap"><table class="t"><thead><tr><th>חומרה</th><th>סוג</th><th>פירוט</th></tr></thead><tbody>
      ${p.issues.map((q) => `<tr><td>${sevPill(q.severity)}</td><td class="small">${esc(q.type_he)}</td><td>${esc(q.message)}</td></tr>`).join("")}</tbody></table></div></section>` : ""}

    <section class="grid grid-2">
      <div class="panel"><div class="panel-h"><h2>היסטוריית ${term("revision", "גרסאות")}</h2></div>
        ${p.history?.length ? `<div class="table-wrap"><table class="t"><thead><tr><th>גרסה</th><th>רוויזיה</th><th>תאריך</th><th>הערה</th></tr></thead><tbody>
          ${p.history.map((h) => `<tr><td class="num">${esc(h.version ?? "")}</td><td>${rev(h.revision)}</td><td>${date(h.date)}</td><td>${esc(h.comment || "")}</td></tr>`).join("")}</tbody></table></div>`
          : '<div class="panel-b muted small">המערכת לא החזירה היסטוריית גרסאות לרשומה הזו.</div>'}</div>
      <div class="panel"><div class="panel-h"><h2>כל המאפיינים מהמערכת</h2><span class="sub">כמו שהם, בלי עיבוד</span></div>
        ${Object.keys(p.props || {}).length ? `<div class="table-wrap" style="max-height:340px"><table class="t"><tbody>
          ${Object.entries(p.props).map(([k, v]) => `<tr><td><span class="mono small ltr">${esc(k)}</span></td><td class="small">${esc(typeof v === "object" && v ? (v.Display ?? JSON.stringify(v)) : v)}</td></tr>`).join("")}</tbody></table></div>`
          : '<div class="panel-b muted small">אין מאפיינים נוספים (למשל קובץ מתיקייה).</div>'}</div>
    </section>`;

  let v = null;
  const box = el.querySelector("#v3d");
  if (box) {
    v = new Viewer(box, { label: `${pnChip(p.pn)} ${sysBadge(p.source_kind, "")}` });
    v.loadUrl(`/api/mesh/latest/${encodeURIComponent(p.uid)}`);
  }
  const sim = el.querySelector("#similar");
  if (sim) {
    get(`/api/runs/latest/similar/${encodeURIComponent(p.uid)}`).then((r) => {
      if (!r.available || !r.rows.length) { sim.querySelector(".panel-b").textContent = "לא ניתן היה לחשב את הצורה של החלק הזה."; return; }
      sim.querySelector(".panel-b").outerHTML = `<div class="table-wrap"><table class="t"><thead><tr><th class="n">#</th><th>חלק</th><th>מידות ונפח</th><th>מה המנוע אומר</th><th>קרבה בצורה</th><th></th></tr></thead>
        <tbody>${shapeRows(r.rows, { action: '<button class="btn small" data-cmp>השוואה בתלת-ממד</button>' })}</tbody></table></div>
        <div class="panel-b small muted">הדירוג לפי פרופורציות המעטפת, כמה מהמעטפת החלק ממלא, סוגי המשטחים והתפלגות המרחקים על פני השטח – בלי תלות במיקום, בסיבוב ובגודל (חלקים בגודל דומה מקבלים עדיפות קטנה). הושווה מול ${n0(r.compared)} חלקים עם מודל. "אותה צורה" ו"כמעט זהה" הם ההחלטות של ההשוואה המלאה.</div>`;
      sim.querySelectorAll("tr[data-s]").forEach((tr) => (tr.onclick = (e) => {
        const row = r.rows[+tr.dataset.s];
        if (!e.target.closest("[data-cmp]")) { location.hash = `#/part/${encodeURIComponent(row.uid)}`; return; }
        compareModal(p, row.part);
      }));
    }).catch((e) => { sim.querySelector(".panel-b").textContent = e.message; });
  }
  return () => v && v.dispose();
}

function compareModal(a, b) {
  let dispose = null;
  const m = modal({ title: `${a.pn || a.name} מול ${b.pn || b.name}`, wide: true, body: '<div class="stack"><div class="row"><div class="seg" id="m-seg"></div></div><div id="m-c3"></div></div>',
    onClose: () => dispose && dispose() });
  dispose = compare3d(m.body.querySelector("#m-c3"), {
    labelA: `${pnChip(a.pn)} ${sysBadge(a.source_kind, "")}`, labelB: `${pnChip(b.pn)} ${sysBadge(b.source_kind, "")}`,
    overlayLabel: `<span class="pill neutral plain">אפור = ${esc(a.pn || "א")}</span> <span class="pill brass plain">זהב שקוף = ${esc(b.pn || "ב")}</span>`,
    seg: m.body.querySelector("#m-seg"),
    load: {
      meshA: () => binary(`/api/mesh/latest/${encodeURIComponent(a.uid)}`),
      meshB: () => binary(`/api/mesh/latest/${encodeURIComponent(b.uid)}`),
      align: () => get("/api/align/latest", { a: a.uid, b: b.uid }),
      compare: () => binary("/api/compare/latest", { a: a.uid, b: b.uid }),
    },
  });
}
