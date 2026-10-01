"""Build RESULTS.md (and the results block in README.md) from measured JSON outputs only.

    python tools/make_results.py --results results/

Expects in --results: dev_metrics.json, test_metrics.json, dev_manifest.json, test_manifest.json,
nist_pairs.json, feasibility_l3.json, bench_summary.json, thresholds.json (any may be missing).
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def load(d: Path, name: str):
    p = d / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def pct(x, digits: int = 1) -> str:
    return "-" if x is None else f"{100 * x:.{digits}f}%"


def metrics_table(m: dict) -> str:
    rows = ["| Type | GT pairs | TP | FN | FP | Precision | Recall | F1 | Target | Met |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---|---|"]
    for r in m["per_type"]:
        if r["type"].startswith(("Hard negatives", "Name links")):
            continue
        def v(k):
            return "-" if r[k] is None else r[k]
        f1 = "-" if r["f1"] is None else f"{r['f1']:.3f}"
        rows.append(f"| {r['type']} | {v('n_pairs')} | {v('tp')} | {v('fn')} | {v('fp')} | "
                    f"{pct(r['precision'])} | {pct(r['recall'])} | {f1} | {r['target']} | {r['met']} |")
    return "\n".join(rows)


def hn_table(m: dict) -> str:
    rows = ["| Hard negative | Pairs | Handled correctly | Outcome counts |", "|---|---:|---:|---|"]
    for r in m["per_type"]:
        if r["type"].startswith("Hard negatives"):
            rows.append(f"| {r['type'].split(': ')[1]} | {r['n_pairs']} | {r['tp']} ({pct(r['recall'], 0)}) | "
                        f"{r['definition'].split('; ', 1)[1] if '; ' in r['definition'] else ''} |")
        elif r["type"].startswith("Name links"):
            name_row = r
    rows.append("")
    rows.append(f"All name-layer links (any type): {name_row['tp'] + name_row['fp']} links, "
                f"{pct(name_row['precision'])} within the same ground-truth group.")
    return "\n".join(rows)


def manifest_table(dev: dict | None, test: dict | None) -> str:
    rows = ["| | Dev (tuning) | Test (held out) |", "|---|---:|---:|"]
    keys = ["base", "A", "B", "C", "D", "E", "F", "HN_material", "HN_thickness", "HN_mirror"]

    def g(m, k):
        return "-" if m is None else m["counts"].get(k, 0)
    for k in keys:
        rows.append(f"| {k} files | {g(dev, k)} | {g(test, k)} |")
    for label, key in (("HN_name pairs", "hn_name_pairs"), ("total STEP files", "files"), ("ERP rows", "erp_rows")):
        rows.append(f"| {label} | {'-' if dev is None else dev[key]} | {'-' if test is None else test[key]} |")
    rows.append(f"| planted A-F share of files | {'-' if dev is None else pct(dev['planted_share'])} | "
                f"{'-' if test is None else pct(test['planted_share'])} |")
    for label, key in (("ABC files screened", "screened"), ("single-body valid", "single_body_valid"),
                       ("natural near-duplicates removed", "natural_duplicates_removed")):
        rows.append(f"| {label} | {'-' if dev is None else dev['screen'][key]} | {'-' if test is None else test['screen'][key]} |")
    return "\n".join(rows)


def nist_section(n: dict) -> str:
    s = n["summary"]
    out = [f"{s['files']} real STEP files (NIST CTC/FTC/STC test cases exported by different CAD systems; "
           f"some files appear in two NIST archives). Read errors: {len(s['errors'])}.", "",
           "| Relation (from NIST file names) | Pairs | Tool result |", "|---|---:|---|"]
    for rel in ("same test case", "stc-vs-ftc", "different test cases"):
        d = s.get(rel, {})
        cats = ", ".join(f"{k}: {v}" for k, v in sorted(d.get("by_category", {}).items())) or "-"
        out.append(f"| {rel} | {d.get('pairs', 0)} | {cats} |")
    out += ["", "Pairs of the same test case (tool category, largest property difference):", "",
            "| File A | File B | Category | Max property diff |", "|---|---|---|---:|"]
    for r in n["pairs"]:
        if r["relation"] == "same test case":
            mr = r["max_rel"]
            out.append(f"| {r['file_a'].split('/')[-1]} | {r['file_b'].split('/')[-1]} | {r['category']} | "
                       f"{'-' if mr is None else f'{100 * mr:.4f}%'} |")
    return "\n".join(out)


def speed_section(feas: dict | None, bench: dict | None) -> str:
    out = []
    if feas:
        s = feas["summary"]
        out.append(f"Feasibility (work order step 2): {s['files']} STEP files ({s['ok']} read OK, {s['errors']} errors), "
                   f"{s['workers']} worker, cold: mean {s['per_file_s']['mean']} s, median {s['per_file_s']['median']} s, "
                   f"p90 {s['per_file_s']['p90']} s, max {s['per_file_s']['max']} s per file "
                   f"(time split: read {pct(s['share_read'], 0)}, properties {pct(s['share_props'], 0)}, "
                   f"mesh {pct(s['share_mesh'], 0)}).")
    if bench:
        b = bench
        g = b["geometry_per_file_s"]
        out.append("")
        out.append(f"Benchmark: {b['files']} random ABC STEP files ({b['total_MB']} MB, median {b['size_kb_median']} KB, "
                   f"max {b['size_kb_max']} KB), {b['workers']} workers on a {b['cpu_count']}-vCPU cloud VM, cold cache: "
                   f"**{b['wall_min_total']} min total** ({b['seconds_per_file_wall']} s per file wall-clock). "
                   f"Geometry per file in a worker: mean {g.get('mean_s', g.get('mean'))} s, median {g.get('median_s', g.get('median'))} s, "
                   f"p90 {g.get('p90_s', g.get('p90'))} s, max {g.get('max_s', g.get('max'))} s. "
                   f"Stages: " + ", ".join(f"{k} {v} s" for k, v in b["stage_s"].items()) + ". "
                   f"Errors/skips: " + (", ".join(f"{k}: {v}" for k, v in b["errors_by_reason"].items()) or "none") + ". "
                   f"Peak RSS of the largest process: {b['peak_rss_MB_largest_child']} MB.")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--readme", default="README.md")
    a = ap.parse_args()
    d = Path(a.results)
    dev, test = load(d, "dev_metrics.json"), load(d, "test_metrics.json")
    dm, tm = load(d, "dev_manifest.json"), load(d, "test_manifest.json")
    nist, feas, bench, th = load(d, "nist_pairs.json"), load(d, "feasibility_l3.json"), load(d, "bench_summary.json"), \
        load(d, "thresholds.json")
    parts = ["# Measured results", "",
             "All numbers below were produced by the scripts in `tools/` on the data described; nothing is estimated. "
             "Synthetic data: accuracy is an upper bound for real factory data.", "",
             "## Test sets", "", manifest_table(dm, tm), ""]
    frozen = load(d, "test_metrics_frozen.json")
    primary = frozen or test
    if primary:
        parts += ["## Held-out test set", "",
                  "Thresholds were tuned on the dev set and frozen; the test set was built afterwards and scored "
                  "once with the frozen code and thresholds:", "", metrics_table(primary), "", hn_table(primary), ""]
    if frozen and test:
        diff = []
        old_rows = {r["type"]: r for r in frozen["per_type"]}
        for r in test["per_type"]:
            o = old_rows.get(r["type"])
            if o and any(o.get(k) != r.get(k) for k in ("tp", "fp", "fn", "precision", "recall")):
                diff.append(f"| {r['type']} | {pct(o['precision'])} / {pct(o['recall'])} | "
                            f"{pct(r['precision'])} / {pct(r['recall'])} |")
        parts += ["### After one post-hoc fix", "",
                  "Error analysis on the test run found one algorithmic bug (not a threshold): for nearly "
                  "axisymmetric parts the L3b rotation search used a 10-degree grid, so a rotated copy could fit "
                  "worse than a reflection and was reported as a mirror image. The search now uses a 5-degree grid "
                  "with 0.5-degree refinement. Thresholds were not changed. Re-running dev and test with the "
                  "fixed code changed only these rows (precision / recall):", "",
                  "| Row | Frozen run | After fix |", "|---|---|---|"] + (diff or ["| (no change) | | |"]) + [""]
    sens = load(d, "test_name_sensitivity.json")
    if sens:
        parts += ["### Name layer: sensitivity on the test set (post-hoc, not used for any number above)", "",
                  "| name_similar | name_k0 | partial factor | F precision | F recall | F1 |", "|---:|---:|---:|---:|---:|---:|"]
        for r in sens:
            p_, m = r["params"], r["metrics"]["F"]
            parts.append(f"| {p_['name_similar']} | {p_['name_k0']} | {p_['name_partial_factor']} | {pct(m['P'])} | "
                         f"{pct(m['R'])} | {m['F1']:.3f} |")
        parts.append("")
    if dev:
        parts += ["## Dev set (used for tuning)", "", metrics_table(dev), "", hn_table(dev), ""]
    if nist:
        parts += ["## Real STEP files: NIST MBE PMI models", "", nist_section(nist), ""]
    if feas or bench:
        parts += ["## Speed", "", speed_section(feas, bench), ""]
    if th:
        parts += ["## Thresholds used", "", "```json", json.dumps(th, indent=1), "```", ""]
    (Path(a.results).parent / "RESULTS.md").write_text("\n".join(parts), encoding="utf-8")
    # short block for the README
    readme = Path(a.readme)
    if readme.exists() and primary:
        block = ["<!-- results:start -->", metrics_table(primary), "", speed_section(None, bench), "<!-- results:end -->"]
        txt = readme.read_text(encoding="utf-8")
        txt = re.sub(r"<!-- results:start -->.*?<!-- results:end -->", "\n".join(block), txt, flags=re.S)
        readme.write_text(txt, encoding="utf-8")
    print("wrote", Path(a.results).parent / "RESULTS.md")


if __name__ == "__main__":
    main()
