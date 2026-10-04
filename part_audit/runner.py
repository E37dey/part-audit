"""One scan of the configured sources: collect (read-only), audit, store the run, compare it with the scan before
and, when the user turned it on, e-mail what changed. Used by the app's 'New scan' button, by its schedule, and by
'python -m part_audit rescan' (a task of the OS scheduler)."""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from typing import Callable

from .changes import compare_runs, unavailable_sources
from .notify import DEFAULT_EMAIL, SECRET, build_message, compose, send, should_send
from .project import ProjectSettings, audit_snapshot, collect
from .schedule import DEFAULT_SCHEDULE

DEFAULT_SETTINGS = {"user_name": "", "mass_tolerance": 0.10, "workers": max(1, (os.cpu_count() or 2) - 1),
                    "cost_per_pn_year": None, "currency": "ILS", "thresholds": {}, "schedule": DEFAULT_SCHEDULE,
                    "email": DEFAULT_EMAIL}

Progress = Callable[[str, float, str], None]


def settings_of(store) -> dict:
    cfg = {**DEFAULT_SETTINGS, **store.get_settings()}
    cfg["schedule"] = {**DEFAULT_SCHEDULE, **(cfg.get("schedule") or {})}
    cfg["email"] = {**DEFAULT_EMAIL, **(cfg.get("email") or {})}
    return cfg


def failed_sources(res: dict) -> list[str]:
    """Names of the sources that could not be read in this scan (an error and nothing read)."""
    ids = unavailable_sources(res)
    return [s["name"] for s in res.get("sources", []) if s["id"] in ids]


def load_result(store, rid: str) -> dict | None:
    f = store.run_dir(rid) / "result.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def changes_since_previous(store, rid: str, res: dict) -> dict | None:
    """Compare a finished scan with the one before it and keep the comparison with the run (changes.json)."""
    prev = store.previous_run(rid)
    old = load_result(store, prev) if prev else None
    if old is None:
        return None
    ch = compare_runs(old, res)
    ch["failed_sources"] = failed_sources(res)
    (store.run_dir(rid) / "changes.json").write_text(json.dumps(ch, ensure_ascii=False), encoding="utf-8")
    return ch


def notify(store, cfg: dict, res: dict, changes: dict | None, trigger: str, app_url: str = "") -> dict | None:
    """E-mail the changes when the user asked for it; the outcome is kept with the run (notify.json)."""
    em = cfg["email"]
    if not should_send(em, changes, trigger):
        return None
    out = {"at": dt.datetime.now().isoformat(timespec="seconds"), "to": em.get("to"), "sent": False, "error": ""}
    try:
        subject, text, body = compose(changes, res["summary"], app_url=app_url, demo=bool(res.get("demo")),
                                      failed=changes.get("failed_sources"), when=res.get("created", ""))
        send(em, store.get_secret(SECRET), build_message(em, subject, text, body))
        out["sent"] = True
    except Exception as exc:          # kept with the run and shown in the app; the scan itself succeeded
        out["error"] = f"{type(exc).__name__}: {exc}"
    (store.run_dir(res["run_id"]) / "notify.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def run_scan(store, progress: Progress, should_stop: Callable[[], bool], trigger: str = "manual",
             app_url: str = "", on_done: Callable[[], None] | None = None, send_email: bool = True) -> dict | None:
    """Returns {'run_id', 'summary', 'headline'} or None when the scan was stopped (a stopped scan is never kept
    as a result)."""
    cfg = settings_of(store)
    t0 = time.time()
    rid = store.new_run(trigger)
    try:
        srcs = [s for s in store.list_sources(with_secrets=True) if s["enabled"]]
        if not srcs:
            raise RuntimeError("אין מקורות נתונים פעילים")
        snap = collect(srcs, store.ws / "cache" / "connectors", progress=progress, should_stop=should_stop)
        if should_stop():
            store.finish_run(rid, "cancelled", None, time.time() - t0)
            return None
        snap.save(store.run_dir(rid) / "snapshot.json")
        (store.run_dir(rid) / "step_paths.json").write_text(json.dumps(
            {r.uid: r.step_path for r in snap.records if r.step_path}), encoding="utf-8")
        st = ProjectSettings.from_dict({"mass_tolerance": cfg["mass_tolerance"], "workers": int(cfg["workers"]),
                                        "cost_per_pn_year": cfg["cost_per_pn_year"], "currency": cfg["currency"],
                                        "thresholds": cfg.get("thresholds") or {}})
        files: dict = {}
        res = audit_snapshot(snap, st, store.ws / "cache", progress=progress, files_out=files)
        if should_stop():
            store.finish_run(rid, "cancelled", None, time.time() - t0)
            return None
        # the STEP records read for this scan: a pre-release check compares with them without reading again
        (store.run_dir(rid) / "files.json").write_text(json.dumps(files, ensure_ascii=False), encoding="utf-8")
        res["run_id"] = rid
        res["trigger"] = trigger
        res["demo"] = any(s.get("simulated") for s in srcs)
        (store.run_dir(rid) / "result.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        store.finish_run(rid, "done", res["summary"], time.time() - t0)
        if on_done:
            on_done()
    except Exception as exc:
        store.finish_run(rid, "error", None, time.time() - t0, f"{type(exc).__name__}: {exc}")
        raise
    changes = None
    try:
        progress("done", 1.0, "משווה לסריקה הקודמת")
        changes = changes_since_previous(store, rid, res)
        if send_email:
            notify(store, cfg, res, changes, trigger, app_url)
    except Exception:                 # the scan is kept even if the comparison or the e-mail fails
        import traceback
        (store.run_dir(rid) / "after_scan_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    return {"run_id": rid, "summary": res["summary"], "headline": changes["headline"] if changes else None}
