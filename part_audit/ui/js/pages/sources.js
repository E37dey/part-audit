import { get, send, upload, isStatic } from "../api.js";
import { esc, sysColor, sysCode, datetime, ICON, n0 } from "../util.js";
import { modal, toast, confirmInline } from "../ui.js";

export async function render({ el, setTitle, refreshStatus, startScan, state }) {
  setTitle("מקורות נתונים", "חיבורים למערכות PDM/PLM, ERP ותיקיות (קריאה בלבד)");
  const [sources, kinds] = await Promise.all([get("/api/sources"), get("/api/connectors")]);
  const byKind = Object.fromEntries(kinds.map((k) => [k.kind, k]));
  const pdm = sources.filter((s) => byKind[s.kind]?.role === "pdm");
  const erp = sources.filter((s) => byKind[s.kind]?.role === "erp");
  el.innerHTML = `
    <div class="row">
      <button class="btn primary" id="scan">${ICON.play}סריקה חדשה של כל המקורות הפעילים</button>
      <button class="btn" id="testall">בדוק את כל החיבורים</button>
      <button class="btn" id="add">+ הוסף מקור</button>
      ${state.status.demo_available && !state.status.demo_loaded ? '<button class="btn" id="demo">טען סביבת הדגמה</button>' : ""}
      <span class="spacer"></span><span class="small muted">${sources.filter((s) => s.enabled).length} מקורות פעילים מתוך ${sources.length}</span>
    </div>
    ${sources.length ? "" : `<div class="panel"><div class="empty">עדיין לא חוברו מקורות. לחצו "הוסף מקור" או טענו את סביבת ההדגמה.</div></div>`}
    ${pdm.length ? `<h2>מערכות הנדסיות (PDM / PLM / קבצים)</h2><div class="sources">${pdm.map((s) => card(s, byKind[s.kind])).join("")}</div>` : ""}
    ${erp.length ? `<h2>ERP</h2><div class="sources">${erp.map((s) => card(s, byKind[s.kind])).join("")}</div>` : ""}
    <div class="callout small">כל חיבור משתמש רק בפעולות קריאה. בקשות שאינן קריאה נחסמות בקוד לפני שהן יוצאות מהמחשב (למשל: בדיקת חיבור ל-SAP Business One מבצעת התחברות והתנתקות בלבד).
      הסיסמאות נשמרות במחשב הזה בלבד${isStatic ? "" : " (במנהל האישורים של מערכת ההפעלה, כשקיים)"}.</div>`;
  el.querySelector("#scan").onclick = startScan;
  el.querySelector("#add").onclick = () => pickKind(kinds, refresh);
  el.querySelector("#testall").onclick = async (e) => {
    if (isStatic) { toast("בגרסת ההדגמה המקוונת אין חיבור למערכות – הפעולה זמינה באפליקציה המקומית"); return; }
    e.target.disabled = true; e.target.textContent = "בודק…";
    const res = await testAll(sources.filter((s) => s.enabled));
    const bad = res.filter((r) => !r.ok).length;
    toast(bad ? `${bad} חיבורים נכשלו – הפרטים בכרטיס של כל מקור` : `כל ${res.length} החיבורים תקינים`, bad > 0);
    await refresh();
  };
  const demo = el.querySelector("#demo");
  if (demo) demo.onclick = async () => {
    demo.disabled = true;
    const list = await send("POST", "/api/demo/load");
    await testAll(list.filter((s) => s.enabled));
    toast("סביבת ההדגמה נטענה והחיבורים נבדקו");
    await refresh();
  };
  el.querySelectorAll("[data-act]").forEach((b) => (b.onclick = () => act(b.dataset.act, sources.find((s) => s.id === b.dataset.id), byKind, refresh, b)));

  async function refresh() { await refreshStatus(); await render({ el, setTitle, refreshStatus, startScan, state }); }
}

// test connections one after the other (each test is a few read-only calls)
export async function testAll(list) {
  const out = [];
  for (const s of list) {
    try { out.push(await send("POST", `/api/sources/${s.id}/test`)); } catch (e) { out.push({ ok: false, message: e.message }); }
  }
  return out;
}

function card(s, k) {
  const t = s.last_test;
  const url = s.config.base_url || s.config.server_url || s.config.service_root || s.config.host || s.config.path || "";
  return `<article class="src ${s.enabled ? "" : "off"}">
    <div class="src-h"><div class="src-logo" style="background:${sysColor(s.kind)}">${sysCode(s.kind)}</div>
      <div style="min-width:0"><h3>${esc(s.name)}</h3><div class="kind">${esc(k?.title || s.kind)} · ${esc(k?.interface || "")}</div></div></div>
    <div class="meta mono ltr">${esc(url)}</div>
    <div class="row">${s.simulated ? '<span class="pill brass">סימולטור מקומי</span>' : ""}${s.enabled ? '<span class="pill ok">פעיל</span>' : '<span class="pill neutral">מושבת</span>'}</div>
    ${t ? `<div class="test ${t.ok ? "ok" : "bad"}"><b>${t.ok ? "החיבור תקין" : "החיבור נכשל"}</b> · ${esc(t.message)}
        ${t.details ? `<div class="small muted">${Object.entries(t.details).filter(([, v]) => v != null).map(([a, b]) => `${esc(a)}: ${esc(b)}`).join(" · ")}</div>` : ""}
        <div class="small muted">${datetime(t.at)}${t.seconds != null ? ` · ${t.seconds} ש'` : ""}</div></div>` : '<div class="test small muted">עדיין לא נבדק</div>'}
    <div class="actions">
      <button class="btn small" data-act="test" data-id="${s.id}">בדוק חיבור</button>
      <button class="btn small" data-act="discover" data-id="${s.id}" title="קורא מדגם קטן ומציע את מיפוי השדות">גילוי שדות</button>
      <button class="btn small" data-act="edit" data-id="${s.id}">הגדרות</button>
      <button class="btn small" data-act="toggle" data-id="${s.id}">${s.enabled ? "השבת" : "הפעל"}</button>
      <button class="btn small ghost" data-act="delete" data-id="${s.id}">מחק</button>
    </div></article>`;
}

async function act(what, s, byKind, refresh, btn) {
  if (what === "discover") { discover(s, byKind[s.kind], refresh); return; }
  if (isStatic && what !== "edit") { toast("בגרסת ההדגמה המקוונת אין חיבור למערכות – הפעולה זמינה באפליקציה המקומית"); return; }
  if (what === "test") {
    btn.disabled = true; btn.textContent = "בודק…";
    try { const r = await send("POST", `/api/sources/${s.id}/test`); toast(r.ok ? `${s.name}: החיבור תקין` : `${s.name}: ${r.message}`, !r.ok); }
    catch (e) { toast(e.message, true); }
    await refresh();
  } else if (what === "toggle") {
    await send("PUT", `/api/sources/${s.id}`, { enabled: !s.enabled }); await refresh();
  } else if (what === "delete") {
    if (await confirmInline(`למחוק את המקור "${s.name}"? הנתונים במערכת עצמה לא מושפעים.`, "מחק")) {
      await send("DELETE", `/api/sources/${s.id}`); await refresh();
    }
  } else if (what === "edit") {
    form(byKind[s.kind], s, refresh);
  }
}

function pickKind(kinds, refresh) {
  if (isStatic) { toast("הוספת מקורות זמינה באפליקציה המקומית"); return; }
  const m = modal({ title: "איזו מערכת לחבר?", wide: true, body: `<div class="stack">
      <h3>מערכות הנדסיות</h3><div class="kinds">${kinds.filter((k) => k.role === "pdm").map(kindCard).join("")}</div>
      <h3>ERP</h3><div class="kinds">${kinds.filter((k) => k.role === "erp").map(kindCard).join("")}</div></div>` });
  m.body.querySelectorAll("[data-kind]").forEach((b) => (b.onclick = () => { m.close(); form(kinds.find((k) => k.kind === b.dataset.kind), null, refresh); }));
}
function kindCard(k) {
  return `<button type="button" class="kind-card" data-kind="${k.kind}"><div class="src-logo" style="background:${sysColor(k.kind)}">${sysCode(k.kind)}</div>
    <div><div class="t">${esc(k.title)}</div><div class="d">${esc(k.interface)}</div></div></button>`;
}

function form(k, s, refresh) {
  const cfg = s ? s.config : {};
  const group = (g) => k.fields.filter((f) => f.group === g);
  const fieldHtml = (f) => {
    const v = cfg[f.name] ?? f.default ?? "";
    const id = `f-${f.name}`;
    let input;
    if (f.type === "bool") return `<div class="field"><label class="check"><input type="checkbox" id="${id}" ${v ? "checked" : ""}> ${esc(f.label)}</label>${f.help ? `<span class="help">${esc(f.help)}</span>` : ""}</div>`;
    if (f.type === "password") input = `<input type="password" id="${id}" value="${esc(v)}" autocomplete="new-password" dir="ltr">`;
    else if (f.type === "number") input = `<input type="number" id="${id}" value="${esc(v)}" dir="ltr">`;
    else input = `<input type="text" id="${id}" value="${esc(v)}" dir="${/url|path|root|host|server/.test(f.name) ? "ltr" : "auto"}">`;
    const up = f.type === "path" && k.kind === "erp_file" ? `<input type="file" id="${id}-up" accept=".xlsx,.csv">` : "";
    return `<div class="field ${f.type === "path" || /url|root/.test(f.name) ? "full" : ""}"><label for="${id}">${esc(f.label)}${f.required ? " *" : ""}</label>${input}${up}${f.help ? `<span class="help">${esc(f.help)}</span>` : ""}</div>`;
  };
  const body = `<div class="stack" style="gap:16px">
    <p class="muted small">${esc(k.description)}</p>
    <div class="field full"><label for="f-name">שם המקור בתוכנה</label><input id="f-name" type="text" value="${esc(s ? s.name : k.title)}"></div>
    <h3>חיבור</h3><div class="form">${group("connection").map(fieldHtml).join("")}</div>
    ${group("mapping").length ? `<details><summary><b>מיפוי שדות</b> <span class="small muted">– שמות המאפיינים אצלכם (ברירת המחדל לפי התיעוד)</span></summary><div class="form" style="margin-top:12px">${group("mapping").map(fieldHtml).join("")}</div></details>` : ""}
    ${group("advanced").length ? `<details><summary><b>מתקדם</b></summary><div class="form" style="margin-top:12px">${group("advanced").map(fieldHtml).join("")}</div></details>` : ""}
    <div class="callout small"><b>רמת אימות:</b> ${esc(k.verification)}${k.unconfirmed?.length ? `<ul style="margin:6px 0 0;padding-inline-start:18px">${k.unconfirmed.map((u) => `<li>${esc(u)}</li>`).join("")}</ul>` : ""}</div>
  </div>`;
  const m = modal({ title: s ? `הגדרות – ${s.name}` : `חיבור ${k.title}`, body, wide: true, actions: [
    { label: s ? "שמור" : "הוסף", kind: "primary", onClick: async (root) => {
      if (isStatic) { toast("שינוי הגדרות זמין באפליקציה המקומית"); return; }
      const config = {};
      for (const f of k.fields) {
        const inp = root.querySelector(`#f-${f.name}`);
        if (!inp) continue;
        config[f.name] = f.type === "bool" ? inp.checked : f.type === "number" ? Number(inp.value) : inp.value.trim();
        if (f.required && !config[f.name]) { toast(`חסר: ${f.label}`, true); return true; }
      }
      const name = root.querySelector("#f-name").value.trim() || k.title;
      try {
        const saved = s ? await send("PUT", `/api/sources/${s.id}`, { name, config }) : await send("POST", "/api/sources", { kind: k.kind, name, config });
        toast("נשמר. בודק חיבור…");
        const r = await send("POST", `/api/sources/${saved.id}/test`);
        toast(r.ok ? "החיבור תקין" : `החיבור נכשל: ${r.message}`, !r.ok);
        await refresh();
      } catch (e) { toast(e.message, true); return true; }
    } },
    { label: "ביטול" }] });
  const up = m.body.querySelector('input[type="file"]');
  if (up) up.onchange = async () => {
    try { const r = await upload(up.files[0]); m.body.querySelector("#f-path").value = r.path; toast(`הקובץ ${r.name} הועלה`); }
    catch (e) { toast(e.message, true); }
  };
}

// ------------------------------------------------------------------ pilot: field discovery
const pctTxt = (x) => (x == null ? "—" : `${Math.round(100 * x)}%`);
const fillPill = (x, found = true) => (!found ? '<span class="pill bad">לא נמצא</span>'
  : `<span class="pill ${x >= 0.8 ? "ok" : x >= 0.3 ? "warn" : "bad"}">${pctTxt(x)}</span>`);
const exChips = (xs) => (xs || []).slice(0, 3).map((x) => `<span class="chip">${esc(x)}</span>`).join(" ") || '<span class="muted">—</span>';

async function discover(s, k, refresh) {
  const m = modal({ title: `גילוי שדות – ${s.name}`, wide: true, body: `<div class="stack">
    <p class="muted">קורא מדגם של עד 40 רשומות מ-${esc(k.title)}. קריאה בלבד, בלי להוריד קבצים.</p>
    <div class="progress"><div style="width:40%"></div></div></div>` });
  let d;
  try { d = isStatic ? await get(`/api/sources/${s.id}/discovery`) : await send("POST", `/api/sources/${s.id}/discover`); }
  catch (e) { m.body.innerHTML = `<div class="callout warn">${esc(e.message)}</div>`; return; }
  const sugg = d.mapping.filter((f) => f.suggested);
  const rx = d.pn_regex && d.pn_regex.matched > (d.pn_found || 0) ? d.pn_regex : null;
  m.body.innerHTML = `<div class="stack" style="gap:16px">
    <div class="readout mini" style="--cells:4">
      <div class="cell"><span class="r-label">רשומות במדגם</span><span class="r-value">${n0(d.records)}</span></div>
      <div class="cell"><span class="r-label">עם קובץ STEP</span><span class="r-value">${d.step ? `${n0(d.step.found)}/${n0(d.step.checked)}` : "—"}</span></div>
      <div class="cell"><span class="r-label">מאפיינים שנמצאו</span><span class="r-value">${n0(d.properties.length)}</span></div>
      <div class="cell"><span class="r-label">קריאות API</span><span class="r-value">${d.api_calls == null ? "—" : n0(d.api_calls)}</span></div>
    </div>
    ${d.notes.length ? `<ul class="small muted" style="margin:0;padding-inline-start:18px">${d.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
    ${d.warnings.map((w) => `<div class="callout warn small">${esc(w)}</div>`).join("")}
    ${d.mapping.length ? `<div><h3 style="margin-bottom:8px">מיפוי שדות</h3>
      <div class="table-wrap"><table class="t"><thead><tr><th>בתוכנה</th><th>המאפיין שמוגדר עכשיו</th><th>מילוי</th><th>הצעה</th><th>דוגמאות</th><th>להחיל</th></tr></thead><tbody>
      ${d.mapping.map((f, i) => `<tr><td><b>${esc(f.target_he)}</b><div class="small muted">${esc(f.label)}</div></td>
        <td><span class="mono small ltr">${esc(f.current || "—")}</span><div class="small muted">${exChips(f.current_examples)}</div></td>
        <td>${fillPill(f.current_fill, f.current_found)}</td>
        <td>${f.suggested ? `<span class="mono small ltr">${esc(f.suggested)}</span> <span class="pill ${f.confidence === "high" ? "ok" : "warn"} plain">${f.confidence === "high" ? "התאמה טובה" : "התאמה חלקית"}</span>
          <div class="small muted">מילוי ${pctTxt(f.suggested_fill)}</div>` : '<span class="small muted">המיפוי הנוכחי מתאים</span>'}</td>
        <td>${f.suggested ? exChips(f.suggested_examples) : ""}</td>
        <td>${f.suggested ? `<input type="checkbox" data-apply="${i}" checked aria-label="להחיל">` : ""}</td></tr>`).join("")}
      </tbody></table></div></div>` : ""}
    ${rx ? `<div class="callout small"><b>תבנית מק"ט בשם הקובץ:</b> <span class="mono ltr">${esc(rx.regex)}</span> מזהה מק"ט ב-${n0(rx.matched)} מתוך ${n0(rx.of)} הקבצים
      (היום: ${n0(d.pn_found)}). <label class="check" style="display:inline-flex;margin-inline-start:8px"><input type="checkbox" id="apply-rx" checked> להחיל</label></div>` : ""}
    <details><summary><b>כל המאפיינים שנמצאו</b> <span class="small muted">(${n0(d.properties.length)})</span></summary>
      <div class="table-wrap" style="max-height:340px;margin-top:8px"><table class="t"><thead><tr><th>מאפיין</th><th>מילוי</th><th class="n">ערכים שונים</th><th>דוגמאות</th></tr></thead><tbody>
      ${d.properties.map((p) => `<tr><td class="mono small ltr">${esc(p.name)}</td><td>${fillPill(p.fill)}</td><td class="n">${n0(p.distinct)}</td><td class="small">${exChips(p.examples)}</td></tr>`).join("")}
      </tbody></table></div></details>
    <div class="row">
      <button class="btn primary" id="apply" ${sugg.length || rx ? "" : "disabled"}>החל את ההצעות שסומנו</button>
      <button class="btn" id="report">הורד דוח חיבור</button>
      <span class="small muted">נבדק ${datetime(d.at)}${d.seconds != null ? `, ${d.seconds} ש'` : ""}</span>
    </div></div>`;
  m.body.querySelector("#report").onclick = () => downloadReport(d);
  m.body.querySelector("#apply").onclick = async () => {
    if (isStatic) { toast("בגרסה המקוונת אפשר רק לראות את ההצעות; החלה זמינה באפליקציה המקומית"); return; }
    const config = { ...s.config };
    m.body.querySelectorAll("[data-apply]").forEach((cb) => { if (cb.checked) { const f = d.mapping[+cb.dataset.apply]; config[f.field] = f.suggested; } });
    if (rx && m.body.querySelector("#apply-rx")?.checked) config.pn_regex = rx.regex;
    try {
      await send("PUT", `/api/sources/${s.id}`, { config });
      toast("המיפוי עודכן. הסריקה הבאה תשתמש בו.");
      m.close(); await refresh();
    } catch (e) { toast(e.message, true); }
  };
}

// a self-contained Hebrew report of the discovery, to keep or send to whoever helps with the connection
function downloadReport(d) {
  if (isStatic) { toast("הורדת הדוח זמינה באפליקציה המקומית"); return; }
  const rows = (xs, f) => xs.map(f).join("");
  const html = `<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><title>דוח חיבור – ${esc(d.source.name)}</title>
<style>body{font-family:Arial,sans-serif;margin:32px;color:#132030}h1{font-size:22px}h2{font-size:16px;margin-top:24px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{border:1px solid #c3cfd8;padding:5px 8px;text-align:right;vertical-align:top}
th{background:#eef2f5}.m{font-family:Consolas,monospace;direction:ltr;unicode-bidi:isolate}.w{background:#fff4e0;padding:6px 10px;margin:6px 0}</style></head><body>
<h1>דוח חיבור: ${esc(d.source.name)}</h1>
<p>מערכת: ${esc(d.source.title)} (${esc(d.source.interface)})${d.source.simulated ? " – סימולטור הדגמה" : ""}<br>
נבדק: ${esc(String(d.at).replace("T", " "))}. מדגם: ${d.records} רשומות${d.step ? `, קובץ STEP ל-${d.step.found} מתוך ${d.step.checked}` : ""}.
הדוח נוצר במחשב הזה ולא נשלח לשום מקום. אין בו סיסמאות.</p>
${d.notes.map((n) => `<p>${esc(n)}</p>`).join("")}${d.warnings.map((w) => `<div class="w">${esc(w)}</div>`).join("")}
<h2>מיפוי שדות</h2><table><tr><th>בתוכנה</th><th>מאפיין מוגדר</th><th>מילוי</th><th>הצעה</th><th>דוגמאות</th></tr>
${rows(d.mapping, (f) => `<tr><td>${esc(f.target_he)}</td><td class="m">${esc(f.current)}</td><td>${f.current_found ? pctTxt(f.current_fill) : "לא נמצא"}</td>
<td class="m">${esc(f.suggested || "—")}</td><td>${esc((f.suggested ? f.suggested_examples : f.current_examples).slice(0, 3).join(" | "))}</td></tr>`)}</table>
<h2>כל המאפיינים שנמצאו</h2><table><tr><th>מאפיין</th><th>מילוי</th><th>ערכים שונים</th><th>דוגמאות</th></tr>
${rows(d.properties, (p) => `<tr><td class="m">${esc(p.name)}</td><td>${pctTxt(p.fill)}</td><td>${p.distinct}</td><td>${esc(p.examples.slice(0, 3).join(" | "))}</td></tr>`)}</table>
</body></html>`;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([html], { type: "text/html" }));
  a.download = `דוח_חיבור_${d.source.name.replace(/[^\w֐-׿ -]+/g, "_")}.html`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
