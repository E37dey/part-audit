"""Local web app: REST API + Hebrew UI + (optionally) the demo simulators, all on 127.0.0.1."""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import __version__, connectors
from ..demo import DEMO_DIR, demo_sources

from ..decisions import effective_mapping
from ..project import ProjectSettings, audit_snapshot, collect
from .store import Store

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
DEFAULT_SETTINGS = {"user_name": "", "mass_tolerance": 0.10, "workers": max(1, (os.cpu_count() or 2) - 1),
                    "cost_per_pn_year": None, "currency": "ILS", "thresholds": {}}


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
                job["status"] = "cancelled" if job["cancel"] else "done"
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
               base_url: str = "http://127.0.0.1:8765") -> FastAPI:
    store = Store(workspace)
    jobs = Jobs()
    results: dict[str, dict] = {}
    app = FastAPI(title="PartAudit", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.store, app.state.jobs, app.state.base_url = store, jobs, base_url
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

    # ------------------------------------------------------------------ helpers
    def settings() -> dict:
        return {**DEFAULT_SETTINGS, **store.get_settings()}

    def load_result(rid: str | None) -> tuple[str, dict]:
        rid = rid if rid and rid != "latest" else store.latest_run()
        if not rid:
            raise HTTPException(404, "עדיין לא בוצעה סריקה")
        if rid not in results:
            f = store.run_dir(rid) / "result.json"
            if not f.exists():
                raise HTTPException(404, "תוצאות הסריקה לא נמצאו")
            results.clear()  # keep one run in memory
            results[rid] = json.loads(f.read_text(encoding="utf-8"))
            results[rid]["_index"] = {p["uid"]: p for p in results[rid]["parts"]}
        return rid, results[rid]

    def with_decisions(rows: list[dict], kind: str, idx: dict | None = None) -> list[dict]:
        dec = store.current_decisions()
        out = []
        for r in rows:
            d = dec.get(f"{kind}:{r['id']}")
            row = {**r, "decision": d["decision"] if d else "", "decision_by": d["user"] if d else "",
                   "decision_at": d["created"] if d else "", "decision_note": d["note"] if d else "",
                   "decision_master": d["master_uid"] if d else ""}
            if kind == "group" and idx is not None:  # the part number that stays, after the engineer's choice
                mu = row["decision_master"]
                row["final_master_pn"] = idx[mu]["pn"] if mu and mu in idx and idx[mu]["pn"] else r.get("master_pn")
            out.append(row)
        return out

    def step_path(rid: str, uid: str) -> str:
        snap = store.run_dir(rid) / "step_paths.json"
        paths = json.loads(snap.read_text(encoding="utf-8")) if snap.exists() else {}
        p = paths.get(uid)
        if not p or not Path(p).exists():
            raise HTTPException(404, "אין קובץ STEP לחלק הזה")
        return p

    # ------------------------------------------------------------------ status / config
    @app.get("/api/status")
    def status():
        latest = store.latest_run()
        summary = None
        if latest:
            summary = next((r["summary"] for r in store.list_runs() if r["id"] == latest), None)
        return {"version": __version__, "demo_available": demo_available, "workspace": str(store.ws),
                "sources": len(store.list_sources()), "latest_run": latest, "summary": summary,
                "running": jobs.running(), "settings": settings(),
                "demo_loaded": any(s["simulated"] for s in store.list_sources())}

    @app.get("/api/connectors")
    def list_connectors():
        return [C.describe() for C in connectors.CONNECTORS.values()]

    @app.get("/api/settings")
    def get_settings():
        return settings()

    @app.put("/api/settings")
    async def put_settings(request: Request):
        body = await request.json()
        allowed = {k: v for k, v in body.items() if k in DEFAULT_SETTINGS}
        return {**DEFAULT_SETTINGS, **store.set_settings(allowed)}

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

    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...)):
        name = Path(file.filename or "upload").name
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
    @app.post("/api/scan")
    def scan():
        if jobs.running("scan"):
            raise HTTPException(409, "סריקה כבר רצה")
        cfg = settings()

        def work(progress, should_stop):
            t0 = time.time()
            rid = store.new_run()
            try:
                srcs = [s for s in store.list_sources(with_secrets=True) if s["enabled"]]
                if not srcs:
                    raise RuntimeError("אין מקורות נתונים פעילים")
                snap = collect(srcs, store.ws / "cache" / "connectors", progress=progress, should_stop=should_stop)
                snap.save(store.run_dir(rid) / "snapshot.json")
                (store.run_dir(rid) / "step_paths.json").write_text(json.dumps(
                    {r.uid: r.step_path for r in snap.records if r.step_path}), encoding="utf-8")
                st = ProjectSettings.from_dict({"mass_tolerance": cfg["mass_tolerance"], "workers": int(cfg["workers"]),
                                                "cost_per_pn_year": cfg["cost_per_pn_year"],
                                                "currency": cfg["currency"], "thresholds": cfg.get("thresholds") or {}})
                res = audit_snapshot(snap, st, store.ws / "cache", progress=progress)
                res["run_id"] = rid
                res["demo"] = any(s.get("simulated") for s in srcs)
                (store.run_dir(rid) / "result.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
                store.finish_run(rid, "done", res["summary"], time.time() - t0)
                results.clear()
                return {"run_id": rid, "summary": res["summary"]}
            except Exception as exc:
                store.finish_run(rid, "error", None, time.time() - t0, f"{type(exc).__name__}: {exc}")
                raise
        return {"job_id": jobs.start("scan", work)}

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
        top = sorted(res["groups"], key=lambda g: (-(g["redundant_stock_value"] or 0), -len(g["members"])))[:10]
        return {"run_id": rid, "created": res["created"], "demo": res.get("demo", False), "summary": res["summary"],
                "timings": res["timings"], "sources": res["sources"], "decisions": {"pending_groups": pending,
                                                                                     "approved_groups": approved},
                "issues_by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1])), "by_source": by_source,
                "cross_source": cross, "top_groups": with_decisions(top, "group", idx)}

    @app.get("/api/runs/{rid}/groups")
    def groups(rid: str):
        rid, res = load_result(rid)
        idx = res["_index"]
        rows = []
        for g in res["groups"]:
            rows.append({k: g[k] for k in ("id", "category", "pns", "sources", "cross_source", "master_uid", "master_pn",
                                           "confidence", "spec", "name", "redundant_pns", "redundant_stock_value",
                                           "stock_value", "bom_lines_to_update")}
                        | {"n_members": len(g["members"]), "n_used": len(g["where_used"]),
                           "family": idx[g["master_uid"]]["make_buy"]})
        return with_decisions(rows, "group", idx)

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
        return with_decisions([out], "group", idx)[0]

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
        rows = with_decisions(effective_mapping(res, dec), "mapping")
        for r in rows:  # a decision on the whole group applies to its rows unless the row has its own
            if not r["decision"]:
                d = dec.get(f"group:{r['group_id']}")
                if d:
                    r["decision"], r["decision_by"], r["decision_at"] = d["decision"], d["user"], d["created"]
                    r["decision_note"], r["inherited"] = d["note"], True
        return rows

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
        erp_parents = [b for b in res.get("erp_bom", []) if p["pn"] and b["child"] == p["pn"]]
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
            if len(align_cache) > 512:
                align_cache.clear()
            align_cache[key] = {"matrix": al["matrix"], "mirror": al["mirror"], "scale": scale}
        return align_cache[key]

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
            if len(compare_cache) > 24:
                compare_cache.clear()
            compare_cache[key] = compare_bytes(c)
        return Response(compare_cache[key], media_type="application/octet-stream")

    # ------------------------------------------------------------------ decisions + export
    @app.post("/api/decisions")
    async def decide(request: Request):
        body = await request.json()
        if body.get("target_type") not in ("group", "pair", "mapping", "issue"):
            raise HTTPException(400, "סוג יעד לא מוכר")
        if body.get("decision") not in ("approve", "reject", "review", "ignore", ""):
            raise HTTPException(400, "החלטה לא מוכרת")
        user = (body.get("user") or settings().get("user_name") or "").strip() or "משתמש"
        ids = body.get("target_ids") or [body.get("target_id")]
        if body.get("master_uid"):
            if body["target_type"] != "group" or len(ids) != 1:
                raise HTTPException(400, "מק\"ט יעד אפשר לבחור רק לקבוצה אחת")
            _, res = load_result("latest")
            g = next((x for x in res["groups"] if x["id"] == ids[0]), None)
            if not g or body["master_uid"] not in g["members"] or not res["_index"][body["master_uid"]]["pn"]:
                raise HTTPException(400, "מק\"ט היעד חייב להיות אחת הרשומות בקבוצה, עם מק\"ט")
        out = [store.add_decision(body["target_type"], tid, body["decision"], body.get("note", ""), user,
                                  body.get("master_uid", ""), store.latest_run() or "") for tid in ids if tid]
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



