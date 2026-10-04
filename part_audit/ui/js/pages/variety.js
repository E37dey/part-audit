// Variety reduction: which standard parts and which part designs are in use, under how many part numbers, and how
// much each one is used. Counted from the last scan; the decisions stay with the engineers.
import { get } from "../api.js";
import { esc, n0, money, pnChip } from "../util.js";

const SCREWS = new Set(["shcs", "hex_screw", "csk", "set_screw", "set_screw_cup"]);
const num = (s) => parseFloat(String(s).replace(/[^0-9.]/g, "")) || 0;

function cell(label, value, note, tone = "") {
  return `<div class="cell ${tone}"><span class="r-label">${label}</span><span class="r-value">${value}</span><span class="r-note">${note}</span></div>`;
}

// screws: diameter x length, each cell the part numbers that carry it (more than one = a duplicate to merge)
function screwGrid(k) {
  const sizes = [...new Set(k.rows.map((r) => r.size))].sort((a, b) => num(a) - num(b));
  const lengths = [...new Set(k.rows.map((r) => r.length))].sort((a, b) => num(a) - num(b));
  const at = (s, l) => k.rows.filter((r) => r.size === s && r.length === l);
  return `<div class="table-wrap"><table class="t grid-map"><thead><tr><th>קוטר \\ אורך</th>${lengths.map((l) => `<th class="n">${esc(l)}</th>`).join("")}</tr></thead>
    <tbody>${sizes.map((s) => `<tr><th scope="row" class="mono">${esc(s)}</th>${lengths.map((l) => {
      const rs = at(s, l);
      if (!rs.length) return "<td></td>";
      const pns = rs.reduce((t, r) => t + r.pns.length, 0), used = rs.reduce((t, r) => t + r.used, 0);
      const tip = rs.map((r) => `${r.spec}: ${r.pns.join(", ")} · ${r.used} שימושים`).join("\n");
      return `<td class="${pns > rs.length ? "many" : ""} ${used ? "" : "unused"}" title="${esc(tip)}"><b>${pns}</b><span>${used ? `${used} שימושים` : "אין שימוש"}</span>${rs.length > 1 ? '<i title="יותר ממפרט אחד (דרגת חוזק או חומר)">+</i>' : ""}</td>`;
    }).join("")}</tr>`).join("")}</tbody></table></div>
    <div class="legend" style="margin-top:8px"><span><span class="swatch" style="background:var(--warn-soft);border:1px solid var(--warn)"></span> אותו מפרט תחת יותר ממק"ט אחד</span>
      <span><span class="swatch" style="background:var(--surface-3)"></span> לא נמצא בשום עץ מוצר</span><span>המספר: כמה מק"טים נושאים את המפרט</span></div>`;
}

function specTable(k, cur) {
  return `<div class="table-wrap"><table class="t"><thead><tr><th>מפרט</th><th>מק"טים</th><th>מערכות</th><th class="n">שימושים</th><th class="n">מלאי</th><th class="n">שווי מלאי</th><th></th></tr></thead>
    <tbody>${k.rows.map((r) => `<tr><td class="mono small">${esc(r.spec)}</td><td>${r.pns.map((p) => pnChip(p)).join(" ")}</td>
      <td class="small">${r.systems.map(esc).join("<br>")}</td><td class="n">${n0(r.used)}</td><td class="n">${n0(r.stock)}</td><td class="n">${money(r.value, cur)}</td>
      <td>${r.group_ids.length ? `<a class="small nowrap" href="#/group/${esc(r.group_ids[0])}">לקבוצת הכפילות</a>` : ""}</td></tr>`).join("")}</tbody></table></div>`;
}

function designTable(f, cur) {
  return `<div class="table-wrap"><table class="t"><thead><tr><th>דגם</th><th>מק"טים</th><th>מידות (מ"מ)</th><th>חומר</th><th class="n">שימושים</th><th class="n">מלאי</th><th class="n">שווי מלאי</th></tr></thead>
    <tbody>${f.rows.map((d) => `<tr class="click" data-h="${d.group_id ? `#/group/${esc(d.group_id)}` : `#/part/${encodeURIComponent(d.uid)}`}">
      <td>${esc(d.name)}${d.group_id ? ` <span class="pill dye plain">${n0(d.records)} רשומות – כפילות</span>` : ""}</td>
      <td>${d.pns.map((p) => pnChip(p)).join(" ") || '<span class="muted">—</span>'}</td>
      <td class="nowrap"><span class="mono small ltr">${d.size.length ? d.size.join(" × ") : "—"}</span></td><td class="small">${esc(d.materials.join(" / ") || "—")}</td>
      <td class="n">${d.used ? n0(d.used) : '<span class="muted">0</span>'}</td><td class="n">${n0(d.stock)}</td><td class="n">${money(d.value, cur)}</td></tr>`).join("")}</tbody></table></div>`;
}

export async function render({ el, setTitle, state }) {
  setTitle("צמצום מגוון", "כמה חלקים שונים בשימוש, וכמה כל אחד מהם בשימוש");
  const v = await get(`/api/runs/${state.status.latest_run}/variety`);
  const s = v.summary, cur = v.currency;
  el.innerHTML = `
    <section class="readout" style="--cells:4">
      ${cell("מפרטים תקניים בשימוש", n0(s.standard_specs), `נושאים ${n0(s.standard_pns)} מק"טים`)}
      ${cell("מק\"טים עודפים לחלקים תקניים", n0(s.standard_extra_pns), "יותר ממק\"ט אחד לאותו מפרט", s.standard_extra_pns ? "bad" : "")}
      ${cell("דגמים של חלקים מתוכננים", n0(s.designs), `ב-${n0(s.families)} משפחות, ${n0(s.design_records)} רשומות`)}
      ${cell("דגמים שלא בשום עץ מוצר", n0(s.designs_unused), "לא מופיעים בעץ מוצר ב-PDM או ב-ERP")}
    </section>

    <section class="panel"><div class="panel-h"><h2>חלקים תקניים לפי סוג</h2><span class="sub">לחיצה על שורה מציגה את המפרטים</span></div>
      <div class="table-wrap"><table class="t" id="kinds"><thead><tr><th>סוג</th><th class="n">מפרטים</th><th class="n">מק"טים</th><th class="n">מק"טים עודפים</th><th class="n">מפרטים בלי שימוש</th><th class="n">שימושים</th><th class="n">שווי מלאי</th></tr></thead>
        <tbody>${v.standard.map((k, i) => `<tr class="click" data-k="${i}"><td>${esc(k.kind_he)}</td><td class="n">${n0(k.specs)}</td><td class="n">${n0(k.pns)}</td>
          <td class="n">${k.extra_pns ? `<b class="d-bad">${n0(k.extra_pns)}</b>` : "0"}</td><td class="n">${n0(k.unused_specs)}</td><td class="n">${n0(k.used)}</td><td class="n">${money(k.value, cur)}</td></tr>`).join("")}</tbody></table></div>
      <div class="panel-b" id="kind-detail" hidden></div></section>

    <section class="panel"><div class="panel-h"><h2>חלקים מתוכננים לפי משפחה</h2><span class="sub">המשפחה נקבעת לפי שם החלק, בעברית ובאנגלית</span></div>
      <div class="table-wrap"><table class="t" id="fams"><thead><tr><th>משפחה</th><th class="n">רשומות</th><th class="n">דגמים</th><th class="n">מידות שונות</th><th class="n">חומרים</th><th class="n">דגמים בלי שימוש</th><th class="n">דגמים כפולים</th></tr></thead>
        <tbody>${v.families.map((f, i) => `<tr class="click" data-f="${i}"><td>${esc(f.family_he)}</td><td class="n">${n0(f.records)}</td><td class="n">${n0(f.designs)}</td>
          <td class="n">${n0(f.sizes)}</td><td class="n">${n0(f.materials)}</td><td class="n">${n0(f.unused)}</td><td class="n">${f.duplicated ? `<b class="d-bad">${n0(f.duplicated)}</b>` : "0"}</td></tr>`).join("")}</tbody></table></div>
      <div class="panel-b" id="fam-detail" hidden></div></section>

    <section class="panel"><div class="panel-b small muted stack">
      <p><b>איך לקרוא:</b> "מפרט" הוא חלק תקני מוגדר (למשל M6x20 DIN 912 12.9). "מק"טים עודפים" – כמה מק"טים יש מעבר לאחד לכל מפרט; אלה בדרך כלל כבר בקבוצות הכפילות. "דגם" הוא חלק מתוכנן; קבוצת כפילות נספרת כדגם אחד.</p>
      <p>"שימושים" הם שורות בעצי מוצר ב-PDM וב-ERP. חלק בלי שימוש יכול להיות חלק חילוף או פריט שמוזמן בנפרד – זה לא אומר שאפשר לבטל אותו. ההחלטה לצמצם מגוון היא הנדסית; המסך מראה רק מה נמדד.</p>
    </div></section>`;

  const show = (box, html, title) => {
    box.hidden = false;
    box.innerHTML = `<div class="row" style="margin-bottom:10px"><h3>${title}</h3><span style="flex:1"></span><button class="btn ghost small" data-x>סגירה</button></div>${html}`;
    box.querySelector("[data-x]").onclick = () => { box.hidden = true; box.closest("section").querySelectorAll("tr.sel").forEach((t) => t.classList.remove("sel")); };
    box.querySelectorAll("tr[data-h]").forEach((tr) => (tr.onclick = (e) => { if (!e.target.closest("a")) location.hash = tr.dataset.h; }));
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };
  el.querySelectorAll("#kinds tr[data-k]").forEach((tr) => (tr.onclick = () => {
    const k = v.standard[+tr.dataset.k];
    el.querySelectorAll("#kinds tr").forEach((t) => t.classList.toggle("sel", t === tr));
    show(el.querySelector("#kind-detail"), (SCREWS.has(k.kind) ? screwGrid(k) + '<div style="height:14px"></div>' : "") + specTable(k, cur),
      `${esc(k.kind_he)}: ${n0(k.specs)} מפרטים, ${n0(k.pns)} מק"טים`);
  }));
  el.querySelectorAll("#fams tr[data-f]").forEach((tr) => (tr.onclick = () => {
    const f = v.families[+tr.dataset.f];
    el.querySelectorAll("#fams tr").forEach((t) => t.classList.toggle("sel", t === tr));
    show(el.querySelector("#fam-detail"), designTable(f, cur), `${esc(f.family_he)}: ${n0(f.designs)} דגמים ב-${n0(f.sizes)} מידות`);
  }));
  return null;
}
