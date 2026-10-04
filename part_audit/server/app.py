"""Local web app: REST API + Hebrew UI + (optionally) the demo simulators, all on 127.0.0.1."""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
import traceback
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .. import __version__, connectors
from ..demo import DEMO_DIR, demo_sources

from ..decisions import chosen_target, effective_mapping, group_impact, group_targets, row_decision
from ..names import pn_key
from ..project import ProjectSettings
from ..runner import DEFAULT_SETTINGS, run_scan, settings_of
from . import oidc
from .auth import (COOKIE, ROLE_HE, ROLES, SESSION_MAX_S, Throttle, allowed, hash_password, password_problem, public_user,
                   required_role, username_problem, verify_password)
from .store import MASK, Store

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
LOOPBACK_NAMES = ("127.0.0.1", "localhost", "::1")
LOOPBACK_IPS = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
RUN_ID = re.compile(r"\d{8}-\d{6}-[0-9a-f]{4}")
EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}")


def _host_name(host_header: str) -> str:
    h = host_header.strip().lower()
    if h.startswith("["):                       # [::1]:8765
        return h[1:h.find("]")] if "]" in h else h
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def _host_port(host_header: str) -> int | None:
    """Port of a Host header ('127.0.0.1:8765', '[::1]:8765'; none written means 80); None if malformed."""
    h = host_header.strip()
    if h.startswith("["):
        rest = h[h.find("]") + 1:] if "]" in h else ""
    elif h.count(":") == 1:
        rest = h[h.find(":"):]
    else:
        rest = ""
    if not rest:
        return 80
    return int(rest[1:]) if rest.startswith(":") and rest[1:].isdigit() else None


# a Host header is a name or an address with an optional port - nothing else (a '?' or '#' in it could make the
# address a framework rebuilds from it disagree with the path the request is routed by)
HOST_OK = re.compile(r"(?:[A-Za-z0-9](?:[A-Za-z0-9.\-]{0,252})|\[[0-9A-Fa-f:.]{2,45}\])(?::\d{1,5})?")


def _same_origin(origin: str, host_header: str, scheme: str = "http") -> bool:
    """The page that sent the request was served by this app (same scheme, host name and port)."""
    try:
        u = urlsplit(origin.strip())
    except ValueError:
        return False
    return u.scheme == scheme and u.netloc.lower() == host_header.strip().lower()


class Jobs:
    """Background jobs (connection tests, scans) with progress for the UI."""

    def __init__(self):
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def start(self, kind: str, fn) -> str:
        jid = uuid.uuid4().hex[:10]
        job = {"id": jid, "kind": kind, "status": "running", "stage": "", "fraction": 0.0, "detail": "", "log": [],
               "started": time.time(), "result": None, "error": None, "cancel": False}
        with self.lock:
            self.jobs[jid] = job

        def progress(stage, frac, detail):
            job["stage"], job["fraction"], job["detail"] = stage, float(frac), detail
            if not job["log"] or job["log"][-1]["detail"] != detail:
                job["log"].append({"t": round(time.time() - job["started"], 1), "stage": stage, "detail": detail})
                job["log"] = job["log"][-200:]

        def run():
            try:
                job["result"] = fn(progress, lambda: job["cancel"])
                # a job that finished before it noticed the stop request is done (a scan's result is kept)
                job["status"] = "cancelled" if job["cancel"] and job["result"] is None else "done"
            except Exception as exc:  # reported to the UI
                job["status"], job["error"] = "error", f"{type(exc).__name__}: {exc}"
                job["trace"] = traceback.format_exc()
            job["finished"] = time.time()
        threading.Thread(target=run, daemon=True, name=f"job-{kind}-{jid}").start()
        return jid

    def get(self, jid: str) -> dict | None:
        j = self.jobs.get(jid)
        if j is None:
            return None
        out = {k: v for k, v in j.items() if k not in ("cancel", "trace")}
        out["elapsed"] = round((j.get("finished") or time.time()) - j["started"], 1)
        return out

    def running(self, kind: str | None = None) -> dict | None:
        for j in self.jobs.values():
            if j["status"] == "running" and (kind is None or j["kind"] == kind):
                return self.get(j["id"])
        return None


def _rebase_demo_sources(store: "Store", base_url: str) -> None:
    """The demo 'systems' run inside this app: point saved demo sources at the address the app runs on now
    (another port than last time, for example)."""
    import re
    base = base_url.rstrip("/")
    for s in store.list_sources(with_secrets=True):
        if not s["simulated"]:
            continue
        cfg = {k: (re.sub(r"^https?://(127\.0\.0\.1|localhost):\d+", base, v) if isinstance(v, str) else v)
               for k, v in s["config"].items()}
        if cfg != s["config"]:
            store.save_source({**s, "config": cfg})


def create_app(workspace: str | Path, factory_dir: str | Path | None = DEMO_DIR, demo: bool = True,
               base_url: str = "http://127.0.0.1:8765", scheduler: bool = False, team: bool = False) -> FastAPI:
    """team=False: this computer only, nobody signs in. team=True (the team server): any address on the network,
    and every request needs a signed-in user with the right role (auth.py)."""
    store = Store(workspace)
    jobs = Jobs()
    results: dict[str, dict] = {}
    # no interactive API docs: they would load scripts from a CDN
    app = FastAPI(title="PartAudit", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)

    own_port = urlsplit(base_url).port or 80

    def client_ip(request: Request) -> str:
        return request.client.host if request.client else ""

    @app.middleware("http")
    async def guard(request: Request, call_next):
        """Single computer: only this computer's browser may use the app - the Host header must be a loopback name
        (blocks DNS rebinding). Team server: every request needs a signed-in user whose role allows it, and the demo
        systems answer only the server itself. Both: a request that changes something must come from the app's own
        page (no other site as its origin)."""
        # the path the router uses, never one rebuilt from the Host header (request.url)
        host, path = request.headers.get("host", ""), request.scope.get("path", "")
        request.state.user = None
        if not HOST_OK.fullmatch(host):
            return JSONResponse({"error": "כתובת לא תקינה"}, status_code=400)
        if not team and _host_name(host) not in LOOPBACK_NAMES:
            return JSONResponse({"error": "גישה מותרת רק מהמחשב הזה (127.0.0.1)"}, status_code=403)
        if team and path.startswith("/sim/") and client_ip(request) not in LOOPBACK_IPS:
            return JSONResponse({"error": "מערכות ההדגמה זמינות רק לשרת עצמו"}, status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            site = (request.headers.get("sec-fetch-site") or "").lower()
            if ((not team and _host_port(host) != own_port)
                    or (origin is not None and not _same_origin(origin, host, request.url.scheme))
                    or site not in ("", "same-origin", "none")):
                return JSONResponse({"error": "בקשה מאתר אחר נחסמה"}, status_code=403)
            if path.startswith("/api/"):
                ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype not in ("", "application/json", "multipart/form-data"):
                    return JSONResponse({"error": "סוג בקשה לא נתמך"}, status_code=415)
        if team and not path.startswith("/sim/"):
            need = required_role(request.method, path)
            user = store.session_user(request.cookies.get(COOKIE, "")) if need is not None or path.startswith("/api/auth/") else None
            request.state.user = user
            if not allowed(user, need):
                if user is None:
                    return JSONResponse({"error": "צריך להיכנס עם שם משתמש", "login": True}, status_code=401)
                return JSONResponse({"error": f"אין לך הרשאה לפעולה הזו (נדרשת הרשאת {ROLE_HE[need]})", "forbidden": True},
                                    status_code=403)
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if path.startswith("/api/auth/") or path.startswith("/api/users"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp
    app.state.store, app.state.jobs, app.state.base_url, app.state.team = store, jobs, base_url, team
    factory_dir = Path(factory_dir) if factory_dir else None
    demo_available = bool(demo and factory_dir and (factory_dir / "factory.json").exists())
    if demo_available:
        from ..simulators import mount_simulators
        mount_simulators(app, factory_dir)
        _rebase_demo_sources(store, base_url)

    from ..viewer import MeshCache, align_meshes, compare_bytes, compare_meshes
    meshes = MeshCache(store.ws / "cache" / "meshes")
    compare_cache: dict[tuple, bytes] = {}
    align_cache: dict[tuple, dict] = {}
    cache_lock = threading.Lock()

    # ------------------------------------------------------------------ helpers
    def settings() -> dict:
        return settings_of(store)

    results_lock = threading.Lock()

    def load_result(rid: str | None) -> tuple[str, dict]:
        rid = rid if rid and rid != "latest" else store.latest_run()
        if not rid:
            raise HTTPException(404, "עדיין לא בוצעה סריקה")
        if not RUN_ID.fullmatch(rid):
            raise HTTPException(404, "הסריקה לא נמצאה")
        with results_lock:
            res = results.get(rid)
            if res is None:
                f = store.run_dir(rid) / "result.json"
                if not f.exists():
                    raise HTTPException(404, "תוצאות הסריקה לא נמצאו")
                res = json.loads(f.read_text(encoding="utf-8"))
                res["_index"] = {p["uid"]: p for p in res["parts"]}
                res["_groups"] = {g["id"]: g for g in res["groups"]}
                results.clear()  # keep one run in memory
                results[rid] = res
        return rid, res

    def with_decisions(rows: list[dict], kind: str, res: dict | None = None) -> list[dict]:
        """Rows with their latest decision; group rows (pass the run's result) also get the part number that
        stays after the engineer's approval and, when that is not the proposed one, the impact for it."""
        dec = store.current_decisions()
        idx, gby = (res["_index"], res["_groups"]) if res else ({}, {})
        out = []
        for r in rows:
            d = dec.get(f"{kind}:{r['id']}")
            row = {**r, "decision": d["decision"] if d else "", "decision_by": d["user"] if d else "",
                   "decision_at": d["created"] if d else "", "decision_note": d["note"] if d else "",
                   "decision_master": d["master_uid"] if d else ""}
            if kind == "group" and res is not None:
                g = gby.get(r["id"])
                tu = chosen_target(g, d, idx) if g else ""
                row["final_master_pn"] = idx[tu]["pn"] if g and tu != g["master_uid"] else r.get("master_pn")
                if g and tu != g["master_uid"]:
                    t_erp = (idx[tu].get("erp") or {}).get("pn")
                    row.update({k: v for k, v in group_impact(g, idx[tu]["pn"], t_erp).items() if k != "currency"})
            out.append(row)
        return out

    def similar_rows(res: dict, uid: str, near: list) -> list[dict]:
        from ..similar import relation_of
        idx = res["_index"]
        pairs = {frozenset((p["a"], p["b"])): p for p in res["pairs"] if uid in (p["a"], p["b"])}
        return [{"uid": u, "distance": round(d, 4), "relation": relation_of(idx[uid], idx[u], pairs.get(frozenset((uid, u)))),
                 "part": {k: idx[u].get(k) for k in ("uid", "pn", "name", "source", "source_kind", "state", "state_class",
                                                    "bbox", "volume_mm3", "material", "group_id", "has_step", "spec")}}
                for u, d in near if u in idx]

    def step_path(rid: str, uid: str) -> str:
        snap = store.run_dir(rid) / "step_paths.json"
        paths = json.loads(snap.read_text(encoding="utf-8")) if snap.exists() else {}
        p = paths.get(uid)
        if not p or not Path(p).exists():
            raise HTTPException(404, "אין קובץ STEP לחלק הזה")
        return p

    # ------------------------------------------------------------------ status / config
    def current(request: Request) -> dict | None:
        return getattr(request.state, "user", None)

    def actor(request: Request, named: str = "") -> str:
        """Who is doing this: the signed-in user on the team server, else the name in this computer's settings."""
        u = current(request)
        if team:
            return (u or {}).get("display_name") or (u or {}).get("username") or "משתמש"
        return (named or settings().get("user_name") or "").strip() or "משתמש"

    @app.get("/api/status")
    def status(request: Request):
        latest = store.latest_run()
        summary = None
        if latest:
            summary = next((r["summary"] for r in store.list_runs() if r["id"] == latest), None)
        st, u = settings(), current(request)
        admin = not team or (u or {}).get("role") == "admin"
        if not admin:                          # mail server and sign-in settings are for admins
            st = {k: v for k, v in st.items() if k not in ("email", "oidc")}
        return {"version": __version__, "demo_available": demo_available, "workspace": str(store.ws) if admin else "",
                "sources": len(store.list_sources()), "latest_run": latest, "summary": summary,
                "running": jobs.running(), "settings": st, "team": team, "user": public_user(u),
                "demo_loaded": any(s["simulated"] for s in store.list_sources())}

    @app.get("/api/connectors")
    def list_connectors():
        return [C.describe() for C in connectors.CONNECTORS.values()]

    @app.get("/api/settings")
    def get_settings():
        import datetime as dt

        from ..notify import SECRET
        from ..schedule import describe, next_slot
        out = settings()
        out["email"] = {**out["email"], "password": MASK if store.get_secret(SECRET) else ""}
        out["oidc"] = {**out["oidc"], "client_secret": MASK if store.get_secret(oidc.SECRET) else ""}
        out["team"] = team
        sc = out["schedule"]
        out["schedule_info"] = {"text": describe(sc), "last": store.get_settings().get("schedule_last"),
                                "next": next_slot(sc, dt.datetime.now()).isoformat(timespec="minutes")
                                if sc["enabled"] else None, "running_here": scheduler}
        return out

    @app.put("/api/settings")
    async def put_settings(request: Request):
        from ..notify import DEFAULT_EMAIL, SECRET
        from ..schedule import DEFAULT_SCHEDULE
        body = await request.json()
        old = settings()
        allowed = {k: v for k, v in body.items() if k in DEFAULT_SETTINGS and k not in ("schedule", "email", "oidc")}
        if isinstance(body.get("schedule"), dict):
            sc = {**old["schedule"], **{k: v for k, v in body["schedule"].items() if k in DEFAULT_SCHEDULE and k != "since"}}
            if sc["frequency"] not in ("daily", "weekly") or not re.fullmatch(r"\d{1,2}:\d{2}", str(sc["time"])):
                raise HTTPException(400, "תזמון לא תקין")
            sc["weekday"] = int(sc["weekday"]) % 7
            sc["enabled"] = bool(sc["enabled"])
            if sc["enabled"] and not old["schedule"]["enabled"]:
                sc["since"] = time.strftime("%Y-%m-%dT%H:%M:%S")     # no catch-up for times before it was turned on
            allowed["schedule"] = sc
        if isinstance(body.get("email"), dict):
            em = {**old["email"], **{k: v for k, v in body["email"].items() if k in DEFAULT_EMAIL}}
            if em["security"] not in ("starttls", "ssl", "none") or em["on"] not in ("changes", "always"):
                raise HTTPException(400, "הגדרות דואר לא תקינות")
            try:
                em["port"] = int(em["port"])
            except (TypeError, ValueError):
                raise HTTPException(400, "פורט לא תקין")
            em["enabled"], em["after_manual"] = bool(em["enabled"]), bool(em["after_manual"])
            pw = body["email"].get("password")
            if pw and pw != MASK:
                store.set_secret(SECRET, pw)
            elif em["host"] != old["email"]["host"] or em["user"] != old["email"]["user"]:
                store.set_secret(SECRET, "")      # a password is never sent to a server it was not entered for
            allowed["email"] = em
        if isinstance(body.get("oidc"), dict):
            oc = {**old["oidc"], **{k: v for k, v in body["oidc"].items() if k in oidc.DEFAULT_OIDC}}
            oc["enabled"], oc["auto_create"] = bool(oc["enabled"]), bool(oc["auto_create"])
            oc["issuer"], oc["client_id"] = str(oc["issuer"]).strip().rstrip("/"), str(oc["client_id"]).strip()
            oc["label"] = str(oc["label"]).strip()[:60] or oidc.DEFAULT_OIDC["label"]
            if oc["default_role"] not in ("viewer", "engineer"):
                raise HTTPException(400, "משתמש חדש מחשבון החברה יכול לקבל הרשאת צפייה או מהנדס")
            if oc["issuer"]:
                try:
                    oidc._check_url(oc["issuer"])
                except oidc.OIDCError as exc:
                    raise HTTPException(400, str(exc))
            if oc["enabled"] and not (oc["issuer"] and oc["client_id"]):
                raise HTTPException(400, "לכניסה עם חשבון החברה צריך כתובת ספק זהות (Issuer) ו-Client ID")
            sec = body["oidc"].get("client_secret")
            if sec and sec != MASK:
                store.set_secret(oidc.SECRET, str(sec))
            elif oc["issuer"] != old["oidc"]["issuer"] or oc["client_id"] != old["oidc"]["client_id"]:
                store.set_secret(oidc.SECRET, "")     # a secret is never sent to a provider it was not entered for
            if oc["issuer"] != old["oidc"]["issuer"]:
                oidc.clear_cache()
            allowed["oidc"] = oc
        store.set_settings(allowed)
        return get_settings()

    # ------------------------------------------------------------------ team mode: sign-in and users
    user_throttle, ip_throttle = Throttle(limit=5), Throttle(limit=20)
    pending_sign_ins: dict[str, dict] = {}
    OIDC_COOKIE = "pa_oidc"

    def set_cookie(resp: Response, name: str, value: str, max_age: int, request: Request, path: str = "/") -> None:
        resp.set_cookie(name, value, max_age=max_age, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", path=path)

    def to_login(message: str) -> RedirectResponse:
        from urllib.parse import quote
        resp = RedirectResponse("/?login_error=" + quote(message[:300]), status_code=303)
        resp.delete_cookie(OIDC_COOKIE, path="/api/auth/oidc")
        return resp

    @app.get("/api/auth/me")
    def auth_me(request: Request):
        oc = settings()["oidc"]
        return {"team": team, "user": public_user(current(request)), "roles": ROLE_HE,
                "oidc": {"enabled": bool(team and oc["enabled"] and oc["issuer"] and oc["client_id"]), "label": oc["label"]}}

    @app.post("/api/auth/login")
    async def auth_login(request: Request):
        if not team:
            raise HTTPException(400, "במצב של מחשב אחד אין צורך בכניסה")
        body = await request.json()
        name, pw = str(body.get("username") or "").strip()[:120], str(body.get("password") or "")[:1024]
        ukey, ikey = f"u:{name.lower()}", f"ip:{client_ip(request)}"
        wait = max(user_throttle.wait(ukey), ip_throttle.wait(ikey))
        if wait:
            raise HTTPException(429, f"יותר מדי ניסיונות כניסה שגויים. נסו שוב בעוד {max(1, round(wait / 60))} דקות")
        u = store.find_user(name) if name else None
        ok = await run_in_threadpool(verify_password, pw, (u or {}).get("pw_hash"))
        if not ok or not u:
            user_throttle.fail(ukey)
            ip_throttle.fail(ikey)
            raise HTTPException(401, "שם המשתמש או הסיסמה שגויים")
        if u["disabled"]:
            raise HTTPException(403, "המשתמש הושבת – פנו למנהל המערכת")
        user_throttle.ok(ukey)
        resp = JSONResponse({"ok": True, "user": public_user(store.get_user(u["id"]))})
        set_cookie(resp, COOKIE, store.new_session(u["id"], "password"), SESSION_MAX_S, request)
        return resp

    @app.post("/api/auth/logout")
    def auth_logout(request: Request):
        tok = request.cookies.get(COOKIE)
        if tok:
            store.end_session(tok)
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    @app.post("/api/auth/password")
    async def auth_password(request: Request):
        """A signed-in user changes their own password; their other sessions end."""
        u = current(request)
        if not team or not u:
            raise HTTPException(400, "במצב של מחשב אחד אין סיסמאות")
        if not u.get("pw_hash"):
            raise HTTPException(400, "נכנסת עם חשבון החברה – הסיסמה מנוהלת שם")
        body = await request.json()
        if not await run_in_threadpool(verify_password, str(body.get("current") or ""), u["pw_hash"]):
            raise HTTPException(400, "הסיסמה הנוכחית שגויה")
        new = str(body.get("new") or "")
        problem = password_problem(new, u["username"])
        if problem:
            raise HTTPException(400, problem)
        store.update_user(u["id"], pw_hash=await run_in_threadpool(hash_password, new))
        store.end_user_sessions(u["id"], keep_token=request.cookies.get(COOKIE))
        return {"ok": True}

    @app.get("/api/auth/oidc/start")
    def oidc_start(request: Request):
        oc = settings()["oidc"]
        if not team or not oc["enabled"]:
            return to_login("הכניסה עם חשבון החברה לא מופעלת")
        callback = f"{request.url.scheme}://{request.headers.get('host', '')}/api/auth/oidc/callback"
        try:
            url, pending = oidc.start(oc, callback)
        except oidc.OIDCError as exc:
            return to_login(str(exc))
        now_t = time.time()
        for k in [k for k, v in pending_sign_ins.items() if now_t - v["at"] > oidc.PENDING_S]:
            pending_sign_ins.pop(k, None)
        while len(pending_sign_ins) >= 500:
            pending_sign_ins.pop(next(iter(pending_sign_ins)))
        pending_sign_ins[pending["state"]] = pending
        resp = RedirectResponse(url, status_code=302)
        set_cookie(resp, OIDC_COOKIE, pending["state"], oidc.PENDING_S, request, path="/api/auth/oidc")
        return resp

    def company_user(ident: dict, oc: dict) -> dict:
        """The account of a company sign-in: the one linked before; else an account an admin added for company
        sign-in (no password) with the same e-mail - only when the provider vouches for that e-mail; else a new one.
        An account with a password is never taken over by a company sign-in."""
        u = store.find_user_oidc(ident["sub"])
        if not u and ident["email"] and ident["email_trusted"]:
            cand = store.find_user(ident["email"]) or next((x for x in store.list_users()
                                                             if (x.get("email") or "").lower() == ident["email"]), None)
            if cand and cand.get("oidc_sub"):
                raise oidc.OIDCError("המשתמש עם המייל הזה כבר מקושר לחשבון חברה אחר")
            if cand and cand.get("pw_hash"):
                raise oidc.OIDCError("קיים משתמש עם המייל הזה שנכנס עם סיסמה. מנהל המערכת יכול להעביר אותו לכניסה "
                                     "עם חשבון החברה (הגדרות > צוות)")
            if cand:
                u = store.update_user(cand["id"], oidc_sub=ident["sub"], email=ident["email"])
        if not u:
            if not oc["auto_create"]:
                raise oidc.OIDCError("החשבון שלך עוד לא נוסף ל-PartAudit – בקשו ממנהל המערכת להוסיף אתכם")
            base = (ident["email"] or ident["login"] or ident["sub"].split("|", 1)[-1])[:100]
            name, n = base, 1
            while store.find_user(name):
                n += 1
                name = f"{base}-{n}"
            u = store.add_user(name, oc["default_role"] if oc["default_role"] in ("viewer", "engineer") else "viewer",
                               display_name=ident["name"], email=ident["email"], oidc_sub=ident["sub"])
        if u["disabled"]:
            raise oidc.OIDCError("המשתמש שלך הושבת ב-PartAudit – פנו למנהל המערכת")
        return u

    @app.get("/api/auth/oidc/callback")
    def oidc_callback(request: Request, code: str = "", state: str = "", error: str = "", error_description: str = ""):
        import hmac
        oc = settings()["oidc"]
        pending = pending_sign_ins.pop(state, None) if state else None
        if not team or not oc["enabled"]:
            return to_login("הכניסה עם חשבון החברה לא מופעלת")
        if error:
            return to_login(f"ספק הזהות לא השלים את הכניסה: {(error_description or error)[:200]}")
        cookie = request.cookies.get(OIDC_COOKIE, "")
        if not pending or not code or not cookie or not hmac.compare_digest(cookie, state):
            return to_login("הכניסה לא הושלמה – נסו שוב")
        try:
            claims = oidc.finish(oc, store.get_secret(oidc.SECRET), code, pending)
            u = company_user(oidc.identity(oc, claims), oc)
        except oidc.OIDCError as exc:
            return to_login(str(exc))
        resp = RedirectResponse("/", status_code=303)
        resp.delete_cookie(OIDC_COOKIE, path="/api/auth/oidc")
        set_cookie(resp, COOKIE, store.new_session(u["id"], "oidc"), SESSION_MAX_S, request)
        return resp

    @app.post("/api/auth/oidc/test")
    def oidc_test():
        """Settings screen: reach the provider entered there and check it publishes what sign-in needs."""
        try:
            return {"ok": True, **oidc.check_config(settings()["oidc"])}
        except oidc.OIDCError as exc:
            raise HTTPException(400, str(exc))

    def keep_an_admin(u: dict, role: str | None, disabled: bool | None) -> None:
        losing = u["role"] == "admin" and not u["disabled"] and ((role and role != "admin") or disabled)
        if losing and store.count_admins(except_id=u["id"]) == 0:
            raise HTTPException(400, "חייב להישאר לפחות מנהל פעיל אחד")

    @app.get("/api/users")
    def users_list():
        return {"users": [public_user(u) for u in store.list_users()], "roles": ROLE_HE, "team": team,
                "admins": store.count_admins()}

    @app.post("/api/users")
    async def users_add(request: Request):
        body = await request.json()
        name = str(body.get("username") or "").strip()
        problem = username_problem(name)
        if problem:
            raise HTTPException(400, problem)
        if store.find_user(name):
            raise HTTPException(400, "כבר יש משתמש בשם הזה")
        if body.get("role") not in ROLES:
            raise HTTPException(400, "הרשאה לא מוכרת")
        email = str(body.get("email") or "").strip().lower()[:200]
        if body.get("company"):
            # signs in only with the company account: linked at the first company sign-in with this e-mail
            email = email or name.lower()
            if not EMAIL.fullmatch(email):
                raise HTTPException(400, "למשתמש של חשבון החברה צריך כתובת מייל")
            if store.find_user(email) and email != name.lower():
                raise HTTPException(400, "כבר יש משתמש עם המייל הזה")
            pw_hash = None
        else:
            pw = str(body.get("password") or "")
            problem = password_problem(pw, name)
            if problem:
                raise HTTPException(400, problem)
            pw_hash = await run_in_threadpool(hash_password, pw)
        u = store.add_user(name, body["role"], display_name=str(body.get("display_name") or "")[:120], email=email,
                           pw_hash=pw_hash)
        return public_user(u)

    @app.put("/api/users/{uid}")
    async def users_update(uid: int, request: Request):
        u = store.get_user(uid)
        if not u:
            raise HTTPException(404, "המשתמש לא נמצא")
        body = await request.json()
        fields: dict = {}
        if "display_name" in body:
            fields["display_name"] = str(body["display_name"] or "").strip()[:120] or u["username"]
        if "email" in body:
            fields["email"] = str(body["email"] or "").strip().lower()[:200]
        if "role" in body:
            if body["role"] not in ROLES:
                raise HTTPException(400, "הרשאה לא מוכרת")
            fields["role"] = body["role"]
        if "disabled" in body:
            fields["disabled"] = 1 if body["disabled"] else 0
        keep_an_admin(u, fields.get("role"), bool(fields.get("disabled")))
        if body.get("company_only") and u.get("pw_hash"):
            # from now on only the company account: the password goes, the account is linked at the next company
            # sign-in with its e-mail
            email = (fields.get("email") or u.get("email") or u["username"]).lower()
            if not EMAIL.fullmatch(email):
                raise HTTPException(400, "קודם צריך לשמור למשתמש כתובת מייל")
            if u["role"] == "admin" and not u.get("oidc_sub") and store.count_admins(except_id=u["id"]) == 0:
                raise HTTPException(400, "חייב להישאר לפחות מנהל אחד שיכול להיכנס")
            fields.update(pw_hash=None, email=email)
        elif body.get("password"):
            problem = password_problem(str(body["password"]), u["username"])
            if problem:
                raise HTTPException(400, problem)
            fields["pw_hash"] = await run_in_threadpool(hash_password, str(body["password"]))
        store.update_user(uid, **fields)
        if fields.get("disabled") or "pw_hash" in fields:
            me = current(request)
            store.end_user_sessions(uid, keep_token=request.cookies.get(COOKIE) if me and me["id"] == uid else None)
        return public_user(store.get_user(uid))

    # ------------------------------------------------------------------ sources
    @app.get("/api/sources")
    def sources():
        return store.list_sources()

    @app.post("/api/sources")
    async def add_source(request: Request):
        body = await request.json()
        if body.get("kind") not in connectors.CONNECTORS:
            raise HTTPException(400, "סוג מקור לא מוכר")
        return store.save_source({"kind": body["kind"], "name": body.get("name") or connectors.get(body["kind"]).title,
                                  "config": body.get("config") or {}, "enabled": body.get("enabled", True)})

    @app.put("/api/sources/{sid}")
    async def update_source(sid: str, request: Request):
        old = store.get_source(sid, with_secrets=False)
        if not old:
            raise HTTPException(404, "המקור לא נמצא")
        body = await request.json()
        return store.save_source({"id": sid, "kind": old["kind"], "name": body.get("name", old["name"]),
                                  "config": body.get("config", old["config"]),
                                  "enabled": body.get("enabled", old["enabled"]), "simulated": old["simulated"]})

    @app.delete("/api/sources/{sid}")
    def delete_source(sid: str):
        store.delete_source(sid)
        discovery_file(sid).unlink(missing_ok=True)
        return {"ok": True}

    @app.post("/api/sources/{sid}/test")
    def test_source(sid: str):
        src = store.get_source(sid, with_secrets=True)
        if not src:
            raise HTTPException(404, "המקור לא נמצא")
        C = connectors.get(src["kind"])
        t0 = time.time()
        try:
            res = C(sid, src["name"], src["config"], store.ws / "cache" / "connectors").test()
        except Exception as exc:
            res = {"ok": False, "message": f"{type(exc).__name__}: {exc}", "details": {}}
        res["seconds"] = round(time.time() - t0, 2)
        store.set_test_result(sid, res)
        return res

    # ------------------------------------------------------------------ pilot: field discovery
    def discovery_file(sid: str) -> Path:
        return store.ws / "discovery" / f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', sid)}.json"

    @app.post("/api/sources/{sid}/discover")
    def discover_source(sid: str):
        """Read a small sample (no file downloads) and suggest the field mapping; nothing is changed."""
        from ..discovery import analyze
        src = store.get_source(sid, with_secrets=True)
        if not src:
            raise HTTPException(404, "המקור לא נמצא")
        C = connectors.get(src["kind"])
        t0 = time.time()
        conn = C(sid, src["name"], src["config"], store.ws / "cache" / "connectors")
        try:
            smp = conn.sample(40)
        except NotImplementedError:
            raise HTTPException(400, "גילוי שדות לא זמין לסוג החיבור הזה")
        except Exception as exc:
            raise HTTPException(502, f"קריאת המדגם נכשלה: {exc}")
        res = analyze(C, conn.cfg, smp)
        res.update({"source": {"id": sid, "name": src["name"], "kind": src["kind"], "title": C.title,
                               "interface": C.interface, "simulated": src["simulated"]},
                    "seconds": round(time.time() - t0, 2), "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "pn_regex": smp.get("pn_regex"), "pn_found": smp.get("pn_found"), "files": smp.get("files")})
        f = discovery_file(sid)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        return res

    @app.get("/api/sources/{sid}/discovery")
    def last_discovery(sid: str):
        f = discovery_file(sid)
        if not f.exists():
            raise HTTPException(404, "עדיין לא בוצע גילוי שדות למקור הזה")
        return json.loads(f.read_text(encoding="utf-8"))

    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...)):
        raw = Path(file.filename or "upload").name
        stem, suffix = Path(raw).stem, Path(raw).suffix.lower()
        name = (re.sub(r"[^\w.\- ]+", "_", stem, flags=re.UNICODE).strip() or "upload")[:60] + suffix
        if Path(name).suffix.lower() not in (".xlsx", ".xlsm", ".csv", ".txt"):
            raise HTTPException(400, "ניתן להעלות קבצי Excel (.xlsx) או CSV בלבד")
        dest = store.ws / "uploads" / f"{time.strftime('%Y%m%d-%H%M%S')}_{name}"
        dest.write_bytes(await file.read())
        return {"path": str(dest), "name": name}

    @app.post("/api/demo/load")
    def load_demo():
        if not demo_available:
            raise HTTPException(400, "נתוני ההדגמה לא נמצאו בהתקנה")
        existing = {s["id"] for s in store.list_sources()}
        for s in demo_sources(app.state.base_url, factory_dir):
            if s["id"] not in existing:
                store.save_source(s)
        return store.list_sources()

    # ------------------------------------------------------------------ scan
    def clear_results():
        with results_lock:
            results.clear()

    def start_scan_job(trigger: str = "manual") -> str:
        def work(progress, should_stop):
            return run_scan(store, progress, should_stop, trigger=trigger, app_url=app.state.base_url,
                            on_done=clear_results)
        return jobs.start("scan", work)

    @app.post("/api/scan")
    def scan():
        if jobs.running("scan"):
            raise HTTPException(409, "סריקה כבר רצה")
        return {"job_id": start_scan_job("manual")}

    if scheduler:      # the app started by a person (not tests or the export tool) runs the scan schedule
        from ..schedule import Scheduler
        app.state.scheduler = Scheduler(
            get_schedule=lambda: settings()["schedule"], get_last=lambda: store.get_settings().get("schedule_last"),
            set_last=lambda t: store.set_settings({"schedule_last": t}),
            start_scan=lambda: not jobs.running("scan") and bool(start_scan_job("schedule"))).start()

    @app.get("/api/jobs/{jid}")
    def job(jid: str):
        j = jobs.get(jid)
        if not j:
            raise HTTPException(404, "המשימה לא נמצאה")
        return j

    @app.post("/api/jobs/{jid}/cancel")
    def cancel(jid: str):
        if jid in jobs.jobs:
            jobs.jobs[jid]["cancel"] = True
        return {"ok": True}

    @app.get("/api/runs")
    def runs():
        return store.list_runs()

    # ------------------------------------------------------------------ changes since the scan before
    changes_cache: dict[tuple, dict] = {}

    @app.get("/api/runs/{rid}/changes")
    def run_changes(rid: str, base: str = ""):
        """What changed between a scan and the one before it (or the scan named in 'base')."""
        from ..changes import compare_runs
        from ..runner import failed_sources, load_result as read_result
        rid = rid if rid != "latest" else (store.latest_run() or "")
        if not RUN_ID.fullmatch(rid) or (base and not RUN_ID.fullmatch(base)):
            raise HTTPException(404, "הסריקה לא נמצאה")
        prev = base or store.previous_run(rid)
        if not prev:
            return {"available": False, "reason": "first", "to": {"run_id": rid}}
        f = store.run_dir(rid) / "changes.json"
        if not base and f.exists():
            ch = json.loads(f.read_text(encoding="utf-8"))
        else:
            key = (prev, rid)
            if key not in changes_cache:
                old, new = read_result(store, prev), read_result(store, rid)
                if old is None or new is None:
                    raise HTTPException(404, "תוצאות הסריקה לא נמצאו")
                ch = compare_runs(old, new)
                ch["failed_sources"] = failed_sources(new)
                with cache_lock:
                    if len(changes_cache) > 8:
                        changes_cache.clear()
                    changes_cache[key] = ch
            ch = changes_cache[key]
        nf = store.run_dir(rid) / "notify.json"
        return {"available": True, **ch, "notify": json.loads(nf.read_text(encoding="utf-8")) if nf.exists() else None}

    TREND_KEYS = ("parts", "assemblies", "with_step", "erp_linked", "groups", "groups_cross_source", "redundant_pns",
                  "redundant_stock_value", "currency", "bom_lines_to_update", "near_pairs", "quality_issues", "erp_issues")

    @app.get("/api/trends")
    def trends():
        """Every finished scan, oldest first: its numbers and what changed since the scan before (when known); and
        how many duplicate groups had an approved decision at the time of each scan."""
        decisions = sorted((d for d in store.all_decisions() if d["target_type"] == "group"), key=lambda d: d["id"])
        runs = list(reversed(store.list_runs()))
        order = {r["id"]: i for i, r in enumerate(runs)}
        out = []
        for i, r in enumerate(runs):
            if r["status"] != "done" or not r["summary"]:
                continue
            ch, f = None, store.run_dir(r["id"]) / "changes.json"
            if f.exists():
                c = json.loads(f.read_text(encoding="utf-8"))
                fi = c["findings"]
                ch = {"new_groups": len(c["groups"]["new"]), "grown_groups": len(c["groups"]["grown"]),
                      "resolved_groups": len(c["groups"]["resolved"]), "shrunk_groups": len(c["groups"]["shrunk"]),
                      "new_findings": fi["quality"]["n_new"] + fi["erp_issues"]["n_new"],
                      "resolved_findings": fi["quality"]["n_resolved"] + fi["erp_issues"]["n_resolved"],
                      "added": c["records"]["n_added"], "removed": c["records"]["n_removed"],
                      "unread": c.get("unread_sources") or []}
            latest: dict[str, str] = {}
            for d in decisions:
                # in effect when the scan ran: made on the results of an earlier scan (timestamps only when the
                # decision does not say which scan it was made on - they have one-second resolution)
                k = order.get(d.get("run_id") or "")
                if (k is not None and k < i) or (k is None and d["created"] < r["created"]):
                    latest[d["target_id"]] = d["decision"]
            out.append({"run_id": r["id"], "created": r["created"], "trigger": r["trigger"],
                        "summary": {k: r["summary"].get(k) for k in TREND_KEYS}, "changes": ch,
                        "approved_groups": sum(1 for v in latest.values() if v == "approve")})
        return {"runs": out}

    @app.post("/api/notify/test")
    def notify_test():
        """A short test message through the configured mail server."""
        from ..notify import SECRET, build_message, recipients, send
        em = settings()["email"]
        text = "זו הודעת בדיקה מ-PartAudit. אם קיבלתם אותה, ההתראות אחרי סריקה מתוזמנת יגיעו לכתובת הזו."
        msg = build_message(em, "PartAudit – הודעת בדיקה", text, f'<div dir="rtl" style="font-family:Arial">{text}</div>')
        try:
            send(em, store.get_secret(SECRET), msg)
        except Exception as exc:
            raise HTTPException(502, f"השליחה נכשלה: {type(exc).__name__}: {exc}")
        return {"ok": True, "to": recipients(em)}

    # ------------------------------------------------------------------ results
    @app.get("/api/runs/{rid}/summary")
    def run_summary(rid: str):
        rid, res = load_result(rid)
        dec = store.current_decisions()
        pending = sum(1 for g in res["groups"] if f"group:{g['id']}" not in dec)
        approved = sum(1 for g in res["groups"] if (dec.get(f"group:{g['id']}") or {}).get("decision") == "approve")
        by_type: dict[str, int] = {}
        for q in res["quality"] + res["erp_issues"]:
            if q["severity"] != "info":
                by_type[q["type_he"]] = by_type.get(q["type_he"], 0) + 1
        by_source: dict[str, dict] = {}
        idx = res["_index"]
        for p in res["parts"]:
            if p["kind"] != "part":
                continue
            d = by_source.setdefault(p["source"], {"parts": 0, "in_groups": 0, "near": 0, "kind": p["source_kind"]})
            d["parts"] += 1
            d["in_groups"] += 1 if p["group_id"] else 0
            d["near"] += 1 if p["near_count"] else 0
        cross: dict[str, int] = {}
        for g in res["groups"]:
            srcs = sorted({idx[u]["source"] for u in g["members"]})
            for i in range(len(srcs)):
                for j in range(i + 1, len(srcs)):
                    k = f"{srcs[i]}|{srcs[j]}"
                    cross[k] = cross.get(k, 0) + 1
        summ = dict(res["summary"])
        final = with_decisions(res["groups"], "group", res)
        summ["redundant_stock_value"] = round(sum(g["redundant_stock_value"] for g in final
                                                  if g.get("currency", summ["currency"]) == summ["currency"]), 2)
        summ["bom_lines_to_update"] = sum(g["bom_lines_to_update"] for g in final)
        top = sorted(final, key=lambda g: (-(g["redundant_stock_value"] or 0), -len(g["members"])))[:10]
        ch_f = store.run_dir(rid) / "changes.json"
        changes = None
        if ch_f.exists():
            ch = json.loads(ch_f.read_text(encoding="utf-8"))
            fi = ch["findings"]
            changes = {"from": ch["from"], "headline": ch["headline"], "alert": ch["alert"],
                       "new_groups": len(ch["groups"]["new"]), "grown_groups": len(ch["groups"]["grown"]),
                       "resolved_groups": len(ch["groups"]["resolved"]),
                       "new_findings": fi["quality"]["n_new"] + fi["erp_issues"]["n_new"],
                       "resolved_findings": fi["quality"]["n_resolved"] + fi["erp_issues"]["n_resolved"]}
        return {"run_id": rid, "created": res["created"], "demo": res.get("demo", False), "summary": summ,
                "changes": changes, "trigger": res.get("trigger", "manual"),
                "timings": res["timings"], "sources": res["sources"], "decisions": {"pending_groups": pending,
                                                                                     "approved_groups": approved},
                "issues_by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1])), "by_source": by_source,
                "cross_source": cross, "top_groups": top}

    @app.get("/api/runs/{rid}/groups")
    def groups(rid: str):
        rid, res = load_result(rid)
        idx = res["_index"]
        rows = []
        for g in res["groups"]:
            rows.append({k: g.get(k) for k in ("id", "category", "pns", "sources", "cross_source", "master_uid",
                                               "master_pn", "confidence", "spec", "name", "redundant_pns",
                                               "redundant_stock_value", "stock_value", "bom_lines_to_update",
                                               "currency")}
                        | {"n_members": len(g["members"]), "n_used": len(g["where_used"]),
                           "family": idx[g["master_uid"]]["make_buy"]})
        return with_decisions(rows, "group", res)

    @app.get("/api/runs/{rid}/groups/{gid}")
    def group(rid: str, gid: str):
        rid, res = load_result(rid)
        g = next((x for x in res["groups"] if x["id"] == gid), None)
        if not g:
            raise HTTPException(404, "הקבוצה לא נמצאה")
        idx = res["_index"]
        mem = set(g["members"])
        pairs = [p for p in res["pairs"] if p["a"] in mem and p["b"] in mem]
        out = dict(g, parts=[idx[u] for u in g["members"]], pairs=pairs,
                   history=store.decision_history("group", gid))
        return with_decisions([out], "group", res)[0]

    @app.get("/api/runs/{rid}/pairs")
    def pairs(rid: str, category: str = ""):
        rid, res = load_result(rid)
        idx = res["_index"]
        cats = set(category.split(",")) if category else None
        rows = []
        for p in res["pairs"]:
            if cats and p["category"] not in cats:
                continue
            a, b = idx[p["a"]], idx[p["b"]]
            rows.append({k: p[k] for k in ("id", "a", "b", "category", "category_he", "geo_relation", "confidence",
                                           "reason_he", "hint_he", "name_score", "cross_source", "spec_note")}
                        | {"metrics": {k: (p.get("metrics") or {}).get(k) for k in ("d_volume", "d_area", "p95_mm",
                                                                                    "max_rel", "scale")},
                           "a_pn": a["pn"], "a_name": a["name"], "a_source": a["source"], "b_pn": b["pn"],
                           "b_name": b["name"], "b_source": b["source"], "has_step": a["has_step"] and b["has_step"]})
        return with_decisions(rows, "pair")

    @app.get("/api/runs/{rid}/pairs/{pid}")
    def pair(rid: str, pid: str):
        rid, res = load_result(rid)
        p = next((x for x in res["pairs"] if x["id"] == pid), None)
        if not p:
            raise HTTPException(404, "הזוג לא נמצא")
        idx = res["_index"]
        out = dict(p, part_a=idx[p["a"]], part_b=idx[p["b"]], history=store.decision_history("pair", pid))
        return with_decisions([out], "pair")[0]

    @app.get("/api/runs/{rid}/findings/{kind}")
    def findings(rid: str, kind: str):
        rid, res = load_result(rid)
        idx = res["_index"]
        if kind not in ("names", "quality", "erp_issues"):
            raise HTTPException(404, "סוג לא מוכר")
        rows = []
        for q in res[kind]:
            ps = [idx[u] for u in q.get("uids", []) if u in idx]
            rows.append(dict(q, parts=[{k: p[k] for k in ("uid", "pn", "name", "source", "state", "kind")} for p in ps]))
        return with_decisions(rows, "issue")

    @app.get("/api/runs/{rid}/mapping")
    def mapping(rid: str):
        rid, res = load_result(rid)
        dec = store.current_decisions()
        # the row's own decision or its group's, whichever was made last
        return [{**r, **row_decision(r, dec)} for r in effective_mapping(res, dec)]

    @app.get("/api/runs/{rid}/parts")
    def parts_list(rid: str, q: str = "", source: str = "", kind: str = "", flag: str = "", limit: int = 200,
                   offset: int = 0):
        rid, res = load_result(rid)
        rows = res["parts"]
        if q:
            ql = q.lower()
            rows = [p for p in rows if ql in (p["pn"] or "").lower() or ql in (p["name"] or "").lower()
                    or ql in (p["native_file"] or "").lower() or ql in (p["description"] or "").lower()]
        if source:
            rows = [p for p in rows if p["source"] == source]
        if kind:
            rows = [p for p in rows if p["kind"] == kind]
        if flag == "group":
            rows = [p for p in rows if p["group_id"]]
        elif flag == "near":
            rows = [p for p in rows if p["near_count"]]
        elif flag == "issues":
            rows = [p for p in rows if p["issues"]]
        elif flag == "nostep":
            rows = [p for p in rows if p["kind"] == "part" and not p["has_step"]]
        return {"total": len(rows), "rows": rows[offset:offset + limit]}

    @app.get("/api/runs/{rid}/parts/{uid:path}")
    def part(rid: str, uid: str):
        rid, res = load_result(rid)
        idx = res["_index"]
        p = idx.get(uid)
        if not p:
            raise HTTPException(404, "החלק לא נמצא")
        parents = [{"uid": a, **{k: idx[a][k] for k in ("pn", "name", "source", "state", "state_class")}, "qty": line["qty"]}
                   for a, lines in res["bom"].items() for line in lines if line["child"] == uid and a in idx]
        children = [{"uid": c["child"], **{k: idx[c["child"]][k] for k in ("pn", "name", "source", "state", "state_class",
                                                                           "kind")},
                     "qty": c["qty"]} for c in res["bom"].get(uid, []) if c["child"] in idx]
        # the ERP BOM names the ERP item the part is linked to (the ERP may write the number with other dashes)
        erp_child = pn_key((p.get("erp") or {}).get("pn") or p["pn"] or "")
        erp_parents = [b for b in res.get("erp_bom", []) if erp_child and pn_key(b["child"]) == erp_child]
        rel_pairs = [dict(x, other=idx[x["b"] if x["a"] == uid else x["a"]]) for x in res["pairs"]
                     if uid in (x["a"], x["b"])]
        issues = [q for q in res["quality"] + res["erp_issues"] if uid in q.get("uids", [])]
        snap_f = store.run_dir(rid) / "snapshot.json"
        hist, props = [], {}
        if snap_f.exists():
            snap = json.loads(snap_f.read_text(encoding="utf-8"))
            rec = next((r for r in snap["records"] if r["uid"] == uid), None)
            if rec:
                hist, props = rec.get("history") or [], rec.get("props") or {}
        # products (top-level assemblies) reached through where-used
        tops, stack, seen = set(), [uid], set()
        while stack:
            u = stack.pop()
            if u in seen:
                continue
            seen.add(u)
            ps = [a for a, lines in res["bom"].items() for line in lines if line["child"] == u]
            if not ps and u != uid:
                tops.add(u)
            stack.extend(ps)
        return {**p, "parents": parents, "children": children, "erp_parents": erp_parents, "pairs": rel_pairs,
                "issues": issues, "history": hist, "props": props,
                "products": [{"uid": t, "pn": idx[t]["pn"], "name": idx[t]["name"]} for t in tops if t in idx]}

    variety_cache: dict[str, dict] = {}

    @app.get("/api/runs/{rid}/variety")
    def variety(rid: str):
        """Standard parts by specification and designed parts by family: what is in use and how much (measured)."""
        from ..variety import analyze
        rid, res = load_result(rid)
        if rid not in variety_cache:
            variety_cache.clear()
            variety_cache[rid] = analyze(res)
        return variety_cache[rid]

    @app.get("/api/runs/{rid}/similar/{uid:path}")
    def similar(rid: str, uid: str, k: int = 10):
        """Parts whose shape is closest to this one (shape search), with the engine's verdict where it has one."""
        rid, res = load_result(rid)
        idx = res["_index"]
        if uid not in idx:
            raise HTTPException(404, "החלק לא נמצא")
        si = shape_index(rid)
        if uid not in si:
            return {"available": False, "uid": uid, "rows": []}
        return {"available": True, "uid": uid, "compared": len(si) - 1,
                "rows": similar_rows(res, uid, si.nearest_to(uid, max(1, min(k, 30))))}

    # ------------------------------------------------------------------ 3D
    @app.get("/api/mesh/{rid}/{uid:path}")
    def mesh(rid: str, uid: str):
        rid, _ = load_result(rid)
        try:
            data = meshes.get_bytes(step_path(rid, uid))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"לא ניתן להכין תצוגה תלת-ממדית: {exc}")
        return Response(data, media_type="application/octet-stream", headers={"Cache-Control": "max-age=3600"})

    def pair_scale(res: dict, a: str, b: str) -> tuple[dict | None, float]:
        pair = next((p for p in res["pairs"] if {p["a"], p["b"]} == {a, b}), None)
        scale = 1.0
        if pair and (pair.get("metrics") or {}).get("scale"):
            s = pair["metrics"]["scale"]
            scale = s if pair["b"] == b else 1.0 / s
        return pair, scale

    @app.get("/api/align/{rid}")
    def align(rid: str, a: str, b: str):
        """Rotation that shows part b in the same orientation as part a (display only; never mirrored)."""
        rid, res = load_result(rid)
        key = (rid, a, b)
        if key not in align_cache:
            _, scale = pair_scale(res, a, b)
            try:
                al = align_meshes(meshes.get(step_path(rid, a)), meshes.get(step_path(rid, b)), scale_b=scale,
                                  proper_only=True)
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(500, f"היישור נכשל: {exc}")
            with cache_lock:
                if len(align_cache) > 512:
                    align_cache.clear()
                align_cache[key] = {"matrix": al["matrix"], "mirror": al["mirror"], "scale": scale}
                return align_cache[key]
        return align_cache.get(key) or align(rid, a, b)

    @app.get("/api/compare/{rid}")
    def compare(rid: str, a: str, b: str, mirror: bool = False):
        rid, res = load_result(rid)
        key = (rid, a, b, mirror)
        if key not in compare_cache:
            pair, scale = pair_scale(res, a, b)
            try:
                c = compare_meshes(meshes.get(step_path(rid, a)), meshes.get(step_path(rid, b)), scale_b=scale,
                                   mirror=mirror or (pair or {}).get("geo_relation") == "mirror")
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(500, f"ההשוואה נכשלה: {exc}")
            data = compare_bytes(c)
            with cache_lock:
                if len(compare_cache) > 24:
                    compare_cache.clear()
                compare_cache[key] = data
            return Response(data, media_type="application/octet-stream")
        data = compare_cache.get(key)
        return Response(data, media_type="application/octet-stream") if data is not None else compare(rid, a, b, mirror)

    # ------------------------------------------------------------------ pre-release check
    # A new part's STEP file compared with the latest scan before a part number is opened. The file and the answer
    # stay in the workspace (checks/<id>/); nothing is sent to any system.
    checks_dir = store.ws / "checks"
    check_indexes: dict[str, object] = {}
    shape_indexes: dict[str, object] = {}
    index_lock = threading.Lock()

    def run_index(rid: str, progress=None):
        """The parts of a scan as the engine sees them (built once per scan, kept for the latest one)."""
        from ..precheck import build_index
        with index_lock:
            ix = check_indexes.get(rid)
            if ix is None:
                if progress:
                    progress("index", 0.0, "מכין את מאגר החלקים מהסריקה האחרונה (פעם אחת לכל סריקה)")
                ix = build_index(store.run_dir(rid), store.ws / "cache", run_id=rid, progress=progress)
                check_indexes.clear()
                check_indexes[rid] = ix
            return ix

    def shape_index(rid: str, progress=None):
        """Shape numbers of every part of a scan that has a model (shape search)."""
        from ..geometry import FingerprintCache
        from ..similar import ShapeIndex
        ix = run_index(rid, progress)
        with index_lock:
            si = shape_indexes.get(rid)
            if si is None:
                cache = FingerprintCache(str(store.ws / "cache" / "fingerprints"))
                try:
                    si = ShapeIndex.build(ix.items, cache)
                finally:
                    if cache.db is not None:
                        cache.db.close()
                shape_indexes.clear()
                shape_indexes[rid] = si
            return si
    max_check_bytes = 200 * 1024 * 1024

    def check_folder(cid: str) -> Path:
        d = checks_dir / cid
        if not re.fullmatch(r"C\d{8}-\d{6}-[0-9a-f]{4}", cid) or not (d / "meta.json").exists():
            raise HTTPException(404, "הבדיקה לא נמצאה")
        return d

    def check_result(cid: str) -> tuple[Path, dict, dict | None]:
        d = check_folder(cid)
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        f = d / "result.json"
        return d, meta, (json.loads(f.read_text(encoding="utf-8")) if f.exists() else None)

    def check_samples() -> dict:
        f = (factory_dir / "checks" / "checks.json") if demo_available else None
        if not f or not f.exists():
            return {}
        return {s["key"]: s for s in json.loads(f.read_text(encoding="utf-8"))}

    def start_check(cid: str, meta: dict) -> str:
        def work(progress, should_stop):
            from ..precheck import CheckError, check_file
            d = checks_dir / cid
            try:
                rid, res = load_result("latest")
                ix = run_index(rid, progress)
                shapes = shape_index(rid)
                st = ProjectSettings.from_dict(res.get("settings") or {})
                out = check_file(ix, d / meta["stored"], res["_index"], filename=meta["file"], pn=meta["pn"],
                                 name=meta["name"], description=meta["description"], material=meta["material"],
                                 th=st.thresholds, cache_dir=store.ws / "cache", own_cache=d / "fingerprint",
                                 timeout_s=st.timeout_s, group_targets=group_targets(res, store.current_decisions()),
                                 shapes=shapes, progress=progress)
            except CheckError as exc:
                out = {"error": str(exc)}
            except Exception as exc:   # kept with the check, so the page can say what happened
                out = {"error": f"הבדיקה נכשלה: {type(exc).__name__}: {exc}"}
            out.update({"id": cid, "at": meta["at"], "sample": meta.get("sample", "")})
            out.setdefault("file", {"name": meta["file"]})
            out.setdefault("input", {k: meta[k] for k in ("pn", "name", "description", "material")})
            (d / "result.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
            progress("done", 1.0, "הבדיקה הסתיימה")
            return {"check_id": cid, "verdict": (out.get("verdict") or {}).get("kind"), "error": out.get("error")}
        return jobs.start("check", work)

    def new_check_folder(filename: str, fields: dict, sample: str = "") -> tuple[str, Path, dict]:
        if not store.latest_run():
            raise HTTPException(400, "קודם צריך סריקה: הבדיקה משווה את החלק החדש לחלקים שנסרקו")
        raw = Path(filename or "part.step").name
        stem, suffix = Path(raw).stem, Path(raw).suffix.lower()
        if suffix not in (".step", ".stp"):
            raise HTTPException(400, "אפשר לבדוק קובץ STEP בלבד (.step או .stp)")
        cid = f"C{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
        d = checks_dir / cid
        d.mkdir(parents=True)
        stored = (re.sub(r"[^\w.\- ]+", "_", stem, flags=re.UNICODE).strip() or "part")[:80] + suffix
        limits = {"pn": 60, "name": 200, "description": 400, "material": 80}
        meta = {"id": cid, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "file": raw, "stored": stored, "sample": sample,
                **{k: str(fields.get(k) or "").strip()[:n] for k, n in limits.items()}}
        return cid, d, meta

    def finish_upload(cid: str, d: Path, meta: dict) -> dict:
        with open(d / meta["stored"], "rb") as fh:
            head = fh.read(256).lstrip(b"\xef\xbb\xbf \t\r\n")
        if not head.startswith(b"ISO-10303-21"):
            shutil.rmtree(d, ignore_errors=True)
            raise HTTPException(400, "הקובץ אינו קובץ STEP (חסרה הכותרת ISO-10303-21)")
        (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return {"check_id": cid, "job_id": start_check(cid, meta)}

    @app.post("/api/checks")
    async def new_check(file: UploadFile = File(...), pn: str = Form(""), name: str = Form(""),
                        description: str = Form(""), material: str = Form("")):
        cid, d, meta = new_check_folder(file.filename or "", {"pn": pn, "name": name, "description": description,
                                                              "material": material})
        size = 0
        with open(d / meta["stored"], "wb") as fh:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > max_check_bytes:
                    fh.close()
                    shutil.rmtree(d, ignore_errors=True)
                    raise HTTPException(413, "הקובץ גדול מדי לבדיקה (עד 200MB)")
                fh.write(chunk)
        return finish_upload(cid, d, meta)

    @app.get("/api/checks/samples")
    def list_check_samples():
        return [{k: s.get(k, "") for k in ("key", "title", "file", "pn", "name", "material", "expect")}
                for s in check_samples().values()]

    @app.post("/api/checks/sample/{key}")
    def sample_check(key: str):
        s = check_samples().get(key)
        if not s:
            raise HTTPException(404, "קובץ הדוגמה לא נמצא")
        cid, d, meta = new_check_folder(s["file"], s, sample=key)
        shutil.copyfile(factory_dir / "checks" / Path(s["file"]).name, d / meta["stored"])
        return finish_upload(cid, d, meta)

    @app.get("/api/checks")
    def list_checks():
        out = []
        for d in sorted((p for p in checks_dir.glob("C*") if (p / "meta.json").exists()), reverse=True)[:100]:
            _, meta, res = check_result(d.name)
            v = (res or {}).get("verdict") or {}
            out.append({"id": meta["id"], "at": meta["at"], "file": meta["file"], "sample": meta.get("sample", ""),
                        "input": {k: meta[k] for k in ("pn", "name", "description", "material")},
                        "status": "running" if res is None else ("error" if res.get("error") else "done"),
                        "error": (res or {}).get("error"), "verdict": {k: v.get(k) for k in ("kind", "tone", "title")},
                        "use_pn": ((v.get("use") or {}).get("pn")), "n_matches": (res or {}).get("n_matches", 0),
                        "run_id": (res or {}).get("run_id")})
        return out

    @app.get("/api/checks/{cid}")
    def get_check(cid: str):
        _, meta, res = check_result(cid)
        if res is None:
            return {"id": cid, "at": meta["at"], "status": "running", "file": {"name": meta["file"]},
                    "input": {k: meta[k] for k in ("pn", "name", "description", "material")}}
        return {**res, "status": "error" if res.get("error") else "done"}

    @app.delete("/api/checks/{cid}")
    def delete_check(cid: str):
        d = check_folder(cid)
        if jobs.running("check"):
            raise HTTPException(409, "בדיקה רצה כרגע – נסו שוב בעוד רגע")
        shutil.rmtree(d, ignore_errors=True)
        return {"ok": True}

    def check_match(cid: str, b: str) -> tuple[Path, dict, dict, dict]:
        d, meta, res = check_result(cid)
        if not res or res.get("error"):
            raise HTTPException(404, "לבדיקה הזו אין תוצאה")
        m = next((x for x in res.get("matches", []) + res.get("similar", []) if x["uid"] == b), None)
        if m is None:
            raise HTTPException(404, "החלק לא נמצא בין ההתאמות של הבדיקה")
        return d, meta, res, m

    @app.get("/api/checks/{cid}/mesh")
    def check_mesh(cid: str):
        d, meta, _ = check_result(cid)
        try:
            data = meshes.get_bytes(str(d / meta["stored"]))
        except Exception as exc:
            raise HTTPException(500, f"לא ניתן להכין תצוגה תלת-ממדית: {exc}")
        return Response(data, media_type="application/octet-stream", headers={"Cache-Control": "max-age=3600"})

    @app.get("/api/checks/{cid}/align")
    def check_align(cid: str, b: str):
        """Rotation that shows the existing part b in the orientation of the new file (display only)."""
        d, meta, res, m = check_match(cid, b)
        key = ("check", cid, b)
        if key not in align_cache:
            scale = (m.get("metrics") or {}).get("scale") or 1.0
            try:
                al = align_meshes(meshes.get(str(d / meta["stored"])), meshes.get(step_path(res["run_id"], b)),
                                  scale_b=scale, proper_only=True)
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(500, f"היישור נכשל: {exc}")
            with cache_lock:
                if len(align_cache) > 512:
                    align_cache.clear()
                align_cache[key] = {"matrix": al["matrix"], "mirror": al["mirror"], "scale": scale}
        return align_cache[key]

    @app.get("/api/checks/{cid}/compare")
    def check_compare(cid: str, b: str):
        d, meta, res, m = check_match(cid, b)
        key = ("check", cid, b)
        data = compare_cache.get(key)
        if data is None:
            scale = (m.get("metrics") or {}).get("scale") or 1.0
            try:
                c = compare_meshes(meshes.get(str(d / meta["stored"])), meshes.get(step_path(res["run_id"], b)),
                                   scale_b=scale, mirror=m.get("geo_relation") == "mirror")
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(500, f"ההשוואה נכשלה: {exc}")
            data = compare_bytes(c)
            with cache_lock:
                if len(compare_cache) > 24:
                    compare_cache.clear()
                compare_cache[key] = data
        return Response(data, media_type="application/octet-stream")

    # ------------------------------------------------------------------ decisions + export
    @app.post("/api/decisions")
    async def decide(request: Request):
        body = await request.json()
        if body.get("target_type") not in ("group", "pair", "mapping", "issue"):
            raise HTTPException(400, "סוג יעד לא מוכר")
        if body.get("decision") not in ("approve", "reject", "review", "ignore", ""):
            raise HTTPException(400, "החלטה לא מוכרת")
        user = actor(request, body.get("user") or "")
        ids = [t for t in (body.get("target_ids") or [body.get("target_id")]) if t]
        if body.get("master_uid") and (body["target_type"] != "group" or len(ids) != 1):
            raise HTTPException(400, "מק\"ט יעד אפשר לבחור רק לקבוצה אחת")
        masters = {}
        if body["target_type"] == "group":
            # every group decision records the target it is about: the one chosen now, else the one in effect (the
            # one approved before, else the proposal) - a bulk decision acts on what the list shows, and a rescan
            # never changes what was approved
            _, res = load_result("latest")
            groups, idx, dec = res["_groups"], res["_index"], store.current_decisions()
            for tid in ids:
                g = groups.get(tid)
                if not g:
                    raise HTTPException(404, "הקבוצה לא נמצאה")
                mu = body.get("master_uid") or chosen_target(g, dec.get(f"group:{tid}"), idx)
                if mu not in g["members"] or not idx[mu]["pn"]:
                    if body.get("master_uid"):
                        raise HTTPException(400, "מק\"ט היעד חייב להיות אחת הרשומות בקבוצה, עם מק\"ט")
                    mu = g["master_uid"]
                masters[tid] = mu
        out = [store.add_decision(body["target_type"], tid, body["decision"], body.get("note", ""), user,
                                  masters.get(tid, ""), store.latest_run() or "") for tid in ids]
        return {"ok": True, "saved": len(out)}

    @app.get("/api/decisions")
    def decisions():
        return store.all_decisions()

    @app.get("/api/runs/{rid}/export.xlsx")
    def export(rid: str):
        from ..excel_he import write_workbook
        rid, res = load_result(rid)
        out = store.ws / "exports" / f"part_audit_{rid}.xlsx"
        write_workbook(res, store.current_decisions(), out, demo=res.get("demo", False),
                       user=settings().get("user_name", ""))
        return FileResponse(out, filename=f"דוח_בקרת_חלקים_{rid}.xlsx",
                            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    # ------------------------------------------------------------------ UI
    if UI_DIR.exists():
        app.mount("/assets", StaticFiles(directory=UI_DIR), name="assets")

        @app.get("/")
        def index():
            return FileResponse(UI_DIR / "index.html")
    return app



