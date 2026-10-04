"""Local persistence: SQLite for sources, runs, decisions (with history) and settings; JSON files for results."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, config TEXT NOT NULL, enabled INTEGER DEFAULT 1,
    simulated INTEGER DEFAULT 0, last_test TEXT, created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, created TEXT, status TEXT, summary TEXT, path TEXT, duration_s REAL, error TEXT);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, target_type TEXT, target_id TEXT, decision TEXT, master_uid TEXT,
    note TEXT, user TEXT, run_id TEXT, created TEXT);
CREATE INDEX IF NOT EXISTS ix_decisions_target ON decisions(target_type, target_id);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS secrets (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE COLLATE NOCASE, display_name TEXT, email TEXT,
    role TEXT NOT NULL, pw_hash TEXT, oidc_sub TEXT UNIQUE, disabled INTEGER DEFAULT 0, created TEXT, last_login TEXT);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, method TEXT, created REAL, last_seen REAL);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);
"""
SECRET_FIELDS = ("password", "app_key", "token")
MASK = "••••••"
URL_FIELDS = ("base_url", "server_url", "service_root", "host", "base_path", "fms_url", "path")


def secret_keys(kind: str) -> set[str]:
    """Config keys that are credentials for this kind of source: never returned by the API."""
    keys = set(SECRET_FIELDS)
    try:
        from .. import connectors
        keys |= {f.name for f in connectors.get(kind).fields if f.type == "password" or f.secret}
    except KeyError:
        pass
    return keys


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, workspace: str | Path):
        self.ws = Path(workspace)
        self.ws.mkdir(parents=True, exist_ok=True)
        for d in ("runs", "cache", "exports", "uploads"):
            (self.ws / d).mkdir(exist_ok=True)
        self.db_path = self.ws / "app.db"
        self._lock = threading.RLock()
        with self._conn() as c:
            c.executescript(SCHEMA)
            cols = {r["name"] for r in c.execute("PRAGMA table_info(runs)")}
            if "trigger" not in cols:          # workspaces from before scheduled scans
                c.execute("ALTER TABLE runs ADD COLUMN trigger TEXT DEFAULT 'manual'")

    def _conn(self):
        c = sqlite3.connect(self.db_path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    # ------------------------------------------------------------------ secrets
    def _keyring(self):
        try:
            import keyring  # type: ignore
            keyring.get_keyring()
            return keyring
        except Exception:
            return None

    def _split_secrets(self, sid: str, kind: str, cfg: dict, simulated: bool) -> dict:
        """Keep secrets in the OS credential store when one exists (Windows Credential Manager, macOS
        Keychain); otherwise they stay in the local database of this computer."""
        out = dict(cfg)
        kr = None if simulated else self._keyring()
        for k in secret_keys(kind):
            if k in out and out[k] and kr is not None:
                try:
                    kr.set_password("part-audit", f"{sid}:{k}", out[k])
                    out[k] = "__keyring__"
                except Exception:
                    pass
        return out

    def _join_secrets(self, sid: str, kind: str, cfg: dict) -> dict:
        out = dict(cfg)
        kr = None
        for k in secret_keys(kind):
            if out.get(k) == "__keyring__":
                kr = kr or self._keyring()
                out[k] = (kr.get_password("part-audit", f"{sid}:{k}") if kr else "") or ""
        return out

    def set_secret(self, name: str, value: str) -> None:
        """An app-level credential (the mail server password): the OS credential store when there is one,
        otherwise a table of this computer's database that the API never returns."""
        kr = self._keyring()
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM secrets WHERE key=?", (name,))
            if not value:
                if kr is not None:
                    try:
                        kr.delete_password("part-audit", f"app:{name}")
                    except Exception:
                        pass
                return
            if kr is not None:
                try:
                    kr.set_password("part-audit", f"app:{name}", value)
                    c.execute("INSERT INTO secrets(key, value) VALUES(?, '__keyring__')", (name,))
                    return
                except Exception:
                    pass
            c.execute("INSERT INTO secrets(key, value) VALUES(?, ?)", (name, value))

    def get_secret(self, name: str) -> str:
        with self._conn() as c:
            r = c.execute("SELECT value FROM secrets WHERE key=?", (name,)).fetchone()
        if not r:
            return ""
        if r["value"] == "__keyring__":
            kr = self._keyring()
            return (kr.get_password("part-audit", f"app:{name}") if kr else "") or ""
        return r["value"]

    # ------------------------------------------------------------------ sources
    def list_sources(self, with_secrets: bool = False) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM sources ORDER BY created").fetchall()
        out = []
        for r in rows:
            cfg = json.loads(r["config"])
            if with_secrets:
                cfg = self._join_secrets(r["id"], r["kind"], cfg)
            else:
                hidden = secret_keys(r["kind"])
                cfg = {k: (MASK if k in hidden and v else v) for k, v in cfg.items()}
            out.append({"id": r["id"], "kind": r["kind"], "name": r["name"], "config": cfg,
                        "enabled": bool(r["enabled"]), "simulated": bool(r["simulated"]),
                        "last_test": json.loads(r["last_test"]) if r["last_test"] else None,
                        "created": r["created"], "updated": r["updated"]})
        return out

    def get_source(self, sid: str, with_secrets: bool = True) -> dict | None:
        return next((s for s in self.list_sources(with_secrets) if s["id"] == sid), None)

    def save_source(self, src: dict) -> dict:
        sid = src.get("id") or f"src-{uuid.uuid4().hex[:8]}"
        old = self.get_source(sid, with_secrets=True) if src.get("id") else None
        cfg = dict(src.get("config") or {})
        if old:
            # the form sends the mask back for an unchanged secret: keep the stored one, but only while the
            # address stays the same (a secret is never sent to a server it was not entered for)
            same_place = all(str(cfg.get(k, old["config"].get(k, ""))) == str(old["config"].get(k, ""))
                             for k in URL_FIELDS)
            for k in secret_keys(src["kind"]):
                if cfg.get(k, MASK) == MASK:
                    cfg[k] = old["config"].get(k, "") if same_place else ""
        simulated = bool(src.get("simulated", old["simulated"] if old else False))
        stored = self._split_secrets(sid, src["kind"], cfg, simulated)
        with self._lock, self._conn() as c:
            c.execute("""INSERT INTO sources(id, kind, name, config, enabled, simulated, created, updated)
                         VALUES(?,?,?,?,?,?,?,?)
                         ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, name=excluded.name, config=excluded.config,
                         enabled=excluded.enabled, simulated=excluded.simulated, updated=excluded.updated""",
                      (sid, src["kind"], src["name"], json.dumps(stored, ensure_ascii=False),
                       int(src.get("enabled", True)), int(simulated), old["created"] if old else now(), now()))
        return self.get_source(sid, with_secrets=False)

    def delete_source(self, sid: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM sources WHERE id=?", (sid,))

    def set_test_result(self, sid: str, result: dict) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE sources SET last_test=? WHERE id=?", (json.dumps(dict(result, at=now()), ensure_ascii=False), sid))

    # ------------------------------------------------------------------ runs
    def new_run(self, trigger: str = "manual") -> str:
        """trigger: manual (the app's button) | schedule (the app's schedule) | cli (a scheduled task of the OS)."""
        rid = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        (self.ws / "runs" / rid).mkdir(parents=True, exist_ok=True)
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO runs(id, created, status, path, trigger) VALUES(?,?,?,?,?)",
                      (rid, now(), "running", str(self.ws / "runs" / rid), trigger))
        return rid

    def finish_run(self, rid: str, status: str, summary: dict | None = None, duration: float = 0.0,
                   error: str = "") -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE runs SET status=?, summary=?, duration_s=?, error=? WHERE id=?",
                      (status, json.dumps(summary or {}, ensure_ascii=False), duration, error, rid))

    def list_runs(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM runs ORDER BY created DESC, rowid DESC").fetchall()
        return [{"id": r["id"], "created": r["created"], "status": r["status"], "duration_s": r["duration_s"],
                 "error": r["error"], "trigger": r["trigger"] or "manual",
                 "summary": json.loads(r["summary"]) if r["summary"] else None} for r in rows]

    def previous_run(self, rid: str) -> str | None:
        """The finished scan before this one."""
        with self._conn() as c:
            me = c.execute("SELECT created, rowid FROM runs WHERE id=?", (rid,)).fetchone()
            if not me:
                return None
            r = c.execute("SELECT id FROM runs WHERE status='done' AND (created<? OR (created=? AND rowid<?)) "
                          "ORDER BY created DESC, rowid DESC LIMIT 1", (me["created"], me["created"], me["rowid"])).fetchone()
        return r["id"] if r else None

    def latest_run(self) -> str | None:
        with self._conn() as c:
            # two scans in the same second keep the order they were started in
            r = c.execute("SELECT id FROM runs WHERE status='done' ORDER BY created DESC, rowid DESC LIMIT 1").fetchone()
        return r["id"] if r else None

    def run_dir(self, rid: str) -> Path:
        return self.ws / "runs" / rid

    # ------------------------------------------------------------------ decisions
    def add_decision(self, target_type: str, target_id: str, decision: str, note: str = "", user: str = "",
                     master_uid: str = "", run_id: str = "") -> dict:
        row = (target_type, target_id, decision, master_uid, note, user, run_id, now())
        with self._lock, self._conn() as c:
            c.execute("""INSERT INTO decisions(target_type, target_id, decision, master_uid, note, user, run_id, created)
                         VALUES(?,?,?,?,?,?,?,?)""", row)
        return dict(zip(("target_type", "target_id", "decision", "master_uid", "note", "user", "run_id", "created"), row))

    def current_decisions(self) -> dict[str, dict]:
        """Latest decision per (type, id) -> keyed 'type:id'."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM decisions ORDER BY id").fetchall()
        out = {}
        for r in rows:
            out[f"{r['target_type']}:{r['target_id']}"] = dict(r)
        return out

    def decision_history(self, target_type: str, target_id: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM decisions WHERE target_type=? AND target_id=? ORDER BY id DESC",
                             (target_type, target_id)).fetchall()
        return [dict(r) for r in rows]

    def all_decisions(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM decisions ORDER BY id DESC").fetchall()]

    # ------------------------------------------------------------------ users and sessions (team mode)
    USER_FIELDS = ("username", "display_name", "email", "role", "pw_hash", "oidc_sub", "disabled", "last_login")

    def list_users(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM users ORDER BY disabled, username COLLATE NOCASE")]

    def get_user(self, uid: int) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return dict(r) if r else None

    def find_user(self, username: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", ((username or "").strip(),)).fetchone()
        return dict(r) if r else None

    def find_user_oidc(self, sub: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM users WHERE oidc_sub=?", (sub,)).fetchone()
        return dict(r) if r else None

    def add_user(self, username: str, role: str, display_name: str = "", email: str = "", pw_hash: str | None = None,
                 oidc_sub: str | None = None) -> dict:
        with self._lock, self._conn() as c:
            cur = c.execute("""INSERT INTO users(username, display_name, email, role, pw_hash, oidc_sub, disabled, created)
                               VALUES(?,?,?,?,?,?,0,?)""", (username.strip(), display_name.strip() or username.strip(),
                                                         email.strip().lower(), role, pw_hash, oidc_sub, now()))
            uid = cur.lastrowid
        return self.get_user(uid)

    def update_user(self, uid: int, **fields) -> dict | None:
        sets = {k: v for k, v in fields.items() if k in self.USER_FIELDS}
        if sets:
            with self._lock, self._conn() as c:
                c.execute(f"UPDATE users SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), uid))
        return self.get_user(uid)

    def count_admins(self, except_id: int | None = None) -> int:
        """Enabled admins (that can sign in: with a password or a company account)."""
        with self._conn() as c:
            r = c.execute("""SELECT COUNT(*) FROM users WHERE role='admin' AND disabled=0 AND id<>?
                             AND (pw_hash IS NOT NULL OR oidc_sub IS NOT NULL)""", (except_id or -1,)).fetchone()
        return int(r[0])

    def new_session(self, uid: int, method: str = "password") -> str:
        from .auth import new_token, token_hash
        token, t = new_token(), time.time()
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO sessions(token_hash, user_id, method, created, last_seen) VALUES(?,?,?,?,?)",
                      (token_hash(token), uid, method, t, t))
            c.execute("UPDATE users SET last_login=? WHERE id=?", (now(), uid))
        return token

    def session_user(self, token: str) -> dict | None:
        """The signed-in user of a session cookie, or None (unknown, expired or the user was disabled)."""
        from .auth import SESSION_IDLE_S, SESSION_MAX_S, token_hash
        if not token or len(token) > 200:
            return None
        th, t = token_hash(token), time.time()
        with self._conn() as c:
            r = c.execute("""SELECT s.created AS s_created, s.last_seen AS s_seen, s.method AS s_method, u.*
                             FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash=?""", (th,)).fetchone()
        if not r:
            return None
        if r["disabled"] or t - r["s_seen"] > SESSION_IDLE_S or t - r["s_created"] > SESSION_MAX_S:
            self.end_session(token)
            return None
        if t - r["s_seen"] > 300:              # write at most every five minutes
            with self._lock, self._conn() as c:
                c.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (t, th))
        out = {k: r[k] for k in r.keys() if not k.startswith("s_")}
        out["session_method"] = r["s_method"]
        return out

    def end_session(self, token: str) -> None:
        from .auth import token_hash
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token or ""),))

    def end_user_sessions(self, uid: int, keep_token: str | None = None) -> None:
        from .auth import token_hash
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (uid, token_hash(keep_token or "")))

    # ------------------------------------------------------------------ settings
    def get_settings(self) -> dict:
        with self._conn() as c:
            rows = c.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: json.loads(r["value"]) for r in rows}

    def set_settings(self, values: dict) -> dict:
        with self._lock, self._conn() as c:
            for k, v in values.items():
                c.execute("INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                          (k, json.dumps(v, ensure_ascii=False)))
        return self.get_settings()
