// "Part numbers - where to start": six short chapters that follow one real part of the latest scan through the
// factory's systems - its identity, its revisions and state, its record in the PDM and in the ERP, the BOMs it is
// in, its other part numbers, and how a duplicate is cleaned up. Everything shown is that part's real data.
import { get } from "../api.js";
import { esc, n0, money, pnChip, sysBadge, statePill, rev, date, ICON, STATE } from "../util.js";
import { term } from "../learn.js";
import { art, mergeArt } from "../art.js";
import { Viewer } from "../viewer3d.js";

const CHAPTERS = [["id", "תעודת זהות"], ["rev", "גרסה ומצב"], ["sys", "שתי מערכות"], ["bom", "עץ מוצר"], ["dup", "כפילות"], ["fix", "איך מתקנים"]];
const LIFE = [["in_work", "בעבודה"], ["review", "בבדיקה"], ["released", "משוחרר"], ["obsolete", "מבוטל"]];

const tagEl = (pn, cls = "") => `<span class="ptag ${cls}"><i aria-hidden="true"></i><span>${esc(pn)}</span></span>`;

function chapter(i, key, title, text, visual) {
  return `<section class="chap" id="ch-${key}" data-ch="${i}" aria-labelledby="h-${key}">
    <div class="chap-text"><span class="chap-n" aria-hidden="true">${i + 1}</span><h2 id="h-${key}">${title}</h2>${text}</div>
    <div class="chap-vis">${visual}</div></section>`;
}

// the identity card: each field numbered, its explanation next to it (hovering one lights the other)
function idCard(p) {
  const rows = [
    ["pn", "מק\"ט", pnChip(p.pn), `${term("pn", "המק\"ט")} – מספר הזהות. אותו חלק בדיוק = אותו מספר, בכל מערכת ובכל אתר.`],
    ["name", "שם", esc(p.name), "השם עוזר לאנשים, אבל שני אנשים יכתבו אותו אחרת. לכן סופרים ומזמינים לפי המק\"ט, לא לפי השם."],
    ["rev", "רוויזיה", rev(p.revision) || "—", `${term("revision", "הרוויזיה")} – הגרסה של החלק. שינוי קטן מעלה אות, והמק"ט נשאר.`],
    ["state", "מצב", statePill(p.state_class, p.state), `${term("state", "המצב")} – רק חלק משוחרר מוכן לייצור ולרכש.`],
    ["spec", p.spec ? "מפרט" : "חומר", p.spec ? `<span class="mono">${esc(p.spec)}</span>` : esc(p.material || "—"),
      p.spec ? `${term("standard", "חלק תקני")}: המידות שלו נקבעות בתקן, ולכן לכל מפרט צריך מק"ט אחד בלבד.` : "החומר נרשם ליד המק\"ט – ואם בשתי רשומות של אותו חלק כתוב חומר אחר, אחת מהן שגויה."],
    ["mb", "ייצור / קנייה", p.make_buy === "buy" ? "קנייה" : p.make_buy === "make" ? "ייצור" : "—",
      p.make_buy === "buy" ? "החלק נקנה מוכן מספק. מזמינים אותו לפי המק\"ט." : "החלק מיוצר אצלכם לפי שרטוט."],
    ["sys", "רשום ב", sysBadge(p.source_kind, p.source), `${term("pdm", "מערכת ההנדסה")} שבה החלק נוצר ונשמר, עם קובץ התלת-ממד שלו.`],
  ];
  return {
    card: `<div class="idcard" role="list">${tagEl(p.pn, "big")}${rows.map(([k, l, v], i) => `<div class="idrow" role="listitem" data-f="${k}">
        <span class="idn">${i + 1}</span><span class="idl">${l}</span><span class="idv">${v}</span></div>`).join("")}</div>`,
    notes: `<ol class="idnotes">${rows.map(([k, , , t]) => `<li data-f="${k}"><span>${t}</span></li>`).join("")}</ol>`,
  };
}

function revTimeline(p) {
  // the versions where the revision letter changed, and the latest one
  const all = p.history || [];
  const h = all.filter((x, i) => i === 0 || x.revision !== all[i - 1].revision);
  if (all.length && h.at(-1) !== all.at(-1)) h.push(all.at(-1));
  h.splice(0, Math.max(0, h.length - 4));
  const cur = p.state_class || "";
  const life = `<div class="life" role="img" aria-label="מחזור החיים, המצב הנוכחי: ${esc(STATE[cur]?.[0] || "")}">${LIFE.map(([k, l]) =>
    `<div class="life-st ${k} ${k === cur ? "on" : ""}"><i></i><span>${l}</span>${k === cur ? `<b>${esc(p.pn)} כאן</b>` : ""}</div>`).join("")}</div>`;
  if (!h.length) return `<div class="vis-card">${art("revision")}</div><div class="vis-card">${life}</div>`;
  return `<div class="vis-card"><div class="revline">${h.map((x, i) => `<div class="rv ${i === h.length - 1 ? "now" : ""}">
      <span class="rv-sheet">${esc(x.revision || "—")}</span><span class="rv-v">גרסה ${esc(x.version ?? i + 1)}</span>
      <span class="rv-d">${date(x.date)}</span><span class="rv-c">${esc(x.comment || "")}</span></div>`).join('<span class="rv-arrow" aria-hidden="true">←</span>')}</div>
    <p class="small muted">מתוך ${n0(all.length)} הגרסאות של ${esc(p.pn)} שהמערכת שלכם רשמה: הגרסאות שבהן הרוויזיה התחלפה, והאחרונה. המק"ט לא השתנה – רק האות.</p></div>
    <div class="vis-card">${life}</div>`;
}

function twoSystems(p) {
  const e = p.erp || {};
  const same = e.pn && e.pn.replace(/[^0-9A-Za-zא-ת]/g, "") === (p.pn || "").replace(/[^0-9A-Za-zא-ת]/g, "");
  return `<div class="twosys">
    <div class="sysbox"><div class="sb-h">${ICON.part}<b>הנדסה</b><span class="small muted">${term("pdm", "PDM / PLM")}</span></div>
      <div class="sb-r"><span>מערכת</span>${sysBadge(p.source_kind, p.source)}</div>
      <div class="sb-r"><span>קובץ</span><span class="mono small ltr">${esc(p.native_file || "—")}</span></div>
      <div class="sb-r"><span>רוויזיה</span>${rev(p.revision) || "—"}</div>
      <div class="sb-r"><span>תוכנת CAD</span><span>${esc(p.cad_app || "—")}</span></div>
      <div class="sb-r"><span>תלת-ממד</span><span>${p.has_step ? "יש מודל STEP" : "אין מודל"}</span></div></div>
    <div class="sys-link" aria-hidden="true"><svg viewBox="0 0 120 40" preserveAspectRatio="none"><path d="M0 20 H120"/></svg>${tagEl(p.pn)}</div>
    <div class="sysbox"><div class="sb-h">${ICON.erp}<b>רכש ומלאי</b><span class="small muted">${term("erp", "ERP")}</span></div>
      ${p.erp ? `<div class="sb-r"><span>פריט</span>${pnChip(e.pn)}</div>
      <div class="sb-r"><span>תיאור</span><span>${esc(e.description || "—")}</span></div>
      <div class="sb-r"><span>במחסן</span><b class="num">${n0(e.stock)} ${esc(e.uom || "")}</b></div>
      <div class="sb-r"><span>עלות ליחידה</span><span class="num">${money(e.unit_cost, e.currency || "ILS")}</span></div>
      <div class="sb-r"><span>ספק</span><span>${esc(e.supplier || "—")}</span></div>` : '<div class="empty small">לחלק הזה אין פריט ב-ERP</div>'}</div></div>
    ${p.erp && !same ? `<p class="small muted">שימו לב: ב-ERP המספר כתוב ${esc(e.pn)}. התוכנה יודעת לזהות שזה אותו מק"ט.</p>` : ""}`;
}

// the product's BOM with every occurrence of the part marked, and how many of it go into one product
function bomVisual(tree, p) {
  if (!tree) return `<div class="vis-card">${art("bom")}</div>`;
  let total = 0;
  const lines = [];
  const walk = (n, mult, path) => {
    if (n.uid === p.uid) { total += mult; lines.push(path.concat(n)); }
    (n.children || []).forEach((c) => walk(c, mult * (c.qty || 1), path.concat(n)));
  };
  walk(tree, 1, []);
  const hasPart = (n) => n.uid === p.uid || (n.children || []).some(hasPart);
  const node = (n, depth) => {
    const kids = n.children || [];
    const mine = n.uid === p.uid;
    const show = depth < 1 || hasPart(n);
    return `<li class="${mine ? "mine" : ""} ${hasPart(n) && !mine ? "path" : ""}"><div class="lt-row">${n.kind === "assembly" ? ICON.asm : ICON.part}
        ${pnChip(n.pn, mine)}<span class="lt-name">${esc(n.name)}</span>${n.qty != null ? `<span class="qty">×${n0(n.qty)}</span>` : ""}</div>
      ${kids.length && show ? `<ul>${kids.filter((c) => depth < 1 || hasPart(c) || c.uid === p.uid).map((c) => node(c, depth + 1)).join("")}
        ${kids.length > kids.filter((c) => depth < 1 || hasPart(c)).length ? `<li class="more">ועוד ${n0(kids.length - kids.filter((c) => depth < 1 || hasPart(c)).length)} רכיבים</li>` : ""}</ul>` : ""}</li>`;
  };
  return `<div class="vis-card"><ul class="ltree">${node(tree, 0)}</ul></div>
    <div class="vis-card sum">${lines.length ? `<b>${esc(tree.name)}</b> צריך <b class="num">${n0(total)}</b> יחידות של ${pnChip(p.pn)}:
      <ul class="rollup">${lines.map((l) => `<li>${l.slice(1).map((n) => `${esc(n.name)} ×${n0(n.qty)}`).join(" ← ")}</li>`).join("")}</ul>
      <span class="small muted">כופלים את הכמויות לאורך הענף: כך מחשב ה-ERP כמה לקנות לכל מוצר.</span>` : ""}</div>`;
}

function constellation(g, part) {
  const members = g.parts.filter((x) => x.pn);
  const seen = new Set();
  const uniq = members.filter((x) => { const k = x.pn; if (seen.has(k)) return false; seen.add(k); return true; });
  const stock = g.erp.reduce((t, e) => t + (e.stock || 0), 0);
  const cur = g.currency || "ILS";
  const stay = g.final_master_pn || g.master_pn;
  // the part in the middle, its part numbers on a circle around it (the first one on top)
  const at = uniq.map((_, i) => { const a = -Math.PI / 2 + (2 * Math.PI * i) / uniq.length; return [50 + 33 * Math.cos(a), 50 + 38 * Math.sin(a)]; });
  return `<div class="vis-card">
    <div class="constel">
      <svg class="c-lines" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">${at.map(([x, y]) => `<line x1="50" y1="50" x2="${x}" y2="${y}"/>`).join("")}</svg>
      <div class="c-center"><div id="dup3d" class="mini3d"></div></div>
      ${uniq.map((x, i) => `<div class="c-tag" style="left:${at[i][0]}%;top:${at[i][1]}%">${tagEl(x.pn, `${x.pn === stay ? "stay" : ""} ${x.uid === part.uid ? "me" : ""}`)}
        <span class="c-src">${sysBadge(x.source_kind, "")}<span class="small">${esc(x.source)}</span></span>${x.erp ? `<span class="small muted">${n0(x.erp.stock)} ${esc(x.erp.uom || "")} במלאי</span>` : ""}</div>`).join("")}
    </div>
    <div class="legend" style="margin-top:6px"><span>${tagEl("", "stay mini")} המק"ט שמוצע להישאר</span>${uniq.some((x) => x.uid === part.uid) ? `<span>${tagEl("", "me mini")} החלק שעקבנו אחריו</span>` : ""}</div></div>
    <div class="vis-card sum"><b>${n0(uniq.length)} מק"טים</b> לאותו חלק, ב-${n0(new Set(members.map((x) => x.source)).size)} מערכות ·
      <b class="num">${n0(stock)}</b> יחידות במלאי, בשווי <b class="num">${money(g.stock_value, cur)}</b>, מפוזרות ב-${n0(g.erp.length)} פריטי ERP.
      ${g.spec ? `<div class="small muted" style="margin-top:6px">איך יודעים שזה אותו חלק? המפרט זהה – <span class="mono">${esc(g.spec)}</span> – והצורה בתלת-ממד זהה.</div>` : ""}</div>`;
}

function fixFlow(c, ex, g) {
  const steps = [
    ["מוצאים", "הסריקה משווה כל חלק לכל חלק, בכל המערכות", `${n0(c.groups)} חלקים עם יותר ממק"ט אחד`, "#/groups"],
    ["בודקים", "רואים את החלקים זה לצד זה בתלת-ממד, עם כל הנתונים", ex.group_id ? "לדוגמה: הקבוצה של החלק שלנו" : "", ex.group_id ? `#/group/${encodeURIComponent(ex.group_id)}` : "#/groups"],
    ["מחליטים", "בוחרים איזה מק\"ט נשאר – ומאשרים", `${n0(c.approved_groups)} אושרו עד עכשיו`, "#/groups"],
    ["ממפים", "כל מק\"ט שיוחלף ← המק\"ט שנשאר", `${n0(c.redundant_pns)} מק"טים יוחלפו`, "#/mapping"],
    ["מבצעים", "חבילת שינוי לכל מערכת: עצי מוצר, מלאי, ביטול", "התוכנה מכינה, אתם מבצעים", "#/package"],
  ];
  return `<ol class="flow">${steps.map(([t, d, n, h], i) => `<li><a href="${h}"><span class="fl-n">${i + 1}</span><span class="fl-t"><b>${t}</b><span>${d}</span></span>${n ? `<em>${n}</em>` : ""}</a></li>`).join("")}</ol>
    <div class="vis-card merge" id="merge">${g ? mergeArt([...new Set(g.pns)].filter((x) => x !== (g.final_master_pn || g.master_pn)), g.final_master_pn || g.master_pn) : art("target")}</div>`;
}

export async function render({ el, setTitle, state }) {
  setTitle("מק\"ט – מאיפה מתחילים", "הדרכה קצרה על חלק אמיתי מהסריקה שלכם");
  const ex = state.status?.latest_run ? await get("/api/learn").catch(() => ({ available: false })) : { available: false };
  let p = null, g = null, tree = null;
  if (ex.available) {
    [p, g, tree] = await Promise.all([
      ex.part_uid ? get(`/api/runs/latest/parts/${encodeURIComponent(ex.part_uid)}`).catch(() => null) : null,
      ex.group_id ? get(`/api/runs/latest/groups/${encodeURIComponent(ex.group_id)}`).catch(() => null) : null,
      ex.product_uid ? get(`/api/runs/latest/products/${encodeURIComponent(ex.product_uid)}`).then((x) => x.tree).catch(() => null) : null,
    ]);
  }
  const c = ex.counts || {};
  if (!p) {
    // before the first scan: the same story with drawings instead of your data
    el.innerHTML = `<div class="primer">
      <header class="lhero"><div class="lh-text"><h1>מק"ט – מאיפה מתחילים</h1>
        <p class="lead">במפעל יש אלפי חלקים, וכל אחד מהם צריך שם אחד שכולם מבינים: מספר. אחרי הסריקה הראשונה ההדרכה הזו תעבור על חלק אמיתי שלכם; בינתיים – הרעיונות בציורים.</p></div>
        <div class="lh-vis">${art("pn")}</div></header>
      ${[["pn", "revision", "state"], ["systems", "bom", "whereused"], ["duplicate", "target", "eco"]].map((row) => `<div class="art-row">${row.map((k) =>
        `<figure class="vis-card">${art(k)}<figcaption>${term(k === "systems" ? "pdm" : k)}</figcaption></figure>`).join("")}</div>`).join("")}
    </div>`;
    return null;
  }
  const id = idCard(p);
  const cur = g?.currency || c.currency || "ILS";
  el.innerHTML = `<div class="primer">
    <header class="lhero">
      <div class="lh-text"><h1>מק"ט – מאיפה מתחילים</h1>
        <p class="lead">במפעל יש אלפי חלקים, וכל אחד מהם צריך שם אחד שכולם מבינים: מספר. נעקוב אחרי חלק אמיתי מהסריקה שלכם –
          <b>${esc(p.name)}</b> – ונראה מה המספר שלו אומר, איפה הוא רשום, ומה קורה כשלאותו חלק יש כמה מספרים.</p>
        <p class="lh-facts"><span><b class="num">${n0(c.parts)}</b> חלקים בסריקה</span><span><b class="num">${n0(c.products)}</b> מוצרים</span>
          <span><b class="num">${n0(c.groups)}</b> חלקים עם יותר ממק"ט אחד</span></p>
        <a class="btn primary" href="#/learn" data-jump="id">מתחילים ${ICON.next || ""}</a></div>
      <div class="lh-vis"><div id="hero3d" class="hero3d"></div>${tagEl(p.pn, "big hero-tag")}</div>
    </header>
    <nav class="chap-nav" aria-label="פרקי ההדרכה">${CHAPTERS.map(([k, t], i) => `<button type="button" data-jump="${k}" data-i="${i}"><span>${i + 1}</span>${t}</button>`).join("")}</nav>

    ${chapter(0, "id", "תעודת הזהות של החלק", `<p>לכל חלק יש רשומה עם כמה שדות קבועים. החשוב מכולם הוא ${term("pn", "המק\"ט")}: לפיו קונים, סופרים מלאי ומרכיבים. כל השאר מתארים את החלק.</p>${id.notes}`, id.card)}

    ${chapter(1, "rev", "גרסה ומצב", `<p>חלקים משתנים עם הזמן. שינוי שלא פוגע בהחלפה – תיקון שרטוט, סבולת – מקבל ${term("revision", "רוויזיה")} חדשה, והמק"ט נשאר.
        שינוי שבגללו החלק החדש כבר לא יכול להחליף את הישן בכל מקום – מקבל מק"ט חדש.</p>
      <p>במקביל, לכל חלק יש ${term("state", "מצב")}: בעבודה, בבדיקה, משוחרר, מבוטל. ${esc(p.pn)} נמצא עכשיו במצב <b>${esc(STATE[p.state_class || ""]?.[0] || p.state || "")}</b>.</p>`, revTimeline(p))}

    ${chapter(2, "sys", "אותו מספר, שתי מערכות", `<p>ההנדסה עובדת ב-${term("pdm", "PDM או PLM")}: שם נמצאים התלת-ממד והשרטוט. הרכש והמחסן עובדים ב-${term("erp", "ERP")}: שם יש מלאי, מחיר וספק.</p>
      <p>המק"ט הוא החוט שמחבר ביניהם. כשההנדסה וה-ERP רושמים את אותו חלק במספר אחר – המערכות כבר לא "מכירות" אותו כאותו חלק.</p>`, twoSystems(p))}

    ${chapter(3, "bom", "עץ מוצר ושימושים", `<p>מוצר בנוי מ${term("assembly", "מכלולים")}, ומכלולים בנויים מחלקים – כמו עץ. זה ${term("bom", "עץ המוצר")}, והכמות ליד כל שורה אומרת כמה יחידות נכנסות.</p>
      <p>הכיוון ההפוך נקרא ${term("whereused", "שימושים")}: באילו מכלולים החלק נמצא. ${esc(p.pn)} נמצא ב-${n0(p.parents.length)} מכלולים
        ${p.products?.length ? `של ${p.products.map((x) => `<b>${esc(x.name)}</b>`).join(", ")}` : ""}. לפני ששינים חלק – בודקים את השימושים שלו.</p>
      <p><a href="#/config/${encodeURIComponent(tree?.uid || "")}">לעץ המלא בבקרת התצורה</a></p>`, bomVisual(tree, p))}

    ${g ? chapter(4, "dup", "כפילות: אותו חלק, כמה מספרים", `<p>כאן מתחילה הבעיה. אותו חלק בדיוק נרשם ב-${n0(new Set(g.parts.map((x) => x.source)).size)} מערכות תחת
        ${n0(new Set(g.pns).size)} מק"טים שונים – בכל אתר מישהו פתח לו מספר משלו. זו ${term("duplicate", "כפילות")}.</p>
      <p>המחיר: כל אתר קונה אותו בנפרד, המלאי מפוזר, ואף אחד לא רואה כמה יש באמת. אם תאחדו, ${money(g.redundant_stock_value, cur)} של מלאי
        יעברו למק"ט אחד, ו-${n0(g.bom_lines_to_update)} שורות בעצי מוצר יתעדכנו.</p>`, constellation(g, p)) : ""}

    ${chapter(5, "fix", "איך מתקנים", `<p>מאחדים: בוחרים ${term("target", "מק\"ט אחד שנשאר")}, ומחליפים בו את כל האחרים – בעצי המוצר, במלאי ובמערכות.</p>
      <p>התוכנה עושה את העבודה הקשה: מוצאת, משווה ומכינה את הרשימה. ההחלטה והביצוע – אצלכם. היא לא כותבת לשום מערכת.</p>`, fixFlow(c, ex, g))}

    <section class="ltry"><h2>לנסות בעצמכם</h2><div class="row wrap">
      ${g ? `<a class="btn primary" href="#/group/${encodeURIComponent(g.id)}">לקבוצת הכפילות של ${esc(p.pn)}</a>` : ""}
      ${tree ? `<a class="btn" href="#/config/${encodeURIComponent(tree.uid)}">בקרת התצורה של ${esc(tree.name)}</a>` : ""}
      <a class="btn" href="#/check">בדיקת חלק חדש לפני שפותחים מק"ט</a></div>
      <p class="small muted">בכל מסך: מילים עם קו מנוקד מסבירות את עצמן בלחיצה. את ההסבר הקצר בראש כל מסך מכבים ומדליקים ב"מצב למידה" בתפריט.</p></section>
  </div>`;

  // the jumps between chapters, and the chapter you are in
  const nav = el.querySelector(".chap-nav");
  el.querySelectorAll("[data-jump]").forEach((b) => (b.onclick = (e) => {
    e.preventDefault();
    el.querySelector(`#ch-${b.dataset.jump}`)?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  }));
  const io = new IntersectionObserver((ents) => ents.forEach((en) => {
    if (en.isIntersecting) nav.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.i === en.target.dataset.ch));
    if (en.isIntersecting && en.target.id === "ch-fix") el.querySelector("#merge")?.classList.add("play");
  }), { rootMargin: "-40% 0px -55% 0px" });
  el.querySelectorAll(".chap").forEach((s) => io.observe(s));
  // the identity card and its notes light each other
  const lite = (k, on) => el.querySelectorAll(`[data-f="${k}"]`).forEach((x) => x.classList.toggle("lit", on));
  el.querySelectorAll("[data-f]").forEach((x) => {
    x.addEventListener("pointerenter", () => lite(x.dataset.f, true));
    x.addEventListener("pointerleave", () => lite(x.dataset.f, false));
  });
  // the part itself, in 3D
  const viewers = [];
  for (const [sel, label] of [["#hero3d", ""], ["#dup3d", ""]]) {
    const box = el.querySelector(sel);
    if (!box || !p.has_step) continue;
    const v = new Viewer(box, { label });
    v.loadUrl(`/api/mesh/latest/${encodeURIComponent(p.uid)}`);
    viewers.push(v);
  }
  return () => { io.disconnect(); viewers.forEach((v) => v.dispose()); };
}
