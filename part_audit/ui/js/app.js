// App shell: navigation rail, top bar, hash router, scan runner.
import { get, send, isStatic } from "./api.js";
import { esc, ICON, LOGO, n0, datetime, pnChip, sysBadge, debounce } from "./util.js";
import { modal, toast } from "./ui.js";

const PAGES = {
  dashboard: () => import("./pages/dashboard.js"), welcome: () => import("./pages/welcome.js"),
  sources: () => import("./pages/sources.js"), groups: () => import("./pages/groups.js"), group: () => import("./pages/group.js"),
  near: () => import("./pages/near.js"), pair: () => import("./pages/pair.js"), names: () => import("./pages/findings.js"),
  quality: () => import("./pages/findings.js"), erp: () => import("./pages/findings.js"), mapping: () => import("./pages/mapping.js"),
  parts: () => import("./pages/parts.js"), part: () => import("./pages/part.js"), settings: () => import("./pages/settings.js"),
  guide: () => import("./pages/guide.js"), check: () => import("./pages/check.js"), changes: () => import("./pages/changes.js"),
};
// the navigation follows the work: connect the systems, go through the findings, decide
const NAV = [
  [null, [["dashboard", "לוח בקרה", ICON.dash], ["changes", "מה השתנה", ICON.delta, "changes"]]],
  ["1", "חיבור", [["sources", "מקורות נתונים", ICON.plug]]],
  ["2", "ממצאים", [["groups", "כפילויות", ICON.copy, "groups"], ["near", "כמעט זהים", ICON.near, "near_pairs"],
    ["names", "שמות ומק\"טים", ICON.tag, "name_findings"], ["quality", "איכות נתונים", ICON.check, "quality_issues"],
    ["erp", "ERP מול PDM", ICON.erp, "erp_issues"]]],
  ["3", "החלטה", [["mapping", "מיפוי ואישורים", ICON.map, "pending"]]],
  ["", "כלים", [["check", "בדיקת חלק חדש", ICON.inspect], ["parts", "חיפוש חלקים", ICON.search]]],
];
export const state = { status: null, summary: null };
let cleanup = null;

const navLink = ([k, label, icon, cnt]) => `<a href="#/${k}" data-k="${k}">${icon}<span>${label}</span>${cnt ? `<span class="count" data-c="${cnt}"></span>` : ""}</a>`;

function theme() { return document.documentElement.dataset.theme === "light" ? "light" : "dark"; }
function themeButton() {
  return theme() === "dark" ? `${ICON.sun}<span>מצב בהיר</span>` : `${ICON.moon}<span>מצב כהה</span>`;
}
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("pa-theme", t); } catch { /* the choice lasts for this visit */ }
  document.getElementById("theme").innerHTML = themeButton();
  window.dispatchEvent(new Event("pa-theme"));
}

function shell() {
  const app = document.getElementById("app");
  app.innerHTML = `<div class="app">
    <aside class="rail">
      <a class="brand" href="#/">${LOGO}<div><b>PartAudit</b><span>בקרת נתונים הנדסיים</span></div></a>
      <nav class="nav" id="nav">${NAV.map(([n, title, links]) => (typeof title === "string" ? `<div class="nav-step">${n ? `<i>${n}</i>` : ""}${title}</div>` : "")
        + (Array.isArray(title) ? title : links).map(navLink).join("")).join("")}
        <div class="nav-sep"></div>
        <a href="#/settings" data-k="settings">${ICON.gear}<span>הגדרות</span></a>
        <a href="#/guide" data-k="guide">${ICON.book}<span>מדריך</span></a></nav>
      <div class="rail-foot">
        <button class="theme-switch" id="theme" type="button">${themeButton()}</button>
        <div class="lock">${ICON.lock}<span>קריאה בלבד: התוכנה לא כותבת ל-PDM, ל-PLM או ל-ERP. הכול רץ במחשב הזה.</span></div>
        <div id="ver"></div></div>
    </aside>
    <div class="main">
      <header class="topbar"><div class="titles"><div class="crumbs" id="crumbs"></div><h1 id="title"></h1></div>
        <div class="gsearch" id="gsearch" hidden>${ICON.search}<input type="search" id="gq" placeholder='חיפוש מק"ט, שם או מפרט' autocomplete="off"
          aria-label="חיפוש חלק בכל המערכות" aria-controls="gs-list" aria-expanded="false"><kbd>/</kbd><div class="gs-list" id="gs-list" role="listbox" hidden></div></div>
        <span class="runinfo" id="runinfo"></span>
        <button class="btn" id="btn-xls" title="ייצוא כל הממצאים וההחלטות לקובץ Excel בעברית">${ICON.xls}ייצוא Excel</button>
        <button class="btn primary" id="btn-scan">${ICON.play}סריקה חדשה</button></header>
      <div class="content" id="content"></div>
    </div></div>`;
  document.getElementById("theme").onclick = () => setTheme(theme() === "dark" ? "light" : "dark");
  globalSearch();
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
  const ch = state.summary?.changes;
  const counts = s ? { groups: s.groups, near_pairs: s.near_pairs, name_findings: s.name_findings,
    quality_issues: s.quality_issues, erp_issues: s.erp_issues, pending: state.summary.decisions.pending_groups,
    changes: ch && ch.new_groups + ch.grown_groups ? ch.new_groups + ch.grown_groups : null } : {};
  document.querySelectorAll("#nav .count").forEach((c) => {
    const v = counts[c.dataset.c];
    c.textContent = v == null ? "" : n0(v);
    c.classList.toggle("hot", (c.dataset.c === "pending" || c.dataset.c === "changes") && v > 0);
  });
  document.getElementById("runinfo").innerHTML = state.summary ? `<span class="live" aria-hidden="true"></span>סריקה אחרונה: ${datetime(state.summary.created)}` : "";
  document.getElementById("ver").textContent = `גרסה ${state.status.version}` + (isStatic ? ", הדגמה מקוונת" : "");
  document.getElementById("gsearch").hidden = !state.summary;
}

// search every record of the last scan from any screen: '/' to focus, arrows to move, Enter to open
function globalSearch() {
  const box = document.getElementById("gsearch"), input = document.getElementById("gq"), list = document.getElementById("gs-list");
  let items = [], on = -1, seq = 0;
  const close = () => { list.hidden = true; input.setAttribute("aria-expanded", "false"); on = -1; };
  const all = () => { const q = input.value.trim(); close(); input.blur(); location.hash = `#/parts/${encodeURIComponent(q)}`; };
  const open = (i) => { const p = items[i]; if (!p) return all(); close(); input.value = ""; input.blur(); location.hash = `#/part/${encodeURIComponent(p.uid)}`; };
  const mark = () => list.querySelectorAll(".gs-item").forEach((x, i) => x.classList.toggle("on", i === on));
  const run = debounce(async () => {
    const q = input.value.trim();
    if (q.length < 2) { close(); return; }
    const my = ++seq;
    let r;
    try { r = await get("/api/runs/latest/parts", { q, limit: 8 }); } catch { return; }
    if (my !== seq) return;
    items = r.rows;
    on = items.length ? 0 : -1;
    list.innerHTML = items.length ? items.map((p, i) => `<a class="gs-item" role="option" data-i="${i}">${pnChip(p.pn)}<span class="nm">${esc(p.name || "")}</span>${sysBadge(p.source_kind, "")}</a>`).join("")
      + `<a class="gs-all" data-all>כל התוצאות (${n0(r.total)})</a>` : `<div class="gs-empty">לא נמצא חלק עם "${esc(q)}"</div>`;
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    mark();
  }, 160);
  input.addEventListener("input", run);
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!items.length || list.hidden) return;
      e.preventDefault();
      on = (on + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      mark();
    } else if (e.key === "Enter") { e.preventDefault(); if (input.value.trim()) (on >= 0 && !list.hidden ? open(on) : all()); }
    else if (e.key === "Escape") { close(); input.blur(); }
  });
  list.addEventListener("mousedown", (e) => {
    e.preventDefault();
    const it = e.target.closest("[data-i]");
    if (it) open(+it.dataset.i); else if (e.target.closest("[data-all]")) all();
  });
  input.addEventListener("blur", () => setTimeout(close, 120));
  document.addEventListener("keydown", (e) => {
    if (e.key !== "/" || box.hidden || e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target;
    if (t.closest && t.closest("input, textarea, select, [contenteditable]")) return;
    e.preventDefault();
    input.focus();
  });
}

const DEMO_NOTE = `מפעל בדוי עם 4 אתרים. כל נתוני העסק (מק"טים, שמות, מלאי, מחירים, אנשים) סינתטיים. הגיאומטריה של החלקים התקניים נבנתה לפי מידות התקנים, ונוספו 5 מודלים אמיתיים של NIST. החיבור למערכות הוא לסימולטורים מקומיים שמחקים את ה-API של כל יצרן.`;

export function setTitle(title, crumbs = "") {
  const h = document.getElementById("title");
  h.textContent = title;
  h.title = title;          // long names are cut with an ellipsis in the top bar
  document.getElementById("crumbs").innerHTML = crumbs;
  document.title = `${title} · PartAudit`;
}

export function go(hash) { location.hash = hash; }

async function route() {
  const raw = decodeURIComponent((location.hash || "#/").slice(2)).split("?")[0];   // ?… are a page's own options
  let [page, ...rest] = raw.split("/");
  const param = rest.join("/");
  if (!page) page = state.summary ? "dashboard" : (state.status?.sources ? "sources" : "welcome");
  if (page === "dashboard" && !state.summary) page = state.status?.sources ? "sources" : "welcome";
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.k === page || (page === "group" && a.dataset.k === "groups")
    || (page === "pair" && a.dataset.k === "near") || (page === "part" && a.dataset.k === "parts")));
  const content = document.getElementById("content");
  if (cleanup) { try { cleanup(); } catch { /* ignore */ } cleanup = null; }
  content.innerHTML = `<div class="skeleton" aria-label="טוען"><i></i><i></i><i></i></div>`;
  window.scrollTo(0, 0);
  const loader = PAGES[page];
  if (!loader) { content.innerHTML = `<div class="empty">הדף לא נמצא</div>`; return; }
  try {
    const mod = await loader();
    content.innerHTML = "";
    if (state.summary?.demo || isStatic) {
      const b = document.createElement("details");
      b.className = "demo-banner";
      b.innerHTML = `<summary><b>סביבת הדגמה</b><span>הנתונים סינתטיים, והמערכות הן סימולטורים מקומיים</span><span class="more">פרטים</span></summary><p>${DEMO_NOTE}</p>`;
      content.appendChild(b);
    }
    const box = document.createElement("div");
    box.className = "page";
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
