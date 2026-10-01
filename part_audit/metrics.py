"""Demo-only evaluation against ground_truth.csv (+ hard_negative_pairs.csv).

Definitions (also written into the Metrics sheet):

* Ground-truth relation of two files: same group_id -> 'identical', or 'near' if
  one of them is an E (tiny change) variant; different group_id -> 'different'.
Recall counts (base, variant) pairs only; precision counts every predicted pair that involves a file of
that type (e.g. an A copy matched to another copy of the same part is a correct prediction too), so the
'predicted' and 'wrong' columns are the precision population, not TP + FP.

* A-D: positives are (base, variant) pairs. Recall = share proposed as merge
  candidates (category 'identical': L1 hash or geometric match incl. unit-scaled,
  and no ERP attribute conflict). Precision = among all merge candidates that
  involve a file of that type, share whose GT relation is identical.
* E: positives are (base, E-variant) pairs. Recall = share predicted 'near'.
  Precision = among pairs predicted near that involve an E file, share whose GT
  relation is near.
* F (name layer alone): a pair is linked when its L2 name score >= name_similar.
  Recall = share of (base, F-variant) pairs linked; precision = among links that
  involve an F file, share whose files are in the same GT group (same part or its
  E revision); links to a different group are false. F1 from those.
* FP rate: flagged pairs = merge candidates (category identical) + near-identical
  alerts; FP = a merge candidate whose files belong to different GT groups, or a
  near-identical alert between geometrically unrelated files (an HN_material copy
  counts as geometrically related to its base: same geometry, different material).
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

TARGETS = {
    "A": ("P>=95% and R>=95%", lambda p, r, f: p >= 0.95 and r >= 0.95),
    "B": ("P>=95% and R>=95%", lambda p, r, f: p >= 0.95 and r >= 0.95),
    "C": ("P>=95% and R>=95%", lambda p, r, f: p >= 0.95 and r >= 0.95),
    "D": ("P>=95% and R>=95%", lambda p, r, f: p >= 0.95 and r >= 0.95),
    "E": ("R>=80% at P>=90%", lambda p, r, f: p >= 0.90 and r >= 0.80),
    "F": ("F1>=0.85", lambda p, r, f: f >= 0.85),
}


def load_ground_truth(path: str | Path):
    rows = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows[r["file_id"]] = r
    hn = []
    hp = Path(path).with_name("hard_negative_pairs.csv")
    if hp.exists():
        with open(hp, newline="", encoding="utf-8") as fh:
            hn = list(csv.DictReader(fh))
    return rows, hn


def _ratio(a: int, b: int):
    return round(a / b, 4) if b else None


def _f1(p, r):
    if not p or not r:
        return 0.0 if (p is not None and r is not None) else None
    return round(2 * p * r / (p + r), 4)


def evaluate(res, gt_path: str | Path) -> dict:
    gt, hn = load_ground_truth(gt_path)
    th = res.config.thresholds
    items = res.items
    missing = [f for f in gt if f not in items]
    group = {f: r["group_id"] for f, r in gt.items()}
    gtype = {f: r["type"] for f, r in gt.items()}
    base_of = {f: r["base_file_id"] for f, r in gt.items()}

    # identity groups decide merges; for *geometric* claims (near-identical alerts) an
    # HN_material copy belongs to its base's group: same geometry, different material.
    geo_group = {f: (group.get(base_of[f], group[f]) if gtype[f] == "HN_material" else group[f]) for f in group}

    def gt_rel(a: str, b: str, geometric: bool = False) -> str:
        if a not in group or b not in group:
            return "unknown"
        g = geo_group if geometric else group
        if g[a] != g[b]:
            return "different"
        return "near" if "E" in (gtype[a], gtype[b]) else "identical"

    pred = {(p.a, p.b): p for p in res.pairs}

    def get(a: str, b: str):
        return pred.get((a, b) if a < b else (b, a))

    def pgeo(p) -> str:
        if p is None:
            return "none"
        return "identical" if p.geo_relation in ("identical", "unit_scaled") else p.geo_relation

    rows, details = [], []
    by_type: dict[str, list[str]] = defaultdict(list)
    for f, t in gtype.items():
        by_type[t].append(f)
    involving: dict[str, list] = defaultdict(list)
    for p in res.pairs:
        for f in (p.a, p.b):
            involving[gtype.get(f, "?")].append(p)

    def predicted(p, want: str) -> bool:
        if p is None:
            return False
        if want == "identical":  # a merge candidate
            return p.category == "identical" and p.merge_ok
        return pgeo(p) == "near"

    for t in ["A", "B", "C", "D", "E"]:
        want = "near" if t == "E" else "identical"
        pos = [(base_of[f], f) for f in by_type.get(t, []) if base_of.get(f) in items and f in items]
        tp = 0
        for b, f in pos:
            p = get(b, f)
            ok = predicted(p, want)
            tp += ok
            details.append({"set": "positive", "type": t, "file_a": b, "file_b": f, "expected": want,
                            "predicted_geo": pgeo(p), "category": p.category if p else "",
                            "correct": ok, "reason": p.reason if p else "not flagged",
                            "variant": gt[f].get("variant", "")})
        flagged = {(p.a, p.b): p for p in involving.get(t, []) if predicted(p, want)}
        geo = want == "near"
        good = sum(1 for (a, b) in flagged if gt_rel(a, b, geo) == want)
        prec, rec = _ratio(good, len(flagged)), _ratio(tp, len(pos))
        target, check = TARGETS[t]
        rows.append({"type": t, "n_pairs": len(pos), "tp": tp, "fn": len(pos) - tp, "n_pred": len(flagged),
                     "fp": len(flagged) - good,
                     "precision": prec, "recall": rec, "f1": _f1(prec, rec), "target": target,
                     "met": ("yes" if check(prec or 0, rec or 0, _f1(prec, rec) or 0) else "no") if pos else "n/a",
                     "definition": (f"(base, {t}) pairs proposed as merge candidates; precision over merge candidates with a {t} file"
                                    if want == "identical" else
                                    "(base, E) pairs predicted near-identical; precision over near predictions with an E file")})
        for (a, b), p in flagged.items():
            if gt_rel(a, b, geo) != want:
                details.append({"set": "false_positive", "type": t, "file_a": a, "file_b": b, "expected": gt_rel(a, b, geo),
                                "predicted_geo": pgeo(p), "category": p.category, "correct": False, "reason": p.reason})

    # F - name layer alone
    f_files = [f for f in by_type.get("F", []) if f in items and base_of.get(f) in items]
    linked = lambda p: p is not None and p.name is not None and p.name.score >= th.name_similar  # noqa: E731
    tp = 0
    for f in f_files:
        p = get(base_of[f], f)
        ok = linked(p)
        tp += ok
        details.append({"set": "positive", "type": "F", "file_a": base_of[f], "file_b": f, "expected": "name link",
                        "predicted_geo": pgeo(p), "category": p.category if p else "", "correct": ok,
                        "reason": (p.name.detail if p and p.name else "no name candidate"),
                        "variant": gt[f].get("variant", "")})
    links = [p for p in involving.get("F", []) if linked(p)]
    same_group = lambda p: gt_rel(p.a, p.b) in ("identical", "near")  # noqa: E731
    good = sum(1 for p in links if same_group(p))
    prec, rec = _ratio(good, len(links)), _ratio(tp, len(f_files))
    f1 = _f1(prec, rec)
    rows.append({"type": "F", "n_pairs": len(f_files), "tp": tp, "fn": len(f_files) - tp, "n_pred": len(links),
                 "fp": len(links) - good,
                 "precision": prec, "recall": rec, "f1": f1, "target": TARGETS["F"][0],
                 "met": ("yes" if (f1 or 0) >= 0.85 else "no") if f_files else "n/a",
                 "definition": "name layer only: (base, F) pairs with name score >= threshold; precision over links with an F file (same GT group = correct)"})
    for p in links:
        if not same_group(p):
            details.append({"set": "false_positive", "type": "F", "file_a": p.a, "file_b": p.b,
                            "expected": gt_rel(p.a, p.b), "predicted_geo": pgeo(p), "category": p.category,
                            "correct": False, "reason": p.name.detail})
    # F through the full pipeline (geometry + names)
    tp_full = sum(1 for f in f_files if pgeo(get(base_of[f], f)) == "identical")
    rows.append({"type": "F (full pipeline)", "n_pairs": len(f_files), "tp": tp_full, "fn": len(f_files) - tp_full,
                 "fp": None, "precision": None, "recall": _ratio(tp_full, len(f_files)), "f1": None, "target": "info",
                 "met": "n/a", "definition": "(base, F) pairs predicted identical by L1/L3 (F files are copies/re-exports)"})

    # name layer over all links (any type)
    all_links = [p for p in res.pairs if linked(p)]
    same = sum(1 for p in all_links if same_group(p))
    rows.append({"type": "Name links, all types", "n_pairs": None, "tp": same, "fn": None, "fp": len(all_links) - same,
                 "precision": _ratio(same, len(all_links)), "recall": None, "f1": None, "target": "info", "met": "n/a",
                 "definition": "all pairs with name score >= threshold; precision = share within the same GT group"})

    # FP rate on truly different parts
    flagged = [p for p in res.pairs if (p.category == "identical" and p.merge_ok) or p.category == "near_identical"]
    fps = [p for p in flagged
           if (p.category == "identical" and gt_rel(p.a, p.b) == "different")
           or (p.category == "near_identical" and gt_rel(p.a, p.b, geometric=True) == "different")]
    for p in fps:
        details.append({"set": "false_positive", "type": "flagged", "file_a": p.a, "file_b": p.b, "expected": "different",
                        "predicted_geo": pgeo(p), "category": p.category, "correct": False, "reason": p.reason})
    fp_rate = _ratio(len(fps), len(flagged))
    rows.append({"type": "False positives / flagged pairs", "n_pairs": len(flagged), "tp": len(flagged) - len(fps),
                 "fn": None, "fp": len(fps), "precision": None, "recall": None, "f1": None, "target": "FP <= 2%",
                 "met": "yes" if fp_rate is not None and fp_rate <= 0.02 else "no",
                 "definition": f"FP rate = {fp_rate}: flagged = merge candidates + near-identical alerts; FP = different GT groups"})

    # hard negatives
    hn_out: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for h in hn:
        a, b, kind = h["file_a"], h["file_b"], h["kind"]
        if a not in items or b not in items:
            hn_out[kind]["missing"] += 1
            continue
        p = get(a, b)
        cat = p.category if p else "none"
        if kind == "HN_material":
            ok = cat in ("identical_attr_conflict",)
        elif kind == "HN_mirror":
            ok = p is not None and p.category == "mirror"
        else:
            ok = cat not in ("identical", "near_identical") and pgeo(p) not in ("identical", "near")
        hn_out[kind]["total"] += 1
        hn_out[kind]["correct"] += ok
        hn_out[kind][f"category={cat or 'none'}"] += 1
        details.append({"set": "hard_negative", "type": kind, "file_a": a, "file_b": b,
                        "expected": {"HN_material": "identical geometry, not merged (attribute conflict)",
                                     "HN_mirror": "mirror image, not merged"}.get(kind, "not a duplicate"),
                        "predicted_geo": pgeo(p), "category": cat, "correct": ok, "reason": p.reason if p else ""})
    for kind, d in sorted(hn_out.items()):
        rows.append({"type": f"Hard negatives: {kind}", "n_pairs": d["total"], "tp": d["correct"],
                     "fn": d["total"] - d["correct"], "fp": None, "precision": None,
                     "recall": _ratio(d["correct"], d["total"]), "f1": None, "target": "info", "met": "n/a",
                     "definition": "share handled correctly; " + ", ".join(f"{k}: {v}" for k, v in sorted(d.items())
                                                                         if k.startswith("category="))})
    summary = {
        "ground-truth files": len(gt), "files missing from scan": len(missing),
        "flagged pairs": len(flagged), "false positives (different parts)": len(fps), "FP rate": fp_rate,
        "name-similarity threshold": th.name_similar,
    }
    return {"per_type": rows, "summary": summary, "details": details}


def write_details(metrics: dict, path: str | Path) -> None:
    rows = metrics.get("details", [])
    if not rows:
        return
    keys = ["set", "type", "file_a", "file_b", "expected", "predicted_geo", "category", "correct", "variant", "reason"]
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
