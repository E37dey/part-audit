"""Pre-release check: does a new part already exist? (read-only)

Before a new part number is opened, an engineer gives the part's STEP file and, if known, the part number,
name and material planned for it. The file is compared with every part of the latest scan by the same engine
as the audit, so the answer agrees with what the next scan would report:

* the same file, or the same model exported again (hashes)
* the same geometry, also after a unit mistake in the export (properties, then aligned surfaces)
* a near-identical shape (a small design change) or a mirror image (the left/right version)
* the same standard-part designation (screw, bearing, key ...)
* the planned part number already used by another shape, or by an ERP item; similar names

Nothing is sent to any system: the file, its fingerprint and the answer stay in the app's workspace.
"""
from __future__ import annotations

import bisect
import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .explain import CATEGORY_HE, _spec_he, pair_reason_he, pct
from .model import Snapshot
from .names import NameIndex, best_match, block_keys, block_too_big, is_generic_product_name, parse_name, pn_key
from .scan import FileRecord, read_step_record
from .scoring import (UNIT_FACTORS, Item, Pair, Thresholds, classify, compare_geometry, enforce_material_consistency,
                      geometry_usable, needs_shape_check)
from .stdparts import compare_specs, parse_spec

Progress = Callable[[str, float, str], None]
NEW_PREFIX = "new:"
# the order in which matches are listed: what decides the answer first
ORDER = ["identical", "standard_part", "identical_attr_conflict", "conflict", "conflict_unverified", "near_identical",
         "mirror", "name_similar"]
MAX_ROWS = 60


class CheckError(ValueError):
    """The file cannot be checked (not a STEP file ...); the message is shown to the user."""


def _noop(*_a, **_k):
    return None


@dataclass
class RunIndex:
    """What a check compares against, built once per scan."""
    run_id: str
    created: str
    items: dict[str, Item]
    blocks: dict[str, set[str]]          # name blocking key -> existing items
    by_sha: dict[str, list[str]]
    by_norm: dict[str, list[str]]
    by_pn: dict[str, list[str]]
    logs: list[float]                     # log surface area of the items with usable geometry, sorted
    log_ids: list[str]
    erp_by_key: dict[str, dict]           # ERP items by part-number key (a planned number may exist only there)
    n_parts: int
    n_with_step: int
    n_geometry: int
    seconds: float


def build_index(run_dir: str | Path, cache_dir: str | Path, run_id: str = "", progress: Progress | None = None) -> RunIndex:
    """Items of a finished scan, with their fingerprints from the cache. Reads the STEP file records the scan kept
    (files.json); an older scan without them reads the files again. Never computes geometry: a part whose
    fingerprint is not in the cache is compared by name and part number only (counted in n_geometry)."""
    from .geometry import FingerprintCache
    from .project import build_items
    progress = progress or _noop
    t0 = time.perf_counter()
    run_dir = Path(run_dir)
    snap = Snapshot.load(run_dir / "snapshot.json")
    known = None
    f = run_dir / "files.json"
    if f.exists():
        known = {uid: FileRecord(**d) for uid, d in json.loads(f.read_text(encoding="utf-8")).items()}
    items, _recs, _links = build_items(snap, lambda _s, frac, txt: progress("index", 0.8 * frac, txt), known_files=known)
    progress("index", 0.85, "טוען טביעות אצבע גיאומטריות מהסריקה")
    cache = FingerprintCache(str(Path(cache_dir) / "fingerprints"))
    try:
        fps = cache.get_many(sorted({it.rec.sha256 for it in items.values() if it.rec.path and it.rec.sha256}))
    finally:
        if cache.db is not None:
            cache.db.close()
    for it in items.values():
        fp = fps.get(it.rec.sha256) if it.rec.path else None
        if fp is not None:
            it.fp = dict(fp, sha=it.rec.sha256)
    blocks: dict[str, set[str]] = defaultdict(set)
    by_sha: dict[str, list[str]] = defaultdict(list)
    by_norm: dict[str, list[str]] = defaultdict(list)
    by_pn: dict[str, list[str]] = defaultdict(list)
    areas = []
    for uid, it in sorted(items.items()):
        for k in block_keys(it.sources):
            blocks[k].add(uid)
        if it.rec.sha256:
            by_sha[it.rec.sha256].append(uid)
        if it.rec.norm_sha256:
            by_norm[it.rec.norm_sha256].append(uid)
        if it.pn_key:
            by_pn[it.pn_key].append(uid)
        if geometry_usable(it.fp):
            areas.append((math.log(it.fp["area"]), uid))
    areas.sort()
    erp = {}
    for e in snap.erp_items:
        erp.setdefault(pn_key(e.pn), {"pn": e.pn, "description": e.description, "stock": e.stock_total,
                                      "status": e.status, "active": e.active})
    progress("index", 1.0, f"מאגר החלקים מוכן ({len(items)} חלקים)")
    return RunIndex(run_id=run_id, created=snap.created, items=items, blocks=dict(blocks), by_sha=dict(by_sha),
                    by_norm=dict(by_norm), by_pn=dict(by_pn), logs=[a for a, _ in areas], log_ids=[u for _, u in areas],
                    erp_by_key=erp, n_parts=len(items), n_with_step=sum(1 for it in items.values() if it.rec.path),
                    n_geometry=len(areas), seconds=round(time.perf_counter() - t0, 2))


class _Samples:
    """Surface samples for the aligned-surface check: the new file's own cache first, then the scan's cache."""

    def __init__(self, *caches):
        self.caches = caches

    def get_samples(self, sha):
        for c in self.caches:
            pts = c.get_samples(sha)
            if pts is not None:
                return pts
        return None


def new_item(fr: FileRecord, fp: dict | None, filename: str, pn: str, name: str, description: str,
             material: str) -> Item:
    """The checked file as an engine item: the same name sources as a part read from a PDM (planned number and
    name, description, file name, the product name inside the STEP)."""
    it = Item(file_id=fr.file_id, rec=fr)
    known = [pn] if pn else None

    def add(text: str, label: str):
        np_ = parse_name(text, known_pns=known) if label != "file" and label != "step" else parse_name(text)
        if np_.words or np_.pns or np_.numbers:
            it.sources.append(np_)
            it.source_labels.append(label)
    main = f"{pn} {name}".strip()
    if main:
        add(main, "pdm")
    if description.strip() and description.strip() != name.strip():
        add(description, "pdm_desc")
    stem = Path(filename).stem
    if stem:
        add(stem, "file")
    for pid, pname, _ in fr.products[:1]:
        txt = " ".join(t for t in (pid, pname) if t and not is_generic_product_name(t))
        if txt and pn_key(txt) != pn_key(stem):
            add(txt, "step")
    it.pn = pn
    it.pn_key = pn_key(pn) if pn else ""
    it.material = material
    it.spec = parse_spec(name, description, "", stem, material, "")
    it.fp = fp
    return it


def compare_with_index(it: Item, index: RunIndex, th: Thresholds, samples=None) -> list[Pair]:
    """Pairs (new item, existing part) found by any layer, classified as the audit would classify them."""
    nid = it.file_id
    cand: dict[str, Pair] = {}

    def get(uid: str) -> Pair:
        if uid not in cand:
            cand[uid] = Pair(nid, uid)
        return cand[uid]
    # L1: the same file, or the same model with another header
    for uid in index.by_sha.get(it.rec.sha256, []) if it.rec.sha256 else []:
        get(uid).l1 = "raw"
    for uid in index.by_norm.get(it.rec.norm_sha256, []) if it.rec.norm_sha256 else []:
        p = get(uid)
        p.l1 = p.l1 or "norm"
    # L3: surface area within the near tolerance, or off by a unit factor (scale multiplies the existing part)
    scales: dict[str, float] = {}
    if geometry_usable(it.fp):
        la = math.log(it.fp["area"])
        win = math.log(1 + th.geo_near) + 1e-12
        for i in range(bisect.bisect_left(index.logs, la - win), bisect.bisect_right(index.logs, la + win)):
            scales.setdefault(index.log_ids[i], 1.0)
        utol = 2 * th.unit_tol + 1e-9
        for f in UNIT_FACTORS:
            # an existing part bigger by f (area f^2) matches when its lengths are multiplied by 1/f, and vice versa
            for shift, s in ((2 * math.log(f), 1.0 / f), (-2 * math.log(f), f)):
                t = la + shift
                for i in range(bisect.bisect_left(index.logs, t - utol), bisect.bisect_right(index.logs, t + utol)):
                    scales[index.log_ids[i]] = s
        for uid in scales:
            get(uid)
    # the same part number
    for uid in index.by_pn.get(it.pn_key, []) if it.pn_key else []:
        get(uid).same_pn = True
    # L2: names, with the same blocking and the same generic-description discount as the audit
    names = {u: x.sources for u, x in index.items.items() if x.sources}
    names[nid] = it.sources
    units = {u: x.pn_key for u, x in index.items.items() if x.pn_key}
    if it.pn_key:
        units[nid] = it.pn_key
    nindex = NameIndex(names, units, k0=th.name_k0, partial_factor=th.name_partial_factor)
    if it.sources:
        seen: set[str] = set()
        for key in sorted(block_keys(it.sources)):
            ids = index.blocks.get(key)
            if not ids or block_too_big(key, len(ids) + 1):
                continue
            for uid in sorted(ids - seen):
                seen.add(uid)
                m = best_match(it.sources, index.items[uid].sources, nindex)
                if m and m.score >= th.name_candidate:
                    get(uid).name = m
    for uid, p in cand.items():
        e = index.items[uid]
        if p.name is None and it.sources and e.sources:
            p.name = best_match(it.sources, e.sources, nindex)
        if not p.l1:
            p.geo = compare_geometry(it.fp, e.fp, th, scales.get(uid, 1.0))
    if samples is not None:
        from .shape import ShapeChecker
        checker = ShapeChecker(samples, th)
        for uid, p in sorted(cand.items()):
            e = index.items[uid]
            if needs_shape_check(p.geo) and not compare_specs(it.spec, e.spec)[0]:
                p.geo.shape = checker(it, e, p.geo)
    out = []
    for uid, p in sorted(cand.items()):
        classify(p, it, index.items[uid], th)
        if p.category:
            out.append(p)
    every = dict(index.items)
    every[nid] = it
    enforce_material_consistency(out, every)
    return out


def _fin(x):
    return None if x is None or x == math.inf else x


HINT_HE = {
    "identical": "אותו חלק – השתמשו במק\"ט הקיים",
    "standard_part": "אותו פריט קנייה – השתמשו במק\"ט הקיים",
    "identical_attr_conflict": "אותה צורה, מפרט שונה – בדקו איזה מהם נכון",
    "conflict": "המק\"ט שתכננתם כבר שייך לחלק אחר",
    "conflict_unverified": "המק\"ט שתכננתם כבר קיים – לא ניתן להשוות צורה",
    "near_identical": "כמעט זהה – אולי אפשר להשתמש בקיים",
    "mirror": "תמונת מראה – גרסת ימין/שמאל",
    "name_similar": "שם דומה, צורה שונה",
}


def _rank_existing(p: dict) -> tuple:
    """Which existing record to recommend: linked to the ERP, released, used in most assemblies, most stock."""
    erp = p.get("erp") or {}
    return (0 if erp else 1, 0 if p.get("state_class") == "released" else 1, -(p.get("used_in") or 0),
            -(erp.get("stock") or 0), 0 if p.get("pn") else 1, p.get("pn") or "~")


def _where(rows: list[dict]) -> str:
    """'ב-X', 'ב-X וב-Y' or 'ב-4 מערכות'."""
    names = sorted({r["part"].get("source", "") for r in rows if r["part"].get("source")})
    if len(names) > 2:
        return f"ב-{len(names)} מערכות"
    # Hebrew attaches the preposition to a Hebrew word ("בארכיון") and uses a hyphen before a Latin one ("ב-Vault")
    with_b = [("ב" + n if "\u05d0" <= n[:1] <= "\u05ea" else "ב-" + n) for n in names]
    return " ו".join(with_b)


def verdict(matches: list[dict], it_pn: str, index: RunIndex, parts: dict[str, dict], geo_ok: bool, geo_error: str,
            group_targets: dict[str, dict]) -> tuple[dict, list[dict]]:
    """The answer in plain Hebrew (one verdict) and the notes that come with it."""
    by_cat = defaultdict(list)
    for m in matches:
        by_cat[m["category"]].append(m)
    notes: list[dict] = []
    same = by_cat["identical"] + by_cat["standard_part"]
    if same:
        best = sorted(same, key=lambda m: _rank_existing(m["part"]))[0]
        use = best["part"]
        why = "מקושר ל-ERP" if use.get("erp") else ""
        gid = next((m["part"].get("group_id") for m in same if m["part"].get("group_id")), None)
        group = group_targets.get(gid) if gid else None
        if group:
            use = group
            why = "היעד של קבוצת הכפילות" + (" (אושר)" if group.get("approved") else " (מוצע)")
        n = len(same)
        std = [m for m in same if m["category"] == "standard_part"]
        records = "ברשומה אחת" if n == 1 else f"ב-{n} רשומות"
        if std and len(std) == len(same):
            title = "החלק התקני הזה כבר קיים"
            text = (f"{std[0]['spec_he'] or 'אותו פריט תקני'} כבר קיים {records} {_where(same)}. "
                    f"במקום לפתוח מק\"ט חדש – השתמשו במק\"ט {use['pn']}.")
        else:
            title = "החלק הזה כבר קיים"
            text = (f"נמצאה התאמה מלאה {'לרשומה קיימת אחת' if n == 1 else f'ל-{n} רשומות קיימות'} {_where(same)}. "
                    f"במקום לפתוח מק\"ט חדש – השתמשו במק\"ט {use['pn']}.")
        if group and len(group.get("pns") or []) > 1:
            text += (f" החלק כבר רשום תחת {len(group['pns'])} מק\"טים שונים – "
                     + ("קבוצת כפילות שכבר אושר לה מק\"ט יעד." if group.get("approved")
                        else "קבוצת כפילות שממתינה להחלטה."))
        unit = next((m for m in same if m["geo_relation"] == "unit_scaled"), None)
        if unit:
            s = unit["metrics"]["scale"] or 1.0
            notes.append({"kind": "unit", "tone": "warn", "text": (
                f"הקובץ שלכם {'קטן' if s > 1 else 'גדול'} פי {max(s, 1 / s):.4g} מהחלק הקיים – כנראה יוצא ביחידות "
                f"שגויות ({unit['metrics'].get('unit_note') or 'יחידות'}). כדאי לייצא אותו שוב במילימטרים.")})
        v = {"kind": "exists", "tone": "bad", "title": title, "text": text,
             "use": {k: use.get(k) for k in ("uid", "pn", "name", "source", "source_kind")} | {"why": why}}
    elif by_cat["identical_attr_conflict"]:
        m = sorted(by_cat["identical_attr_conflict"], key=lambda x: _rank_existing(x["part"]))[0]
        v = {"kind": "attr_conflict", "tone": "warn", "title": "אותה צורה כבר קיימת – עם מפרט אחר",
             "text": (f"מק\"ט {m['part']['pn'] or m['part']['name']} זהה בצורה, אבל {m['attr_note'] or 'המפרט שונה'}. "
                      "אם ההבדל אמיתי, זה פריט חדש; אם לא – השתמשו במק\"ט הקיים."),
             "use": {k: m["part"].get(k) for k in ("uid", "pn", "name", "source", "source_kind")}}
    elif by_cat["near_identical"]:
        m = sorted(by_cat["near_identical"], key=lambda x: (-round(x["confidence"], 2), _rank_existing(x["part"])))[0]
        dv = m["metrics"].get("d_volume")
        v = {"kind": "near", "tone": "warn", "title": "קיים חלק כמעט זהה",
             "text": (f"מק\"ט {m['part']['pn'] or m['part']['name']} כמעט זהה"
                      + (f" (הפרש נפח {pct(dv)})" if dv is not None else "")
                      + ". בדקו אם אפשר להשתמש בו במקום לפתוח מק\"ט חדש."),
             "use": {k: m["part"].get(k) for k in ("uid", "pn", "name", "source", "source_kind")}}
    elif by_cat["mirror"]:
        m = sorted(by_cat["mirror"], key=lambda x: _rank_existing(x["part"]))[0]
        v = {"kind": "mirror", "tone": "info", "title": "קיימת גרסת ראי (ימין/שמאל)",
             "text": (f"מק\"ט {m['part']['pn'] or m['part']['name']} הוא תמונת המראה של החלק. אם צריך את שני הצדדים זה "
                      "תקין – ודאו שהשמות מציינים ימין ושמאל."),
             "use": {k: m["part"].get(k) for k in ("uid", "pn", "name", "source", "source_kind")}}
    elif not geo_ok:
        v = {"kind": "no_geometry", "tone": "warn", "title": "לא ניתן היה לבדוק את הצורה",
             "text": f"את הגיאומטריה בקובץ לא הצלחנו לקרוא ({geo_error or 'שגיאה לא ידועה'}). נבדקו רק שמות ומק\"טים.",
             "use": None}
    else:
        v = {"kind": "new", "tone": "ok", "title": "לא נמצא חלק קיים כזה",
             "text": (f"הצורה הושוותה ל-{index.n_geometry} חלקים עם קובץ STEP מתוך {index.n_parts} בסריקה, ולא נמצא "
                      "חלק זהה, כמעט זהה או תמונת מראה. אפשר לפתוח מק\"ט חדש."),
             "use": None}
    # the planned part number: looked up in every record of the scan and in the ERP, not only among the matches
    if it_pn:
        k = pn_key(it_pn)
        holders = index.by_pn.get(k, [])
        same_part = [m for m in same if pn_key(m["part"].get("pn") or "") == k]
        others = [u for u in holders if u not in {m["uid"] for m in same_part}]
        if same_part and not others:
            notes.append({"kind": "pn_same_part", "tone": "info",
                          "text": f"המק\"ט {it_pn} כבר שייך לחלק הזה בדיוק – אין צורך לפתוח אותו שוב."})
        elif others:
            p0 = parts.get(others[0]) or {}
            m = next((x for x in matches if x["uid"] == others[0]), None)
            shape = {"conflict": ", עם צורה שונה", "conflict_unverified": " (בלי קובץ STEP להשוואת צורה)"}.get(
                m["category"] if m else "", "")
            notes.append({"kind": "pn_taken", "tone": "bad", "text": (
                f"המק\"ט {it_pn} כבר קיים על חלק אחר: {p0.get('name') or p0.get('pn') or others[0]}"
                + (f" ({p0['source']})" if p0.get("source") else "") + shape + ". בחרו מק\"ט אחר.")})
        elif k in index.erp_by_key:
            e = index.erp_by_key[k]
            notes.append({"kind": "pn_in_erp", "tone": "bad", "text": (
                f"המק\"ט {it_pn} כבר קיים ב-ERP: {e['description'] or e['pn']}"
                + (f" (מלאי {e['stock']:g})" if e.get("stock") else "") + ". בחרו מק\"ט אחר.")})
        else:
            notes.append({"kind": "pn_free", "tone": "ok", "text": f"המק\"ט {it_pn} לא קיים באף מערכת שנסרקה."})
    if v["kind"] == "new" and any(n["kind"] in ("pn_taken", "pn_in_erp") for n in notes):
        v["tone"] = "warn"
        v["text"] = v["text"].replace("אפשר לפתוח מק\"ט חדש.", "אפשר לפתוח מק\"ט חדש – אבל לא את המק\"ט שתכננתם (ראו למטה).")
    if by_cat["name_similar"] and v["kind"] in ("new", "no_geometry"):
        n = len(by_cat["name_similar"])
        notes.append({"kind": "names", "tone": "info", "text": (
            f"{'חלק אחד' if n == 1 else f'{n} חלקים'} עם שם דומה אבל צורה שונה – כדאי לוודא שהשם החדש לא יבלבל.")})
    missing = index.n_parts - index.n_geometry
    if missing > 0:
        notes.append({"kind": "coverage", "tone": "info", "text": (
            f"ל-{missing} מתוך {index.n_parts} החלקים בסריקה אין קובץ STEP שנקרא – אותם בדקנו רק לפי שם ומק\"ט.")})
    return v, notes


def check_file(index: RunIndex, path: str | Path, parts: dict[str, dict], *, filename: str = "", pn: str = "",
               name: str = "", description: str = "", material: str = "", th: Thresholds | None = None,
               cache_dir: str | Path, own_cache: str | Path, timeout_s: float = 60.0,
               group_targets: dict[str, dict] | None = None, shapes=None, progress: Progress | None = None) -> dict:
    """Check one STEP file against a scan. ``parts`` are the scan's part rows by uid (for display); ``own_cache``
    is the folder where the new file's fingerprint is kept (apart from the scan's cache, so a running scan and a
    check never wait for each other)."""
    from .geometry import FingerprintCache, fingerprint_files
    progress = progress or _noop
    th = th or Thresholds()
    t0 = time.perf_counter()
    path = Path(path)
    pn, name, description, material = (str(x or "").strip() for x in (pn, name, description, material))
    fr = read_step_record(str(path), str(path.parent))
    if fr.error:
        raise CheckError(f"הקובץ אינו קובץ STEP תקין ({fr.error})" if "ISO-10303-21" in fr.error
                         else f"לא ניתן לקרוא את הקובץ: {fr.error}")
    fr.file_id = NEW_PREFIX + fr.sha256[:16]
    t_read = time.perf_counter() - t0
    progress("geometry", 0.1, "מחשב את הצורה של החלק החדש (נפח, שטח, מידות)")
    t1 = time.perf_counter()
    fps, errors, _stats, own = fingerprint_files([(fr.file_id, str(path), fr.sha256)], workers=1, timeout_s=timeout_s,
                                                 cache_dir=str(own_cache))
    fp = fps.get(fr.file_id)
    geo_error = ""
    if fr.file_id in errors:
        geo_error = " – ".join(x for x in errors[fr.file_id] if x)
    geo_ok = geometry_usable(fp)
    t_geo = time.perf_counter() - t1
    it = new_item(fr, fp if geo_ok else None, filename or path.name, pn, name, description, material)
    progress("compare", 0.5, f"משווה מול {index.n_parts} חלקים מהסריקה")
    t2 = time.perf_counter()
    scan_cache = FingerprintCache(str(Path(cache_dir) / "fingerprints"))
    near_shapes: list[tuple[str, float]] = []
    try:
        pairs = compare_with_index(it, index, th, samples=_Samples(own, scan_cache))
        if shapes is not None and geo_ok and len(shapes):
            from .similar import shape_vector, size_of
            vec = shape_vector(fp, own.get_samples(fp["sha"]))
            if vec is not None:
                near_shapes = shapes.nearest(vec, size_of(fp), k=8)
    finally:
        for c in (own, scan_cache):
            if c.db is not None:
                c.db.close()
    t_cmp = time.perf_counter() - t2
    rows = []
    for p in pairs:
        e = index.items[p.b]
        part = parts.get(p.b)
        if part is None:
            continue
        g = p.geo
        shp = (g.shape or {}) if g else {}
        attr = ""
        for issue in p.attr_issues or []:
            if issue.startswith("material differs"):
                attr = "החומר שונה: " + issue.split("(", 1)[-1].rstrip(")")
        if not attr and p.spec_relation == "spec_conflict":
            attr = f"המפרט שונה ({p.spec_note})"
        if not attr and "different materials" in p.reason:
            attr = "אותה צורה רשומה עם חומרים שונים – ציינו את החומר כדי לדעת איזה מהם מתאים"
        reason = pair_reason_he(p, it, e)
        if p.category == "conflict":   # in a check the shared number is the one the engineer planned
            reason = "המק\"ט שתכננתם כבר שייך לחלק הזה, והצורה שלו " + {
                "near": "שונה מעט (רוויזיה אחרת?)", "mirror": "היא תמונת מראה"}.get(p.geo_relation, "שונה")
        elif p.category == "conflict_unverified":
            reason = "המק\"ט שתכננתם כבר שייך לחלק הזה (אין לו קובץ STEP, ולכן הצורה לא הושוותה)"
        rows.append({
            "uid": p.b, "category": p.category, "category_he": CATEGORY_HE.get(p.category, p.category),
            "hint_he": HINT_HE.get(p.category, ""), "geo_relation": p.geo_relation, "confidence": round(p.confidence, 3),
            "reason_he": reason, "l1": p.l1, "same_pn": p.same_pn, "attr_note": attr,
            "spec_note": p.spec_note, "spec_label": e.spec.label if e.spec else "", "spec_he": _spec_he(e),
            "name_score": None if p.name is None else p.name.score,
            "metrics": None if g is None else {
                "max_rel": _fin(g.max_rel), "d_volume": _fin(g.d_volume), "d_area": _fin(g.d_area),
                "d_bbox": _fin(g.d_bbox), "scale": g.scale, "unit_note": g.unit_note, "topo_same": g.topo_same,
                "p95_mm": (shp["p95_rel"] * shp["diag"]) if shp.get("p95_rel") is not None and shp.get("diag") else None,
                "excess50": shp.get("excess50"), "mirror": shp.get("mirror")},
            "part": part})
    # what decides the answer first; among equally close records the one to recommend (in the ERP, released ...)
    rows.sort(key=lambda r: (ORDER.index(r["category"]) if r["category"] in ORDER else 99, -round(r["confidence"], 2),
                             _rank_existing(r["part"])))
    v, notes = verdict(rows, pn, index, parts, geo_ok, geo_error, group_targets or {})
    # shape search: the closest shapes of the scan, whatever their size (for reuse when nothing matched)
    found = {r["uid"]: r["category"] for r in rows}
    similar = [{"uid": u, "distance": round(d, 4), "relation": found.get(u, "similar"),
                "part": {k: parts[u].get(k) for k in ("uid", "pn", "name", "source", "source_kind", "state", "state_class",
                                                     "bbox", "volume_mm3", "material", "group_id", "has_step", "spec")}}
               for u, d in near_shapes if u in parts]
    counts = defaultdict(int)
    for r in rows:
        counts[r["category"]] += 1
    geo = {"ok": geo_ok, "error": geo_error}
    if geo_ok:
        geo.update({"volume_mm3": fp["volume"] if fp.get("closed") else None, "area_mm2": fp["area"],
                    "bbox": fp.get("bbox_pca"), "n_faces": fp.get("n_faces"), "closed": fp.get("closed"),
                    "unit": fr.length_unit})
    product = next(((p[1] or p[0]) for p in fr.products[:1]), "")
    return {
        "file": {"name": filename or path.name, "size": fr.size, "sha256": fr.sha256, "schema": fr.schema,
                 "unit": fr.length_unit, "product": product, "system": fr.originating_system},
        "input": {"pn": pn, "name": name, "description": description, "material": material},
        "spec": it.spec.label if it.spec else "",
        "run_id": index.run_id, "run_created": index.created,
        "coverage": {"parts": index.n_parts, "with_step": index.n_with_step, "with_geometry": index.n_geometry},
        "verdict": v, "notes": notes, "counts": dict(counts), "matches": rows[:MAX_ROWS], "n_matches": len(rows),
        "geometry": geo, "similar": similar,
        "timings": {"read_s": round(t_read, 2), "geometry_s": round(t_geo, 2), "compare_s": round(t_cmp, 2),
                    "total_s": round(time.perf_counter() - t0, 2)},
    }
