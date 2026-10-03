// App shell: navigation rail, top bar, hash router, scan runner.
import { get, send, isStatic } from "./api.js";
import { esc, ICON, LOGO, n0, datetime } from "./util.js";
import { modal, toast } from "./ui.js";

const PAGES = {
  dashboard: () => import("./pages/dashboard.js"), welcome: () => import("./pages/welcome.js"),
  sources: () => import("./pages/sources.js"), groups: () => import("./pages/groups.js"), group: () => import("./pages/group.js"),
  near: () => import("./pages/near.js"), pair: () => import("./pages/pair.js"), names: () => import("./pages/findings.js"),
  quality: () => import("./pages/findings.js"), erp: () => import("./pages/findings.js"), mapping: () => import("./pages/mapping.js"),
  parts: () => import("./pages/parts.js"), part: () => import("./pages/part.js"), settings: () => import("./pages/settings.js"),
  guide: () => import("./pages/guide.js"),
};
const NAV = [
  ["dashboard", "לוח בקרה", ICON.dash], ["sources", "מקורות נתונים", ICON.plug], ["groups", "כפילויות", ICON.copy, "groups"],
  ["near", "כמעט זהים", ICON.near, "near_pairs"], ["names", "שמות ומק\"טים", ICON.tag, "name_findings"],
  ["quality", "איכות נתונים", ICON.check, "quality_issues"], ["erp", "ERP מול PDM", ICON.erp, "erp_issues"],
  ["mapping", "מיפוי ואישורים", ICON.map, "pending"], ["parts", "חיפוש חלקים", ICON.search],
];
export const state = { status: null, summary: null };
let cleanup = null;

function shell() {
  const app = document.getElementById("app");
  app.innerHTML = `<div class="app">
    <aside class="rail">
      <div class="brand">${LOGO}<div><b>PartAudit</b><span>בקרת נתונים הנדסיים</span></div></div>
      <nav class="nav" id="nav">${NAV.map(([k, label, icon, cnt]) => `<a href="#/${k}" data-k="${k}">${icon}<span>${label}</span>${cnt ? `<span class="count" data-c="${cnt}"></span>` : ""}</a>`).join("")}
        <div class="nav-sep"></div>
        <a href="#/settings" data-k="settings">${ICON.gear}<span>הגדרות</span></a>
        <a href="#/guide" data-k="guide">${ICON.book}<span>מדריך</span></a></nav>
      <div class="rail-foot"><div class="lock">${ICON.lock}<span>קריאה בלבד: התוכנה לא כותבת ל-PDM, ל-PLM או ל-ERP. הכול רץ במחשב הזה.</span></div>
        <div id="ver" style="margin-top:8px"></div></div>
    </aside>
    <div class="main">
      <header class="topbar"><div><div class="crumbs" id="crumbs"></div><h1 id="title"></h1></div><span class="spacer"></span>
        <span class="runinfo" id="runinfo"></span>
        <button class="btn" id="btn-xls" title="ייצוא כל הממצאים וההחלטות לקובץ Excel בעברית">${ICON.xls}ייצוא Excel</button>
        <button class="btn primary" id="btn-scan">${ICON.play}סריקה חדשה</button></header>
      <div class="content" id="content"></div>
    </div></div>`;
  document.getElementById("btn-scan").onclick = startScan;
  document.getElementById("btn-xls").onclick = () => {
    if (isStatic) { toast("ייצוא Excel זמין באפליקציה המקומית"); return; }
    if (!state.status?.latest_run) { toast("אין עדיין תוצאות לייצוא", true); return; }
    location.href = `/api/runs/${state.status.latest_run}/export.xlsx`;
  };
  if (isStatic) document.getElementById("btn-scan").title = "בגרסה המקוונת מוצגות תוצאות של סריקה שבוצעה; סריקה חדשה רצה באפליקציה המקומית";
}

export async function refreshStatus() {
  state.status = await get("/api/status");
  state.summary = null;
  if (state.status.latest_run) {
    try { state.summary = await get(`/api/runs/${state.status.latest_run}/summary`); } catch { state.summary = null; }
  }
  const s = state.summary?.summary;
  const counts = s ? { groups: s.groups, near_pairs: s.near_pairs, name_findings: s.name_findings,
    quality_issues: s.quality_issues, erp_issues: s.erp_issues, pending: state.summary.decisions.pending_groups } : {};
  document.querySelectorAll("#nav .count").forEach((c) => {
    const v = counts[c.dataset.c];
    c.textContent = v == null ? "" : n0(v);
    c.classList.toggle("hot", c.dataset.c === "pending" && v > 0);
  });
  document.getElementById("runinfo").textContent = state.summary ? `סריקה אחרונה: ${datetime(state.summary.created)}` : "";
  document.getElementById("ver").textContent = `גרסה ${state.status.version}` + (isStatic ? " · הדגמה מקוונת" : "");
}

export function setTitle(title, crumbs = "") {
  document.getElementById("title").textContent = title;
  document.getElementById("crumbs").innerHTML = crumbs;
  document.title = `${title} · PartAudit`;
}

export function go(hash) { location.hash = hash; }

async function route() {
  const raw = decodeURIComponent((location.hash || "#/").slice(2));
  let [page, ...rest] = raw.split("/");
  const param = rest.join("/");
  if (!page) page = state.summary ? "dashboard" : (state.status?.sources ? "sources" : "welcome");
  if (page === "dashboard" && !state.summary) page = state.status?.sources ? "sources" : "welcome";
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.k === page || (page === "group" && a.dataset.k === "groups")
    || (page === "pair" && a.dataset.k === "near") || (page === "part" && a.dataset.k === "parts")));
  const content = document.getElementById("content");
  if (cleanup) { try { cleanup(); } catch { /* ignore */ } cleanup = null; }
  content.innerHTML = `<div class="empty">טוען…</div>`;
  window.scrollTo(0, 0);
  const loader = PAGES[page];
  if (!loader) { content.innerHTML = `<div class="empty">הדף לא נמצא</div>`; return; }
  try {
    const mod = await loader();
    content.innerHTML = "";
    if (state.summary?.demo || isStatic) {
      const b = document.createElement("div");
      b.className = "demo-banner";
      b.innerHTML = `<b>סביבת הדגמה</b><span>מפעל בדוי עם 4 אתרים. כל נתוני העסק (מק"טים, שמות, מלאי, מחירים, אנשים) סינתטיים; גיאומטריית החלקים התקניים לפי מידות התקנים, ו-5 מודלים אמיתיים של NIST. החיבור למערכות הוא לסימולטורים מקומיים שמחקים את ה-API של כל יצרן.</span>`;
      content.appendChild(b);
    }
    const box = document.createElement("div");
    box.className = "stack";
    box.style.gap = "20px";
    content.appendChild(box);
    cleanup = await mod.render({ el: box, page, param, state, setTitle, go, refreshStatus, startScan }) || null;
  } catch (e) {
    console.error(e);
    content.innerHTML = `<div class="panel"><div class="empty">שגיאה: ${esc(e.message)}</div></div>`;
  }
}

const STAGES = [["collect", "איסוף נתונים מהמערכות המחוברות"], ["read", "קריאת קבצי STEP"], ["geometry", "חישוב נפח, שטח ומידות של כל חלק"],
  ["compare", "השוואת חלקים: שמות, מק\"טים, גיאומטריה, מפרט"], ["impact", "השפעה: עצי מוצר, שימושים ומלאי"],
  ["quality", "בדיקות איכות נתונים ו-ERP"], ["done", "סיום"]];

export async function startScan() {
  if (isStatic) { toast("בגרסת ההדגמה המקוונת מוצגות תוצאות קיימות. סריקה חדשה רצה באפליקציה המקומית."); return; }
  let jid;
  try { jid = (await send("POST", "/api/scan")).job_id; } catch (e) { toast(e.message, true); return; }
  const m = modal({ title: "סריקה פועלת", body: `<div class="stack">
      <p class="muted small">התוכנה קוראת מכל מערכת (קריאה בלבד), מורידה קבצי STEP למטמון מקומי ומשווה. בסריקה הראשונה זה לוקח כמה דקות; סריקות חוזרות מהירות יותר.</p>
      <div class="progress"><div style="width:0%"></div></div>
      <div class="stages">${STAGES.map(([k, l]) => `<div class="stage" data-s="${k}"><span class="dot"></span>${l}</div>`).join("")}</div>
      <div class="small" id="scan-detail"></div><div class="log" id="scan-log"></div></div>`,
    actions: [{ label: "עצור סריקה", kind: "bad", onClick: async () => { await send("POST", `/api/jobs/${jid}/cancel`); return true; } }] });
  const order = STAGES.map((s) => s[0]);
  const weights = { collect: [0, 0.15], read: [0.15, 0.25], geometry: [0.25, 0.6], compare: [0.6, 0.85], impact: [0.85, 0.9], quality: [0.9, 0.98], done: [1, 1] };
  for (;;) {
    await new Promise((r) => setTimeout(r, 900));
    let j;
    try { j = await get(`/api/jobs/${jid}`); } catch { continue; }
    const idx = order.indexOf(j.stage);
    m.el.querySelectorAll(".stage").forEach((s, i) => { s.classList.toggle("done", i < idx || j.status === "done"); s.classList.toggle("now", i === idx && j.status === "running"); });
    const [a, b] = weights[j.stage] || [0, 0];
    m.el.querySelector(".progress > div").style.width = `${Math.round(100 * (a + (b - a) * (j.fraction || 0)))}%`;
    m.el.querySelector("#scan-detail").textContent = j.detail || "";
    const log = m.el.querySelector("#scan-log");
    log.innerHTML = j.log.slice(-60).map((l) => `<div>${l.t.toFixed(1)}s · ${esc(l.detail)}</div>`).join("");
    log.scrollTop = log.scrollHeight;
    if (j.status !== "running") {
      if (j.status === "done") {
        m.close();
        toast(`הסריקה הסתיימה (${Math.round(j.elapsed)} שניות)`);
        await refreshStatus();
        go("#/dashboard");
        route();
      } else {
        m.el.querySelector("#scan-detail").innerHTML = `<div class="callout warn">${j.status === "cancelled" ? "הסריקה נעצרה. התוצאות של הסריקה הקודמת נשארו כמו שהן." : "הסריקה נכשלה: " + esc(j.error || "")}</div>`;
      }
      return;
    }
  }
}

async function main() {
  shell();
  try { await refreshStatus(); } catch (e) { document.getElementById("content").innerHTML = `<div class="empty">לא ניתן להתחבר לשרת המקומי: ${esc(e.message)}</div>`; return; }
  window.addEventListener("hashchange", route);
  route();
}
main();
