// Settings: who approves, tolerances, speed, optional cost assumption, advanced thresholds; and the decision log.
import { get, send, isStatic } from "../api.js";
import { esc, datetime, DECISION } from "../util.js";
import { toast, modal } from "../ui.js";

const TYPE_HE = { group: "קבוצת כפילות", pair: "זוג", mapping: "שורת מיפוי", issue: "ממצא" };
const ISSUE = { approve: "לתקן", reject: "לא בעיה", review: "לבדיקה", ignore: "להתעלם" };
const DAYS = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"];
const ROLE_CARDS = [["viewer", "צפייה", "רואה את כל המסכים, הדוחות והתלת-ממד, ומייצא ל-Excel."],
  ["engineer", "מהנדס", "גם מחליט על כפילויות ועל ממצאים, מריץ סריקה ובודק חלק חדש."],
  ["admin", "מנהל", "גם מחבר מקורות נתונים, משנה הגדרות ומנהל משתמשים."]];

function userRows(users) {
  if (!users.length) return '<tr><td colspan="6"><div class="empty">עדיין אין משתמשים</div></td></tr>';
  return users.map((u) => `<tr data-u="${u.id}" class="${u.disabled ? "muted" : ""}">
    <td><b>${esc(u.display_name)}</b><div class="small muted"><span class="ltr">${esc(u.username)}</span></div></td>
    <td><select data-role aria-label="הרשאה" ${isStatic ? "disabled" : ""}>${ROLE_CARDS.map(([v, l]) => `<option value="${v}" ${u.role === v ? "selected" : ""}>${l}</option>`).join("")}</select></td>
    <td class="small">${[u.password ? "סיסמה" : "", u.company ? "חשבון החברה" : ""].filter(Boolean).join(" + ") || "—"}</td>
    <td class="small nowrap">${u.last_login ? datetime(u.last_login) : '<span class="muted">עוד לא נכנס</span>'}</td>
    <td>${u.disabled ? '<span class="pill bad plain">מושבת</span>' : '<span class="pill ok plain">פעיל</span>'}</td>
    <td class="nowrap"><button class="btn small ghost" data-act="pw" type="button">סיסמה חדשה</button>
      <button class="btn small ghost" data-act="${u.disabled ? "enable" : "disable"}" type="button">${u.disabled ? "הפעלה" : "השבתה"}</button></td></tr>`).join("");
}

function teamPanels(s, users) {
  const oc = s.oidc || {};
  const callback = isStatic ? "https://<השרת שלכם>/api/auth/oidc/callback" : `${location.origin}/api/auth/oidc/callback`;
  return `
    <section class="panel" id="team"><div class="panel-h"><h2>צוות והרשאות</h2>
        <span class="sub">${s.team ? "שרת צוות פעיל – כל אחד נכנס עם משתמש" : "כבוי – התוכנה עובדת רק במחשב הזה, בלי כניסה"}</span></div>
      <div class="panel-b stack">
        <div class="role-cards">${ROLE_CARDS.map(([k, l, t]) => `<div class="role-card r-${k}"><b>${l}</b><span>${t}</span></div>`).join("")}</div>
        ${s.team ? "" : `<div class="callout small"><b>כדי שכל הצוות יעבוד מהדפדפן:</b>
          <ol class="tight"><li>מוסיפים כאן משתמש אחד לפחות עם הרשאת <b>מנהל</b>.</li>
          <li>מפעילים את <b>שרת הצוות</b> במחשב שיהיה השרת: "PartAudit – שרת צוות" בתפריט התחל, או הפקודה <span class="mono ltr">python -m part_audit serve</span>.</li>
          <li>כל אחד פותח בדפדפן את הכתובת שהשרת מציג ונכנס עם המשתמש שלו.</li></ol></div>`}
        <div class="table-wrap"><table class="t" id="users"><thead><tr><th>משתמש</th><th>הרשאה</th><th>כניסה עם</th><th>כניסה אחרונה</th><th>מצב</th><th></th></tr></thead>
          <tbody>${isStatic ? '<tr><td colspan="6"><div class="empty">בגרסה המקוונת אין משתמשים. באפליקציה מוסיפים אותם כאן.</div></td></tr>' : userRows(users)}</tbody></table></div>
        <form class="form" id="add-user" autocomplete="off">
          <div class="field"><label for="nu-name">שם משתמש לכניסה</label><input id="nu-name" dir="auto" maxlength="64" placeholder="למשל: dana.levi"></div>
          <div class="field"><label for="nu-disp">שם מלא (יופיע ליד החלטות)</label><input id="nu-disp" maxlength="120" placeholder="למשל: דנה לוי"></div>
          <div class="field"><label for="nu-role">הרשאה</label><select id="nu-role">${ROLE_CARDS.map(([v, l]) => `<option value="${v}" ${v === "engineer" ? "selected" : ""}>${l}</option>`).join("")}</select></div>
          <div class="field"><label for="nu-pw">סיסמה ראשונית</label><input id="nu-pw" type="password" dir="ltr" autocomplete="new-password">
            <span class="help">לפחות 8 תווים. המשתמש יכול להחליף אותה אחרי הכניסה.</span></div>
          <div class="field full"><button class="btn" type="submit" style="align-self:flex-start">+ הוספת משתמש</button></div>
        </form>
      </div></section>

    <section class="panel" id="sso"><div class="panel-h"><h2>כניסה עם חשבון החברה</h2><span class="sub">${oc.enabled ? "פעילה" : "כבויה (לא חובה)"}</span></div>
      <div class="panel-b stack">
        <label class="check"><input type="checkbox" id="oc-on" ${oc.enabled ? "checked" : ""}> לאפשר כניסה עם חשבון החברה (Microsoft Entra ID, Google Workspace, Okta, Keycloak ועוד)</label>
        <div class="form">
          <div class="field full"><label for="oc-iss">כתובת ספק הזהות (Issuer)</label><input id="oc-iss" dir="ltr" value="${esc(oc.issuer || "")}" placeholder="https://login.microsoftonline.com/<tenant-id>/v2.0">
            <span class="help">מקבלים ממנהל ה-IT. התוכנה קוראת ממנה את כל השאר (OpenID Connect).</span></div>
          <div class="field"><label for="oc-cid">Client ID</label><input id="oc-cid" dir="ltr" value="${esc(oc.client_id || "")}" autocomplete="off"></div>
          <div class="field"><label for="oc-sec">Client secret</label><input id="oc-sec" type="password" dir="ltr" value="${esc(oc.client_secret || "")}" autocomplete="new-password">
            <span class="help">נשמר במנהל האישורים של מערכת ההפעלה. שינוי הכתובת או ה-Client ID מוחק אותו.</span></div>
          <div class="field"><label for="oc-label">הכיתוב על כפתור הכניסה</label><input id="oc-label" maxlength="60" value="${esc(oc.label || "")}"></div>
          <div class="field"><label for="oc-dom">רק מהדומיינים (לא חובה)</label><input id="oc-dom" dir="ltr" value="${esc(oc.domains || "")}" placeholder="company.co.il"></div>
          <div class="field"><label for="oc-role">הרשאה למשתמש חדש</label><select id="oc-role">
            <option value="viewer" ${oc.default_role !== "engineer" ? "selected" : ""}>צפייה</option><option value="engineer" ${oc.default_role === "engineer" ? "selected" : ""}>מהנדס</option></select></div>
          <label class="check" style="align-self:end"><input type="checkbox" id="oc-auto" ${oc.auto_create !== false ? "checked" : ""}> ליצור משתמש אוטומטית בכניסה הראשונה</label>
        </div>
        <div class="callout small">אצל ספק הזהות רושמים את PartAudit כאפליקציית Web עם כתובת החזרה (Redirect URI):
          <div class="row" style="margin-top:6px"><span class="mono ltr" id="oc-cb">${esc(callback)}</span>${isStatic ? "" : '<button class="btn small" type="button" id="oc-copy">העתקה</button>'}</div></div>
        <div class="callout small">כשהאפשרות פעילה, השרת פונה רק לכתובת ספק הזהות שהוזנה כאן. הכניסה עובדת בשרת הצוות; במחשב יחיד אין כניסה בכלל.</div>
        <div><button class="btn small" type="button" id="oc-test">שמירה ובדיקת החיבור לספק</button></div>
      </div></section>`;
}

export async function render({ el, setTitle, refreshStatus, state }) {
  setTitle("הגדרות");
  const [s, decisions, team] = await Promise.all([get("/api/settings"), get("/api/decisions"), get("/api/users").catch(() => ({ users: [] }))]);
  const th = s.thresholds || {};
  const sc = s.schedule || {}, em = s.email || {};
  s.schedule_info = s.schedule_info || {};
  el.innerHTML = `
    <section class="panel"><div class="panel-h"><h2>כללי</h2></div><div class="panel-b">
      <div class="form">
        ${s.team ? "" : `<div class="field"><label for="user">השם שלך</label><input id="user" type="text" value="${esc(s.user_name)}" placeholder="למשל: יוסי כהן, מהנדס תקינה">
          <span class="help">יירשם ליד כל החלטה ובקובץ ה-Excel.</span></div>`}
        <div class="field"><label for="mass">סבילות בבדיקת משקל (%)</label><input id="mass" type="number" min="1" max="100" step="1" value="${Math.round((s.mass_tolerance ?? 0.1) * 100)}" dir="ltr">
          <span class="help">משקל רשום שרחוק יותר מזה מהמשקל שמחושב מהמודל והחומר יסומן כבעיה.</span></div>
        <div class="field"><label for="workers">מספר תהליכים לניתוח גיאומטריה</label><input id="workers" type="number" min="1" max="64" value="${esc(s.workers)}" dir="ltr">
          <span class="help">יותר תהליכים = סריקה מהירה יותר, ויותר עומס על המחשב.</span></div>
        <div class="field full"><label for="cost">עלות שנתית משוערת להחזקת מק"ט אחד (לא חובה)</label>
          <input id="cost" type="number" min="0" step="1" value="${s.cost_per_pn_year ?? ""}" dir="ltr" placeholder="ריק = לא להציג חיסכון משוער">
          <span class="help">התוכנה לא ממציאה את המספר הזה. אם תזינו אותו, החיסכון יוצג כ"משוער לפי ההנחה שלכם", בנפרד מהנתונים שנמדדו.</span></div>
      </div></div></section>

    <section class="panel"><div class="panel-h"><h2>ספים מתקדמים</h2><span class="sub">לשנות רק אם יש סיבה</span></div><div class="panel-b stack">
      <div class="callout warn small">ערכי ברירת המחדל כוילו על נתוני פיתוח, והדיוק נמדד איתם. שינוי ישפיע על מה שייחשב כפילות או "כמעט זהה".</div>
      <div class="form">
        <div class="field"><label for="near">"כמעט זהים": הפרש מרבי בתכונות הגיאומטריות (%)</label>
          <input id="near" type="number" min="0.5" max="50" step="0.5" value="${((th.geo_near ?? 0.1) * 100).toFixed(1)}" dir="ltr">
          <span class="help">ברירת מחדל 10%. נפח, שטח פנים, מומנטי התמד ומידות מעטפת.</span></div>
        <div class="field"><label for="names">דמיון שמות שנחשב "אותו שם" (%)</label>
          <input id="names" type="number" min="50" max="100" step="1" value="${Math.round((th.name_similar ?? 0.9) * 100)}" dir="ltr">
          <span class="help">ברירת מחדל 90%. משמש כשאין קובץ STEP להשוואה.</span></div>
      </div>
      <div><button class="btn small" id="reset">חזרה לברירות המחדל</button></div>
    </div></section>

    <section class="panel" id="schedule"><div class="panel-h"><h2>סריקה אוטומטית</h2><span class="sub">${sc.enabled ? esc(s.schedule_info.text) : "כבויה"}</span></div>
      <div class="panel-b stack">
        <label class="check"><input type="checkbox" id="sc-on" ${sc.enabled ? "checked" : ""}> לסרוק את כל המקורות אוטומטית</label>
        <div class="form">
          <div class="field"><label for="sc-freq">תדירות</label><select id="sc-freq"><option value="weekly" ${sc.frequency === "weekly" ? "selected" : ""}>פעם בשבוע</option>
            <option value="daily" ${sc.frequency === "daily" ? "selected" : ""}>כל יום</option></select></div>
          <div class="field" id="sc-day-f"><label for="sc-day">יום</label><select id="sc-day">${DAYS.map((d, i) => `<option value="${i}" ${+sc.weekday === i ? "selected" : ""}>${d}</option>`).join("")}</select></div>
          <div class="field"><label for="sc-time">שעה</label><input id="sc-time" type="time" value="${esc(sc.time)}" dir="ltr"></div>
        </div>
        <p class="small muted">הסריקה רצה כשהתוכנה פתוחה, ומושווית לסריקה שלפניה במסך "מה השתנה". אם המחשב היה כבוי בשעה שנקבעה, הסריקה תרוץ פעם אחת כשהתוכנה תיפתח.
          ${sc.enabled && s.schedule_info.next ? `הסריקה הבאה: <b>${datetime(s.schedule_info.next)}</b>.` : ""}
          ${s.schedule_info.last ? `הסריקה המתוזמנת האחרונה התחילה ב-${datetime(s.schedule_info.last)}.` : ""}
          לסריקה גם כשהתוכנה סגורה אפשר להגדיר משימה מתוזמנת של Windows (<a href="#/guide">במדריך</a>).</p>
      </div></section>

    <section class="panel" id="email"><div class="panel-h"><h2>התראה במייל</h2><span class="sub">${em.enabled ? "פעילה" : "כבויה (ברירת מחדל)"}</span></div>
      <div class="panel-b stack">
        <label class="check"><input type="checkbox" id="em-on" ${em.enabled ? "checked" : ""}> לשלוח מייל עם מה שהשתנה אחרי סריקה מתוזמנת</label>
        <div class="form">
          <div class="field"><label for="em-host">שרת דואר (SMTP)</label><input id="em-host" dir="ltr" value="${esc(em.host)}" placeholder="smtp.company.co.il"></div>
          <div class="field"><label for="em-port">פורט</label><input id="em-port" type="number" min="1" max="65535" dir="ltr" value="${esc(em.port)}"></div>
          <div class="field"><label for="em-sec">אבטחה</label><select id="em-sec">
            ${[["starttls", "STARTTLS (בדרך כלל פורט 587)"], ["ssl", "SSL (בדרך כלל פורט 465)"], ["none", "ללא הצפנה (שרת פנימי בלבד)"]].map(([v, l]) => `<option value="${v}" ${em.security === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
          <div class="field"><label for="em-user">משתמש</label><input id="em-user" dir="ltr" value="${esc(em.user)}" autocomplete="off"></div>
          <div class="field"><label for="em-pw">סיסמה</label><input id="em-pw" type="password" dir="ltr" value="${esc(em.password)}" autocomplete="new-password">
            <span class="help">נשמרת במנהל האישורים של מערכת ההפעלה. שינוי השרת מוחק אותה.</span></div>
          <div class="field"><label for="em-from">כתובת השולח</label><input id="em-from" dir="ltr" value="${esc(em.sender)}" placeholder="partaudit@company.co.il"></div>
          <div class="field full"><label for="em-to">נמענים</label><input id="em-to" dir="ltr" value="${esc(em.to)}" placeholder="name@company.co.il, other@company.co.il"></div>
          <div class="field"><label for="em-when">מתי לשלוח</label><select id="em-when">
            <option value="changes" ${em.on === "changes" ? "selected" : ""}>רק כשיש כפילות או ממצא חדש</option>
            <option value="always" ${em.on === "always" ? "selected" : ""}>אחרי כל סריקה מתוזמנת</option></select></div>
          <label class="check" style="align-self:end"><input type="checkbox" id="em-manual" ${em.after_manual ? "checked" : ""}> גם אחרי סריקה ידנית</label>
        </div>
        <div class="callout small">המייל יוצא רק דרך שרת הדואר שהגדרתם כאן, ומכיל את המק"טים והשמות של הכפילויות והממצאים החדשים. שום דבר אחר לא יוצא מהמחשב.</div>
        <div><button class="btn small" id="em-test">שמור ושלח מייל בדיקה</button></div>
      </div></section>

    ${teamPanels(s, team.users || [])}

    <div class="row"><button class="btn primary" id="save">שמור הגדרות</button><span class="small muted">ההגדרות חלות מהסריקה הבאה.</span></div>

    <section class="panel"><div class="panel-h"><h2>יומן החלטות</h2><span class="sub">כל ההחלטות שנרשמו, מהחדשה לישנה</span></div>
      <div class="table-wrap" style="max-height:420px"><table class="t"><thead><tr><th>מתי</th><th>מי</th><th>על מה</th><th>מזהה</th><th>החלטה</th><th>הערה</th></tr></thead><tbody>
      ${decisions.length ? decisions.slice(0, 500).map((d) => `<tr><td class="nowrap">${datetime(d.created)}</td><td>${esc(d.user)}</td><td>${TYPE_HE[d.target_type] || esc(d.target_type)}</td>
        <td class="mono small">${d.target_type === "group" ? `<a href="#/group/${esc(d.target_id)}">${esc(d.target_id)}</a>` : d.target_type === "pair" ? `<a href="#/pair/${esc(d.target_id)}">${esc(d.target_id)}</a>` : esc(d.target_id)}</td>
        <td>${d.target_type === "issue" ? (ISSUE[d.decision] || "ממתין") : (DECISION[d.decision] || [d.decision || "ממתין"])[0]}</td><td class="small">${esc(d.note || "")}</td></tr>`).join("")
        : '<tr><td colspan="6"><div class="empty">עדיין לא נרשמו החלטות</div></td></tr>'}
      </tbody></table></div></section>

    <section class="panel"><div class="panel-b small muted">
      גרסה ${esc(state.status.version)} · תיקיית העבודה: <span class="mono ltr">${esc(state.status.workspace || "")}</span><br>
      בתיקייה הזו נשמרים מסד הנתונים של האפליקציה, עותקים מקומיים של קבצי STEP שנקראו (מטמון), תוצאות הסריקות וקבצי ה-Excel. אפשר למחוק אותה בכל רגע.
    </div></section>`;

  const dayField = () => { el.querySelector("#sc-day-f").hidden = el.querySelector("#sc-freq").value === "daily"; };
  el.querySelector("#sc-freq").onchange = dayField;
  dayField();
  let resetTh = false;
  el.querySelector("#reset").onclick = () => { el.querySelector("#near").value = "10.0"; el.querySelector("#names").value = "90"; resetTh = true; };
  const val = (id) => el.querySelector(id).value.trim();
  const on = (id) => el.querySelector(id).checked;
  const save = async () => {
    const num = (id) => Number(el.querySelector(id).value);
    const cost = el.querySelector("#cost").value.trim();
    const near = Math.round(num("#near") * 10) / 1000, names = Math.round(num("#names")) / 100;
    const thresholds = resetTh ? {} : { ...th };
    if (Math.abs(near - 0.1) > 1e-9) thresholds.geo_near = near; else delete thresholds.geo_near;
    if (Math.abs(names - 0.9) > 1e-9) thresholds.name_similar = names; else delete thresholds.name_similar;
    await send("PUT", "/api/settings", { ...(s.team ? {} : { user_name: el.querySelector("#user").value.trim() }),
      mass_tolerance: num("#mass") / 100, workers: Math.max(1, Math.round(num("#workers"))),
      cost_per_pn_year: cost === "" ? null : Number(cost), thresholds,
      schedule: { enabled: on("#sc-on"), frequency: val("#sc-freq"), weekday: Number(val("#sc-day")), time: val("#sc-time") || "06:00" },
      email: { enabled: on("#em-on"), host: val("#em-host"), port: Number(val("#em-port")) || 587, security: val("#em-sec"),
        user: val("#em-user"), password: el.querySelector("#em-pw").value, sender: val("#em-from"), to: val("#em-to"),
        on: val("#em-when"), after_manual: on("#em-manual") },
      oidc: { enabled: on("#oc-on"), issuer: val("#oc-iss"), client_id: val("#oc-cid"), client_secret: el.querySelector("#oc-sec").value,
        label: val("#oc-label"), domains: val("#oc-dom"), default_role: val("#oc-role"), auto_create: on("#oc-auto") } });
  };
  el.querySelector("#save").onclick = async () => {
    if (isStatic) { toast("שינוי הגדרות זמין באפליקציה המקומית"); return; }
    try { await save(); toast("ההגדרות נשמרו"); await refreshStatus(); } catch (e) { toast(e.message, true); }
  };
  wireTeam(el, save, refreshStatus);
  el.querySelector("#em-test").onclick = async () => {
    if (isStatic) { toast("שליחת מייל זמינה באפליקציה המקומית"); return; }
    try {
      await save();
      const r = await send("POST", "/api/notify/test");
      toast(`נשלח מייל בדיקה ל-${r.to.join(", ")}`);
    } catch (e) { toast(e.message, true); }
  };
}

function wireTeam(el, save, refreshStatus) {
  const reload = async () => {
    const t = await get("/api/users");
    el.querySelector("#users tbody").innerHTML = userRows(t.users);
  };
  el.querySelector("#add-user").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (isStatic) { toast("ניהול משתמשים זמין באפליקציה"); return; }
    const v = (id) => el.querySelector(id).value.trim();
    try {
      await send("POST", "/api/users", { username: v("#nu-name"), display_name: v("#nu-disp"), role: v("#nu-role"), password: el.querySelector("#nu-pw").value });
      toast(`המשתמש ${v("#nu-name")} נוסף`);
      ["#nu-name", "#nu-disp", "#nu-pw"].forEach((id) => (el.querySelector(id).value = ""));
      await reload();
    } catch (err) { toast(err.message, true); }
  });
  const table = el.querySelector("#users");
  table.addEventListener("change", async (e) => {
    const sel = e.target.closest("select[data-role]");
    if (!sel) return;
    const id = sel.closest("tr").dataset.u;
    try { await send("PUT", `/api/users/${id}`, { role: sel.value }); toast("ההרשאה עודכנה"); } catch (err) { toast(err.message, true); }
    await reload();
  });
  table.addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-act]");
    if (!b || isStatic) return;
    const id = b.closest("tr").dataset.u;
    if (b.dataset.act === "pw") {
      modal({ title: "סיסמה חדשה", body: `<div class="form one"><div class="field"><label for="rp">הסיסמה החדשה</label>
          <input id="rp" type="password" dir="ltr" autocomplete="new-password"><span class="help">לפחות 8 תווים. הכניסות הפתוחות של המשתמש יסתיימו.</span></div></div>`,
        actions: [{ label: "שמירה", kind: "primary", onClick: async (body) => {
          try { await send("PUT", `/api/users/${id}`, { password: body.querySelector("#rp").value }); toast("הסיסמה הוחלפה"); }
          catch (err) { toast(err.message, true); return true; }
          return false;
        } }, { label: "ביטול" }] });
      return;
    }
    try { await send("PUT", `/api/users/${id}`, { disabled: b.dataset.act === "disable" }); } catch (err) { toast(err.message, true); }
    await reload();
  });
  const copy = el.querySelector("#oc-copy");
  if (copy) copy.onclick = async () => {
    try { await navigator.clipboard.writeText(el.querySelector("#oc-cb").textContent); toast("הכתובת הועתקה"); } catch { toast("לא ניתן להעתיק – סמנו את הכתובת והעתיקו ידנית", true); }
  };
  el.querySelector("#oc-test").onclick = async () => {
    if (isStatic) { toast("הכניסה עם חשבון החברה זמינה באפליקציה"); return; }
    try {
      await save();
      const r = await send("POST", "/api/auth/oidc/test");
      toast(`ספק הזהות עונה: ${r.issuer} · ${r.keys} מפתחות חתימה${r.pkce ? "" : " · בלי PKCE"}`);
      await refreshStatus();
    } catch (err) { toast(err.message, true); }
  };
}
