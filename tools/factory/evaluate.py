"""Measure the v2 pipeline on the demo factory against what was planted (factory.json 'truth').

Runs the real connectors against the local simulators (no shortcuts), then the audit, and compares:
duplicate groups (pairwise precision/recall, by how the copy was made), near-identical, mirror pairs,
hard negatives, same-PN conflicts, NIST cross-CAD exports, and every planted data-quality issue.

    python tools/factory/evaluate.py --out results/demo_factory_eval.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path[:0] = [str(ROOT)]

from part_audit.demo import DEMO_DIR, demo_sources  # noqa: E402
from part_audit.project import ProjectSettings, audit_snapshot, collect  # noqa: E402
from part_audit.simulators import ServerThread, create_sim_app  # noqa: E402

KIND_TO_SYSTEM = {"swpdm_web": "swpdm", "vault": "vault", "windchill": "windchill", "teamcenter": "teamcenter",
                  "folder": "folder"}
PLANT_TO_CHECK = {
    "missing_material": "missing_material", "stale_mass_high": "mass_mismatch", "stale_mass_low": "mass_mismatch",
    "filename_pn_mismatch": "filename_pn_mismatch", "pn_format": "pn_format", "bom_state_in_work": "bom_state",
    "bom_state_obsolete": "obsolete_in_use", "missing_in_erp": "released_not_in_erp",
    "erp_description_differs": "erp_description_mismatch", "erp_material_differs": "erp_material_mismatch",
    "erp_bom_qty_differs": "erp_bom_mismatch", "obsolete_but_active_in_erp": "erp_status_mismatch",
    "missing_description": "missing_description",
}


def ratio(a: int, b: int):
    return None if b == 0 else round(a / b, 4)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--factory", default=str(DEMO_DIR))
    ap.add_argument("--cache", default=str(ROOT / "out" / "demo_eval_cache"))
    ap.add_argument("--out", default=str(ROOT / "results" / "demo_factory_eval.json"))
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    fac = json.loads((Path(a.factory) / "factory.json").read_text(encoding="utf-8"))
    t0 = time.time()
    with ServerThread(create_sim_app(a.factory)) as srv:
        snap = collect([s for s in demo_sources(srv.url, a.factory) if s["enabled"]], a.cache)
    t_collect = time.time() - t0
    t1 = time.time()
    res = audit_snapshot(snap, ProjectSettings(workers=a.workers), a.cache)
    t_audit = time.time() - t1
    (Path(a.cache) / "result.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")

    # ---------------------------------------------------------------- map app records to factory records
    by_native = {(r["system"], r.get("native_file")): r for r in fac["records"] if r["site"] != "archive"}
    by_step = {r.get("step_file"): r for r in fac["records"] if r["site"] == "archive"}
    truth_of: dict[str, dict] = {}
    for p in res["parts"]:
        sysname = KIND_TO_SYSTEM.get(p["source_kind"], "")
        if sysname == "folder":
            rel = p["uid"].split(":", 1)[1]
            r = by_step.get(f"archive/{rel}")
        else:
            r = by_native.get((sysname, p["native_file"]))
        if r is not None:
            truth_of[p["uid"]] = r
    parts = [p for p in res["parts"] if p["kind"] == "part"]
    unmapped = [p["uid"] for p in parts if p["uid"] not in truth_of]

    # ---------------------------------------------------------------- duplicates (pairwise)
    group_of = {u: g["id"] for g in res["groups"] for u in g["members"]}
    pair_cat = {(p["a"], p["b"]): p for p in res["pairs"]}
    uids = sorted(p["uid"] for p in parts if p["uid"] in truth_of)
    has_step = {p["uid"]: p["has_step"] for p in parts}
    tp = fp_ = fn = 0
    by_how = defaultdict(lambda: [0, 0])
    fp_examples, fn_examples = [], []
    rel = Counter()
    for u, v in combinations(uids, 2):
        ru, rv = truth_of[u], truth_of[v]
        same = ru["gt"] == rv["gt"]
        pred = group_of.get(u) is not None and group_of.get(u) == group_of.get(v)
        if same:
            how = "+".join(sorted({_how(ru), _how(rv)}))
            step = "both STEP" if has_step[u] and has_step[v] else "STEP missing"
            by_how[f"{how} | {step}"][1] += 1
            if pred:
                tp += 1
                by_how[f"{how} | {step}"][0] += 1
            else:
                fn += 1
                if len(fn_examples) < 15:
                    pc = pair_cat.get((u, v)) or pair_cat.get((v, u))
                    fn_examples.append({"a": ru["name"], "b": rv["name"], "how": how, "step": step,
                                        "category": pc["category"] if pc else None})
        elif pred:
            fp_ += 1
            if len(fp_examples) < 15:
                fp_examples.append({"a": ru["name"], "b": rv["name"], "gt_a": ru["gt"], "gt_b": rv["gt"]})
        # relations that are not duplicates
        if ru["did"] and ru["did"] == rv["did"] and ru["gt"] != rv["gt"]:
            kinds = {ru["variant"], rv["variant"]}
            pc = pair_cat.get((u, v)) or pair_cat.get((v, u))
            cat = pc["category"] if pc else "(not flagged)"
            for k in ("near", "mirror", "oldrev", "legacy_only"):
                if k in kinds:
                    label = k
                    if k == "near" and ru.get("volume_mm3") and rv.get("volume_mm3"):
                        dv = abs(ru["volume_mm3"] - rv["volume_mm3"]) / max(ru["volume_mm3"], rv["volume_mm3"])
                        label = "near (volume change <= 10%)" if dv <= 0.10 else "near (volume change > 10%)"
                    rel[(label, cat, "merged" if pred else "not merged")] += 1
    # hard negatives: same geometry by construction, different item
    hn = Counter()
    hn_dids = [t["dids"] for t in fac["truth"] if t["type"] == "hard_negative"]
    for base, twin in hn_dids:
        us = [u for u in uids if truth_of[u]["did"] == base]
        vs = [u for u in uids if truth_of[u]["did"] == twin]
        for u in us:
            for v in vs:
                pred = group_of.get(u) is not None and group_of.get(u) == group_of.get(v)
                pc = pair_cat.get((u, v)) or pair_cat.get((v, u))
                hn[("merged" if pred else "not merged", pc["category"] if pc else "(not flagged)")] += 1
    # NIST real cross-CAD exports
    nist = Counter()
    nist_u = [u for u in uids if str(truth_of[u]["gt"]).startswith("nist_")]
    for u, v in combinations(nist_u, 2):
        same_case = truth_of[u]["gt"] == truth_of[v]["gt"]
        pc = pair_cat.get((u, v)) or pair_cat.get((v, u))
        nist[("same case" if same_case else "different case", pc["category"] if pc else "(not flagged)")] += 1

    # ---------------------------------------------------------------- data quality plants
    issues = defaultdict(set)
    for q in res["quality"] + res["erp_issues"]:
        for u in q["uids"]:
            issues[q["type"]].add(u)
    plant_rows = {}
    planted_uids = defaultdict(set)
    for u, r in truth_of.items():
        for pl in r.get("plants", []):
            planted_uids[pl].add(u)
    for u, r in ((p["uid"], truth_of.get(p["uid"])) for p in res["parts"]):
        pass
    part_by_uid = {p["uid"]: p for p in res["parts"]}

    def detectable(pl: str, u: str) -> bool:
        p = part_by_uid.get(u, {})
        if pl == "missing_material":
            return p.get("make_buy") != "buy"                      # the check covers manufactured parts
        if pl.startswith("stale_mass"):
            return bool(p.get("has_step") and p.get("material"))   # needs geometry and a material
        if pl == "missing_description":
            # the demo's SOLIDWORKS PDM keeps the description in the name variable: an empty one is not visible
            return p.get("source_kind") != "swpdm_web"
        return True
    for pl, check in PLANT_TO_CHECK.items():
        all_planted = planted_uids.get(pl, set())
        us = {u for u in all_planted if detectable(pl, u)}
        found = {u for u in us if u in issues.get(check, set())}
        # planted: everything planted; checkable: the part the check is designed to see (see detectable())
        plant_rows[pl] = {"check": check, "planted": len(all_planted), "checkable": len(us), "found": len(found),
                          "recall": ratio(len(found), len(us)),
                          "issues_of_this_type": len(issues.get(check, set())),
                          "on_unplanted_records": len(issues.get(check, set()) - set().union(
                              *[planted_uids.get(p2, set()) for p2, c2 in PLANT_TO_CHECK.items() if c2 == check]))}
    unit_err = [u for u, r in truth_of.items() if r["variant"] == "unit_error"]
    plant_rows["unit_error (archive)"] = {"check": "unit_error", "planted": len(unit_err), "checkable": len(unit_err),
                                          "found": sum(1 for u in unit_err if u in issues.get("unit_error", set())),
                                          "recall": ratio(sum(1 for u in unit_err if u in issues.get("unit_error", set())),
                                                          len(unit_err))}
    out = {
        "what": "v2 pipeline on the synthetic demo factory, via real connectors against local simulators",
        "seconds": {"collect": round(t_collect, 1), "audit": round(t_audit, 1)}, "timings": res["timings"],
        "summary": res["summary"], "records_mapped": len(truth_of), "records_unmapped": len(unmapped),
        "duplicates": {"pairs_true": tp + fn, "pairs_predicted": tp + fp_, "tp": tp, "fp": fp_, "fn": fn,
                       "precision": ratio(tp, tp + fp_), "recall": ratio(tp, tp + fn),
                       "recall_by_how": {k: {"found": v[0], "total": v[1], "recall": ratio(*v)} for k, v in
                                         sorted(by_how.items())},
                       "fp_examples": fp_examples, "fn_examples": fn_examples},
        "same_design_not_duplicate": {f"{k[0]} -> {k[1]} ({k[2]})": n for k, n in sorted(rel.items())},
        "hard_negatives": {f"{k[0]} / {k[1]}": n for k, n in sorted(hn.items())},
        "nist": {f"{k[0]} -> {k[1]}": n for k, n in sorted(nist.items())},
        "data_quality": plant_rows,
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("seconds", "records_mapped", "records_unmapped", "duplicates",
                                          "same_design_not_duplicate", "hard_negatives", "nist", "data_quality")},
                     ensure_ascii=False, indent=1, default=str))


def _how(r: dict) -> str:
    v = r["variant"]
    if v == "library":
        return "library"
    return v


if __name__ == "__main__":
    main()
