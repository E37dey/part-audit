// Learn as you go. Every key term can explain itself (a dotted underline; a click opens a short plain-Hebrew
// explanation with a small drawing), and "learning mode" adds to each screen a card that says what you see there
// and what to do with it. Both are for people who meet part numbers, BOMs and PDM / ERP for the first time.
import { art } from "./art.js";
import { esc } from "./util.js";

export const TERMS = {
  pn: { t: "מק\"ט", en: "Part number", art: "pn",
    text: "מספר הזהות של חלק – כמו תעודת זהות. לכל חלק שונה יש מק\"ט אחד, ואותו חלק בדיוק צריך לקבל את אותו מק\"ט בכל מערכת ובכל אתר. לפי המק\"ט קונים, מחזיקים מלאי ובונים עצי מוצר." },
  revision: { t: "רוויזיה", en: "Revision", art: "revision",
    text: "גרסה של אותו חלק. שינוי שלא פוגע בהחלפה (תיקון שרטוט, סבולת) מקבל אות חדשה – A, B, C – והמק\"ט נשאר. שינוי שבגללו החלק החדש כבר לא מחליף את הישן בכל מקום צריך מק\"ט חדש (הכלל: צורה, התאמה ותפקוד)." },
  state: { t: "מצב", en: "Lifecycle state", art: "state",
    text: "איפה החלק נמצא במחזור החיים: בעבודה, בבדיקה, משוחרר או מבוטל. רק חלק משוחרר מוכן לייצור ולרכש, וחלק מבוטל לא אמור להופיע במוצר פעיל." },
  bom: { t: "עץ מוצר", en: "BOM – bill of materials", art: "bom",
    text: "רשימת הרכיבים של מוצר או מכלול, עם הכמות של כל רכיב. מכלול מכיל חלקים ותתי-מכלולים – ולכן זה נראה כמו עץ. עץ המוצר קיים גם ב-PDM של ההנדסה וגם ב-ERP של הייצור, ושניהם צריכים להיות זהים." },
  assembly: { t: "מכלול", en: "Assembly", art: "bom",
    text: "פריט שבנוי מכמה חלקים, למשל יחידת הנעה או מסגרת. גם למכלול יש מק\"ט, גרסה ועץ מוצר משלו." },
  whereused: { t: "שימושים", en: "Where-used", art: "whereused",
    text: "הכיוון ההפוך של עץ המוצר: באילו מכלולים ומוצרים החלק נמצא. לפני כל שינוי בחלק בודקים את השימושים – הם מה שיושפע מהשינוי." },
  pdm: { t: "PDM / PLM", en: "Product data / lifecycle management", art: "systems",
    text: "המערכות של ההנדסה. PDM שומרת את קבצי התלת-ממד והשרטוטים עם הגרסאות שלהם (SOLIDWORKS PDM, Vault). PLM מנהלת את כל חיי המוצר, כולל תהליכי שינוי ואישורים (Windchill, Teamcenter)." },
  erp: { t: "ERP", en: "Enterprise resource planning", art: "systems",
    text: "המערכת של הרכש, המלאי, הייצור והכספים (Priority, SAP): כמה יש במחסן, כמה זה עולה וממי קונים. מה שמגיע לרצפת הייצור יוצא מה-ERP." },
  step: { t: "קובץ STEP", en: "STEP 3D file", art: "step",
    text: "פורמט תלת-ממד סטנדרטי שכל תוכנות ה-CAD קוראות. בעזרתו התוכנה משווה את הצורה של חלקים ממערכות שונות – גם כשהשם והמק\"ט שונים לגמרי." },
  duplicate: { t: "כפילות", en: "Duplicate", art: "duplicate",
    text: "אותו חלק בדיוק שנרשם תחת יותר ממק\"ט אחד – באתר אחר, במערכת אחרת או אצל מהנדס אחר. המחיר: קונים את אותו חלק כמה פעמים, המלאי מתפצל, ואי אפשר לדעת כמה באמת יש." },
  near: { t: "כמעט זהים", en: "Near-identical", art: "near",
    text: "שני חלקים שנראים כמעט אותו דבר, עם הבדל קטן – חור נוסף, אורך אחר. זו לא כפילות: לפני שמאחדים בודקים אם ההבדל חשוב. מפת הצבעים מראה בדיוק איפה הם שונים." },
  mirror: { t: "ימין / שמאל", en: "Mirror part", art: "mirror",
    text: "חלק שהוא תמונת מראה של חלק אחר, כמו כפפה ימנית ושמאלית. כל המידות שוות – אבל אי אפשר להחליף אחד בשני, ולכן אלה שני מק\"טים נכונים." },
  standard: { t: "חלק תקני", en: "Standard part", art: "standard",
    text: "חלק שהמידות שלו מוגדרות בתקן: בורג DIN 912 M10×25, מסב 6205-2RS. לכל מפרט צריך מק\"ט אחד בכל החברה; מק\"ט נוסף לאותו מפרט הוא כפילות גם בלי להשוות צורה." },
  target: { t: "המק\"ט שנשאר", en: "Target part number", art: "target",
    text: "כשמאחדים כפילות בוחרים מק\"ט אחד שנשאר. כל שאר המק\"טים מוחלפים בו בעצי המוצר, המלאי שלהם עובר אליו, ואותם מבטלים. התוכנה מציעה את המק\"ט עם הכי הרבה שימושים ומלאי – ההחלטה שלכם." },
  mapping: { t: "מיפוי", en: "Part number mapping", art: "mapping",
    text: "טבלה של \"מק\"ט ישן ← המק\"ט שנשאר\". ממנה יודעים מה להחליף בכל עץ מוצר ואיזה מלאי להעביר." },
  config: { t: "בקרת תצורה", en: "Configuration control", art: "config",
    text: "לדעת בכל רגע ממה בנוי כל מוצר – אילו חלקים, באיזו גרסה ובאיזה מצב – ושכל המערכות מסכימות על כך. וכל שינוי עובר בדרך מסודרת: מבקשים, בודקים את ההשפעה, מאשרים ומבצעים." },
  eco: { t: "חבילת שינוי", en: "Engineering change order (ECO)", art: "eco",
    text: "רשימה מסודרת של כל מה שמשנים בעקבות החלטה: אילו שורות בעצי המוצר, אילו מק\"טים מבטלים, איזה מלאי מעבירים – לכל מערכת בנפרד. אחרי אישור מבצעים אותה במערכות עצמן." },
  stock: { t: "שווי מלאי", en: "Stock value", art: "stock",
    text: "הכמות במחסן כפול העלות ליחידה, כפי שהן רשומות ב-ERP. \"מלאי במק\"טים הכפולים\" הוא שווי המלאי שרשום תחת המק\"טים שיוחלפו – כסף שמחכה לאיחוד." },
  quality: { t: "בעיית נתונים", en: "Data quality issue", art: "quality",
    text: "רשומה שחסר בה משהו או שיש בה סתירה: אין חומר, המשקל לא מתאים למודל, המק\"ט בשם הקובץ שונה מהמק\"ט ברשומה. זו לא כפילות – אבל זה גורם לטעויות ברכש ובייצור." },
  erpgap: { t: "פער מול ERP", en: "PDM / ERP mismatch", art: "erpgap",
    text: "ההנדסה וה-ERP לא מסכימים על אותו פריט: תיאור או חומר שונה, פריט משוחרר שלא הוקם ב-ERP, או עץ מוצר עם כמויות אחרות. הייצור עובד לפי ה-ERP – אז הפער מגיע לרצפה." },
  source: { t: "מקור נתונים", en: "Data source", art: "source",
    text: "מערכת שהתוכנה קוראת ממנה: PDM, PLM, ERP או תיקיית קבצים. התוכנה רק קוראת – היא לא משנה דבר באף מערכת." },
  makebuy: { t: "ייצור / קנייה", en: "Make or buy", art: "",
    text: "האם החלק מיוצר אצלכם לפי שרטוט, או נקנה מוכן מספק (כמו בורג או מסב)." },
};

// what each screen shows and what to do there (learning mode)
export const CARDS = {
  dashboard: { see: "המספרים הגדולים הם מה שנמצא בסריקה האחרונה: כמה חלקים רשומים יותר מפעם אחת, כמה מק\"טים מיותרים, וכמה כסף יושב במלאי שלהם. כל מספר לחיץ ומוביל לפירוט.",
    do: ["מתחילים בקבוצות עם המלאי הגדול (בטבלה)", "לכל קבוצה מחליטים: לאחד או לא", "אחרי הסריקה הבאה בודקים כאן מה השתנה"], terms: ["duplicate", "pn", "stock", "target"] },
  sources: { see: "כאן מחברים את המערכות שהתוכנה קוראת מהן: PDM או PLM של ההנדסה, ERP של הרכש והמלאי, או תיקיית קבצים.",
    do: ["\"הוסף מקור\" ובוחרים מערכת", "ממלאים כתובת ומשתמש עם הרשאת קריאה בלבד", "\"בדוק חיבור\", ואז \"סריקה חדשה\""], terms: ["source", "pdm", "erp", "step"] },
  groups: { see: "כל שורה היא חלק אחד שנמצא תחת כמה מק\"טים. המק\"ט המודגש בזהב הוא זה שמוצע להישאר; השאר יוחלפו בו.",
    do: ["פותחים קבוצה ורואים את החלקים זה לצד זה", "מאשרים או דוחים – אפשר גם כמה קבוצות ביחד", "קבוצות של חלקים תקניים הן בדרך כלל הקלות ביותר"], terms: ["duplicate", "target", "standard", "stock"] },
  group: { see: "חלק אחד, כמה מק\"טים. בציור: החלק באמצע וכל המק\"טים שלו מסביב. מתחת: התלת-ממד, השוואת הנתונים, איפה כל מק\"ט בשימוש ומה ישתנה אם תאשרו.",
    do: ["בודקים שהחלקים באמת זהים – בתלת-ממד ובטבלה", "בוחרים איזה מק\"ט נשאר – בלחיצה על הכרטיס שלו בציור", "מאשרים, או מסמנים \"לבדיקה\" אם לא בטוחים"], terms: ["duplicate", "target", "whereused", "revision"] },
  near: { see: "זוגות של חלקים כמעט זהים: אותה צורה כמעט, עם הבדל קטן. אולי אפשר להשתמש בחלק אחד במקום שניים – אבל רק אם ההבדל לא חשוב.",
    do: ["פותחים זוג ורואים במפת הצבעים איפה ההבדל", "מחליטים אם אפשר לתקנן לחלק אחד"], terms: ["near", "mirror", "step"] },
  pair: { see: "שני חלקים זה לצד זה. מפת הצבעים צובעת כל נקודה לפי המרחק שלה מהחלק השני: גוון אחד = זהה, צבע חזק = שונה.",
    do: ["מסובבים את המודל ומחפשים את האזור הצבוע", "בודקים בטבלה אם גם החומר והמידות זהים"], terms: ["near", "mirror", "step"] },
  names: { see: "שמות ומק\"טים שנראים כמו טעות או כפילות: אותו שם עם מק\"ט אחר, מק\"ט בפורמט חריג.", do: ["בודקים כל שורה מול השרטוט"], terms: ["pn", "quality"] },
  quality: { see: "רשומות עם מידע חסר או סותר: חלק בלי חומר, משקל שלא מתאים למודל, חלק מבוטל שעדיין בשימוש.",
    do: ["מתחילים מחומרה גבוהה", "מתקנים במערכת המקור ומסמנים \"לתקן\""], terms: ["quality", "state", "bom"] },
  erp: { see: "איפה ההנדסה וה-ERP לא מסכימים: פריט שהוקם רק באחת מהן, תיאור או חומר שונה, עץ מוצר עם כמויות אחרות.",
    do: ["מחליטים איזו מערכת צודקת", "מתקנים את השנייה"], terms: ["erpgap", "erp", "pdm", "bom"] },
  mapping: { see: "הטבלה הסופית: כל מק\"ט שיוחלף ← המק\"ט שנשאר. ממנה בונים את חבילת השינוי לכל מערכת.",
    do: ["עוברים על השורות ומאשרים", "בונים חבילת שינוי או מייצאים ל-Excel"], terms: ["mapping", "target", "eco"] },
  parts: { see: "כל הרשומות מכל המערכות במקום אחד. מחפשים לפי מק\"ט, שם או מפרט.", do: ["לוחצים על שורה לכרטיס החלק"], terms: ["pn", "source"] },
  part: { see: "כרטיס הזהות של רשומה אחת: המק\"ט, הגרסה והמצב, באילו מכלולים היא נמצאת וממה היא בנויה, ומה רשום עליה ב-ERP.",
    do: ["בודקים אם יש לה כפילות או חלקים דומים בצורה", "בודקים את השימושים לפני כל שינוי"], terms: ["pn", "revision", "state", "whereused", "bom"] },
  check: { see: "לפני שפותחים מק\"ט חדש: גוררים לכאן את קובץ ה-STEP של החלק, והתוכנה בודקת אם הוא כבר קיים באחת המערכות.",
    do: ["גוררים קובץ STEP (אפשר להוסיף את המק\"ט המתוכנן)", "אם החלק קיים – משתמשים במק\"ט הקיים"], terms: ["pn", "step", "duplicate"] },
  changes: { see: "מה השתנה מאז הסריקה הקודמת: כפילויות חדשות, כאלה שנפתרו, וממצאים שנוספו או תוקנו.", do: ["מטפלים קודם בכפילויות החדשות"], terms: ["duplicate", "quality"] },
  trends: { see: "המספרים של כל הסריקות לאורך זמן. קו שיורד בכפילויות ובבעיות = המצב משתפר.", do: ["מגדירים סריקה קבועה כדי לראות מגמה"], terms: ["duplicate", "quality"] },
  variety: { see: "כמה סוגים שונים של חלקים בשימוש: כמה מפרטים של ברגים, אומים ומסבים ותחת כמה מק\"טים. פחות מגוון = פחות מלאי ופחות טעויות.",
    do: ["מחפשים מפרטים עם יותר ממק\"ט אחד", "מחפשים מפרטים שכמעט לא בשימוש"], terms: ["standard", "pn"] },
  report: { see: "דוח של שני עמודים להנהלה, עם המספרים שנמדדו בלבד.", do: ["מדפיסים או שומרים כ-PDF מהדפדפן"], terms: ["duplicate", "stock"] },
  config: { see: "בקרת תצורה: בוחרים מוצר ורואים ממה הוא בנוי. ליד כל רכיב מסומן בצבע ובסמל אם יש בו משהו לטפל בו.",
    do: ["בוחרים מוצר מהכרטיסים", "לוחצים על רכיב – בצד מופיע הסבר מה הבעיה ומה עושים", "\"השוואה ל-ERP\" מראה שורה מול שורה איפה עץ המוצר שונה"], terms: ["config", "bom", "state", "erpgap"] },
  package: { see: "חבילת השינוי: מה צריך לשנות בכל מערכת כדי לבצע את ההחלטות שאושרו. התוכנה רק מכינה את הרשימה; את השינוי עושים במערכות עצמן.",
    do: ["בודקים את \"לפני ואחרי\" בכל עץ מוצר", "מייצאים ומעבירים לאחראי של כל מערכת"], terms: ["eco", "mapping", "bom", "target"] },
};

const KEY = "pa-learn", SEEN = "pa-learn-hidden";
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : v; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* this visit only */ } },
};
let hidden = new Set(store.get(SEEN, "").split(",").filter(Boolean));

export const learning = () => store.get(KEY, "on") === "on";
export function setLearning(on) {
  store.set(KEY, on ? "on" : "off");
  if (on) { hidden = new Set(); store.set(SEEN, ""); }
  document.body.classList.toggle("learn", on);
  window.dispatchEvent(new Event("pa-learn"));
}

/** A term that explains itself: a dotted underline, a click opens the explanation. */
export function term(key, label) {
  const d = TERMS[key];
  if (!d) return esc(label ?? key);
  return `<button type="button" class="term" data-term="${key}" aria-haspopup="dialog">${label ?? esc(d.t)}</button>`;
}

/** The learning card of a screen (shown in learning mode until the user hides it), or "". */
export function learnCard(page) {
  const c = CARDS[page];
  if (!c || !learning() || hidden.has(page)) return "";
  return `<aside class="learn-card" data-page="${page}" aria-label="הסבר על המסך">
    <div class="lc-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/></svg></div>
    <div class="lc-body"><p><b>מה רואים כאן?</b> ${c.see}</p>
      ${c.do?.length ? `<p class="lc-do"><b>מה עושים:</b> ${c.do.map((x) => `<span>${x}</span>`).join("")}</p>` : ""}
      ${c.terms?.length ? `<p class="lc-terms"><b>מונחים:</b> ${c.terms.map((k) => term(k)).join("")}</p>` : ""}</div>
    <button type="button" class="lc-x" data-hide-learn="${page}">הבנתי</button></aside>`;
}

// ---------------------------------------------------------------------------------------------- the popover
let pop = null, owner = null;

function close() {
  if (!pop) return;
  pop.remove();
  pop = null;
  if (owner) { owner.setAttribute("aria-expanded", "false"); owner = null; }
}

function open(btn) {
  const key = btn.dataset.term, d = TERMS[key];
  if (!d) return;
  if (owner === btn) { close(); return; }
  close();
  owner = btn;
  btn.setAttribute("aria-expanded", "true");
  pop = document.createElement("div");
  pop.className = "term-pop";
  pop.setAttribute("role", "dialog");
  pop.setAttribute("aria-label", d.t);
  pop.innerHTML = `${d.art ? `<div class="tp-art">${art(d.art)}</div>` : ""}
    <div class="tp-head"><b>${esc(d.t)}</b><span class="tp-en">${esc(d.en)}</span></div>
    <p>${d.text}</p>
    <div class="tp-foot"><a href="#/learn">איך כל זה מתחבר – בהדרכה</a><button type="button" class="btn ghost small" data-tp-close>סגירה</button></div>`;
  document.body.appendChild(pop);
  place(btn);
  pop.querySelector("[data-tp-close]").onclick = () => { const b = owner; close(); b?.focus(); };
  pop.querySelector("a").onclick = () => close();
}

function place(btn) {
  const r = btn.getBoundingClientRect(), w = Math.min(340, window.innerWidth - 24);
  pop.style.width = `${w}px`;
  if (window.innerWidth < 640) { pop.classList.add("sheet"); return; }       // phones: a sheet at the bottom
  const h = pop.offsetHeight;
  let top = r.bottom + 8 + window.scrollY;
  if (r.bottom + 8 + h > window.innerHeight && r.top - 8 - h > 0) top = r.top - 8 - h + window.scrollY;
  // RTL: align the popover's right edge with the term's right edge, inside the window
  let left = r.right - w + window.scrollX;
  left = Math.max(12 + window.scrollX, Math.min(left, window.scrollX + window.innerWidth - w - 12));
  pop.style.top = `${top}px`;
  pop.style.left = `${left}px`;
}

let ready = false;
/** Once per page load: term clicks, closing, hiding learning cards. */
export function initLearning() {
  document.body.classList.toggle("learn", learning());
  if (ready) return;
  ready = true;
  document.addEventListener("click", (e) => {
    const t = e.target.closest(".term");
    if (t) { e.preventDefault(); e.stopPropagation(); open(t); return; }
    const h = e.target.closest("[data-hide-learn]");
    if (h) {
      hidden.add(h.dataset.hideLearn);
      store.set(SEEN, [...hidden].join(","));
      h.closest(".learn-card")?.remove();
      return;
    }
    if (pop && !e.target.closest(".term-pop")) close();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && pop) { const b = owner; close(); b?.focus(); } });
  window.addEventListener("hashchange", close);
  window.addEventListener("resize", () => { if (pop && owner) place(owner); });
}
