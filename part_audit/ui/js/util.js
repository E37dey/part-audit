// Formatting, escaping and small shared view helpers (Hebrew locale).
const nf0 = new Intl.NumberFormat("he-IL", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("he-IL", { maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat("he-IL", { maximumFractionDigits: 2 });

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const n0 = (x) => (x == null || Number.isNaN(x) ? "—" : nf0.format(x));
export const n1 = (x) => (x == null || Number.isNaN(x) ? "—" : nf1.format(x));
export const n2 = (x) => (x == null || Number.isNaN(x) ? "—" : nf2.format(x));
export const money = (x, cur = "ILS") => (x == null ? "—" : (cur === "ILS" ? "₪" : cur + " ") + (Math.abs(x) < 100 && x % 1 !== 0 ? nf2 : nf0).format(x));
export const pct = (x, d = 1) => (x == null ? "—" : (100 * x).toFixed(x < 0.001 ? 3 : d) + "%");
export const mm = (x) => (x == null ? "—" : (x < 1 ? x.toFixed(2) : x < 10 ? x.toFixed(2) : x.toFixed(1)) + " מ\"מ");
export const kg = (x) => (x == null ? "—" : (x < 0.01 ? (x * 1000).toFixed(1) + " גרם" : x < 1 ? x.toFixed(3) + " ק\"ג" : x.toFixed(2) + " ק\"ג"));
export const date = (s) => {
  if (!s) return "—";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return esc(s);
  return d.toLocaleDateString("he-IL", { day: "2-digit", month: "2-digit", year: "numeric" });
};
export const datetime = (s) => {
  if (!s) return "—";
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? esc(s) : d.toLocaleString("he-IL", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
};

// systems: short code + color for the small badges
const SYS = {
  swpdm_web: ["SW", "#c8102e"], swpdm_com: ["SW", "#c8102e"], vault: ["AV", "#0696d7"], windchill: ["WC", "#3a8d3a"],
  teamcenter: ["TC", "#00557f"], folder: ["FS", "#6b7280"], priority: ["PR", "#5b3fb8"], sap_s4: ["S4", "#0a6ed1"],
  sap_b1: ["B1", "#0a6ed1"], erp_file: ["XL", "#1d6f42"], ERP: ["ERP", "#5b3fb8"],
};
export function sysBadge(kind, label) {
  const [code, color] = SYS[kind] || ["?", "#6b7280"];
  return `<span class="sys"><i style="background:${color}">${code}</i>${esc(label ?? "")}</span>`;
}
export function sysColor(kind) { return (SYS[kind] || ["", "#6b7280"])[1]; }
export function sysCode(kind) { return (SYS[kind] || ["?"])[0]; }

export const STATE = { released: ["משוחרר", "ok"], in_work: ["בעבודה", "info"], review: ["בבדיקה", "warn"], obsolete: ["מבוטל", "bad"], "": ["—", "neutral"] };
export function statePill(cls, label) {
  const [he, tone] = STATE[cls || ""] || STATE[""];
  return `<span class="pill ${tone}" title="${esc(label || "")}">${esc(he)}</span>`;
}
export const DECISION = { approve: ["אושר", "ok"], reject: ["נדחה", "bad"], review: ["לבדיקה", "warn"], ignore: ["התעלם", "neutral"], "": ["ממתין", "neutral"] };
export function decisionPill(d) {
  const [he, tone] = DECISION[d || ""] || DECISION[""];
  return `<span class="pill ${tone}">${he}</span>`;
}
export const SEVERITY = { high: ["גבוהה", "bad"], medium: ["בינונית", "warn"], low: ["נמוכה", "info"], info: ["מידע", "neutral"] };
export function sevPill(s) { const [he, tone] = SEVERITY[s] || SEVERITY.info; return `<span class="pill ${tone}">${he}</span>`; }
export const CATEGORY = {
  identical: ["כפילות – אותה גיאומטריה", "dye"], standard_part: ["אותו חלק תקני", "dye"],
  identical_attr_conflict: ["צורה זהה, מפרט שונה", "warn"], near_identical: ["כמעט זהים", "brass"],
  conflict: ["אותו מק\"ט – גיאומטריה שונה", "bad"], conflict_unverified: ["אותו מק\"ט בשתי רשומות", "warn"],
  name_similar: ["שמות דומים", "info"], mirror: ["ימין / שמאל", "info"],
};
export const GROUP_CAT = { standard: ["חלק תקני – אותו מפרט", "dye"], geometry: ["אותה גיאומטריה", "dye"] };
export function groupPill(c) { const [he, tone] = GROUP_CAT[c] || [c, "neutral"]; return `<span class="pill ${tone}">${esc(he)}</span>`; }
export function catPill(c) { const [he, tone] = CATEGORY[c] || [c, "neutral"]; return `<span class="pill ${tone}">${esc(he)}</span>`; }
export function pnChip(pn, master = false) {
  return pn ? `<span class="chip pn${master ? " master" : ""}"${master ? ' title="המק&quot;ט שנשאר"' : ""}>${esc(pn)}</span>` : `<span class="muted">ללא מק"ט</span>`;
}
export const rev = (r) => (r && r !== "-" ? `<span class="rev" title="רוויזיה">${esc(r)}</span>` : "");
export const cm3 = (v) => (v == null ? "—" : (v / 1000 < 10 ? (v / 1000).toFixed(2) : nf1.format(v / 1000)) + " סמ\"ק");
export const dims = (b) => (b && b.length === 3 ? `<span class="ltr num">${[...b].sort((x, y) => y - x).map((x) => (x < 10 ? x.toFixed(2) : x.toFixed(1))).join(" × ")}</span> מ"מ` : "—");
export const secs = (x) => (x == null ? "—" : x < 0.1 ? "פחות מ-0.1 ש'" : `${x < 10 ? x.toFixed(1) : Math.round(x)} ש'`);
export const mb = (x) => (x === "buy" ? "קנייה" : x === "make" ? "ייצור" : "—");
export function confBar(c) {
  if (c == null) return "—";
  const p = Math.round(c * 100);
  return `<span class="num" title="ציון ביטחון (ראיות, לא הסתברות)">${p}%</span>`;
}
export function uidLink(uid, text) { return `<a href="#/part/${encodeURIComponent(uid)}">${text}</a>`; }
export function qs(sel, root = document) { return root.querySelector(sel); }
export function qsa(sel, root = document) { return [...root.querySelectorAll(sel)]; }
export function debounce(fn, ms = 200) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

export const ICON = {
  anchor: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="5" r="2"/><path d="M12 7v14M8 10h8M4 13a8 8 0 0 0 16 0"/></svg>',
  learn: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-4.2 10.3c.8.8 1.2 1.6 1.2 2.7h6c0-1.1.4-1.9 1.2-2.7A6 6 0 0 0 12 3z"/></svg>',
  tree: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="9" y="3" width="6" height="5" rx="1"/><rect x="3" y="16" width="6" height="5" rx="1"/><rect x="15" y="16" width="6" height="5" rx="1"/><path d="M12 8v4M6 16v-4h12v4"/></svg>',
  eco: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V3h6v1M9 11l2 2 4-4M9 17h6"/></svg>',
  part: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/></svg>',
  asm: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M7 4l5 2.8v5.6L7 15.2 2 12.4V6.8z"/><path d="M17 8.8l5 2.8v5.6L17 20l-5-2.8v-5.6z"/></svg>',
  bolt: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M4 7h6v10H4z"/><path d="M10 9.5h10v5H10M13 9.5l1.5 5M16 9.5l1.5 5"/></svg>',
  dash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>',
  plug: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4"/></svg>',
  copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/></svg>',
  near: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="9" cy="12" r="5"/><circle cx="15" cy="12" r="5" stroke-dasharray="2 2"/></svg>',
  tag: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 12V4h8l10 10-8 8z"/><circle cx="7.5" cy="8.5" r="1.5"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M9 12l2 2 4-4"/><path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/></svg>',
  erp: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16M4 12h16M4 17h10"/><path d="M17 15l3 2-3 2"/></svg>',
  map: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M5 7h9l-3-3M19 17h-9l3 3"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>',
  gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/></svg>',
  book: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 5a2 2 0 0 1 2-2h14v16H6a2 2 0 0 0-2 2z"/><path d="M4 19V5"/></svg>',
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>',
  xls: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M9 13l4 5M13 13l-4 5"/></svg>',
  lock: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>',
  sun: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
  moon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/></svg>',
  next: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M14 6l-6 6 6 6"/></svg>',
  prev: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M10 6l6 6-6 6"/></svg>',
  inspect: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M19 10V7l-7-4-7 4v10l7 4 1.5-.9"/><path d="M5 7l7 4 7-4M12 11v4"/><circle cx="17.5" cy="16.5" r="3"/><path d="M19.7 18.7L22 21"/></svg>',
  upload: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M12 15V4M7.5 8.5L12 4l4.5 4.5"/><path d="M4 14v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4"/></svg>',
  stop: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/></svg>',
  caution: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3.5L2.5 20h19z"/><path d="M12 10v4.5M12 17.2v.3"/></svg>',
  go: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.8 2.8L16.5 9.5"/></svg>',
  mirror: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3v18" stroke-dasharray="2 2.5"/><path d="M9 7L4 17h5zM15 7l5 10h-5z"/></svg>',
  trend: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 20h18"/><path d="M4 15l5-5 4 3 7-7"/><path d="M15 6h5v5"/></svg>',
  variety: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><path d="M14.5 17.5h6M17.5 14.5v6"/></svg>',
  print: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M7 9V3h10v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M7 14h10v7H7z"/></svg>',
  report: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5"/><path d="M9.5 17.5v-3M12.5 17.5v-6M15.5 17.5v-4"/></svg>',
  delta: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 18h16L12 5z"/><path d="M12 10v4M12 16.5v.3"/></svg>',
  clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>',
};
export const LOGO = `<svg width="34" height="34" viewBox="0 0 32 32" aria-hidden="true"><rect x="0.5" y="0.5" width="31" height="31" rx="8" fill="#16202b" stroke="#ffffff" stroke-opacity="0.12"/>
  <path d="M9 23V9h8.6a5 5 0 0 1 0 10H13" stroke="#e2b45e" stroke-width="2.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="22.5" cy="22.5" r="2.2" fill="#5b8cff"/></svg>`;

// shape search: what the engine says about a similar shape (its own verdict when it has one)
export const SHAPE_REL = { same_group: ["אותו חלק – באותה קבוצת כפילות", "bad"], identical: ["אותה צורה", "bad"],
  standard_part: ["אותו חלק תקני", "bad"], near_identical: ["כמעט זהה", "warn"], mirror: ["תמונת מראה", "info"],
  identical_attr_conflict: ["אותה צורה, מפרט אחר", "warn"], conflict: ["אותו מק\"ט", "warn"], name_similar: ["צורה דומה", "neutral"],
  conflict_unverified: ["אותו מק\"ט", "warn"], similar: ["צורה דומה", "neutral"] };
// the bar is the same scale in every list: a full bar is the same shape, about half is "related", little is unrelated
export function shapeRows(rows, { action = "" } = {}) {
  return rows.map((r, i) => {
    const [he, tone] = SHAPE_REL[r.relation] || SHAPE_REL.similar;
    const w = Math.max(4, Math.round(100 * Math.max(0, 1 - r.distance / 2)));
    const p = r.part;
    return `<tr class="click" data-s="${i}"><td class="n">${i + 1}</td>
      <td>${pnChip(p.pn)} <span>${esc(p.name || "")}</span><div class="small" style="margin-top:3px">${sysBadge(p.source_kind, p.source)}</div></td>
      <td class="small">${dims(p.bbox)}${p.volume_mm3 != null ? `<div class="muted">${cm3(p.volume_mm3)}</div>` : ""}</td>
      <td><span class="pill ${tone} plain">${he}</span></td>
      <td style="min-width:110px"><div class="simbar" title="דירוג לפי מדד צורה יחסי – לא אחוז"><i style="width:${w}%"></i></div></td>
      <td>${action}</td></tr>`;
  }).join("");
}
