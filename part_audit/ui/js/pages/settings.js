// Settings: who approves, tolerances, speed, optional cost assumption, advanced thresholds; and the decision log.
import { get, send, isStatic } from "../api.js";
import { esc, datetime, DECISION } from "../util.js";
import { toast } from "../ui.js";

const TYPE_HE = { group: "קבוצת כפילות", pair: "זוג", mapping: "שורת מיפוי", issue: "ממצא" };
const ISSUE = { approve: "לתקן", reject: "לא בעיה", review: "לבדיקה", ignore: "להתעלם" };
const DAYS = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"];

export async function render({ el, setTitle, refreshStatus, state }) {
  setTitle("הגדרות");
  const [s, decisions] = await Promise.all([get("/api/settings"), get("/api/decisions")]);
  const th = s.thresholds || {};
  const sc = s.schedule || {}, em = s.email || {};
  s.schedule_info = s.schedule_info || {};
  el.innerHTML = `
    <section class="panel"><div class="panel-h"><h2>כללי</h2></div><div class="panel-b">
      <div class="form">
        <div class="field"><label for="user">השם שלך</label><input id="user" type="text" value="${esc(s.user_name)}" placeholder="למשל: יוסי כהן, מהנדס תקינה">
          <span class="help">יירשם ליד כל החלטה ובקובץ ה-Excel.</span></div>
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
    await send("PUT", "/api/settings", { user_name: el.querySelector("#user").value.trim(),
      mass_tolerance: num("#mass") / 100, workers: Math.max(1, Math.round(num("#workers"))),
      cost_per_pn_year: cost === "" ? null : Number(cost), thresholds,
      schedule: { enabled: on("#sc-on"), frequency: val("#sc-freq"), weekday: Number(val("#sc-day")), time: val("#sc-time") || "06:00" },
      email: { enabled: on("#em-on"), host: val("#em-host"), port: Number(val("#em-port")) || 587, security: val("#em-sec"),
        user: val("#em-user"), password: el.querySelector("#em-pw").value, sender: val("#em-from"), to: val("#em-to"),
        on: val("#em-when"), after_manual: on("#em-manual") } });
  };
  el.querySelector("#save").onclick = async () => {
    if (isStatic) { toast("שינוי הגדרות זמין באפליקציה המקומית"); return; }
    try { await save(); toast("ההגדרות נשמרו"); await refreshStatus(); } catch (e) { toast(e.message, true); }
  };
  el.querySelector("#em-test").onclick = async () => {
    if (isStatic) { toast("שליחת מייל זמינה באפליקציה המקומית"); return; }
    try {
      await save();
      const r = await send("POST", "/api/notify/test");
      toast(`נשלח מייל בדיקה ל-${r.to.join(", ")}`);
    } catch (e) { toast(e.message, true); }
  };
}
