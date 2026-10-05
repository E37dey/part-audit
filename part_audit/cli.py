"""Command line interface.

    python -m part_audit app [--port 8765] [--workspace DIR]   # the local Hebrew web app (opens the browser)
    python -m part_audit scan DATA_DIR [--erp erp.csv] [--out out/report.xlsx]
    python -m part_audit fingerprint FILE.step        # debug one file
    python -m part_audit check NEW.step [--pn P] [--name N] [--workspace DIR] [--json]
        # pre-release check against the app's latest scan; exit code 0 = not found (a new part number may be opened),
        # 1 = the part already exists or the planned part number is taken, 3 = needs a look (near-identical, mirror,
        # same shape with another specification, geometry not readable), 2 = cannot check
    python -m part_audit rescan [--workspace DIR] [--no-email]
        # scan the sources configured in the app now, compare with the scan before and e-mail the changes when that
        # is turned on in the app's settings (for a task of the OS scheduler while the app is closed)
    python -m part_audit users add NAME --role admin [--display "שם"] [--workspace DIR]   # accounts for team mode
    python -m part_audit users list | password NAME | role NAME ROLE | disable NAME | enable NAME
    python -m part_audit serve [--host 0.0.0.0] [--port 8765] [--workspace DIR] [--cert C --key K]
        # team server: the app for everyone on the network, each person signs in (needs an admin account)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _default_workers() -> int:
    return max(1, (os.cpu_count() or 2))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="part_audit", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("scan", help="audit a folder of STEP files (+ optional ERP CSV) and write an Excel report")
    sc.add_argument("folder")
    sc.add_argument("--erp", help="ERP export CSV (part number, description, unit, material, supplier)")
    sc.add_argument("--out", default="out/part_audit_report.xlsx", help="Excel report path")
    sc.add_argument("--json", help="also write pairs/groups/mapping as JSON")
    sc.add_argument("--workers", type=int, default=_default_workers())
    sc.add_argument("--timeout", type=float, default=60.0, help="per-file geometry timeout in seconds")
    sc.add_argument("--cache", help="fingerprint cache folder (default: <out folder>/.part_audit_cache)")
    sc.add_argument("--no-geometry", action="store_true", help="hashes and names only (L1+L2), no OpenCascade")
    sc.add_argument("--no-shape-check", action="store_true", help="disable the L3b aligned-surface check")
    sc.add_argument("--ground-truth", help="ground_truth.csv to compute demo metrics (adds a Metrics sheet)")
    sc.add_argument("--thresholds", help="JSON file overriding scoring thresholds")
    sc.add_argument("--llm-endpoint", help="OPTIONAL local OpenAI-compatible endpoint (e.g. http://localhost:11434/v1). "
                                         "Off by default; only candidate names are sent, never files.")
    sc.add_argument("--llm-model", default="")
    sc.add_argument("--llm-allow-remote", action="store_true", help="allow a non-localhost LLM endpoint")
    sc.add_argument("-q", "--quiet", action="store_true")

    fp = sub.add_parser("fingerprint", help="print the geometry fingerprint of one STEP file")
    fp.add_argument("file")

    ck = sub.add_parser("check", help="pre-release check: is this STEP file already a part of the latest scan?")
    ck.add_argument("file")
    ck.add_argument("--pn", default="", help="the part number planned for the new part")
    ck.add_argument("--name", default="", help="the planned name / description")
    ck.add_argument("--material", default="")
    ck.add_argument("--workspace", default=str(Path.home() / "PartAudit"), help="the app's workspace (its latest scan)")
    ck.add_argument("--json", action="store_true", help="print the whole result as JSON")

    rs = sub.add_parser("rescan", help="scan the sources configured in the app's workspace (OS task scheduler)")
    rs.add_argument("--workspace", default=str(Path.home() / "PartAudit"))
    rs.add_argument("--no-email", action="store_true", help="do not send the e-mail even when it is turned on")

    ap_app = sub.add_parser("app", help="start the local web app (Hebrew UI) on 127.0.0.1")
    ap_app.add_argument("--port", type=int, default=8765)
    ap_app.add_argument("--host", default="127.0.0.1", help="loopback only (127.0.0.1, localhost, ::1)")
    ap_app.add_argument("--workspace", default=str(Path.home() / "PartAudit"),
                        help="folder for the app database, caches, results and exports")
    ap_app.add_argument("--no-demo", action="store_true", help="do not offer the demo environment")
    ap_app.add_argument("--no-browser", action="store_true")

    sv = sub.add_parser("serve", help="team server: the app for the whole network, everyone signs in")
    sv.add_argument("--host", default="0.0.0.0", help="address to listen on (default: every network interface)")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--workspace", default=str(Path.home() / "PartAudit"))
    sv.add_argument("--cert", help="TLS certificate file (PEM) for https; recommended outside a closed network")
    sv.add_argument("--key", help="TLS private key file (PEM)")
    sv.add_argument("--no-demo", action="store_true", help="do not offer the demo environment")

    us = sub.add_parser("users", help="accounts for team mode")
    us.add_argument("action", choices=["list", "add", "password", "role", "disable", "enable"])
    us.add_argument("name", nargs="?", default="")
    us.add_argument("role_arg", nargs="?", default="", metavar="ROLE")
    us.add_argument("--role", default="", help="viewer | engineer | admin")
    us.add_argument("--display", default="", help="the name shown next to decisions")
    us.add_argument("--email", default="")
    us.add_argument("--password-stdin", action="store_true", help="read the password from standard input")
    us.add_argument("--workspace", default=str(Path.home() / "PartAudit"))

    bk = sub.add_parser("backup", help="save the workspace (decisions, sources, results) to a zip file")
    bk.add_argument("out", help="the zip file to write")
    bk.add_argument("--workspace", default=str(Path.home() / "PartAudit"))
    rt = sub.add_parser("restore", help="restore a backup zip into a workspace")
    rt.add_argument("zip", help="the backup file")
    rt.add_argument("--workspace", default=str(Path.home() / "PartAudit"))
    rt.add_argument("--force", action="store_true", help="replace an existing workspace (its database is kept aside)")

    args = ap.parse_args(argv)
    if args.cmd in ("backup", "restore"):
        from . import backup
        try:
            if args.cmd == "backup":
                n = backup.make_backup(args.workspace, args.out)
                print(f"{args.out}: {n} files. It holds the sources' connection settings: keep it private.")
            else:
                n = backup.restore_backup(args.zip, args.workspace, args.force)
                print(f"restored {n} files into {args.workspace}")
        except (OSError, ValueError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        return 0
    if args.cmd == "app":
        return run_app(args)
    if args.cmd == "serve":
        return run_server(args)
    if args.cmd == "users":
        return run_users(args)
    if args.cmd == "check":
        return run_check(args)
    if args.cmd == "rescan":
        return run_rescan(args)
    if args.cmd == "fingerprint":
        from .geometry import fingerprint_path
        print(json.dumps(fingerprint_path(args.file), indent=1, default=str))
        return 0

    from .audit import AuditConfig, run_audit, save_json
    from .report import write_report
    from .scoring import Thresholds

    th = Thresholds()
    if args.thresholds:
        for k, v in json.loads(Path(args.thresholds).read_text()).items():
            if not hasattr(th, k):
                ap.error(f"unknown threshold {k}")
            setattr(th, k, v)
    cache = args.cache or str(Path(args.out).resolve().parent / ".part_audit_cache")
    cfg = AuditConfig(root=args.folder, erp_csv=args.erp, out_xlsx=args.out, workers=args.workers,
                      use_geometry=not args.no_geometry, shape_check=not args.no_shape_check,
                      timeout_s=args.timeout, cache_dir=cache, ground_truth=args.ground_truth,
                      llm_endpoint=args.llm_endpoint, llm_model=args.llm_model,
                      llm_allow_remote=args.llm_allow_remote, thresholds=th, verbose=not args.quiet)
    res = run_audit(cfg)
    path = write_report(res, args.out)
    if args.json:
        save_json(res, args.json)
    print(f"report: {path}")
    if res.metrics:
        from .metrics import write_details
        stem = Path(args.out).with_suffix("")
        write_details(res.metrics, f"{stem}_eval_details.csv")
        Path(f"{stem}_metrics.json").write_text(json.dumps({k: v for k, v in res.metrics.items() if k != "details"},
                                                           indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"metrics: {stem}_metrics.json, details: {stem}_eval_details.csv")
        for row in res.metrics.get("per_type", []):
            print(f"  {row['type']:<34} n={row['n_pairs']} tp={row['tp']} fp={row['fp']} P={row['precision']} "
                  f"R={row['recall']} F1={row['f1']} target={row['target']} met={row['met']}")
    return 0


def run_check(args) -> int:
    """Pre-release check from the command line; nothing is stored in the workspace."""
    import tempfile

    from .decisions import group_targets
    from .precheck import CheckError, build_index, check_file
    from .project import ProjectSettings
    from .server.store import Store
    if not Path(args.file).is_file():
        print(f"file not found: {args.file}", file=sys.stderr)
        return 2
    store = Store(args.workspace)
    rid = store.latest_run()
    if not rid:
        print(f"no finished scan in {args.workspace} - run a scan in the app first", file=sys.stderr)
        return 2
    res = json.loads((store.run_dir(rid) / "result.json").read_text(encoding="utf-8"))
    st = ProjectSettings.from_dict(res.get("settings") or {})
    index = build_index(store.run_dir(rid), store.ws / "cache", run_id=rid)
    with tempfile.TemporaryDirectory(prefix="pa-check-") as own:
        try:
            out = check_file(index, args.file, {p["uid"]: p for p in res["parts"]}, pn=args.pn, name=args.name,
                             material=args.material, th=st.thresholds, cache_dir=store.ws / "cache", own_cache=own,
                             timeout_s=st.timeout_s, group_targets=group_targets(res, store.current_decisions()))
        except CheckError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    v = out["verdict"]
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print(v["title"])
        print(v["text"])
        for n in out["notes"]:
            print("- " + n["text"])
        for m in out["matches"][:10]:
            p = m["part"]
            print(f"  {m['category_he']}: {p['pn'] or '-'} {p['name']} ({p['source']})")
    bad_note = any(n["tone"] == "bad" for n in out["notes"])
    if v["kind"] == "exists" or bad_note:
        return 1
    return 0 if v["kind"] == "new" else 3


def run_rescan(args) -> int:
    """One scan of the workspace's sources, like the app's button; prints what changed since the scan before."""
    import time

    from .runner import run_scan
    from .server.store import Store
    store = Store(args.workspace)
    if not [s for s in store.list_sources() if s["enabled"]]:
        print(f"no active sources in {args.workspace} - add them in the app first", file=sys.stderr)
        return 2
    if any(s["simulated"] for s in store.list_sources() if s["enabled"]):
        print("note: the demo systems run inside the app - keep the app open while this scan runs")
    last = [""]

    def progress(stage, frac, detail):
        if detail != last[0]:
            last[0] = detail
            print(f"[{time.strftime('%H:%M:%S')}] {detail}", flush=True)
    try:
        out = run_scan(store, progress, lambda: False, trigger="cli", send_email=not args.no_email)
    except Exception as exc:
        print(f"scan failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(f"run {out['run_id']}: {out['summary']['parts']} parts, {out['summary']['groups']} duplicate groups")
    if out.get("headline"):
        print(out["headline"])
    return 0


def _read_password(from_stdin: bool, username: str) -> str | None:
    import getpass

    from .server.auth import password_problem
    if from_stdin:
        pw = sys.stdin.readline().rstrip("\r\n")
    else:
        pw = getpass.getpass("password: ")
        if getpass.getpass("again: ") != pw:
            print("the two passwords differ", file=sys.stderr)
            return None
    problem = password_problem(pw, username)
    if problem:
        print(problem, file=sys.stderr)
        return None
    return pw


def run_users(args) -> int:
    """Manage team-mode accounts from the command line (the first admin, a forgotten password)."""
    from .server.auth import ROLES, hash_password, username_problem
    from .server.store import Store
    store = Store(args.workspace)
    if args.action == "list":
        for u in store.list_users():
            how = "+".join(x for x, on in (("password", u["pw_hash"]), ("company", u["oidc_sub"])) if on) or "-"
            print(f"{u['username']:<30} {u['role']:<9} {'disabled' if u['disabled'] else 'active':<9} {how:<17} "
                  f"{u['display_name'] or ''}  last sign-in: {u['last_login'] or '-'}")
        return 0
    if not args.name:
        print("a user name is needed", file=sys.stderr)
        return 2
    u = store.find_user(args.name)
    if args.action == "add":
        role = args.role or args.role_arg or "viewer"
        problem = username_problem(args.name)
        if problem or role not in ROLES or u:
            print(problem or (f"unknown role {role!r} (viewer, engineer, admin)" if role not in ROLES
                              else f"user {args.name!r} exists"), file=sys.stderr)
            return 2
        pw = _read_password(args.password_stdin, args.name)
        if pw is None:
            return 2
        store.add_user(args.name, role, display_name=args.display, email=args.email, pw_hash=hash_password(pw))
        print(f"user {args.name} added ({role})")
        return 0
    if not u:
        print(f"no user {args.name!r}", file=sys.stderr)
        return 2
    if args.action == "password":
        pw = _read_password(args.password_stdin, u["username"])
        if pw is None:
            return 2
        store.update_user(u["id"], pw_hash=hash_password(pw))
        store.end_user_sessions(u["id"])
    elif args.action == "role":
        role = args.role_arg or args.role
        if role not in ROLES:
            print(f"unknown role {role!r} (viewer, engineer, admin)", file=sys.stderr)
            return 2
        if u["role"] == "admin" and role != "admin" and not store.count_admins(except_id=u["id"]):
            print("at least one active admin has to stay", file=sys.stderr)
            return 2
        store.update_user(u["id"], role=role)
    else:
        off = args.action == "disable"
        if off and u["role"] == "admin" and not store.count_admins(except_id=u["id"]):
            print("at least one active admin has to stay", file=sys.stderr)
            return 2
        store.update_user(u["id"], disabled=int(off))
        if off:
            store.end_user_sessions(u["id"])
    print("done")
    return 0


def run_server(args) -> int:
    """The team server: listens on the network; every person signs in (auth.py has who may do what)."""
    import socket

    import uvicorn

    from .server.app import create_app
    from .server.store import Store
    store = Store(args.workspace)
    if not store.count_admins():
        print("Team mode needs an admin account first. Create one with:\n"
              f"  python -m part_audit users add <name> --role admin --workspace \"{args.workspace}\"\n"
              "or in the app (Settings > Team) on this computer.", file=sys.stderr)
        return 3
    if bool(args.cert) != bool(args.key):
        print("--cert and --key go together", file=sys.stderr)
        return 2
    if not _port_free(args.host, args.port):
        print(f"port {args.port} is in use on {args.host} - choose another with --port", file=sys.stderr)
        return 2
    demo = not args.no_demo
    if args.cert and demo:
        demo = False          # the demo systems are called by the server over plain http on 127.0.0.1
        print("note: the demo environment is not offered with --cert")
    scheme = "https" if args.cert else "http"
    app = create_app(args.workspace, demo=demo, base_url=f"http://127.0.0.1:{args.port}", scheduler=True, team=True)
    print(f"PartAudit team server: {scheme}://{socket.gethostname()}:{args.port}  (workspace: {args.workspace})")
    if not args.cert:
        print("note: without --cert passwords cross the network unencrypted - use it outside a closed network, "
              "or put the server behind your https proxy")
    uvicorn.run(app, host=args.host, port=args.port, ssl_certfile=args.cert, ssl_keyfile=args.key, log_level="warning")
    return 0


def _running_here(url: str) -> bool:
    """True if a PartAudit app already answers on this address (asked directly, never through a proxy)."""
    import json
    import urllib.request
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + "/api/status", timeout=1.5) as r:
            return "demo_available" in json.loads(r.read().decode("utf-8"))
    except Exception:
        return False


def _port_free(host: str, port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def run_app(args) -> int:
    import threading
    import webbrowser

    import uvicorn

    from .server.app import create_app
    host = args.host if args.host in ("127.0.0.1", "localhost", "::1") else "127.0.0.1"
    if host != args.host:
        print(f"PartAudit only listens on this computer: {args.host!r} ignored, using 127.0.0.1")
    name = f"[{host}]" if ":" in host else host
    port = args.port
    if _running_here(f"http://{name}:{port}"):
        print(f"PartAudit already runs at http://{name}:{port} - opening it")
        if not args.no_browser:
            webbrowser.open(f"http://{name}:{port}")
        return 0
    for p in range(args.port, args.port + 30):
        if _port_free(host, p):
            port = p
            break
    url = f"http://{name}:{port}"
    app = create_app(args.workspace, demo=not args.no_demo, base_url=url, scheduler=True)
    print(f"PartAudit is running: {url}  (workspace: {args.workspace})  - close this window to stop")
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
