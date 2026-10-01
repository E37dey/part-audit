"""L5 - combine L1 (hashes), L2 (names), L3/L3b (geometry) into pair classes.

Every candidate pair gets one category:

* ``identical``          - same part (byte/normalized hash, or geometry match). Merge candidate,
                           unless ERP attributes (material) differ -> ``identical_attr_conflict``.
* ``near_identical``     - geometry within a few percent: alert only, never merged.
* ``conflict``           - same part number but different geometry.
* ``name_similar``       - names match strongly, geometry different (or not comparable).

Confidence values are heuristic evidence scores in [0, 1] (not calibrated
probabilities); the measured precision per category is in the Metrics sheet.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .names import NameMatch, NameParts, best_match, blocking_pairs

# unit conversion factors that explain an exact uniform scale between two files
UNIT_FACTORS = {
    25.4: "inch<->mm", 10.0: "cm<->mm", 1000.0: "m<->mm", 304.8: "ft<->mm", 2.54: "inch<->cm",
    100.0: "m<->cm", 12.0: "ft<->inch",
}


@dataclass
class Thresholds:
    geo_exact: float = 1e-6        # every global property within this -> identical even if topology differs
    geo_identical: float = 1e-4    # within this and same topology -> identical
    geo_near: float = 0.05         # within this -> near-identical candidate
    near_max_face_ratio: float = 3.0     # topology guard for near-identical (no L3b)
    near_max_type_dist: float = 0.25     # surface-type area-fraction L1 distance guard
    unit_tol: float = 1e-4         # tolerance on the scale factor for unit mismatches
    name_similar: float = 0.85     # L2 score for a name match
    name_candidate: float = 0.70   # L2 score kept for context in reports
    shape_near: float = 0.03       # L3b: aligned surface distance (p95 / bbox diagonal) for near-identical
    shape_identical: float = 0.01  # L3b: above this an 'identical' by properties is downgraded
    mirror_ratio: float = 0.5      # L3b: improper/proper alignment ratio below which -> mirror image

    def as_dict(self) -> dict:
        return dict(self.__dict__)


# --------------------------------------------------------------------------- items


@dataclass
class Item:
    file_id: str
    rec: object                                   # scan.FileRecord
    sources: list[NameParts] = field(default_factory=list)
    source_labels: list[str] = field(default_factory=list)
    pn: str = ""                                  # primary part number (raw spelling)
    pn_key: str = ""
    erp: dict | None = None                       # linked ERP row
    erp_link: str = ""                            # how the ERP row was linked
    fp: dict | None = None                        # geometry fingerprint (L3)


# --------------------------------------------------------------------------- geometry comparison


@dataclass
class GeoMatch:
    relation: str               # identical | unit_scaled | near | different | unknown
    max_rel: float = math.inf   # max relative difference of V, A, I1..I3 (after unit scaling)
    d_volume: float = math.inf
    d_area: float = math.inf
    d_inertia: float = math.inf
    d_bbox: float = math.inf
    topo_same: bool = False
    face_ratio: float = math.inf
    type_dist: float = math.inf
    scale: float = 1.0
    unit_note: str = ""
    shape: dict | None = None   # L3b result, if computed
    note: str = ""


def _rel(a: float, b: float) -> float:
    m = max(abs(a), abs(b))
    return 0.0 if m == 0 else abs(a - b) / m


def _type_dist(fa: dict, fb: dict) -> float:
    ta, tb = fa.get("surf_area_frac") or {}, fb.get("surf_area_frac") or {}
    keys = set(ta) | set(tb)
    return sum(abs(ta.get(k, 0.0) - tb.get(k, 0.0)) for k in keys)


def geometry_usable(fp: dict | None) -> bool:
    return bool(fp) and fp.get("ok") and fp.get("area", 0) > 0


def compare_geometry(fa: dict | None, fb: dict | None, th: Thresholds, scale: float = 1.0) -> GeoMatch:
    """Compare two fingerprints; ``scale`` multiplies lengths of ``fb`` (unit mismatch)."""
    if not geometry_usable(fa) or not geometry_usable(fb):
        return GeoMatch("unknown", note="geometry not available for both files")
    s = scale
    va, vb = abs(fa["volume"]), abs(fb["volume"]) * s**3
    aa, ab = fa["area"], fb["area"] * s**2
    ia = fa["inertia"]
    ib = [x * s**5 for x in fb["inertia"]]
    d_v, d_a = _rel(va, vb), _rel(aa, ab)
    d_i = max(_rel(x, y) for x, y in zip(ia, ib)) if ia and ib else math.inf
    ba, bb = fa.get("bbox_pca") or [], [x * s for x in (fb.get("bbox_pca") or [])]
    d_b = max((_rel(x, y) for x, y in zip(ba, bb)), default=math.inf)
    solid_ok = fa.get("closed", False) and fb.get("closed", False) and va > 0 and vb > 0
    if solid_ok:
        max_rel = max(d_v, d_a, d_i)
    else:  # volume/inertia unreliable for open shells: use area and bbox only
        max_rel = max(d_a, d_b)
    topo_same = (fa.get("n_faces") == fb.get("n_faces") and fa.get("n_edges") == fb.get("n_edges")
                 and fa.get("surf_counts") == fb.get("surf_counts"))
    nf_a, nf_b = max(fa.get("n_faces", 0), 1), max(fb.get("n_faces", 0), 1)
    gm = GeoMatch("different", max_rel, d_v, d_a, d_i, d_b, topo_same, max(nf_a, nf_b) / min(nf_a, nf_b),
                  _type_dist(fa, fb), scale)
    if scale != 1.0:
        gm.unit_note = UNIT_FACTORS.get(round(scale if scale > 1 else 1 / scale, 4), f"x{scale:g}")
    if max_rel <= th.geo_exact or (max_rel <= th.geo_identical and topo_same):
        gm.relation = "unit_scaled" if scale != 1.0 else "identical"
        if not solid_ok:
            gm.note = "open shell: compared by area and bounding box only"
    elif max_rel <= th.geo_near and scale == 1.0:
        if gm.face_ratio <= th.near_max_face_ratio and gm.type_dist <= th.near_max_type_dist:
            gm.relation = "near"
    return gm


def geometry_candidates(items: dict[str, Item], th: Thresholds) -> dict[tuple[str, str], float]:
    """Pairs whose surface areas are within the near tolerance (scale 1) or differ by a unit factor.

    Returns {(a, b): scale} where scale multiplies lengths of b to match a.
    """
    rows = sorted((math.log(it.fp["area"]), fid) for fid, it in items.items() if geometry_usable(it.fp))
    out: dict[tuple[str, str], float] = {}
    if not rows:
        return out
    logs = [r[0] for r in rows]
    ids = [r[1] for r in rows]
    import bisect
    win = math.log(1 + th.geo_near) + 1e-12
    n = len(rows)
    for i in range(n):
        j = i + 1
        while j < n and logs[j] - logs[i] <= win:
            a, b = sorted((ids[i], ids[j]))
            out.setdefault((a, b), 1.0)
            j += 1
    # unit factors: area scales with the square of the factor
    utol = 2 * th.unit_tol + 1e-9
    for f in UNIT_FACTORS:
        shift = 2 * math.log(f)
        for i in range(n):
            target = logs[i] + shift
            lo = bisect.bisect_left(logs, target - utol)
            hi = bisect.bisect_right(logs, target + utol)
            for j in range(lo, hi):
                # ids[j] is bigger by factor f: scale of j relative to i is 1/f (j lengths * (1/f) = i)
                a, b = ids[i], ids[j]
                if a < b:
                    out[(a, b)] = 1.0 / f
                else:
                    out[(b, a)] = f
    return out


# --------------------------------------------------------------------------- ERP attributes

_MATERIAL_SYNONYMS = {
    "aluminium": "aluminum", "alu": "aluminum", "al": "aluminum", "alum": "aluminum", "אלומיניום": "aluminum",
    "אלומיניון": "aluminum", "steel": "steel", "st": "steel", "stl": "steel", "פלדה": "steel", "ss": "stainless",
    "inox": "stainless", "stainless": "stainless", "נירוסטה": "stainless", "brass": "brass", "פליז": "brass",
    "copper": "copper", "cu": "copper", "נחושת": "copper", "delrin": "pom", "acetal": "pom", "pom": "pom",
    "דלרין": "pom", "אצטל": "pom", "nylon": "nylon", "pa6": "nylon", "ניילון": "nylon", "abs": "abs",
    "peek": "peek", "pvc": "pvc", "polycarbonate": "pc", "pc": "pc", "titanium": "titanium", "ti": "titanium",
    "טיטניום": "titanium", "plastic": "plastic", "פלסטיק": "plastic", "rubber": "rubber", "גומי": "rubber",
}


def material_key(text: str) -> str:
    toks = re.findall(r"[a-z]+|\d+|[א-ת]+", str(text).lower().replace("-", " "))
    out = []
    for t in toks:
        if t.isdigit():
            out.append(t)
        elif t in _MATERIAL_SYNONYMS:
            out.append(_MATERIAL_SYNONYMS[t])
        elif re.fullmatch(r"(?:al|ss|aisi|en|st)", t):
            continue
        else:
            out.append(t)
    return " ".join(sorted(set(out)))


def erp_attribute_conflicts(a: Item, b: Item) -> list[str]:
    if not a.erp or not b.erp:
        return []
    issues = []
    ma, mb = a.erp.get("material", ""), b.erp.get("material", "")
    if ma and mb and material_key(ma) != material_key(mb):
        issues.append(f"material differs ({ma} vs {mb})")
    return issues


# --------------------------------------------------------------------------- pairs


@dataclass
class Pair:
    a: str
    b: str
    l1: str = ""                       # raw | norm | ''
    geo: GeoMatch | None = None
    name: NameMatch | None = None
    same_pn: bool = False
    attr_issues: list[str] = field(default_factory=list)
    category: str = ""
    geo_relation: str = "unknown"      # identical | unit_scaled | near | mirror | different | unknown
    confidence: float = 0.0
    reason: str = ""
    merge_ok: bool = False


def _fmt_pct(x: float) -> str:
    if x == math.inf:
        return "n/a"
    if x < 1e-6:
        return "<0.0001%"
    return f"{100 * x:.4g}%"


def classify(p: Pair, a: Item, b: Item, th: Thresholds) -> Pair:
    """Assign category, geometry relation, confidence and a human-readable reason."""
    g = p.geo
    name_ok = p.name is not None and p.name.score >= th.name_similar
    name_txt = f"names: {p.name.detail}" if p.name else ""
    if p.l1:
        p.geo_relation = "identical"
        p.confidence = 1.0 if p.l1 == "raw" else 0.99
        p.reason = ("byte-identical files" if p.l1 == "raw"
                    else "same STEP geometry data; only header/timestamp/names/formatting differ")
    elif g and g.relation in ("identical", "unit_scaled"):
        p.geo_relation = g.relation
        shp = g.shape or {}
        if shp.get("mirror"):
            p.geo_relation = "mirror"
        elif shp and shp.get("p95_rel", 0) > th.shape_identical and g.max_rel > th.geo_exact:
            p.geo_relation = "near"  # properties agree but the aligned shapes do not
        if p.geo_relation in ("identical", "unit_scaled"):
            base = 0.97 if g.max_rel <= th.geo_exact else 0.95
            if g.relation == "unit_scaled":
                base = 0.9
            if not g.topo_same:
                base -= 0.02
            p.confidence = base
            bits = [f"geometry match: max property difference {_fmt_pct(g.max_rel)}"]
            if g.relation == "unit_scaled":
                bits.append(f"uniform scale factor {max(g.scale, 1 / g.scale):.6g} ({g.unit_note}) - probable unit error")
            bits.append("same topology" if g.topo_same else "topology differs (re-export/split faces)")
            if g.note:
                bits.append(g.note)
            p.reason = "; ".join(bits)
    elif g and g.relation == "near":
        p.geo_relation = "near"
    elif g and g.relation == "different":
        p.geo_relation = "different"
    # L3b on near candidates
    if p.geo_relation == "near" and g is not None:
        shp = g.shape
        if shp and shp.get("mirror"):
            p.geo_relation = "mirror"
        elif shp and shp.get("p95_rel") is not None and shp["p95_rel"] > th.shape_near:
            p.geo_relation = "different"
            p.reason = f"properties within {_fmt_pct(g.max_rel)} but shapes differ (surface distance {shp['p95_rel']:.2%})"
        else:
            p.confidence = round(max(0.5, 0.9 - 0.4 * g.max_rel / th.geo_near), 3)
            bits = [f"geometry within {_fmt_pct(g.max_rel)} (volume {_fmt_pct(g.d_volume)}, area {_fmt_pct(g.d_area)}, "
                    f"inertia {_fmt_pct(g.d_inertia)}, bbox {_fmt_pct(g.d_bbox)})"]
            if shp and shp.get("p95_rel") is not None:
                bits.append(f"aligned surface distance p95 {shp['p95_rel']:.2%} of size")
            bits.append(f"faces {a.fp.get('n_faces')} vs {b.fp.get('n_faces')}")
            p.reason = "; ".join(bits) + " - small design change or different export; review"
    if p.geo_relation == "mirror":
        p.confidence = 0.8
        p.reason = "same properties but mirror image (left/right-hand version?) - different parts"

    # ---- category
    if p.geo_relation in ("identical", "unit_scaled"):
        p.attr_issues = erp_attribute_conflicts(a, b)
        if p.attr_issues:
            p.category = "identical_attr_conflict"
            p.reason += "; ERP " + "; ".join(p.attr_issues) + " - do not merge without review"
            p.merge_ok = False
        else:
            p.category = "identical"
            p.merge_ok = True
    elif p.same_pn and p.geo_relation in ("near", "different", "mirror"):
        p.category = "conflict"
        p.confidence = 0.9 if p.geo_relation == "different" else max(p.confidence, 0.8)
        what = {"near": "slightly different geometry (revision?)", "different": "different geometry",
                "mirror": "mirror-image geometry"}[p.geo_relation]
        p.reason = f"same part number but {what}" + (f"; {p.reason}" if p.reason else "")
    elif p.geo_relation == "near":
        p.category = "near_identical"
    elif p.geo_relation == "mirror":
        p.category = "near_identical"
    elif p.same_pn and p.geo_relation == "unknown":
        p.category = "conflict_unverified"
        p.confidence = 0.5
        p.reason = "same part number in two different files; geometry could not be compared"
    elif name_ok:
        p.category = "name_similar"
        p.confidence = round(0.8 * p.name.score, 3)
        if p.geo_relation == "different":
            p.reason = "similar names but different geometry (risk of mix-up)"
        else:
            p.reason = "similar names; geometry not compared"
    else:
        p.category = ""
    if name_txt and p.category:
        p.reason = f"{p.reason}; {name_txt}" if p.reason else name_txt
    return p


def build_pairs(items: dict[str, Item], th: Thresholds, use_geometry: bool = True, shape_check=None) -> list[Pair]:
    """Generate candidate pairs from all layers and classify them."""
    cand: dict[tuple[str, str], Pair] = {}

    def get(a: str, b: str) -> Pair:
        key = (a, b) if a < b else (b, a)
        if key not in cand:
            cand[key] = Pair(*key)
        return cand[key]

    # L1
    for attr, tag in (("sha256", "raw"), ("norm_sha256", "norm")):
        groups: dict[str, list[str]] = {}
        for fid, it in items.items():
            h = getattr(it.rec, attr, "")
            if h:
                groups.setdefault(h, []).append(fid)
        for ids in groups.values():
            ids.sort()
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    p = get(ids[i], ids[j])
                    if not p.l1:
                        p.l1 = tag
    # L3
    scales: dict[tuple[str, str], float] = {}
    if use_geometry:
        scales = geometry_candidates(items, th)
        for key in scales:
            get(*key)
    # same part number
    by_pn: dict[str, list[str]] = {}
    for fid, it in items.items():
        if it.pn_key:
            by_pn.setdefault(it.pn_key, []).append(fid)
    for ids in by_pn.values():
        ids.sort()
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                get(ids[i], ids[j]).same_pn = True
    # L2
    name_items = {fid: it.sources for fid, it in items.items() if it.sources}
    for a, b in blocking_pairs(name_items):
        m = best_match(items[a].sources, items[b].sources)
        if m and m.score >= th.name_candidate:
            get(a, b).name = m

    out: list[Pair] = []
    for (a, b), p in sorted(cand.items()):
        ia, ib = items[a], items[b]
        if p.name is None and ia.sources and ib.sources:
            p.name = best_match(ia.sources, ib.sources)
        if use_geometry and not p.l1:
            p.geo = compare_geometry(ia.fp, ib.fp, th, scales.get((a, b), 1.0))
            if shape_check is not None and p.geo.relation in ("identical", "unit_scaled", "near"):
                p.geo.shape = shape_check(ia, ib, p.geo)
        classify(p, ia, ib, th)
        if p.category:
            out.append(p)
    return out


# --------------------------------------------------------------------------- groups


class UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            if rb < ra:
                ra, rb = rb, ra
            self.parent[rb] = ra


def duplicate_groups(pairs: list[Pair]) -> list[list[str]]:
    """Connected components of merge-eligible identical pairs (sorted, largest first)."""
    uf = UnionFind()
    for p in pairs:
        if p.category == "identical" and p.merge_ok:
            uf.union(p.a, p.b)
    comps: dict[str, list[str]] = {}
    for x in list(uf.parent):
        comps.setdefault(uf.find(x), []).append(x)
    groups = [sorted(v) for v in comps.values() if len(v) > 1]
    groups.sort(key=lambda g: (-len(g), g[0]))
    return groups


def propose_mapping(groups: list[list[str]], items: dict[str, Item], pairs: list[Pair]) -> list[dict]:
    """For each duplicate group with several part numbers, propose one canonical PN.

    Rule: prefer a PN that exists in the ERP, then the PN used by most files, then the
    lowest (oldest-looking) PN. Every row is 'pending approval'.
    """
    conf: dict[tuple[str, str], Pair] = {(p.a, p.b): p for p in pairs if p.category == "identical"}
    rows: list[dict] = []
    for gi, g in enumerate(groups, start=1):
        by_key: dict[str, list[str]] = {}
        for fid in g:
            by_key.setdefault(items[fid].pn_key or "", []).append(fid)
        keys = [k for k in by_key if k]
        if len(keys) + (1 if "" in by_key else 0) < 2:
            continue  # one PN only (or no PN at all): nothing to map

        def rank(k: str):
            in_erp = any(items[f].erp for f in by_key[k])
            return (0 if in_erp else 1, -len(by_key[k]), len(k), k)

        if not keys:
            continue
        canon = sorted(keys, key=rank)[0]
        canon_pn = next(items[f].erp["part_number"] for f in by_key[canon] if items[f].erp) \
            if any(items[f].erp for f in by_key[canon]) else items[by_key[canon][0]].pn
        for k, fids in sorted(by_key.items()):
            if k == canon:
                continue
            best = None
            for fa in fids:
                for fb in by_key[canon]:
                    p = conf.get((fa, fb) if fa < fb else (fb, fa))
                    if p and (best is None or p.confidence > best.confidence):
                        best = p
            if best is None:  # connected only through other members
                cs = [p for (x, y), p in conf.items() if x in g and y in g]
                best = min(cs, key=lambda p: p.confidence) if cs else None
            old_pn = items[fids[0]].pn if k else ""
            erp_old = next((items[f].erp for f in fids if items[f].erp), None)
            reason = best.reason if best else "same duplicate group"
            why_canon = "exists in ERP" if any(items[f].erp for f in by_key[canon]) else "used by most files"
            rows.append({
                "group_id": f"G{gi:04d}",
                "old_pn": erp_old["part_number"] if erp_old else old_pn,
                "proposed_pn": canon_pn,
                "files_old": "; ".join(fids),
                "files_proposed": "; ".join(by_key[canon]),
                "reason": (f"{reason}. Proposed PN chosen because it {why_canon}."
                           if k else f"file has no part number; {reason}"),
                "confidence": round(best.confidence, 3) if best else 0.5,
                "status": "pending approval",
            })
    return rows
