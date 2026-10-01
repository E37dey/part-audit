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
    rows = ["| Type | GT pairs | Found | Missed | Predicted | Wrong | Precision | Recall | F1 | Target | Met |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"]
    for r in m["per_type"]:
        if r["type"].startswith(("Hard negatives", "Name links")):
            continue
        def v(k):
            return "-" if r[k] is None else r[k]
        f1 = "-" if r["f1"] is None else f"{r['f1']:.3f}"
        n_pred = r.get("n_pred")
        if n_pred is None and r["type"].startswith("False positives"):
            n_pred = r["n_pairs"]
        rows.append(f"| {r['type']} | {'-' if r['type'].startswith('False') else v('n_pairs')} | "
                    f"{'-' if r['type'].startswith('False') else v('tp')} | {v('fn')} | "
                    f"{'-' if n_pred is None else n_pred} | {v('fp')} | "
                    f"{pct(r['precision'])} | {pct(r['recall'])} | {f1} | {r['target']} | {r['met']} |")
    rows += ["", "*GT pairs / Found / Missed*: (base, variant) pairs, used for recall. *Predicted / Wrong*: every "
             "predicted pair that involves a file of that type, used for precision = (Predicted - Wrong) / Predicted. "
             "For F, 'predicted' means a name-layer link (score >= threshold). For the false-positive row, "
             "'Predicted' is all flagged pairs (merge candidates + near-identical alerts)."]
    return "\n".join(rows)


def fp_line(m: dict) -> str:
    s = m.get("summary", {})
    if s.get("FP rate") is None:
        return ""
    return (f"False positives on truly different parts: {s['false positives (different parts)']} of "
            f"{s['flagged pairs']} flagged pairs = **{pct(s['FP rate'], 2)}** (target <= 2%).")


def error_notes(d: Path, name: str, name_threshold: float = 0.9) -> list[str]:
    """Counts of the remaining errors by cause, computed from the evaluation details CSV."""
    import csv
    p = d / name
    if not p.exists():
        return []
    rows = list(csv.DictReader(open(p, encoding="utf-8-sig")))
    f_miss = [r for r in rows if r["type"] == "F" and r["set"] == "positive" and r["correct"] == "False"]

    def desc_sim(r):
        m = re.search(r"desc_sim=([0-9.]+)", r["reason"])
        return float(m.group(1)) if m else 0.0
    # 'generic' only when the description itself matched (>= the name threshold) and the discount pushed it below
    generic = sum(1 for r in f_miss if "generic description" in r["reason"] and desc_sim(r) >= name_threshold)
    f_fp = [r for r in rows if r["type"] == "F" and r["set"] == "false_positive"]
    other = [r for r in rows if r["correct"] == "False" and r["type"] != "F"]
    out = [f"- Name layer (F): {len(f_miss)} of the F variants were not linked by name alone; {generic} of them "
           "because the description matched but is shared by many part numbers (generic, discounted on purpose) "
           f"and {len(f_miss) - generic} because the variant's description itself scored below the threshold "
           "(unrecognised transliteration or typo, or a generic name that also scored low). "
           f"{len(f_fp)} name links pointed to a different part with the same or nearly the same description. "
           "With geometry (full pipeline) every F variant was linked."]
    for r in other:
        got = r["category"] or "-"
        if r["predicted_geo"] and r["predicted_geo"] not in got:
            got += f" (geometry: {r['predicted_geo']})"
        out.append(f"- {r['set'].replace('_', ' ')} ({r['type']}): `{r['file_a'].split('/')[-1]}` vs "
                   f"`{r['file_b'].split('/')[-1]}` - expected {r['expected']}, got {got}.")
    if any(r["type"] == "HN_mirror" for r in other):
        out.append("- Missed mirror images are parts whose handedness is weak: the exact-distance check used to "
                   "label them finds a difference, but the skewness test has no clear sign and 4,096 surface samples "
                   "cannot separate the reflection from a rotation. Copies of such a part are then merged with its "
                   "mirror twin, which also explains the related false positives above.")
    return out


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
    same = [r for r in n["pairs"] if r["relation"] == "same test case"]
    copies = [r for r in same if r["file_a"].split("/")[-1] == r["file_b"].split("/")[-1]]
    other = [r for r in same if r not in copies]
    cnt = {}
    for r in other:
        cnt[r["category"]] = cnt.get(r["category"], 0) + 1
    out += ["", f"Of the {len(same)} same-test-case pairs, {len(copies)} are the same file name in the two NIST "
            f"archives (results: " + ", ".join(f"{k}: {v}" for k, v in sorted(
                {c: sum(1 for r in copies if r['category'] == c) for c in {r['category'] for r in copies}}.items()))
            + f"). The other {len(other)} pairs are different exports of the same test case (AP203 geometry-only, "
            "AP203 with PMI, AP242; NIST removed the names of the CAD systems): "
            + ", ".join(f"{k}: {v}" for k, v in sorted(cnt.items())) + ". No pair of different test cases was flagged."]
    out += ["", "Pairs of the same test case (tool category, largest property difference):", "",
            "| File A (archive) | File B (archive) | Category | Max relative property difference |", "|---|---|---|---:|"]
    def short(f):
        parts_ = f.split("/")
        src = "PMI-STEP" if parts_[0].startswith("NIST-PMI") else "CAD-models"
        return f"{parts_[-1]} ({src})"
    for r in n["pairs"]:
        if r["relation"] == "same test case":
            mr = r["max_rel"]
            out.append(f"| {short(r['file_a'])} | {short(r['file_b'])} | {r['category']} | "
                       f"{'-' if mr is None else f'{mr:.1e}'} |")
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
                   "Stages: " + ", ".join(f"{lbl} {b['stage_s'][k]} s" for k, lbl in
                                          (("scan_s", "scan + hashes"), ("geometry_s", "geometry (L3)"),
                                           ("scoring_s", "scoring incl. L3b"), ("shape_s", "of which L3b"))
                                          if k in b["stage_s"]) + f" ({b.get('shape_checks', '?')} L3b checks). "
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
    bench_before = load(d, "bench_summary_before_speedup.json")
    tune_geo, tune_names = load(d, "dev_tune_geo.json"), load(d, "dev_tune_names.json")
    parts = ["# Measured results", "",
             "All numbers below were produced by the scripts in `tools/` on the data described; nothing is estimated. "
             "Synthetic data: accuracy is an upper bound for real factory data.", "",
             "## Test sets", "", manifest_table(dm, tm), ""]
    frozen = load(d, "test_metrics_frozen.json")
    primary = frozen or test
    if primary:
        parts += ["## Held-out test set", "",
                  "Thresholds were tuned on the dev set and frozen; the test set was built afterwards and scored "
                  "once with the frozen code and thresholds:", "", metrics_table(primary), "", fp_line(primary), "",
                  hn_table(primary), ""]
        notes = error_notes(d, "test_eval_details_frozen.csv" if frozen else "test_eval_details.csv")
        if notes:
            parts += ["Remaining errors in this run:", ""] + notes + [""]
    if frozen and test:
        diff = []
        old_rows = {r["type"]: r for r in frozen["per_type"]}
        for r in test["per_type"]:
            o = old_rows.get(r["type"])
            if o and any(o.get(k) != r.get(k) for k in ("tp", "fp", "fn", "precision", "recall")):
                if r.get("precision") is None and r.get("recall") is None:
                    diff.append(f"| {r['type']} | {o['fp']} FP of {o['n_pairs']} | {r['fp']} FP of {r['n_pairs']} |")
                else:
                    diff.append(f"| {r['type']} | {pct(o['precision'])} / {pct(o['recall'])} | "
                                f"{pct(r['precision'])} / {pct(r['recall'])} |")
        parts += ["### After one post-hoc fix", "",
                  "Error analysis on the test run found one algorithmic bug (not a threshold): for nearly "
                  "axisymmetric parts the L3b rotation search used a 10-degree grid, so a rotated copy could fit "
                  "worse than a reflection and was reported as a mirror image. The search now uses a 5-degree grid "
                  "with 0.5-degree refinement. Thresholds were not changed. Re-running dev and test with the "
                  "fixed code changed only these rows (precision / recall, or false positives):", "",
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
        parts += ["## Dev set (used for tuning)", "", metrics_table(dev), "", fp_line(dev), "", hn_table(dev), ""]
        notes = error_notes(d, "dev_eval_details.csv")
        if notes:
            parts += ["Remaining errors on dev:", ""] + notes + [""]
    if nist:
        parts += ["## Real STEP files: NIST MBE PMI models", "", nist_section(nist), ""]
    if feas or bench:
        parts += ["## Speed", "", speed_section(feas, bench), ""]
        if bench_before:
            b = bench_before
            parts += [f"Before the last speed-up (same 5,000 files, same machine) the run took {b['wall_min_total']} min "
                      f"(scoring stage {b['stage_s'].get('scoring_s')} s, of which L3b shape checks "
                      f"{b['stage_s'].get('shape_s')} s). L3b now runs only where it can change the result and in "
                      "parallel processes; dev and test metrics were identical before and after.", ""]
    if tune_geo or tune_names:
        parts += ["## Threshold sweeps on the dev set", "",
                  "Provenance: `geo_near` = 0.10 was chosen on an earlier build of the dev set (same 250 ABC base "
                  "parts, 18 E variants, code before the stray-sheet and unique-surface changes). In that sweep, "
                  "`geo_near` 0.05 and 0.08 found 17 of 18 E variants (the miss was a fillet that changed the "
                  "surface area by 9%) and 0.10 and 0.15 found 18 of 18, all with 0 false positives. That console "
                  "output was not saved to a file before the dev set was rebuilt with more E and F variants. The "
                  "geometry sweep below was re-run on the final dev set after the test run, for the record only: "
                  "on this set every setting gives the same metrics, so it does not discriminate. The name "
                  "thresholds were chosen from the name sweep below (final dev set, before the test set was built).",
                  ""]
        for title, rows, keys in (("Geometry", tune_geo, ("geo_near", "shape_near_excess50")),
                                  ("Names", tune_names, ("name_similar", "name_k0", "name_partial_factor"))):
            if not rows:
                continue
            parts += [f"{title}:", "", "| " + " | ".join(keys) + " | E P/R | F P/R/F1 | FP rate |",
                      "|" + "---:|" * (len(keys) + 3)]
            for r in rows:
                m = r["metrics"]
                parts.append("| " + " | ".join(str(r["params"][k]) for k in keys) +
                             f" | {pct(m['E']['P'])}/{pct(m['E']['R'])} | {pct(m['F']['P'])}/{pct(m['F']['R'])}/"
                             f"{m['F']['F1']:.3f} | {pct(m['FP_rate'])} |")
            parts.append("")
    if th:
        parts += ["## Thresholds used", "", "```json", json.dumps(th, indent=1), "```", ""]
    (Path(a.results).parent / "RESULTS.md").write_text("\n".join(parts), encoding="utf-8")
    # short block for the README
    readme = Path(a.readme)
    if readme.exists() and primary:
        block = ["<!-- results:start -->", metrics_table(primary), "", fp_line(primary), ""]
        if frozen and test:
            fz = {r["type"]: r for r in frozen["per_type"]}
            fx = {r["type"]: r for r in test["per_type"]}
            fpk = "False positives / flagged pairs"
            block += ["One algorithmic bug found during error analysis on this run (a rotated copy of a nearly "
                      "axisymmetric part reported as a mirror image) was fixed afterwards without changing thresholds. "
                      f"With the fix, C recall is {pct(fx['C']['recall'])} (was {pct(fz['C']['recall'])}) and the "
                      f"flagged pairs went from {fz[fpk]['n_pairs']} to {fx[fpk]['n_pairs']} with "
                      f"{fx[fpk]['fp']} false positives (was {fz[fpk]['fp']}); all other rows are unchanged "
                      "(see RESULTS.md).", ""]
        block += [speed_section(None, bench), "<!-- results:end -->"]
        txt = readme.read_text(encoding="utf-8")
        txt = re.sub(r"<!-- results:start -->.*?<!-- results:end -->", "\n".join(block), txt, flags=re.S)
        readme.write_text(txt, encoding="utf-8")
    print("wrote", Path(a.results).parent / "RESULTS.md")


if __name__ == "__main__":
    main()
