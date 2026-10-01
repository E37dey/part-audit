"""Real STEP files from different CAD systems: NIST MBE PMI test models.

Copies the NIST STEP files (from the 'NIST-PMI-STEP-Files' and 'NIST-FTC-CTC-PMI-CAD-models'
archives) into one folder, runs the audit, and lists for every pair of files of the same
NIST test case (same ctc/ftc number) what the tool reported, plus every flagged pair that
crosses test cases. NIST does not publish which files share identical geometry, so the
only label used is 'same test case' (same design, possibly modelled independently in
different CAD systems).

    python tools/nist_check.py --nist RAW/nist RAW/NIST-FTC-CTC-PMI-CAD-models --out out/nist
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent)]

from part_audit.audit import AuditConfig, run_audit  # noqa: E402
from part_audit.report import write_report  # noqa: E402


def case_id(name: str) -> str:
    m = re.search(r"nist_(ctc|ftc|stc)_(\d+)", name)
    return f"{m.group(1)}_{int(m.group(2)):02d}" if m else ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nist", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    out = Path(a.out)
    data = out / "nist_files"
    if data.exists():
        shutil.rmtree(data)
    for src in a.nist:
        for p in sorted(Path(src).rglob("*.stp")):
            rel = Path(Path(src).name) / p.relative_to(src)
            dst = data / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dst)
    cfg = AuditConfig(root=str(data), out_xlsx=str(out / "nist_report.xlsx"), workers=a.workers,
                      cache_dir=str(out / ".cache"), verbose=False)
    res = run_audit(cfg)
    write_report(res, out / "nist_report.xlsx")
    pairs = {(p.a, p.b): p for p in res.pairs}
    files = sorted(res.items)
    rows = []
    for x, y in combinations(files, 2):
        cx, cy = case_id(x), case_id(y)
        p = pairs.get((x, y))
        same_case = bool(cx) and cx == cy
        kind = "stc-vs-ftc" if {cx[:3], cy[:3]} == {"stc", "ftc"} and cx[4:] == cy[4:] else ""
        if same_case or kind or (p and p.category in ("identical", "near_identical", "conflict")):
            rows.append({"file_a": x, "file_b": y, "case_a": cx, "case_b": cy,
                         "relation": "same test case" if same_case else (kind or "different test cases"),
                         "category": p.category if p else "(not flagged)", "geo": p.geo_relation if p else "",
                         "max_rel": None if (p is None or p.geo is None or p.geo.max_rel == float("inf")) else p.geo.max_rel,
                         "reason": p.reason if p else ""})
    summary: dict = {"files": len(files), "errors": [(s.file_id, s.reason) for s in res.skipped]}
    for rel in ("same test case", "stc-vs-ftc", "different test cases"):
        sub = [r for r in rows if r["relation"] == rel]
        cats: dict[str, int] = {}
        for r in sub:
            cats[r["category"]] = cats.get(r["category"], 0) + 1
        summary[rel] = {"pairs": len(sub), "by_category": cats}
    summary["timings"] = res.timings
    (out / "nist_pairs.json").write_text(json.dumps({"summary": summary, "pairs": rows}, indent=1, default=str))
    print(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    main()
