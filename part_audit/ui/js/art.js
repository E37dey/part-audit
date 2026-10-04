// Small line illustrations of the ideas behind the screens (part number, revision, BOM, duplicate ...), drawn in
// the app's own tokens so they work in both themes. Used by the term popovers and the "part numbers 101" page.
// Codes and numbers are drawn left to right; Hebrew labels are centered so their direction never matters.

const svg = (w, h, body, label) => `<svg class="art" viewBox="0 0 ${w} ${h}" role="img" aria-label="${label}">${body}</svg>`;
const code = (x, y, t, cls = "") => `<text x="${x}" y="${y}" class="code ${cls}" text-anchor="middle">${t}</text>`;
const he = (x, y, t, cls = "") => `<text x="${x}" y="${y}" class="he ${cls}" text-anchor="middle">${t}</text>`;
// a part number tag: the shape of a luggage tag, its hole on the side of the string
const tag = (x, y, t, cls = "", w = 74) => `<g class="tag ${cls}"><path d="M${x} ${y} l9 -11 h${w} v22 h-${w} z"/><circle cx="${x + 9}" cy="${y}" r="2.4"/>${code(x + 9 + w / 2, y + 4, t)}</g>`;
// a small bracket (the "part" of the drawings)
const part = (x, y, s = 1, cls = "") => `<g class="part ${cls}" transform="translate(${x} ${y}) scale(${s})"><path d="M0 26 h40 v-9 h-28 v-25 h-12 z"/><circle cx="6" cy="0" r="3"/><circle cx="30" cy="21.5" r="2.4"/></g>`;
const arrow = (d, cls = "") => `<path class="arw ${cls}" d="${d}" marker-end="url(#ah)"/>`;
const defs = `<defs><marker id="ah" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L8 4 L0 8 z" class="ahd"/></marker></defs>`;

export const ART = {
  pn: () => svg(240, 96, `${defs}${part(30, 44, 1.25)}<path class="string" d="M82 66 C 100 66, 104 48, 122 48"/>${tag(120, 48, "900-1289", "br", 92)}
    ${he(178, 84, "מספר הזהות של החלק")}`, "מק\"ט: תווית עם מספר שמחוברת לחלק"),

  revision: () => svg(240, 96, `${defs}${["A", "B", "C"].map((r, i) => `<g class="sheet ${i === 2 ? "br" : ""}" transform="translate(${26 + i * 72} 18)">
      <path d="M0 0 h38 l10 10 v40 h-48 z"/><path class="fold" d="M38 0 v10 h10"/>${part(9, 30, 0.62)}${code(24, 66, r, "big")}</g>`).join("")}
    ${arrow("M78 42 h18")}${arrow("M150 42 h18")}${he(120, 92, "אותו מק\"ט, גרסה חדשה")}`, "רוויזיות A, B, C של אותו מק\"ט"),

  state: () => svg(240, 96, `${[["בעבודה", "info"], ["בבדיקה", "warn"], ["משוחרר", "ok"], ["מבוטל", "bad"]].map(([t, c], i) => `
      <g class="st ${c}"><circle cx="${210 - i * 60}" cy="38" r="${c === "ok" ? 11 : 8}"/>${he(210 - i * 60, 72, t)}</g>`).join("")}
    <path class="rail" d="M30 38 H 210"/><path class="rail on" d="M90 38 H 210"/>
    ${he(120, 92, "רק חלק משוחרר נכנס לייצור ולרכש", "small")}`, "מחזור חיים: בעבודה, בבדיקה, משוחרר, מבוטל"),

  bom: () => svg(240, 104, `<g class="tree"><path d="M120 22 V34 M60 34 H180 M60 34 V44 M180 34 V44 M180 58 V66 M150 66 H210 M150 66 V74 M210 66 V74"/></g>
    <g class="node asm br"><rect x="88" y="6" width="64" height="18" rx="4"/>${he(120, 19, "מוצר")}</g>
    <g class="node asm"><rect x="32" y="44" width="56" height="16" rx="4"/>${he(60, 56, "מכלול")}</g>
    <g class="node asm"><rect x="152" y="44" width="56" height="16" rx="4"/>${he(180, 56, "מכלול")}</g>
    <g class="node"><rect x="128" y="74" width="44" height="16" rx="4"/>${code(150, 86, "×4")}</g>
    <g class="node"><rect x="188" y="74" width="44" height="16" rx="4"/>${code(210, 86, "×2")}</g>
    ${he(60, 84, "רכיבים + כמויות", "small")}`, "עץ מוצר: מוצר, מכלולים, חלקים וכמויות"),

  whereused: () => svg(240, 100, `${defs}<g class="node br"><rect x="96" y="70" width="48" height="18" rx="4"/>${code(120, 83, "900-1289")}</g>
    ${[40, 120, 200].map((x, i) => `<g class="node asm"><rect x="${x - 34}" y="10" width="68" height="18" rx="4"/>${he(x, 23, ["יחידת הנעה", "מסגרת", "רגל מסוע"][i])}</g>
      ${arrow(`M120 68 C 120 50, ${x} 46, ${x} 32`)}`).join("")}`, "שימושים: באילו מכלולים החלק נמצא"),

  systems: () => svg(240, 104, `${defs}<g class="box"><rect x="10" y="12" width="92" height="64" rx="8"/>${he(56, 30, "הנדסה")}${code(56, 46, "PDM / PLM", "dim")}
      ${part(38, 58, 0.5)}<text x="68" y="68" class="he small" text-anchor="middle">שרטוט</text></g>
    <g class="box"><rect x="138" y="12" width="92" height="64" rx="8"/>${he(184, 30, "רכש ומלאי")}${code(184, 46, "ERP", "dim")}
      <g class="shelf"><path d="M158 70 h52 M162 70 v-10 h12 v10 M178 70 v-10 h12 v10 M194 70 v-14 h12 v14"/></g></g>
    ${tag(72, 94, "900-1289", "br", 78)}${arrow("M102 44 C 116 44, 120 44, 136 44", "two")}`, "אותו מק\"ט בהנדסה וב-ERP"),

  duplicate: () => svg(240, 104, `${defs}${part(102, 56, 1.1)}
    ${tag(6, 22, "900-9077", "bad", 70)}${tag(160, 22, "N-STD-0961", "bad", 70)}${tag(6, 86, "0000024648", "bad", 70)}${tag(160, 86, "054408", "bad", 70)}
    <path class="string" d="M84 26 C 100 30, 104 40, 112 46 M156 26 C 140 30, 138 40, 132 46 M84 86 C 100 84, 104 80, 112 76 M156 86 C 140 84, 138 80, 134 76"/>`,
  "חלק אחד עם ארבעה מק\"טים"),

  near: () => svg(240, 96, `${part(36, 46, 1.4)}${part(150, 46, 1.4, "dy")}<circle class="hole" cx="${150 + 18 * 1.4}" cy="${46 + 21.5 * 1.4}" r="3.4"/>
    ${he(120, 50, "≈", "big")}${he(120, 90, "כמעט אותו דבר – הבדל קטן")}`, "שני חלקים כמעט זהים"),

  mirror: () => svg(240, 96, `<path class="mirror" d="M120 8 V 80"/>${part(52, 46, 1.4)}
    <g transform="translate(240 0) scale(-1 1)">${part(52, 46, 1.4, "dy")}</g>${he(66, 92, "שמאל")}${he(174, 92, "ימין")}`, "ימין ושמאל: תמונת מראה"),

  standard: () => svg(240, 96, `<g class="bolt"><path d="M40 30 h22 v36 h-22 z"/><path d="M62 40 h96 v16 h-96"/>
      ${Array.from({ length: 11 }, (_, i) => `<path d="M${76 + i * 8} 40 l4 16"/>`).join("")}<path class="hex" d="M44 36 h14 M44 60 h14"/></g>
    ${code(120, 84, "M10×25  DIN 912  12.9", "br")}${he(120, 18, "המפרט מוגדר בתקן")}`, "חלק תקני: בורג לפי DIN 912"),

  target: () => svg(240, 104, `${defs}${tag(8, 22, "900-9077", "", 70)}${tag(8, 56, "N-STD-0961", "", 70)}${tag(8, 90, "0000024648", "", 70)}
    ${arrow("M88 22 C 120 22, 130 50, 150 54")}${arrow("M88 56 H 150")}${arrow("M88 90 C 120 90, 130 62, 150 60")}
    ${tag(152, 57, "054408", "br", 70)}${he(196, 92, "נשאר", "small")}`, "כל המק\"טים מתאחדים למק\"ט אחד שנשאר"),

  mapping: () => svg(240, 96, `${defs}${[["900-9077", 22], ["N-STD-0961", 48], ["0000024648", 74]].map(([o, y]) => `
      <g class="row"><rect x="10" y="${y - 13}" width="220" height="20" rx="4"/>${code(62, y + 1, o, "dim strike")}${arrow(`M112 ${y - 3} H 140`)}${code(184, y + 1, "054408", "brt")}</g>`).join("")}`,
  "טבלת מיפוי: מק\"ט ישן ← מק\"ט שנשאר"),

  step: () => svg(240, 96, `<g class="cube"><path d="M96 30 l24 -12 l24 12 v28 l-24 12 l-24 -12 z"/><path d="M96 30 l24 12 l24 -12 M120 42 v28"/></g>
    ${code(120, 88, "part.step", "dim")}${he(46, 46, "SOLIDWORKS")}${he(194, 46, "Creo · NX")}`, "קובץ STEP: תלת-ממד שכל תוכנה קוראת"),

  eco: () => svg(240, 100, `<g class="sheet"><path d="M70 8 h100 v84 h-100 z"/><path class="clip" d="M104 4 h32 v10 h-32 z"/>
    ${[30, 50, 70].map((y, i) => `<path class="chk ${i < 2 ? "ok" : ""}" d="M82 ${y} h10 v10 h-10 z"/>${i < 2 ? `<path class="tick" d="M84 ${y + 5} l3 3 l5 -7"/>` : ""}<path class="lnx" d="M100 ${y + 5} h${56 - i * 8}"/>`).join("")}</g>
    ${he(200, 40, "מה לשנות")}${he(200, 58, "בכל מערכת")}`, "חבילת שינוי: רשימת פעולות לכל מערכת"),

  config: () => svg(240, 104, `<g class="tree"><path d="M40 20 V86 M40 42 H62 M40 64 H62 M40 86 H62 M84 64 V76 H104"/></g>
    <g class="node asm br"><rect x="16" y="6" width="58" height="16" rx="4"/>${he(45, 18, "מוצר")}</g>
    ${[[42, "ok"], [64, "ok"], [86, "bad"]].map(([y, c]) => `<g class="node"><rect x="62" y="${y - 8}" width="74" height="16" rx="4"/></g><circle class="st ${c}" cx="148" cy="${y}" r="5"/>`).join("")}
    <g class="node"><rect x="104" y="68" width="0" height="0"/></g>${he(196, 46, "כל רכיב נבדק")}${he(196, 66, "ומסומן בצבע", "small")}`,
  "בקרת תצורה: עץ מוצר שכל רכיב בו מסומן"),

  stock: () => svg(240, 96, `<g class="shelf big"><path d="M30 76 h120 M30 52 h120 M36 76 v-18 h22 v18 M62 76 v-18 h22 v18 M92 52 v-18 h22 v18 M118 52 v-14 h22 v14 M36 52 v-14 h22 v14"/></g>
    ${code(196, 46, "84 × ₪31.75", "dim")}${code(196, 70, "₪2,667", "br big")}`, "שווי מלאי: כמות כפול עלות"),

  quality: () => svg(240, 96, `<g class="card"><rect x="40" y="10" width="160" height="70" rx="8"/>
    ${[["חומר", "—", "bad"], ["משקל", "0.084 ק\"ג", ""], ["תיאור", "תושבת", ""]].map(([k, v, c], i) => `${he(170, 32 + i * 20, k, "dim")}<text x="70" y="${32 + i * 20}" class="he ${c}" text-anchor="middle">${v}</text>`).join("")}</g>`,
  "רשומה עם שדה חסר"),

  erpgap: () => svg(240, 96, `<g class="box"><rect x="10" y="14" width="96" height="60" rx="8"/>${code(58, 34, "PDM", "dim")}${he(58, 56, "פלדה 1045")}</g>
    <g class="box"><rect x="134" y="14" width="96" height="60" rx="8"/>${code(182, 34, "ERP", "dim")}${he(182, 56, "פלב\"מ 304", "bad")}</g>${he(120, 50, "≠", "big bad")}
    ${he(120, 90, "שתי המערכות לא מסכימות")}`, "פער בין PDM ל-ERP"),

  source: () => svg(240, 96, `${defs}${[["PDM", 30], ["PLM", 90], ["ERP", 150]].map(([t, x]) => `<g class="box"><rect x="${x - 22}" y="12" width="56" height="28" rx="6"/>${code(x + 6, 31, t)}</g>`).join("")}
    ${[36, 96, 156].map((x) => arrow(`M${x} 42 C ${x} 60, 196 56, 196 66`)).join("")}<g class="node br"><rect x="164" y="66" width="66" height="22" rx="5"/>${code(197, 81, "PartAudit")}</g>
    ${he(70, 80, "קריאה בלבד", "small")}`, "מקורות נתונים: התוכנה קוראת מכל מערכת"),
};

/** Part numbers converging into the one that stays (up to four old ones), for real part numbers. */
export function mergeArt(olds, target) {
  const xs = olds.slice(0, 4), h = 30 + xs.length * 32, mid = h / 2;
  const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  return svg(240, h + 14, `${defs}${xs.map((pn, i) => {
    const y = 22 + i * 32;
    return `${tag(8, y, esc(pn), "", 70)}${arrow(`M88 ${y} C 120 ${y}, 130 ${mid}, 150 ${mid}`)}`;
  }).join("")}${tag(152, mid, esc(target), "br", 70)}${he(196, mid + 26, "נשאר", "small")}`, "כל המק\"טים מתאחדים למק\"ט אחד שנשאר");
}

/** The illustration of an idea, or "" when there is none. */
export function art(key) {
  const f = ART[key];
  return f ? f() : "";
}
