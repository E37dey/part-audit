"""Optional e-mail after a scheduled scan: what changed since the scan before. Off by default.

The message goes only to the mail server the user configured (their own SMTP server), and carries part numbers and
names of the records that changed: nothing else leaves the computer. The password is kept in the OS credential
store when there is one (see Store.set_secret)."""
from __future__ import annotations

import datetime as dt
import html
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

DEFAULT_EMAIL = {"enabled": False, "host": "", "port": 587, "security": "starttls", "user": "", "sender": "",
                 "to": "", "on": "changes", "after_manual": False}
SECRET = "smtp_password"


def recipients(cfg: dict) -> list[str]:
    return [a.strip() for a in str(cfg.get("to") or "").replace(";", ",").split(",") if "@" in a]


def _fmt_money(x, cur) -> str:
    if x is None:
        return "—"
    sym = "₪" if cur in (None, "", "ILS") else f"{cur} "
    return f"{sym}{x:,.0f}"


def _rows(items, fn, limit=8) -> str:
    out = "".join(f"<li>{fn(x)}</li>" for x in items[:limit])
    more = f"<li>ועוד {len(items) - limit}</li>" if len(items) > limit else ""
    return f"<ul>{out}{more}</ul>"


def compose(changes: dict, summary: dict, *, app_url: str = "", demo: bool = False, failed: list[str] | None = None,
            when: str = "") -> tuple[str, str, str]:
    """(subject, plain text, html) in Hebrew."""
    e = html.escape
    g, f = changes["groups"], changes["findings"]
    s = changes["summary"]
    cur = changes.get("currency")
    subject = ("PartAudit – " + ("שינויים מאז הסריקה הקודמת" if changes.get("alert") else "סריקה הסתיימה – אין חדש")
               + (" (הדגמה)" if demo else ""))
    lines = [changes["headline"]]
    if failed:
        lines.append("שימו לב: " + ", ".join(failed) + " לא היו זמינים בסריקה הזו, והשינויים שלהם לא נספרו.")
    lines.append(f"קבוצות כפילות: {s['groups']['after']} (שינוי {s['groups']['delta']:+g})" if s["groups"]["delta"] is not None
                 else f"קבוצות כפילות: {s['groups']['after']}")
    for title, items in (("כפילויות חדשות", g["new"]), ("קבוצות שקיבלו רשומה נוספת", g["grown"])):
        if items:
            lines.append(title + ":")
            lines += [f"  - {x['name']}: {', '.join(x['pns'])} ({', '.join(x['sources'])})" for x in items[:8]]
    if app_url:
        lines.append(f"הפרטים בתוכנה (במחשב שבו היא מותקנת): {app_url}/#/changes")
    text = "\n".join(lines)

    def grp(x):
        new = [j for j in x.get("joined", []) if j.get("new_record")]
        tail = f" – נוספו: {', '.join(e(j['pn'] or j['name']) for j in new)}" if new else ""
        return f"<b>{e(x['name'])}</b> · {e(', '.join(x['pns']))} · <span style='color:#5f7082'>{e(', '.join(x['sources']))}</span>{tail}"

    def num(k, label, money=False):
        d = s[k]
        after = _fmt_money(d["after"], cur) if money else f"{d['after']:,}" if isinstance(d["after"], (int, float)) else "—"
        dd = d["delta"]
        sign = "" if dd is None else (f" ({_fmt_money(dd, cur)})" if money and dd else f" ({dd:+,g})" if dd else "")
        return f"<td style='padding:8px 12px;border:1px solid #dae2e8'><div style='color:#5f7082;font-size:12px'>{label}</div><div style='font-size:20px;font-family:monospace'>{after}{sign}</div></td>"
    body = f"""<div dir="rtl" style="font-family:Arial,sans-serif;color:#132030;max-width:720px">
<p style="font-size:17px"><b>{e(changes['headline'])}</b></p>
{f"<p style='color:#c2352b'>שימו לב: {e(', '.join(failed))} לא היו זמינים בסריקה הזו, והשינויים שלהם לא נספרו.</p>" if failed else ""}
<table style="border-collapse:collapse;margin:10px 0"><tr>{num('groups', 'קבוצות כפילות')}{num('redundant_pns', 'מק"טים מיותרים')}{num('redundant_stock_value', 'מלאי על מק"טים כפולים', True)}{num('quality_issues', 'ממצאי איכות')}</tr></table>
{f"<h3>כפילויות חדשות ({len(g['new'])})</h3>" + _rows(g['new'], grp) if g['new'] else ""}
{f"<h3>קבוצות שקיבלו רשומה נוספת ({len(g['grown'])})</h3>" + _rows(g['grown'], grp) if g['grown'] else ""}
{f"<p>נפתרו {len(g['resolved'])} קבוצות כפילות.</p>" if g['resolved'] else ""}
{f"<p>ממצאי נתונים חדשים: {f['quality']['n_new'] + f['erp_issues']['n_new']}. תוקנו: {f['quality']['n_resolved'] + f['erp_issues']['n_resolved']}.</p>"}
<p style="color:#5f7082;font-size:12px">{e(when)} · PartAudit קורא מהמערכות בלבד ולא משנה בהן דבר.
{f"הפרטים בתוכנה: {e(app_url)}/#/changes (במחשב שבו היא מותקנת)." if app_url else ""}</p></div>"""
    return subject, text, body


def build_message(cfg: dict, subject: str, text: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    sender = cfg.get("sender") or cfg.get("user") or "partaudit@localhost"
    msg["Subject"] = subject
    msg["From"] = formataddr(("PartAudit", sender))
    msg["To"] = ", ".join(recipients(cfg))
    msg["Date"] = dt.datetime.now().astimezone().strftime("%a, %d %b %Y %H:%M:%S %z")
    msg["Message-ID"] = make_msgid(domain="partaudit.local")
    msg.set_content(text)
    msg.add_alternative(body, subtype="html")
    return msg


def send(cfg: dict, password: str, msg: EmailMessage, timeout: float = 20.0) -> None:
    """Send through the configured server: STARTTLS (587), SSL (465) or plain (an internal relay)."""
    host, port = str(cfg.get("host") or "").strip(), int(cfg.get("port") or 0)
    if not host or not port:
        raise ValueError("לא הוגדר שרת דואר")
    if not recipients(cfg):
        raise ValueError("לא הוגדרו נמענים")
    sec = cfg.get("security") or "starttls"
    ctx = ssl.create_default_context()
    if sec == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ctx)
    else:
        server = smtplib.SMTP(host, port, timeout=timeout)
    try:
        server.ehlo()
        if sec == "starttls":
            server.starttls(context=ctx)
            server.ehlo()
        if cfg.get("user") and password:
            server.login(cfg["user"], password)
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:
            pass


def should_send(cfg: dict, changes: dict | None, trigger: str) -> bool:
    if not cfg.get("enabled") or not recipients(cfg):
        return False
    if trigger == "manual" and not cfg.get("after_manual"):
        return False
    return changes is not None and (cfg.get("on") == "always" or bool(changes.get("alert")))
