"""Command line interface.

    python -m part_audit app [--port 8765] [--workspace DIR]   # the local Hebrew web app (opens the browser)
    python -m part_audit scan DATA_DIR [--erp erp.csv] [--out out/report.xlsx]
    python -m part_audit fingerprint FILE.step        # debug one file
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

    ap_app = sub.add_parser("app", help="start the local web app (Hebrew UI) on 127.0.0.1")
    ap_app.add_argument("--port", type=int, default=8765)
    ap_app.add_argument("--host", default="127.0.0.1", help="loopback only (127.0.0.1, localhost, ::1)")
    ap_app.add_argument("--workspace", default=str(Path.home() / "PartAudit"),
                        help="folder for the app database, caches, results and exports")
    ap_app.add_argument("--no-demo", action="store_true", help="do not offer the demo environment")
    ap_app.add_argument("--no-browser", action="store_true")

    args = ap.parse_args(argv)
    if args.cmd == "app":
        return run_app(args)
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
    app = create_app(args.workspace, demo=not args.no_demo, base_url=url)
    print(f"PartAudit is running: {url}  (workspace: {args.workspace})  - close this window to stop")
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
