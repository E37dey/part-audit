"""Work-order step 2: L3 feasibility check - fingerprint N STEP files and report timing.

    python tools/feasibility.py --abc-dir RAW/abc0 --nist-dir RAW/nist --n 50 --out out/feasibility.json
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import random
import statistics
import time
from pathlib import Path

from part_audit.geometry import fingerprint_files


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--abc-dir", required=True)
    ap.add_argument("--nist-dir")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--timeout", type=float, default=60)
    ap.add_argument("--seed", type=int, default=2)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    abc = sorted(str(p) for p in Path(a.abc_dir).rglob("*.step"))
    rng = random.Random(a.seed)
    files = rng.sample(abc, a.n)
    if a.nist_dir:
        files += sorted(str(p) for p in Path(a.nist_dir).rglob("*.stp"))
    tasks = [(f, f, f) for f in files]
    t0 = time.perf_counter()
    fps, errs, stats, _ = fingerprint_files(tasks, workers=a.workers, timeout_s=a.timeout)
    wall = time.perf_counter() - t0
    rows = []
    for f in files:
        fp = fps.get(f, {})
        rows.append({"file": os.path.relpath(f, Path(a.abc_dir).parent), "size_kb": round(os.path.getsize(f) / 1024, 1),
                     "ok": bool(fp.get("ok")) and f not in errs, "error": errs.get(f, ("", ""))[0],
                     "t_wall": fp.get("t_wall"), "t_read": fp.get("t_read"), "t_props": fp.get("t_props"),
                     "t_mesh": fp.get("t_mesh"), "n_faces": fp.get("n_faces"), "n_solids": fp.get("n_solids")})
    tw = [r["t_wall"] for r in rows if r["t_wall"] is not None]

    def q(xs, p):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(p * (len(xs) - 1)))] if xs else None

    summary = {
        "files": len(files), "ok": sum(r["ok"] for r in rows), "errors": len(errs), "workers": a.workers,
        "timeout_s": a.timeout, "wall_s": round(wall, 2),
        "per_file_s": {"mean": round(statistics.mean(tw), 3), "median": round(q(tw, 0.5), 3),
                       "p90": round(q(tw, 0.9), 3), "max": round(max(tw), 3)},
        "share_read": round(sum(r["t_read"] or 0 for r in rows) / max(1e-9, sum(tw)), 3),
        "share_props": round(sum(r["t_props"] or 0 for r in rows) / max(1e-9, sum(tw)), 3),
        "share_mesh": round(sum(r["t_mesh"] or 0 for r in rows) / max(1e-9, sum(tw)), 3),
        "size_kb": {"median": q([r["size_kb"] for r in rows], 0.5), "max": max(r["size_kb"] for r in rows)},
        "machine": {"cpu_count": os.cpu_count(), "platform": platform.platform(), "python": platform.python_version()},
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"summary": summary, "files": rows}, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
