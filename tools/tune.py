"""Threshold sweep on the DEV set only (never on the test set).

Runs the audit once (fingerprints cached), then re-scores with every threshold
combination in a grid and prints the metrics, so thresholds can be chosen on dev.

    python tools/tune.py --data data/dev --out out/tune_dev.json
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent)]

from part_audit.audit import AuditConfig, run_audit  # noqa: E402
from part_audit.metrics import evaluate  # noqa: E402
from part_audit.scoring import Thresholds, build_pairs, duplicate_groups, propose_mapping  # noqa: E402

GRIDS = {  # geometry and name thresholds act on different metrics, so they are swept separately
    "geo": {"geo_near": [0.05, 0.08, 0.10, 0.15], "shape_near_excess50": [2.0, 3.0, 4.0]},
    "names": {"name_similar": [0.85, 0.90], "name_k0": [2, 3, 4], "name_partial_factor": [0.8, 0.85, 0.9]},
}


def key_metrics(m: dict) -> dict:
    out = {}
    for r in m["per_type"]:
        t = r["type"]
        if t in "ABCDEF" and len(t) == 1:
            out[t] = {"P": r["precision"], "R": r["recall"], "F1": r["f1"], "met": r["met"]}
        elif t.startswith("False positives"):
            out["FP_rate"] = m["summary"]["FP rate"]
        elif t.startswith("Hard negatives"):
            out[t.split(": ")[1]] = r["recall"]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--sweep", choices=sorted(GRIDS), action="append")
    a = ap.parse_args()
    d = Path(a.data)
    cfg = AuditConfig(root=str(d / "cad"), erp_csv=str(d / "erp_export.csv"), workers=a.workers,
                      cache_dir=str(d / "out" / "cache"), verbose=False)
    base = run_audit(cfg)
    from part_audit.geometry import FingerprintCache
    from part_audit.shape import ShapeChecker
    memo: dict = {}
    checker = ShapeChecker(FingerprintCache(cfg.cache_dir), cfg.thresholds)

    def shape_fn(ia, ib, geo):
        k = (ia.file_id, ib.file_id, round(geo.scale, 6))
        if k not in memo:
            memo[k] = checker(ia, ib, geo)
        return memo[k]

    results = []
    combos = []
    for name in a.sweep or sorted(GRIDS):
        grid = GRIDS[name]
        keys = list(grid)
        combos += [dict(zip(keys, c)) for c in itertools.product(*(grid[k] for k in keys))]
    for params in combos:
        th = replace(Thresholds(), **params)
        pairs = build_pairs(base.items, th, use_geometry=True, shape_check=shape_fn)
        groups = duplicate_groups(pairs)
        res = replace(base, pairs=pairs, groups=groups, mapping=propose_mapping(groups, base.items, pairs),
                      config=replace(cfg, thresholds=th))
        km = key_metrics(evaluate(res, d / "ground_truth.csv"))
        results.append({"params": params, "metrics": km})
        print(params, json.dumps(km), flush=True)
    Path(a.out).write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
