// Side-by-side attribute table for 2+ part records, with differences from the first column highlighted.
import { esc, n0, kg, date, money, sysBadge, statePill, pnChip, rev, mb, cm3, dims } from "./util.js";

const norm = (v) => String(v ?? "").trim().toLowerCase().replace(/\s+/g, " ");
const t = (v) => (v == null || v === "" ? '<span class="muted">—</span>' : esc(v));

// label, html(p), value(p) used for the comparison (numbers compared with a relative tolerance)
export const PART_ROWS = [
  { label: 'מק"ט', html: (p, m) => pnChip(p.pn, m), value: (p) => norm(p.pn) },
  { label: "מערכת", html: (p) => sysBadge(p.source_kind, p.source), value: (p) => p.source, same: true },
  { label: "שם", html: (p) => t(p.name), value: (p) => norm(p.name) },
  { label: "תיאור", html: (p) => t(p.description), value: (p) => norm(p.description) },
  { label: "רוויזיה / גרסה", html: (p) => `${rev(p.revision) || '<span class="muted">—</span>'}${p.version ? ` <span class="small muted">גרסה ${esc(p.version)}</span>` : ""}`, value: (p) => norm(p.revision), same: true },
  { label: "מצב", html: (p) => `${statePill(p.state_class, p.state)} <span class="small muted">${esc(p.state || "")}</span>`, value: (p) => p.state_class },
  { label: "מפרט תקני", html: (p) => (p.spec ? `<span class="mono small">${esc(p.spec)}</span>` : '<span class="muted">—</span>'), value: (p) => p.spec_key || norm(p.spec) },
  { label: "חומר", html: (p) => t(p.material), value: (p) => p.material_key || norm(p.material) },
  { label: "גימור", html: (p) => t(p.finish), value: (p) => p.finish_key || norm(p.finish) },
  { label: "משקל רשום", html: (p) => kg(p.mass_kg), value: (p) => p.mass_kg, tol: 0.05 },
  { label: "נפח (מחושב מהמודל)", html: (p) => cm3(p.volume_mm3), value: (p) => p.volume_mm3, tol: 0.02 },
  { label: "מידות מעטפת", html: (p) => dims(p.bbox), value: (p) => (p.bbox ? [...p.bbox].sort((a, b) => b - a)[0] : null), tol: 0.01 },
  { label: "מספר פאות במודל", html: (p) => n0(p.n_faces), value: (p) => p.n_faces, same: true },
  { label: "ייצור / קנייה", html: (p) => mb(p.make_buy), value: (p) => p.make_buy },
  { label: "קובץ", html: (p) => (p.native_file ? `<span class="mono small ltr">${esc(p.native_file)}</span>` : '<span class="muted">—</span>'), value: (p) => p.native_file, same: true },
  { label: "תיקייה", html: (p) => (p.folder ? `<span class="small ltr">${esc(p.folder)}</span>` : '<span class="muted">—</span>'), value: (p) => p.folder, same: true },
  { label: "תוכנת CAD", html: (p) => t(p.cad_app), value: (p) => p.cad_app, same: true },
  { label: "יוצר", html: (p) => t(p.author), value: (p) => p.author, same: true },
  { label: "עודכן", html: (p) => date(p.modified || p.created), value: (p) => p.modified, same: true },
  { label: "ERP – תיאור", html: (p) => t(p.erp?.description), value: (p) => norm(p.erp?.description), erp: true },
  { label: "ERP – מלאי", html: (p) => (p.erp ? `<span class="num">${n0(p.erp.stock)}</span> ${esc(p.erp.uom || "")}` : '<span class="muted">לא נמצא ב-ERP</span>'), value: (p) => p.erp?.stock, same: true, erp: true },
  { label: "ERP – עלות יחידה", html: (p) => (p.erp ? money(p.erp.unit_cost, p.erp.currency || "ILS") : '<span class="muted">—</span>'), value: (p) => p.erp?.unit_cost, tol: 0.1, erp: true },
  { label: "ERP – סטטוס", html: (p) => t(p.erp?.status), value: (p) => norm(p.erp?.status), erp: true },
  { label: "ERP – ספק", html: (p) => t(p.erp?.supplier), value: (p) => norm(p.erp?.supplier), erp: true },
  { label: "שימושים בעצי מוצר", html: (p) => n0(p.used_in), value: (p) => p.used_in, same: true },
];

function differs(row, a, b) {
  if (row.same) return false;            // informational rows are expected to differ
  const x = row.value(a), y = row.value(b);
  if (x == null || x === "" || y == null || y === "") return false;
  if (typeof x === "number" && typeof y === "number") {
    const tol = row.tol ?? 0;
    return Math.abs(x - y) > tol * Math.max(Math.abs(x), Math.abs(y), 1e-12);
  }
  return x !== y;
}

// parts[0] is the reference column (the proposed master); head(p, i) renders the column header
export function attrTable(parts, head, { masterUid = null } = {}) {
  const rows = PART_ROWS.filter((r) => parts.some((p) => { const v = r.value(p); return v != null && v !== "" && !(Array.isArray(v) && !v.length); }) || r.erp);
  return `<div class="table-wrap"><table class="t attr"><thead><tr><th style="width:150px"></th>${parts.map((p, i) => `<th>${head(p, i)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r) => `<tr><th scope="row">${r.label}</th>${parts.map((p, i) => {
      const d = i > 0 && differs(r, parts[0], p);
      return `<td class="${d ? "diff" : ""}"${d ? ' title="שונה מהעמודה הראשונה"' : ""}>${r.html(p, p.uid === masterUid)}</td>`;
    }).join("")}</tr>`).join("")}</tbody></table></div>
    <div class="legend" style="margin-top:8px"><span class="swatch" style="background:var(--warn-soft);border:1px solid var(--warn)"></span> שונה מהעמודה הראשונה</div>`;
}
