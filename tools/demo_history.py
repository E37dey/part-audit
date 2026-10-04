"""Build a demo workspace with a few weeks of scan history (for the online copy and for trying "what changed").

The demo factory is scanned as it was 5, 4, 3, 2 and 1 weeks ago - every Sunday at 06:00, like a weekly scheduled
scan - and then as it is now. The past weeks are made from the factory's own records (synthetic, like all its
business data):

* duplicates created over time: 10 records of today's factory did not exist yet and appear one week after another
  (another copy of a library screw, a plate saved again under a new number ...)
* a clean-up: 8 copies of existing parts (new part numbers, the same model) existed and were removed, two a week
* data fixes: 6 records had no material; it was filled in, two a week

Then the field discovery of every source and the pre-release sample checks run on the latest scan.

    python tools/demo_history.py --workspace out/demo_ws [--weeks 5]

The workspace must be new (or one this tool made). Nothing is written to the demo factory itself.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT)]

from part_audit.demo import DEMO_DIR, demo_sources  # noqa: E402

MARKER = ".partaudit-demo-history"
# records of today's factory and the scan (weeks ago, 0 = the latest) in which they are seen for the first time
APPEAR = {"vault:north:1384": 4, "teamcenter:south:1323": 4,
          "vault:north:1026": 3, "teamcenter:south:1245": 3,
          "swpdm:center:1496": 2, "vault:north:1221": 2,
          "windchill:hq:1327": 1, "teamcenter:south:1248": 1,
          "vault:north:1076": 0, "vault:north:1306": 0}
# copies of these records (a new number, the same model) existed until the scan in which they are gone
EXTRA = [("windchill:hq:1187", 3), ("teamcenter:south:1235", 3), ("vault:north:1225", 2), ("swpdm:center:1329", 2),
         ("vault:north:1251", 1), ("windchill:hq:1216", 1), ("teamcenter:south:1193", 0), ("vault:north:1246", 0)]
N_FIXED = 6                       # records whose material was missing until it was filled in (two a week, the last
                                  # two in the latest scan)


def new_pn(pn: str, taken: set[str]) -> str:
    """Another number in the same format: the last digits changed."""
    digits = [i for i, ch in enumerate(pn) if ch.isdigit()]
    for k in range(1, 200):
        chars = list(pn)
        tail = str((int("".join(pn[i] for i in digits[-2:])) + 37 * k) % 100).zfill(2)
        for i, ch in zip(digits[-2:], tail):
            chars[i] = ch
        cand = "".join(chars)
        if cand not in taken:
            taken.add(cand)
            return cand
    raise RuntimeError(f"no free number like {pn}")


def plan(base: dict) -> tuple[dict, list[dict], dict]:
    by_rid = {r["rid"]: r for r in base["records"]}
    for rid in list(APPEAR) + [r for r, _ in EXTRA]:
        if rid not in by_rid:
            raise SystemExit(f"{rid} is not in the demo factory - was it rebuilt?")
    taken = {r["pn"] for r in base["records"]} | {i["pn"] for i in base["erp"]["items"]}
    copies = []
    for rid, removed in EXTRA:
        r = dict(by_rid[rid])
        pn = new_pn(r["pn"], taken)
        r.update({"rid": f"{r['system']}:{r['site']}:{r['native_id'] + 5000}", "native_id": r["native_id"] + 5000,
                  "pn": pn, "native_file": r["native_file"].replace(by_rid[rid]["pn"], pn) if by_rid[rid]["pn"]
                  in r["native_file"] else f"{pn}_{r['native_file']}", "revision": "A", "version": 1, "bom": [],
                  "plants": [], "created": "2024-05-12", "modified": "2024-05-12", "variant": "copy",
                  "history": [{"version": 1, "revision": "A", "date": "2024-05-12", "comment": "יצירה"}],
                  "_removed": removed})
        copies.append(r)
    skip = set(APPEAR) | {r for r, _ in EXTRA}
    fixable = sorted((r for r in base["records"] if r["kind"] == "part" and r.get("make_buy") == "make"
                      and r.get("material_text") and r["system"] != "folder" and r["rid"] not in skip),
                     key=lambda r: r["rid"])
    step = max(1, len(fixable) // N_FIXED)
    fixed = {r["rid"]: 2 - i // 2 for i, r in enumerate(fixable[::step][:N_FIXED])}     # scans 2, 2, 1, 1, 0, 0
    return APPEAR, copies, fixed


def factory_state(base: dict, week: int, appear: dict, copies: list[dict], fixed: dict) -> dict:
    """The factory as it was ``week`` weeks ago (week 0 is today's factory: nothing of this applies)."""
    recs = []
    for r in base["records"]:
        if r["rid"] in appear and week > appear[r["rid"]]:
            continue                                  # not created yet
        if r["rid"] in fixed and week > fixed[r["rid"]]:
            r = dict(r, material_text="")             # the material was filled in later
        recs.append(r)
    recs += [{k: v for k, v in c.items() if k != "_removed"} for c in copies if week > c["_removed"]]
    return dict(base, records=recs)


def wait_job(client, jid: str, what: str) -> dict:
    for _ in range(3600):
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] != "running":
            if j["status"] != "done":
                raise SystemExit(f"{what} failed: {j.get('error')}")
            return j
        time.sleep(0.5)
    raise SystemExit(f"{what} did not finish")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--weeks", type=int, default=5)
    args = ap.parse_args()
    ws = Path(args.workspace)
    if ws.exists() and any(ws.iterdir()) and not (ws / MARKER).exists():
        raise SystemExit(f"{ws} is not empty and was not made by this tool")
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    (ws / MARKER).write_text("written by tools/demo_history.py\n", encoding="utf-8")

    import httpx

    from part_audit.runner import run_scan
    from part_audit.server.app import create_app
    from part_audit.server.store import Store
    from part_audit.simulators import ServerThread, free_port

    base = json.loads((DEMO_DIR / "factory.json").read_text(encoding="utf-8"))
    appear, copies, fixed = plan(base)
    store = Store(ws)
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    for s in demo_sources(url, DEMO_DIR):
        store.save_source(s)
    today = dt.date.today()
    sunday = today - dt.timedelta(days=(today.weekday() + 1) % 7)       # the latest Sunday (today if it is one)
    hist = ws / "_history"

    def progress(stage, frac, detail, _last=[""]):
        if detail != _last[0] and stage in ("collect", "done"):
            _last[0] = detail
    for week in range(args.weeks, -1, -1):
        if week:
            d = hist / f"week-{week}"
            d.mkdir(parents=True, exist_ok=True)
            (d / "factory.json").write_text(json.dumps(factory_state(base, week, appear, copies, fixed),
                                                       ensure_ascii=False), encoding="utf-8")
            for sub in ("files", "archive"):
                if not (d / sub).exists():
                    (d / sub).symlink_to(DEMO_DIR / sub, target_is_directory=True)
            factory = d
        else:
            factory = DEMO_DIR
        t0 = time.time()
        app = create_app(ws, factory_dir=factory, base_url=url)
        with ServerThread(app, port=port):
            out = run_scan(Store(ws), progress, lambda: False, trigger="schedule", app_url=url)
        when = dt.datetime.combine(sunday - dt.timedelta(days=7 * week), dt.time(6, 0)).isoformat(timespec="seconds")
        with sqlite3.connect(ws / "app.db") as c:
            c.execute("UPDATE runs SET created=? WHERE id=?", (when, out["run_id"]))
        f = ws / "runs" / out["run_id"] / "result.json"
        res = json.loads(f.read_text(encoding="utf-8"))
        res["created"] = res["snapshot_created"] = when
        f.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        for name in ("changes.json",):
            cf = ws / "runs" / out["run_id"] / name
            if cf.exists():
                ch = json.loads(cf.read_text(encoding="utf-8"))
                ch["to"]["created"] = when
                prev = Store(ws).previous_run(out["run_id"])
                if prev:
                    ch["from"]["created"] = json.loads((ws / "runs" / prev / "result.json").read_text(encoding="utf-8"))["created"]
                cf.write_text(json.dumps(ch, ensure_ascii=False), encoding="utf-8")
        print(f"week -{week}: {when}  {out['summary']['parts']} parts, {out['summary']['groups']} groups"
              f"  ({time.time() - t0:.0f} s)  {out.get('headline') or ''}", flush=True)
    shutil.rmtree(hist)

    # the latest scan: field discovery of every source and the pre-release sample checks
    app = create_app(ws, factory_dir=DEMO_DIR, base_url=url)
    with ServerThread(app, port=port), httpx.Client(base_url=url, timeout=300, trust_env=False) as client:
        for s in client.get("/api/sources").json():
            r = client.post(f"/api/sources/{s['id']}/discover")
            print(f"discovery {s['name']}: {r.status_code}")
        for smp in client.get("/api/checks/samples").json():
            r = client.post(f"/api/checks/sample/{smp['key']}").json()
            wait_job(client, r["job_id"], f"check {smp['key']}")
            c = client.get(f"/api/checks/{r['check_id']}").json()
            print(f"check {smp['key']}: {c['verdict']['kind']} {c['verdict'].get('use') and c['verdict']['use']['pn']}")
            time.sleep(1.1)                                   # one check per second: ids keep the order
    print(f"demo workspace ready: {ws}")


if __name__ == "__main__":
    main()
