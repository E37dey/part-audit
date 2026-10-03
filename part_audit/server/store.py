"""Local persistence: SQLite for sources, runs, decisions (with history) and settings; JSON files for results."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
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
"""
SECRET_FIELDS = ("password", "app_key", "token")


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

    def _split_secrets(self, sid: str, cfg: dict, simulated: bool) -> dict:
        """Keep secrets in the OS credential store when one exists (Windows Credential Manager, macOS
        Keychain); otherwise they stay in the local database of this computer."""
        out = dict(cfg)
        kr = None if simulated else self._keyring()
        for k in SECRET_FIELDS:
            if k in out and out[k] and kr is not None:
                try:
                    kr.set_password("part-audit", f"{sid}:{k}", out[k])
                    out[k] = "__keyring__"
                except Exception:
                    pass
        return out

    def _join_secrets(self, sid: str, cfg: dict) -> dict:
        out = dict(cfg)
        kr = None
        for k in SECRET_FIELDS:
            if out.get(k) == "__keyring__":
                kr = kr or self._keyring()
                out[k] = (kr.get_password("part-audit", f"{sid}:{k}") if kr else "") or ""
        return out

    # ------------------------------------------------------------------ sources
    def list_sources(self, with_secrets: bool = False) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM sources ORDER BY created").fetchall()
        out = []
        for r in rows:
            cfg = json.loads(r["config"])
            if with_secrets:
                cfg = self._join_secrets(r["id"], cfg)
            else:
                cfg = {k: ("••••••" if k in SECRET_FIELDS and v else v) for k, v in cfg.items()}
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
        if old:  # keep stored secrets when the form sends the mask back
            for k in SECRET_FIELDS:
                if cfg.get(k) in ("••••••", None) and old["config"].get(k):
                    cfg[k] = old["config"][k]
        simulated = bool(src.get("simulated", old["simulated"] if old else False))
        stored = self._split_secrets(sid, cfg, simulated)
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
    def new_run(self) -> str:
        rid = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        (self.ws / "runs" / rid).mkdir(parents=True, exist_ok=True)
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO runs(id, created, status, path) VALUES(?,?,?,?)",
                      (rid, now(), "running", str(self.ws / "runs" / rid)))
        return rid

    def finish_run(self, rid: str, status: str, summary: dict | None = None, duration: float = 0.0,
                   error: str = "") -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE runs SET status=?, summary=?, duration_s=?, error=? WHERE id=?",
                      (status, json.dumps(summary or {}, ensure_ascii=False), duration, error, rid))

    def list_runs(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM runs ORDER BY created DESC").fetchall()
        return [{"id": r["id"], "created": r["created"], "status": r["status"], "duration_s": r["duration_s"],
                 "error": r["error"], "summary": json.loads(r["summary"]) if r["summary"] else None} for r in rows]

    def latest_run(self) -> str | None:
        with self._conn() as c:
            r = c.execute("SELECT id FROM runs WHERE status='done' ORDER BY created DESC LIMIT 1").fetchone()
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
