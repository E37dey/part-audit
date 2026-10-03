"""Audit of connected systems: collect from every source -> one snapshot -> L1-L5 + quality + impact.

Nothing is written to any source system. The result is a JSON-ready dict used by the app and the
Hebrew Excel report; every proposed change is 'pending approval'.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import connectors
from .decisions import group_impact
from .explain import CATEGORY_HE, CATEGORY_HINT_HE, pair_reason_he
from .model import ErpItem, PartRecord, Snapshot, SourceInfo
from .names import is_generic_product_name, parse_name, pn_core, pn_key, pn_letters_compatible
from .quality import bom_checks, erp_checks, record_checks
from .scan import FileRecord, read_step_record
from .scoring import Item, Thresholds, build_pairs, duplicate_groups, finish_key, material_key
from .stdparts import parse_spec

Progress = Callable[[str, float, str], None]   # (stage, fraction 0..1, detail)


@dataclass
class ProjectSettings:
    thresholds: Thresholds = field(default_factory=Thresholds)
    mass_tolerance: float = 0.10
    workers: int = max(1, (os.cpu_count() or 2) - 1)
    timeout_s: float = 60.0
    use_geometry: bool = True
    shape_check: bool = True
    cost_per_pn_year: float | None = None     # optional user assumption, never defaulted
    currency: str = "ILS"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["thresholds"] = self.thresholds.as_dict()
        return d

    @staticmethod
    def from_dict(d: dict | None) -> "ProjectSettings":
        d = dict(d or {})
        th = Thresholds(**{k: v for k, v in (d.pop("thresholds", None) or {}).items() if k in Thresholds().__dict__})
        known = {k: v for k, v in d.items() if k in ProjectSettings.__dataclass_fields__}
        return ProjectSettings(thresholds=th, **known)


def _noop(*_a, **_k):
    return None


# ================================================================================= collect


def collect(sources: list[dict], cache_dir: str | Path, progress: Progress | None = None,
            should_stop: Callable[[], bool] | None = None) -> Snapshot:
    """sources: [{'id','kind','name','config','enabled','simulated'}] -> Snapshot (read-only calls only)."""
    progress = progress or _noop
    snap = Snapshot(created=dt.datetime.now().isoformat(timespec="seconds"))
    active = [s for s in sources if s.get("enabled", True)]
    for i, s in enumerate(active):
        C = connectors.get(s["kind"])
        base = i / max(len(active), 1)

        def prog(text, done, total, _s=s, _base=base):
            frac = _base + (done / total if total else 0) / max(len(active), 1)
            progress("collect", min(frac, 1.0), f"{_s['name']}: {text}" + (f" ({done}/{total})" if total else ""))

        con = C(s["id"], s["name"], s.get("config") or {}, cache_dir, progress=prog, should_stop=should_stop)
        info = SourceInfo(id=s["id"], kind=s["kind"], name=s["name"], role=C.role, simulated=bool(s.get("simulated")),
                          url=str((s.get("config") or {}).get("base_url") or (s.get("config") or {}).get("server_url")
                                  or (s.get("config") or {}).get("service_root") or (s.get("config") or {}).get("host")
                                  or (s.get("config") or {}).get("path") or ""))
        t0 = time.perf_counter()
        try:
            col = con.collect()
        except Exception as exc:  # one failing source must not stop the others
            info.errors.append(f"{type(exc).__name__}: {exc}")
            snap.sources.append(info)
            continue
        info.stats = dict(col.stats, seconds=round(time.perf_counter() - t0, 2), records=len(col.records),
                          erp_items=len(col.erp_items))
        info.errors = list(col.errors)
        snap.records += col.records
        snap.erp_items += col.erp_items
        snap.erp_bom += col.bom
        snap.skipped += col.skipped
        snap.sources.append(info)
    progress("collect", 1.0, "האיסוף הסתיים")
    return snap


# ================================================================================= audit


def _stub_record(r: PartRecord) -> FileRecord:
    p = Path(r.native_file or r.uid)
    return FileRecord(file_id=r.uid, path="", folder=r.folder, filename=p.name, stem=p.stem, ext=p.suffix.lower(),
                      size=0, mtime=0.0)


def build_items(snap: Snapshot, progress: Progress) -> tuple[dict[str, Item], dict[str, PartRecord], dict]:
    erp_by_key: dict[str, list[ErpItem]] = defaultdict(list)
    erp_by_core: dict[str, list[ErpItem]] = defaultdict(list)
    for e in snap.erp_items:
        erp_by_key[pn_key(e.pn)].append(e)
        c = pn_core(e.pn)
        if len(c) >= 4:
            erp_by_core[c].append(e)
    items: dict[str, Item] = {}
    recs: dict[str, PartRecord] = {}
    links: dict[str, ErpItem] = {}
    parts = [r for r in snap.records if r.kind == "part"]
    for i, r in enumerate(parts):
        if i % 25 == 0:
            progress("read", i / max(len(parts), 1), f"קורא קבצי STEP ({i}/{len(parts)})")
        fr = None
        if r.step_path and Path(r.step_path).exists():
            fr = read_step_record(r.step_path, str(Path(r.step_path).parent))
            fr.file_id = r.uid
            if fr.error:
                fr = None
        it = Item(file_id=r.uid, rec=fr or _stub_record(r))
        main = parse_name(f"{r.pn} {r.name}".strip(), known_pns=[r.pn] if r.pn else None)
        it.sources.append(main)
        it.source_labels.append("pdm")
        if r.description and r.description.strip() != r.name.strip():
            it.sources.append(parse_name(r.description, known_pns=[r.pn] if r.pn else None))
            it.source_labels.append("pdm_desc")
        if r.native_file:
            it.sources.append(parse_name(Path(r.native_file).stem))
            it.source_labels.append("file")
        if fr is not None:
            for pid, pname, _ in fr.products[:1]:
                txt = " ".join(t for t in (pid, pname) if t and not is_generic_product_name(t))
                if txt and pn_key(txt) != pn_key(Path(r.native_file or "").stem):
                    it.sources.append(parse_name(txt))
                    it.source_labels.append("step")
        it.pn = r.pn
        it.pn_key = pn_key(r.pn) if r.pn else ""
        e = None
        if r.pn:
            cands = erp_by_key.get(pn_key(r.pn), [])
            if len(cands) >= 1:
                e = cands[0]
                it.erp_link = f"מק\"ט {r.pn} = ERP {e.pn}"
            else:
                core = pn_core(r.pn)
                cands = erp_by_core.get(core, []) if len(core) >= 4 else []
                if len(cands) == 1 and pn_letters_compatible(r.pn, cands[0].pn):
                    e = cands[0]
                    it.erp_link = f"ספרות המק\"ט {r.pn} = ERP {e.pn}"
        if e is not None:
            links[r.uid] = e
            it.erp = {"part_number": e.pn, "description": e.description, "material": e.material, "unit": e.uom,
                      "supplier": e.supplier, "erp_row": e.pn}
            it.sources.append(parse_name(e.description, known_pns=[e.pn]))
            it.source_labels.append("erp")
        it.material = r.material
        it.spec = parse_spec(r.name, r.description, r.name_en, Path(r.native_file or "").stem, r.material,
                             e.description if e else "")
        items[r.uid] = it
        recs[r.uid] = r
    return items, recs, links


def bom_maps(snap: Snapshot) -> tuple[dict, dict, dict]:
    """children_of[uid] -> [(child uid, qty)], parents_of[uid] -> [(parent uid, qty)], by_uid."""
    by_uid = {r.uid: r for r in snap.records}
    by_src_pn: dict[tuple[str, str], str] = {}
    for r in snap.records:
        if r.pn:
            by_src_pn.setdefault((r.source_id, pn_key(r.pn)), r.uid)
    children_of: dict[str, list] = defaultdict(list)
    parents_of: dict[str, list] = defaultdict(list)
    for a in snap.records:
        for line in a.children:
            ch = line.get("child")
            if line.get("by") == "pn":
                ch = by_src_pn.get((a.source_id, pn_key(str(ch))))
            if ch and ch in by_uid:
                children_of[a.uid].append((ch, float(line.get("qty") or 1)))
                parents_of[ch].append((a.uid, float(line.get("qty") or 1)))
    return children_of, parents_of, by_uid


def _top_products(uid: str, parents_of: dict, by_uid: dict, seen=None) -> set[str]:
    seen = seen or set()
    if uid in seen:
        return set()
    seen.add(uid)
    ps = parents_of.get(uid, [])
    if not ps:
        return {uid}
    out = set()
    for p, _ in ps:
        out |= _top_products(p, parents_of, by_uid, seen)
    return out


def _gid(prefix: str, members) -> str:
    return prefix + hashlib.sha1("|".join(sorted(members)).encode()).hexdigest()[:8]


def audit_snapshot(snap: Snapshot, settings: ProjectSettings, cache_dir: str | Path,
                   progress: Progress | None = None) -> dict:
    progress = progress or _noop
    t0 = time.perf_counter()
    timings: dict = {}
    th = settings.thresholds
    items, recs, links = build_items(snap, progress)
    timings["read_s"] = round(time.perf_counter() - t0, 2)
    fps: dict[str, dict] = {}
    shape_fn = None
    geo_errors: dict = {}
    if settings.use_geometry:
        from .geometry import fingerprint_files
        t1 = time.perf_counter()
        todo = [(it.file_id, it.rec.path, it.rec.sha256) for it in items.values() if it.rec.path]

        def gp(done, n):
            progress("geometry", done / max(n, 1), f"מחשב טביעות אצבע גיאומטריות ({done}/{n})")
        fps, geo_errors, gstats, fp_cache = fingerprint_files(todo, workers=settings.workers,
                                                              timeout_s=settings.timeout_s,
                                                              cache_dir=str(Path(cache_dir) / "fingerprints"),
                                                              progress=gp)
        for fid, fp in fps.items():
            items[fid].fp = fp
        timings["geometry_s"] = round(time.perf_counter() - t1, 2)
        timings.update({f"geometry_{k}": v for k, v in gstats.items()})
        if settings.shape_check:
            from .shape import ShapeChecker
            shape_fn = ShapeChecker(fp_cache, th, workers=settings.workers,
                                    cache_dir=str(Path(cache_dir) / "fingerprints"))
    progress("compare", 0.1, "משווה חלקים (שמות, מק\"טים, גיאומטריה)")
    t2 = time.perf_counter()
    pairs = build_pairs(items, th, use_geometry=settings.use_geometry, shape_check=shape_fn)
    groups = duplicate_groups(pairs)
    timings["compare_s"] = round(time.perf_counter() - t2, 2)
    if shape_fn is not None:
        timings["shape_checks"] = shape_fn.n_checks
        timings["shape_s"] = round(shape_fn.seconds, 2)
    progress("impact", 0.5, "מחשב השפעה: עצי מוצר, מלאי ושימושים")
    children_of, parents_of, by_uid = bom_maps(snap)
    parts = [r for r in snap.records if r.kind == "part"]
    assemblies = [r for r in snap.records if r.kind == "assembly"]
    erp_by_key = {pn_key(e.pn): e for e in snap.erp_items}
    erp_parents: dict[str, list] = defaultdict(list)
    for b in snap.erp_bom:
        erp_parents[pn_key(b.child)].append((b.parent, b.qty))
    src_name = {s.id: s.name for s in snap.sources}
    src_kind = {s.id: s.kind for s in snap.sources}

    # ------------------------------------------------------------------ pairs -> JSON
    pair_rows = []
    for p in pairs:
        a, b = items[p.a], items[p.b]
        g = p.geo
        shp = (g.shape or {}) if g else {}
        pair_rows.append({
            "id": _gid("P", [p.a, p.b]), "a": p.a, "b": p.b, "category": p.category,
            "category_he": CATEGORY_HE.get(p.category, p.category), "hint_he": CATEGORY_HINT_HE.get(p.category, ""),
            "geo_relation": p.geo_relation, "confidence": round(p.confidence, 3), "reason": p.reason,
            "reason_he": pair_reason_he(p, a, b), "l1": p.l1, "same_pn": p.same_pn, "merge_ok": p.merge_ok,
            "spec_relation": p.spec_relation, "spec_note": p.spec_note,
            "name_score": None if p.name is None else p.name.score,
            "cross_source": recs[p.a].source_id != recs[p.b].source_id,
            "metrics": None if g is None else {
                "max_rel": _fin(g.max_rel), "d_volume": _fin(g.d_volume), "d_area": _fin(g.d_area),
                "d_inertia": _fin(g.d_inertia), "d_bbox": _fin(g.d_bbox), "topo_same": g.topo_same, "scale": g.scale,
                "unit_note": g.unit_note, "chirality": g.chirality,
                "p95_mm": (shp["p95_rel"] * shp["diag"]) if shp.get("p95_rel") is not None and shp.get("diag") else None,
                "excess50": shp.get("excess50"), "mirror": shp.get("mirror"),
                "t_proper": shp.get("proper_t"), "t_improper": shp.get("improper_t")},
        })
    pair_by_key = {(r["a"], r["b"]): r for r in pair_rows}

    # ------------------------------------------------------------------ groups + master + impact
    group_rows, mapping = [], []
    group_of: dict[str, str] = {}
    for gm in groups:
        gid = _gid("G", gm)
        members = [recs[u] for u in gm]
        cats = {pair_by_key[(x, y)]["category"] for x in gm for y in gm if (x, y) in pair_by_key}

        def master_key(r: PartRecord):
            e = links.get(r.uid)
            return (0 if e else 1, 0 if r.state_class == "released" else (1 if r.state_class in ("review", "in_work") else 2),
                    -len(parents_of.get(r.uid, [])) - len(erp_parents.get(pn_key(r.pn), [])) if r.pn else 0,
                    -(e.stock_total if e else 0), 0 if r.step_path else 1, r.created or "9999", r.pn or "~")
        master = sorted(members, key=master_key)[0]
        why = []
        if links.get(master.uid):
            why.append("קיים ב-ERP")
        if master.state_class == "released":
            why.append("משוחרר")
        n_used = len(parents_of.get(master.uid, [])) + (len(erp_parents.get(pn_key(master.pn), [])) if master.pn else 0)
        if n_used:
            why.append(f"בשימוש ב-{n_used} עצי מוצר")
        if links.get(master.uid) and links[master.uid].stock_total:
            why.append(f"מלאי {links[master.uid].stock_total:g}")
        pns = sorted({r.pn for r in members if r.pn})
        erp_rows, seen_pn = [], set()
        for r in members:
            e = links.get(r.uid)
            if e and e.pn not in seen_pn:
                seen_pn.add(e.pn)
                val = None if e.unit_cost is None else round(e.stock_total * e.unit_cost, 2)
                erp_rows.append({"pn": e.pn, "description": e.description, "stock": e.stock_total, "unit_cost": e.unit_cost,
                                 "value": val, "currency": e.currency or settings.currency, "status": e.status,
                                 "active": e.active, "supplier": e.supplier,
                                 "is_master": bool(master.pn) and pn_key(e.pn) == pn_key(master.pn)})
        used = []
        for r in members:
            for par, q in parents_of.get(r.uid, []):
                pr = by_uid[par]
                used.append({"uid": pr.uid, "pn": pr.pn, "name": pr.name, "source": src_name.get(pr.source_id, pr.source_id),
                             "qty": q, "via": r.pn, "state": pr.state})
            for ppn, q in erp_parents.get(pn_key(r.pn), []) if r.pn else []:
                used.append({"uid": "", "pn": ppn, "name": (erp_by_key.get(pn_key(ppn)).description
                                                            if erp_by_key.get(pn_key(ppn)) else ""),
                             "source": "ERP", "qty": q, "via": r.pn, "state": ""})
        products = set()
        for r in members:
            for t in _top_products(r.uid, parents_of, by_uid):
                if t != r.uid:
                    products.add(t)
        category = "standard" if "standard_part" in cats else "geometry"
        best = max((pair_by_key[(x, y)] for x in gm for y in gm if (x, y) in pair_by_key
                    and pair_by_key[(x, y)]["category"] in ("identical", "standard_part")),
                   key=lambda r: r["confidence"], default=None)
        impact = group_impact({"erp": erp_rows, "pns": pns, "where_used": used}, master.pn or "")
        main_cur = impact["currency"]
        row = {"id": gid, "members": gm, "category": category, "pns": pns,
               "sources": sorted({src_name.get(r.source_id, r.source_id) for r in members}),
               "cross_source": len({r.source_id for r in members}) > 1, "master_uid": master.uid, "master_pn": master.pn,
               "master_reason_he": ", ".join(why) if why else "נבחר לפי מצב, שימושים ומלאי",
               "confidence": best["confidence"] if best else None, "reason_he": best["reason_he"] if best else "",
               "spec": (items[gm[0]].spec.label if items[gm[0]].spec else ""), "where_used": used,
               "products": sorted(by_uid[t].pn or by_uid[t].name for t in products),
               "erp": erp_rows, "stock_total": sum(x["stock"] for x in erp_rows),
               "stock_value": round(sum(x["value"] or 0 for x in erp_rows if not main_cur or x["currency"] == main_cur), 2),
               "currency": main_cur or settings.currency,
               "redundant_pns": impact["redundant_pns"], "redundant_stock_value": impact["redundant_stock_value"],
               "bom_lines_to_update": impact["bom_lines_to_update"], "name": master.name}
        group_rows.append(row)
        for u in gm:
            group_of[u] = gid
        for r in members:
            if not r.pn or pn_key(r.pn) == pn_key(master.pn or ""):
                continue
            if any(m["old_pn"] == r.pn and m["group_id"] == gid for m in mapping):
                continue
            pr = pair_by_key.get(tuple(sorted((r.uid, master.uid))))
            # the id includes the target: an approval of "X -> A" never applies to "X -> B" after a rescan
            mapping.append({"id": _gid("M", [gid, r.pn, "target:" + (master.pn or "")]), "group_id": gid,
                            "old_pn": r.pn, "old_uid": r.uid,
                            "old_name": r.name, "old_source": src_name.get(r.source_id, r.source_id),
                            "new_pn": master.pn, "new_uid": master.uid, "new_name": master.name,
                            "reason_he": (pr["reason_he"] if pr else row["reason_he"]),
                            "why_target_he": row["master_reason_he"],
                            "confidence": pr["confidence"] if pr else row["confidence"],
                            "where_used": sum(1 for x in used if x["via"] == r.pn),
                            "erp_stock": links[r.uid].stock_total if links.get(r.uid) else None,
                            "status": "ממתין לאישור"})
    group_rows.sort(key=lambda g: (-(g["redundant_stock_value"] or 0), -len(g["members"])))

    # ------------------------------------------------------------------ quality + ERP checks
    progress("quality", 0.7, "בדיקות איכות נתונים")
    quality = record_checks(parts + assemblies, fps, settings)
    quality += bom_checks(snap.records, children_of, by_uid)
    for uid, (reason, detail) in geo_errors.items():
        quality.append({"type": "geometry_error", "type_he": "קובץ STEP לא נקרא", "severity": "medium",
                        "severity_he": "בינונית", "uids": [uid], "message": f"{reason}: {detail}", "details": {}})
    for p in pair_rows:
        m = p.get("metrics") or {}
        if p["geo_relation"] == "unit_scaled" and m.get("scale") and m["scale"] != 1:
            small = p["a"] if m["scale"] > 1 else p["b"]
            quality.append({"type": "unit_error", "type_he": "קובץ STEP ביחידות שגויות", "severity": "medium",
                            "severity_he": "בינונית", "uids": [small, p["b"] if small == p["a"] else p["a"]],
                            "message": f"הקובץ קטן פי {max(m['scale'], 1 / m['scale']):.4g} מהחלק הזהה לו ({m.get('unit_note')})",
                            "details": {"scale": m["scale"]}})
    erp_issues = erp_checks(parts, assemblies, snap.erp_items, snap.erp_bom, items, children_of, by_uid, parents_of)
    for q in quality + erp_issues:
        q["id"] = _gid("Q", [q["type"], *q["uids"], q["message"]])

    # ------------------------------------------------------------------ name / PN findings
    names = []
    by_pn: dict[str, list[PartRecord]] = defaultdict(list)
    for r in parts:
        if r.pn:
            by_pn[pn_key(r.pn)].append(r)
    from .names import compare_names
    for k, rs in by_pn.items():
        if len({r.source_id for r in rs}) < 1 or len(rs) < 2:
            continue
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                ra, rb = rs[i], rs[j]
                na, nb = parse_name(ra.name, [ra.pn]), parse_name(rb.name, [rb.pn])
                if not na.words or not nb.words:
                    continue  # a name that is only the part number / file name says nothing about the part
                m = compare_names(na, nb)
                if m.desc_sim < 0.6:
                    names.append({"id": _gid("N", [ra.uid, rb.uid]), "type": "same_pn_different_name",
                                  "type_he": "אותו מק\"ט – שמות שונים", "uids": [ra.uid, rb.uid], "pn": ra.pn,
                                  "names": [ra.name, rb.name], "similarity": m.desc_sim})
    for p in pair_rows:
        if p["category"] == "name_similar":
            names.append({"id": p["id"], "type": "similar_names", "type_he": "שמות דומים – מק\"טים שונים",
                          "uids": [p["a"], p["b"]], "pn": "", "names": [recs[p["a"]].name, recs[p["b"]].name],
                          "similarity": p["name_score"], "geo_relation": p["geo_relation"]})
        elif p["category"] in ("conflict", "conflict_unverified"):
            names.append({"id": p["id"], "type": "same_pn_different_geometry", "type_he": "אותו מק\"ט – גיאומטריה שונה",
                          "uids": [p["a"], p["b"]], "pn": recs[p["a"]].pn,
                          "names": [recs[p["a"]].name, recs[p["b"]].name], "similarity": p["name_score"],
                          "geo_relation": p["geo_relation"]})
    for q in quality:
        if q["type"] in ("filename_pn_mismatch", "pn_format", "missing_pn"):
            names.append({"id": q["id"], "type": q["type"], "type_he": q["type_he"], "uids": q["uids"],
                          "pn": recs[q["uids"][0]].pn if q["uids"] and q["uids"][0] in recs else "",
                          "names": [recs[q["uids"][0]].name] if q["uids"] and q["uids"][0] in recs else [],
                          "message": q["message"]})

    # ------------------------------------------------------------------ parts table
    near_count = defaultdict(int)
    for p in pair_rows:
        if p["category"] == "near_identical":
            near_count[p["a"]] += 1
            near_count[p["b"]] += 1
    issue_count = defaultdict(int)
    for q in quality + erp_issues:
        for u in q["uids"][:1]:
            issue_count[u] += 1
    part_rows = []
    for r in snap.records:
        it = items.get(r.uid)
        fp = fps.get(r.uid) or {}
        e = links.get(r.uid) or (erp_by_key.get(pn_key(r.pn)) if r.pn else None)
        part_rows.append({
            "uid": r.uid, "source_id": r.source_id, "source": src_name.get(r.source_id, r.source_id),
            "source_kind": src_kind.get(r.source_id, r.source_kind), "kind": r.kind, "pn": r.pn, "name": r.name,
            "description": r.description, "revision": r.revision, "version": r.version, "state": r.state,
            "state_class": r.state_class, "material": r.material, "finish": r.finish, "mass_kg": r.mass_kg,
            "make_buy": r.make_buy, "author": r.author, "created": r.created, "modified": r.modified,
            "native_file": r.native_file, "folder": r.folder, "cad_app": r.cad_app, "has_step": bool(r.step_path),
            "step_name": r.step_name, "step_note": r.step_note,
            "volume_mm3": fp.get("volume") if fp.get("closed") else None, "n_faces": fp.get("n_faces"),
            "bbox": fp.get("bbox_pca"), "unit": (it.rec.length_unit if it else ""),
            "erp": None if e is None else {"pn": e.pn, "description": e.description, "stock": e.stock_total,
                                           "unit_cost": e.unit_cost, "currency": e.currency, "status": e.status,
                                           "active": e.active, "supplier": e.supplier, "family": e.family,
                                           "uom": e.uom},
            "spec": it.spec.label if it and it.spec else "", "group_id": group_of.get(r.uid),
            # canonical keys, so the UI compares 'פלדה 12.9' with 'STEEL 12.9' and DIN 912 with ISO 4762 correctly
            "material_key": material_key(r.material) if r.material else "", "finish_key": finish_key(r.finish),
            "spec_key": "|".join((it.spec.kind, it.spec.size, it.spec.length, it.spec.grade, it.spec.seal))
            if it and it.spec else "",
            "near_count": near_count.get(r.uid, 0), "issues": issue_count.get(r.uid, 0),
            "used_in": len(parents_of.get(r.uid, [])), "children": len(children_of.get(r.uid, [])),
        })

    # ------------------------------------------------------------------ summary
    # money is added up in one currency only (the most common one); groups priced in another are counted apart
    cur_count = defaultdict(int)
    for g in group_rows:
        cur_count[g["currency"]] += 1
    main_currency = max(cur_count, key=cur_count.get) if cur_count else settings.currency
    red_value = sum(g["redundant_stock_value"] for g in group_rows if g["currency"] == main_currency)
    sev = defaultdict(int)
    for q in quality + erp_issues:
        if q["severity"] != "info":
            sev[q["severity"]] += 1
    cat_count = defaultdict(int)
    for p in pair_rows:
        cat_count[p["category"]] += 1
    summary = {
        "parts": len(parts), "assemblies": len(assemblies), "with_step": sum(1 for r in parts if r.step_path),
        "erp_items": len(snap.erp_items), "erp_linked": len(links), "sources": len(snap.sources),
        "groups": len(group_rows), "groups_cross_source": sum(1 for g in group_rows if g["cross_source"]),
        "groups_standard": sum(1 for g in group_rows if g["category"] == "standard"),
        "parts_in_groups": sum(len(g["members"]) for g in group_rows),
        "redundant_pns": sum(g["redundant_pns"] for g in group_rows),
        "redundant_stock_value": round(red_value, 2), "currency": main_currency,
        "groups_other_currency": sum(1 for g in group_rows if g["currency"] != main_currency),
        "bom_lines_to_update": sum(g["bom_lines_to_update"] for g in group_rows),
        "near_pairs": cat_count.get("near_identical", 0), "mirror_pairs": cat_count.get("mirror", 0),
        "spec_conflicts": cat_count.get("identical_attr_conflict", 0),
        "pn_conflicts": cat_count.get("conflict", 0) + cat_count.get("conflict_unverified", 0),
        "name_findings": len(names), "quality_high": sev["high"], "quality_medium": sev["medium"],
        "quality_low": sev["low"], "quality_issues": len([q for q in quality if q["severity"] != "info"]),
        "erp_issues": len(erp_issues), "skipped_files": len(snap.skipped),
        "per_source": {s.name: {"records": s.stats.get("records", 0), "erp_items": s.stats.get("erp_items", 0),
                                "errors": len(s.errors)} for s in snap.sources},
    }
    if settings.cost_per_pn_year:
        summary["assumed_saving_per_year"] = round(summary["redundant_pns"] * settings.cost_per_pn_year, 2)
    timings["total_s"] = round(time.perf_counter() - t0, 2)
    progress("done", 1.0, "הסריקה הסתיימה")
    return {
        "created": dt.datetime.now().isoformat(timespec="seconds"), "snapshot_created": snap.created,
        "settings": settings.to_dict(), "timings": timings, "summary": summary,
        "sources": [asdict(s) for s in snap.sources], "parts": part_rows, "groups": group_rows, "pairs": pair_rows,
        "mapping": mapping, "quality": quality, "erp_issues": erp_issues, "names": names, "skipped": snap.skipped,
        "bom": {u: [{"child": c, "qty": q} for c, q in v] for u, v in children_of.items()},
        "erp_bom": [asdict(b) for b in snap.erp_bom],
    }


def _fin(x):
    return None if x is None or x == float("inf") else x
