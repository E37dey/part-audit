// Sign-in screen of the team server: user name and password, or the company account when an admin turned it on.
import { session } from "./api.js";
import { esc, ICON, LOGO } from "./util.js";

export function showLogin({ expired = false } = {}) {
  const params = new URLSearchParams(location.search);
  const failed = params.get("login_error");
  if (failed) history.replaceState(null, "", location.pathname + location.hash);
  document.title = "כניסה · PartAudit";
  const oidc = session.oidc && session.oidc.enabled;
  document.getElementById("app").innerHTML = `<main class="login">
    <form class="login-card" id="login-form" novalidate>
      <div class="login-brand">${LOGO}<div><b>PartAudit</b><span>בקרת נתונים הנדסיים</span></div></div>
      <h1>כניסה לשרת של הצוות</h1>
      <p class="muted">כאן רואים אילו חלקים רשומים יותר מפעם אחת במערכות ה-PDM וה-ERP, ומחליטים מה לאחד.</p>
      ${expired ? '<div class="callout warn small">עבר זמן רב מהכניסה האחרונה, או שהסיסמה הוחלפה. צריך להיכנס שוב.</div>' : ""}
      ${failed ? `<div class="callout bad small" role="alert">${esc(failed)}</div>` : ""}
      ${oidc ? `<a class="btn primary block" href="/api/auth/oidc/start">${ICON.lock}${esc(session.oidc.label)}</a>
        <div class="login-or"><span>או עם שם משתמש וסיסמה</span></div>` : ""}
      <div class="field"><label for="lu">שם משתמש</label><input id="lu" name="username" autocomplete="username" dir="auto" required></div>
      <div class="field"><label for="lp">סיסמה</label><input id="lp" name="password" type="password" autocomplete="current-password" dir="ltr" required></div>
      <div class="login-err small" id="lerr" role="alert" aria-live="assertive"></div>
      <button class="btn ${oidc ? "" : "primary"} block" type="submit" id="lgo">כניסה</button>
      <p class="login-note small muted">${ICON.lock}<span>קריאה בלבד: התוכנה לא כותבת ל-PDM, ל-PLM או ל-ERP. אין לכם משתמש? מנהל המערכת מוסיף משתמשים בהגדרות.</span></p>
    </form></main>`;
  const form = document.getElementById("login-form"), err = document.getElementById("lerr"), go = document.getElementById("lgo");
  document.getElementById("lu").focus();
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = form.username.value.trim(), password = form.password.value;
    if (!username || !password) { err.textContent = "צריך שם משתמש וסיסמה"; return; }
    go.disabled = true;
    err.textContent = "";
    try {
      const r = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }) });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.error || `שגיאה ${r.status}`);
      location.reload();
    } catch (ex) {
      err.textContent = ex.message;
      form.password.value = "";
      form.password.focus();
      go.disabled = false;
    }
  });
}
