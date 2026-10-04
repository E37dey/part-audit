// Management report: one printable document (A4, "save as PDF" in the browser) with the measured numbers of the last
// scan, where the duplicates are, the progress of the decisions and what to do next. Nothing in it is estimated:
// an annual saving appears only when the user entered their own cost assumption, and it says so.
import { get, isStatic } from "../api.js";
import { esc, n0, money, date, datetime, pnChip, ICON } from "../util.js";

const pct = (a, b) => (b ? Math.round((100 * a) / b) : 0);

function big(label, value, note) {
  return `<div class="r-cell"><span class="r-label">${label}</span><span class="r-value">${value}</span><span class="r-note">${note}</span></div>`;
}

// what to do next, from the numbers only (each rule says which number it comes from)
function advice(s, d, top, ch) {
  const out = [];
  const total = s.redundant_stock_value || 0;
  const topValue = top.reduce((t, g) => t + (g.redundant_stock_value || 0), 0);
  if (s.groups) {
    out.push(`<b>לאשר את הכפילויות לפי סדר המלאי.</b> ${total ? `10 הקבוצות הראשונות מחזיקות ${pct(topValue, total)}% מהמלאי שעל מק"טים כפולים.` : ""}
      ${d.decisions.pending_groups ? `${n0(d.decisions.pending_groups)} קבוצות עוד ממתינות להחלטה של מהנדס.` : "כל הקבוצות כבר קיבלו החלטה."}`);
  }
  if (s.groups_standard) {
    out.push(`<b>ספריית חלקים תקניים אחת.</b> ${n0(s.groups_standard)} מתוך ${n0(s.groups)} הקבוצות הן חלקים תקניים (ברגים, אומים, מסבים, שגמים) שנפתחו שוב בכל אתר. ספרייה משותפת עם מק"ט אחד לכל מפרט תמנע את רוב הכפילויות האלה.`);
  }
  if (s.groups_cross_source) {
    out.push(`<b>כפילויות בין אתרים.</b> ${n0(s.groups_cross_source)} קבוצות כוללות רשומות ביותר ממערכת אחת. כדאי לקבוע לכל חלק משותף מערכת אחת שבה הוא "גר".`);
  }
  if (ch && ch.new_groups + ch.grown_groups) {
    const what = [ch.new_groups ? `נוצרו ${n0(ch.new_groups)} כפילויות חדשות` : "",
      ch.grown_groups ? `${n0(ch.grown_groups)} קבוצות כפילות קיבלו עוד רשומה` : ""].filter(Boolean).join(" ו-");
    out.push(`<b>לעצור כפילויות חדשות.</b> מאז הסריקה של ${date(ch.from.created)} ${what}. בדיקת חלק חדש לפני שחרור תופסת אותן לפני שהן נכנסות לעצי מוצר ולמלאי.`);
  }
  if (s.parts && s.with_step / s.parts < 0.9) {
    out.push(`<b>קובצי STEP לכל החלקים.</b> ל-${100 - pct(s.with_step, s.parts)}% מהחלקים אין קובץ STEP, ולכן הם הושוו לפי שם, מק"ט ומפרט בלבד. המרה אוטומטית ל-STEP במערכת ה-PDM תשפר את הדיוק.`);
  }
  if (s.erp_issues) {
    out.push(`<b>ליישר את ה-ERP עם ההנדסה.</b> ${n0(s.erp_issues)} פערים בין ה-PDM ל-ERP: חלקים משוחררים שחסרים ב-ERP, ותיאור, חומר, סטטוס או עץ מוצר שונים.`);
  }
  return out;
}

export async function render({ el, setTitle, state }) {
  setTitle("דוח להנהלה", "מסמך להדפסה או לשמירה כ-PDF");
  const [d, runs] = await Promise.all([get(`/api/runs/${state.status.latest_run}/summary`), get("/api/runs").catch(() => [])]);
  const s = d.summary, cur = s.currency || "ILS", m = (x) => money(x, cur);
  const ch = d.changes;
  const top = d.top_groups || [];
  const done = runs.filter((r) => r.status === "done");
  const first = done.length > 1 ? done[done.length - 1] : null;
  const unread = d.sources.filter((x) => x.errors?.length && !(x.stats.records || x.stats.erp_items));
  const assumed = state.status.settings?.cost_per_pn_year;
  const systems = Object.entries(d.by_source).sort((a, b) => b[1].in_groups - a[1].in_groups);
  const cross = Object.entries(d.cross_source).sort((a, b) => b[1] - a[1]).slice(0, 6);
  const tips = advice(s, d, top, ch);
  el.innerHTML = `
    <div class="row no-print"><button class="btn primary" id="print">${ICON.print}הדפסה / שמירה כ-PDF</button>
      <span class="small muted">בחלון ההדפסה בוחרים "שמירה כ-PDF". המסמך מותאם לדף A4.</span></div>
    <article class="sheet" lang="he" dir="rtl">
      <header class="sh-head">
        <div><div class="sh-kicker">PartAudit · דוח בקרת נתונים הנדסיים${d.demo ? " · סביבת הדגמה (נתונים סינתטיים)" : ""}</div>
          <h1>כפילויות חלקים ואיכות נתונים</h1>
          <p class="sh-meta">סריקה מ-${datetime(d.created)} · ${n0(s.sources)} מקורות נתונים · ${n0(s.parts)} חלקים ו-${n0(s.assemblies)} מכלולים</p></div>
      </header>

      <section class="sh-lead">
        <p>נמצאו <b>${n0(s.groups)} חלקים שרשומים יותר מפעם אחת</b> (${n0(s.parts_in_groups)} רשומות). אחרי איחוד נשאר מק"ט אחד לכל חלק, וכך אפשר לבטל
          <b>${n0(s.redundant_pns)} מק"טים</b>. על המק"טים האלה רשום ב-ERP מלאי בשווי <b>${m(s.redundant_stock_value)}</b>.</p>
        ${unread.length ? `<p class="sh-warn">שימו לב: ${esc(unread.map((x) => x.name).join(", "))} לא נקרא בסריקה הזו, והמספרים לא כוללים אותו.</p>` : ""}
      </section>

      <section class="sh-numbers">
        ${big("קבוצות כפילות", n0(s.groups), `${n0(s.groups_cross_source)} מהן חוצות מערכות`)}
        ${big("מק\"טים שאפשר לבטל", n0(s.redundant_pns), "מק\"ט אחד נשאר בכל קבוצה")}
        ${big("מלאי על מק\"טים כפולים", m(s.redundant_stock_value), "כמות × עלות מה-ERP")}
        ${big("שורות עץ מוצר לעדכון", n0(s.bom_lines_to_update), "PDM ו-ERP, אחרי איחוד")}
        ${big("ממתינות להחלטה", n0(d.decisions.pending_groups), `${n0(d.decisions.approved_groups)} קבוצות כבר אושרו`)}
        ${big("כמעט זהים", n0(s.near_pairs), "זוגות שאולי אפשר לתקנן")}
        ${big("בעיות איכות נתונים", n0(s.quality_issues), "משקל, חומר, מק\"ט, יחידות")}
        ${big("פערים מול ה-ERP", n0(s.erp_issues), "חסרים, תיאור, סטטוס, עץ מוצר")}
      </section>

      ${ch || first ? `<section><h2>מגמה</h2><ul class="sh-list">
        ${ch ? `<li>מאז הסריקה של ${date(ch.from.created)}: ${esc(ch.headline)}</li>` : ""}
        ${first ? `<li>מאז הסריקה הראשונה (${date(first.created)}): ${n0(first.summary?.groups)} → ${n0(s.groups)} קבוצות כפילות, ${n0(first.summary?.quality_issues)} → ${n0(s.quality_issues)} בעיות איכות. בסך הכול ${n0(done.length)} סריקות.</li>` : ""}
      </ul></section>` : ""}

      <section><h2>איפה הכפילויות</h2>
        <table class="sh-table"><thead><tr><th>מערכת</th><th class="n">חלקים</th><th class="n">בקבוצת כפילות</th><th class="n">אחוז</th></tr></thead><tbody>
        ${systems.map(([name, v]) => `<tr><td>${esc(name)}</td><td class="n">${n0(v.parts)}</td><td class="n">${n0(v.in_groups)}</td><td class="n">${pct(v.in_groups, v.parts)}%</td></tr>`).join("")}
        </tbody></table>
        ${cross.length ? `<table class="sh-table" style="margin-top:10px"><thead><tr><th>שתי מערכות עם הכי הרבה כפילויות משותפות</th><th class="n">קבוצות</th></tr></thead><tbody>
          ${cross.slice(0, 4).map(([k, v]) => `<tr><td>${k.split("|").map(esc).join(' <span class="muted">↔</span> ')}</td><td class="n">${n0(v)}</td></tr>`).join("")}</tbody></table>` : ""}
      </section>

      <section class="sh-break"><h2>10 הקבוצות עם המלאי הגדול ביותר על מק"טים כפולים</h2>
        <table class="sh-table"><thead><tr><th>חלק</th><th>מק"ט שנשאר</th><th>מק"טים לביטול</th><th class="n">מלאי על הכפולים</th></tr></thead><tbody>
        ${top.map((g) => `<tr><td>${esc(g.name)}</td><td>${pnChip(g.final_master_pn || g.master_pn, true)}</td>
          <td>${g.pns.filter((p) => p !== (g.final_master_pn || g.master_pn)).map((p) => pnChip(p)).join(" ")}</td><td class="n">${m(g.redundant_stock_value)}</td></tr>`).join("")}
        </tbody></table></section>

      <section><h2>על מה מבוססים המספרים</h2><ul class="sh-list">
        <li>${pct(s.with_step, s.parts)}% מהחלקים (${n0(s.with_step)}) הושוו גם לפי הגיאומטריה בקובץ STEP; השאר לפי שם, מק"ט ומפרט בלבד.</li>
        <li>${pct(s.erp_linked, s.parts)}% מהחלקים (${n0(s.erp_linked)}) מקושרים לפריט ERP, ומהם נלקחו המלאי והעלות.</li>
        <li>סכומי כסף מחושבים במטבע אחד (${esc(cur)})${s.groups_other_currency ? `; ${n0(s.groups_other_currency)} קבוצות במטבע אחר לא נכללו בסכום` : ""}.</li>
      </ul></section>

      ${tips.length ? `<section><h2>מה מומלץ</h2><ol class="sh-steps">${tips.map((t) => `<li>${t}</li>`).join("")}</ol></section>` : ""}

      ${assumed ? `<section><h2>לפי הנחה שלכם</h2><p>בהגדרות הוזנה עלות שנתית של ${m(assumed)} להחזקת מק"ט. לפי ההנחה הזו, ביטול ${n0(s.redundant_pns)} מק"טים חוסך כ-${m(s.redundant_pns * assumed)} בשנה.
        זו הערכה לפי ההנחה, לא מדידה.</p></section>` : ""}

      <footer class="sh-foot">המספרים נמדדו בסריקה של ${datetime(d.created)}. PartAudit קורא מהמערכות בלבד ולא משנה בהן דבר; כל איחוד מחכה לאישור מהנדס.
        ${d.demo ? "זו סביבת הדגמה: כל נתוני העסק סינתטיים." : ""} ${isStatic ? "" : `הופק ב-${datetime(new Date().toISOString())}.`}</footer>
    </article>`;
  el.querySelector("#print").onclick = () => window.print();
  return null;
}
