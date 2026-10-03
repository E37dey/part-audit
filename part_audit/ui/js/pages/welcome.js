import { send, isStatic } from "../api.js";
import { toast } from "../ui.js";
import { testAll } from "./sources.js";

export async function render({ el, setTitle, go, refreshStatus, state }) {
  setTitle("ברוכים הבאים");
  el.innerHTML = `<section class="panel"><div class="panel-b welcome" style="padding:28px">
    <div class="stack" style="gap:14px">
      <h1>כל מה שיש לכם על כל חלק – ממקום אחד</h1>
      <p style="max-width:62ch">PartAudit מתחבר למערכות ה-PDM/PLM ול-ERP שלכם (קריאה בלבד), קורא את הקבצים והנתונים של כל חלק,
        ומוצא חלקים שמופיעים פעמיים תחת מק"טים שונים, חלקים כמעט זהים שאפשר לתקנן, שמות ומק"טים לא עקביים,
        ופערים בין ההנדסה ל-ERP. כל הצעה לשינוי ממתינה לאישור של מהנדס – שום דבר לא נכתב למערכות.</p>
      <ol class="steps" style="padding:0;margin:6px 0">
        <li><div><b>מחברים מקורות</b><div class="muted small">SOLIDWORKS PDM, Autodesk Vault, Windchill, Teamcenter, תיקיית רשת, Priority, SAP או קובץ Excel</div></div></li>
        <li><div><b>מריצים סריקה</b><div class="muted small">השוואה לפי גיאומטריה תלת-ממדית, מק"ט, שם, מפרט תקני וחומר</div></div></li>
        <li><div><b>מאשרים ומייצאים</b><div class="muted small">מהנדס מאשר או דוחה כל הצעה, ומקבל קובץ Excel מסודר לביצוע</div></div></li>
      </ol>
      <div class="row">
        ${state.status.demo_available ? '<button class="btn primary big" id="demo">טען סביבת הדגמה</button>' : ""}
        <button class="btn big" id="own">חבר מערכת משלי</button>
      </div>
      ${state.status.demo_available ? '<p class="small muted">סביבת ההדגמה: קבוצת תעשייה בדויה עם 4 אתרים, 4 מערכות PDM/PLM שונות, ארכיון קבצים ישן ו-ERP. בערך 500 חלקים אמיתיים מבחינה הנדסית (ברגים לפי ISO/DIN, מסבים, צירים, פלטות, חלקי פח ו-5 מודלים של NIST).</p>' : ""}
    </div>
    <div aria-hidden="true">${diagram()}</div>
  </div></section>`;
  const demo = el.querySelector("#demo");
  if (demo) demo.onclick = async () => {
    if (isStatic) return;
    demo.disabled = true;
    demo.textContent = "טוען ובודק חיבורים…";
    try {
      const list = await send("POST", "/api/demo/load");
      await testAll(list.filter((s) => s.enabled));
      toast("סביבת ההדגמה נטענה – אפשר להתחיל סריקה");
      await refreshStatus(); go("#/sources");
    }
    catch (e) { toast(e.message, true); demo.disabled = false; }
  };
  el.querySelector("#own").onclick = () => go("#/sources");
}

function diagram() {
  const sys = [["SW", "#c8102e", "SOLIDWORKS PDM"], ["AV", "#0696d7", "Autodesk Vault"], ["WC", "#3a8d3a", "Windchill"],
    ["TC", "#00557f", "Teamcenter"], ["FS", "#6b7280", "תיקיית רשת"], ["PR", "#5b3fb8", "Priority / SAP"]];
  return `<svg viewBox="0 0 360 300" width="100%" style="max-width:420px;display:block;margin:auto;direction:ltr" role="img" aria-label="מערכות מתחברות לבקרה אחת">
    ${sys.map(([c, col, label], i) => {
      const y = 22 + i * 46;
      return `<g><rect x="230" y="${y}" width="120" height="34" rx="6" fill="var(--surface)" stroke="var(--line)"/>
        <rect x="236" y="${y + 7}" width="20" height="20" rx="4" fill="${col}"/><text x="246" y="${y + 21}" fill="#fff" font-size="9" text-anchor="middle" font-family="var(--mono)">${c}</text>
        <text x="342" y="${y + 22}" fill="var(--ink)" font-size="11" text-anchor="end">${label}</text>
        <path d="M230 ${y + 17} C 190 ${y + 17}, 170 150, 130 150" stroke="var(--line-strong)" fill="none"/></g>`;
    }).join("")}
    <rect x="20" y="118" width="110" height="64" rx="8" fill="var(--rail)"/>
    <text x="75" y="146" fill="#d9a54a" font-size="13" text-anchor="middle" font-weight="700">PartAudit</text>
    <text x="75" y="165" fill="#d8e0e4" font-size="10" text-anchor="middle">קריאה בלבד</text>
  </svg>`;
}
