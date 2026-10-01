"""Orchestration: scan -> ERP link -> L1/L2/L3 -> L5 scoring -> report tables.

Nothing is ever written back to an ERP; the outputs are an Excel report and
(optionally) JSON/CSV tables, and every proposed mapping is 'pending approval'.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .names import (NameIndex, NameParts, best_match, blocking_pairs, is_generic_product_name, parse_name,
                    pn_core, pn_key)
from .scan import SkipRecord, load_erp, scan_folder
from .scoring import Item, Pair, Thresholds, build_pairs, duplicate_groups, propose_mapping


@dataclass
class AuditConfig:
    root: str
    erp_csv: str | None = None
    out_xlsx: str = "out/part_audit_report.xlsx"
    workers: int = 1
    use_geometry: bool = True
    shape_check: bool = True
    timeout_s: float = 60.0
    cache_dir: str | None = None
    ground_truth: str | None = None
    llm_endpoint: str | None = None
    llm_model: str = ""
    llm_allow_remote: bool = False
    thresholds: Thresholds = field(default_factory=Thresholds)
    verbose: bool = True


@dataclass
class AuditResult:
    config: AuditConfig
    items: dict[str, Item]
    skipped: list[SkipRecord]
    pairs: list[Pair]
    groups: list[list[str]]
    mapping: list[dict]
    erp_rows: list[dict]
    erp_duplicates: list[dict]
    timings: dict
    metrics: dict | None = None
    llm_notes: dict = field(default_factory=dict)


def _log(cfg: AuditConfig, msg: str) -> None:
    if cfg.verbose:
        print(msg, flush=True)


def build_items(records, erp_rows: list[dict] | None) -> dict[str, Item]:
    """Create an Item per STEP file with its name sources and ERP link."""
    by_key: dict[str, list[dict]] = {}
    by_core: dict[str, list[dict]] = {}
    for row in erp_rows or []:
        by_key.setdefault(pn_key(row["part_number"]), []).append(row)
        c = pn_core(row["part_number"])
        if len(c) >= 4:
            by_core.setdefault(c, []).append(row)
    items: dict[str, Item] = {}
    for rec in records:
        if rec.error:
            continue
        it = Item(file_id=rec.file_id, rec=rec)
        file_np = parse_name(rec.stem)
        it.sources.append(file_np)
        it.source_labels.append("file")
        step_np = None
        for pid, pname, _pdesc in rec.products[:1]:
            txt = " ".join(t for t in (pid, pname) if t and not is_generic_product_name(t))
            if txt and pn_key(txt) != pn_key(rec.stem):
                step_np = parse_name(txt)
        if step_np and (step_np.words or step_np.pns):
            it.sources.append(step_np)
            it.source_labels.append("step")
        # ERP link: exact normalized PN first, then unique digit core
        cands = list(file_np.pns) + (list(step_np.pns) if step_np else [])
        for pn in cands:
            rows = by_key.get(pn_key(pn), [])
            if len(rows) == 1:
                it.erp, it.erp_link = rows[0], f"part number '{pn}' = ERP '{rows[0]['part_number']}'"
                break
        if it.erp is None:
            for pn in cands:
                rows = by_core.get(pn_core(pn), [])
                if len(rows) == 1:
                    it.erp, it.erp_link = rows[0], f"part number digits of '{pn}' = ERP '{rows[0]['part_number']}'"
                    break
        if it.erp:
            it.pn = it.erp["part_number"]
            erp_np = parse_name(f"{it.erp.get('description', '')}", known_pns=[it.erp["part_number"]])
            it.sources.append(erp_np)
            it.source_labels.append("erp")
        elif cands:
            it.pn = cands[0]
        it.pn_key = pn_key(it.pn) if it.pn else ""
        items[rec.file_id] = it
    return items


def erp_duplicate_candidates(erp_rows: list[dict], th: Thresholds) -> list[dict]:
    """ERP rows whose descriptions match strongly although their PNs differ."""
    parsed = {str(r["erp_row"]): [parse_name(str(r.get("description", "")), known_pns=[r["part_number"]])]
              for r in erp_rows}
    by_row = {str(r["erp_row"]): r for r in erp_rows}
    index = NameIndex(parsed, {str(r["erp_row"]): pn_key(r["part_number"]) for r in erp_rows}, k0=th.name_k0,
                      partial_factor=th.name_partial_factor)
    out = []
    for a, b in sorted(blocking_pairs(parsed)):
        m = best_match(parsed[a], parsed[b], index)
        ra, rb = by_row[a], by_row[b]
        if m and m.score >= th.name_similar and pn_key(ra["part_number"]) != pn_key(rb["part_number"]):
            out.append({"erp_row_a": ra["erp_row"], "pn_a": ra["part_number"], "desc_a": ra.get("description", ""),
                        "erp_row_b": rb["erp_row"], "pn_b": rb["part_number"], "desc_b": rb.get("description", ""),
                        "name_score": m.score, "detail": m.detail})
    return out


def run_audit(cfg: AuditConfig) -> AuditResult:
    t0 = time.perf_counter()
    timings: dict = {}
    _log(cfg, f"[scan] {cfg.root}")
    records, skipped = scan_folder(cfg.root, workers=cfg.workers)
    timings["scan_s"] = time.perf_counter() - t0
    _log(cfg, f"[scan] {len(records)} STEP files, {len(skipped)} skipped ({timings['scan_s']:.1f}s)")

    erp_rows: list[dict] = []
    if cfg.erp_csv:
        df = load_erp(cfg.erp_csv)
        erp_rows = df.to_dict("records")
        _log(cfg, f"[erp] {len(erp_rows)} rows from {cfg.erp_csv}")
    items = build_items(records, erp_rows)

    shape_fn = None
    if cfg.use_geometry:
        from .geometry import fingerprint_files
        t1 = time.perf_counter()
        fps, geo_errors, gstats, fp_cache = fingerprint_files(
            [(it.file_id, it.rec.path, it.rec.sha256) for it in items.values()],
            workers=cfg.workers, timeout_s=cfg.timeout_s, cache_dir=cfg.cache_dir,
            progress=(lambda d, n: _log(cfg, f"[geometry] {d}/{n}")) if cfg.verbose else None)
        for fid, fp in fps.items():
            items[fid].fp = fp
        for fid, (reason, detail) in geo_errors.items():
            skipped.append(SkipRecord(fid, reason, detail, items[fid].rec.size, stage="geometry"))
        timings["geometry_s"] = time.perf_counter() - t1
        timings.update({f"geometry_{k}": v for k, v in gstats.items()})
        _log(cfg, f"[geometry] ok={len(fps) - len(geo_errors)} errors={len(geo_errors)} "
                  f"({timings['geometry_s']:.1f}s)")
        if cfg.shape_check:
            from .shape import ShapeChecker
            shape_fn = ShapeChecker(fp_cache, cfg.thresholds)

    t2 = time.perf_counter()
    pairs = build_pairs(items, cfg.thresholds, use_geometry=cfg.use_geometry, shape_check=shape_fn)
    groups = duplicate_groups(pairs)
    mapping = propose_mapping(groups, items, pairs)
    erp_dups = erp_duplicate_candidates(erp_rows, cfg.thresholds) if erp_rows else []
    timings["scoring_s"] = time.perf_counter() - t2
    if shape_fn is not None:
        timings["shape_checks"] = shape_fn.n_checks
        timings["shape_s"] = shape_fn.seconds
    timings["total_s"] = time.perf_counter() - t0
    res = AuditResult(cfg, items, skipped, pairs, groups, mapping, erp_rows, erp_dups, timings)

    if cfg.llm_endpoint:
        from .llm import explain_mappings
        res.llm_notes = explain_mappings(res, cfg.llm_endpoint, cfg.llm_model, allow_remote=cfg.llm_allow_remote)

    if cfg.ground_truth:
        from .metrics import evaluate
        res.metrics = evaluate(res, cfg.ground_truth)
    _log(cfg, f"[score] {len(pairs)} flagged pairs, {len(groups)} duplicate groups, {len(mapping)} mapping rows "
              f"({timings['scoring_s']:.1f}s)")
    return res


def save_json(res: AuditResult, path: str | Path) -> None:
    """Machine-readable dump of pairs/groups/mapping (for tests and diffing)."""
    data = {
        "pairs": [{"a": p.a, "b": p.b, "category": p.category, "geo_relation": p.geo_relation, "l1": p.l1,
                   "confidence": p.confidence, "name_score": p.name.score if p.name else None,
                   "max_rel": (None if p.geo is None or p.geo.max_rel == float("inf") else p.geo.max_rel),
                   "reason": p.reason} for p in res.pairs],
        "groups": res.groups, "mapping": res.mapping, "timings": res.timings, "metrics": res.metrics,
        "thresholds": res.config.thresholds.as_dict(),
    }
    Path(path).write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
