"""L5 - combine L1 (hashes), L2 (names), L3/L3b (geometry) into pair classes.

Every candidate pair gets one category:

* ``identical``          - same part (byte/normalized hash, or geometry match). Merge candidate,
                           unless ERP attributes (material) differ -> ``identical_attr_conflict``.
* ``near_identical``     - geometry within a few percent: alert only, never merged.
* ``conflict``           - same part number but different geometry.
* ``name_similar``       - names match strongly, geometry different (or not comparable).
* ``mirror``             - same size and properties but mirror images (left/right-hand parts):
                           reported for information, never merged.

Confidence values are heuristic evidence scores in [0, 1] (not calibrated
probabilities); the measured precision per category is in the Metrics sheet.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .names import NameIndex, NameMatch, NameParts, best_match, blocking_pairs

# unit conversion factors that explain an exact uniform scale between two files
UNIT_FACTORS = {
    25.4: "inch<->mm", 10.0: "cm<->mm", 1000.0: "m<->mm", 304.8: "ft<->mm", 2.54: "inch<->cm",
    100.0: "m<->cm", 12.0: "ft<->inch",
}


@dataclass
class Thresholds:
    geo_exact: float = 1e-6        # every global property within this -> identical even if topology differs
    geo_identical: float = 1e-4    # within this and same topology -> identical
    geo_near: float = 0.10         # within this -> near-identical candidate (tuned on dev)
    geo_split_type_tol: float = 2e-4  # per-type area shares equal within this -> faces only split differently
    near_max_face_ratio: float = 3.0     # topology guard for near-identical (no L3b)
    near_max_type_dist: float = 0.25     # surface-type area-fraction L1 distance guard
    unit_tol: float = 1e-4         # tolerance on the scale factor for unit mismatches
    name_similar: float = 0.90     # L2 score for a name match (tuned on dev)
    name_k0: int = 3               # L2: descriptions shared by more distinct PNs than this are discounted
    name_partial_factor: float = 0.85  # L2: one name gives a dimension/material, the other does not (tuned on dev)
    name_candidate: float = 0.70   # L2 score kept for context in reports
    shape_same_excess50: float = 2.0   # L3b: 'identical' by properties is downgraded above this median excess
    shape_near_excess50: float = 3.0   # L3b: near-identical needs median surface distance <= this x noise
    shape_near_p95: float = 0.10       # L3b: ... and p95 surface distance <= this share of the size
    mirror_ratio: float = 0.6          # L3b: improper/proper excess ratio below which -> mirror image
    skew_min: float = 0.004            # L3: smallest |surface skewness| needed to trust the chirality sign

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
    chirality: str = ""         # same | opposite | undetermined (from surface skewness)
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
    gm.chirality = chirality_relation(fa, fb, th)
    # faces split differently (other CAD system) but the same surfaces: per-type areas and the set of
    # underlying planes/cylinders/... unchanged. A micro fillet or hole adds a surface instead.
    ua, ub = fa.get("unique_surfaces"), fb.get("unique_surfaces")
    same_surfaces = ua is not None and ua == ub
    split_only = not topo_same and same_surfaces and gm.type_dist <= th.geo_split_type_tol
    if (max_rel <= th.geo_exact and (topo_same or same_surfaces or ua is None or ub is None)) or \
            (max_rel <= th.geo_identical and (topo_same or split_only)):
        gm.relation = "unit_scaled" if scale != 1.0 else "identical"
        if not solid_ok:
            gm.note = "open shell: compared by area and bounding box only"
        if not topo_same:
            gm.note = (gm.note + "; " if gm.note else "") + "same surfaces split into different faces (re-export)"
    elif max_rel <= th.geo_near and scale == 1.0:
        tess = max(fa.get("surf_area_frac", {}).get("other", 0), fb.get("surf_area_frac", {}).get("other", 0)) > 0.9
        if tess or (gm.face_ratio <= th.near_max_face_ratio and gm.type_dist <= th.near_max_type_dist):
            gm.relation = "near"
            if tess:
                gm.note = "one file has tessellated (mesh) faces: compared without surface types"
    return gm


def chirality_relation(fa: dict, fb: dict, th: Thresholds) -> str:
    """'opposite' if the two parts have opposite handedness (mirror images), judged from the sign of
    the product of the surface skewness along the principal axes; 'undetermined' when the part is
    (nearly) symmetric or its principal axes are ambiguous."""
    sa, sb, ea, eb = fa.get("surf_skew"), fb.get("surf_skew"), fa.get("surf_eig"), fb.get("surf_eig")
    if not (sa and sb and ea and eb):
        return "undetermined"
    for e in (ea, eb):
        l1, l2, l3 = (max(x, 1e-30) for x in e)
        if (l1 - l2) / l1 < 0.02 or (l2 - l3) / l2 < 0.02:
            return "undetermined"
    if min(abs(x) for x in sa) < th.skew_min or min(abs(x) for x in sb) < th.skew_min:
        return "undetermined"
    pa, pb = sa[0] * sa[1] * sa[2], sb[0] * sb[1] * sb[2]
    return "opposite" if pa * pb < 0 else "same"


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


_MATERIAL_CODES = {"al": "aluminum", "ss": "stainless", "aisi": "stainless", "st": "steel"}
_GRADED = ("aluminum", "stainless", "steel")


def material_key(text: str) -> str:
    """Canonical material: family (+ grade for aluminium/stainless/steel). 'AL 6061', 'Aluminium 6061' and
    'אלומיניום 6061' -> 'aluminum 6061'; 'PA6', 'Nylon PA6', 'ניילון' -> 'nylon'."""
    t = str(text).lower()
    t = re.sub(r"(?<![a-z])pa\s*-?\s*6{1,2}(?![0-9])", " nylon ", t)
    family, digits, other = "", [], []
    for tok in re.findall(r"[a-z]+|\d+|[\u05d0-\u05ea]+", t.replace("-", " ")):
        if tok.isdigit():
            digits.append(tok)
        elif tok in _MATERIAL_SYNONYMS:
            family = family or _MATERIAL_SYNONYMS[tok]
        elif tok in _MATERIAL_CODES:
            family = family or _MATERIAL_CODES[tok]
        elif tok != "en":
            other.append(tok)
    if family:
        return family + (" " + digits[0] if family in _GRADED and digits else "")
    return " ".join(sorted(set(other + digits)))


def item_material(it: Item) -> tuple[str, str]:
    """(material key, label) from the linked ERP row, else from a material named in the file/STEP name."""
    if it.erp and str(it.erp.get("material", "")).strip():
        m = str(it.erp["material"]).strip()
        return material_key(m), f"{m} (ERP)"
    for src in it.sources:
        if src.materials:
            m = " ".join(src.materials)
            return material_key(m), f"{m} (name)"
    return "", ""


def materials_conflict(ka: str, kb: str) -> bool:
    """Different family, or the same family with two different grades ('aluminum' vs 'aluminum 6061' is
    not a conflict: the grade is simply unspecified on one side)."""
    if not ka or not kb or ka == kb:
        return False
    fa, _, ga = ka.partition(" ")
    fb, _, gb = kb.partition(" ")
    if fa in _GRADED or fb in _GRADED:
        return fa != fb or (bool(ga) and bool(gb) and ga != gb)
    return True


def erp_attribute_conflicts(a: Item, b: Item) -> list[str]:
    (ka, la), (kb, lb) = item_material(a), item_material(b)
    if materials_conflict(ka, kb):
        return [f"material differs ({la} vs {lb})"]
    return []


def enforce_material_consistency(pairs: list["Pair"], items: dict[str, Item]) -> None:
    """If identical geometry is used by parts with different known materials, nothing in that cluster is
    merged unless both files are known to have the same material (a file without material information
    cannot be assigned to either part)."""
    uf = UnionFind()
    for p in pairs:
        if p.geo_relation in ("identical", "unit_scaled"):
            uf.union(p.a, p.b)
    mats: dict[str, dict[str, str]] = {}
    for x in list(uf.parent):
        k, label = item_material(items[x])
        if k:
            mats.setdefault(uf.find(x), {})[k] = label
    for p in pairs:
        if p.category != "identical":
            continue
        known = mats.get(uf.find(p.a), {})
        keys = sorted(known)
        if not any(materials_conflict(x, y) for i, x in enumerate(keys) for y in keys[i + 1:]):
            continue
        ka, kb = item_material(items[p.a])[0], item_material(items[p.b])[0]
        if ka and kb and not materials_conflict(ka, kb):
            continue
        p.category, p.merge_ok = "identical_attr_conflict", False
        p.reason += ("; the same geometry is used by parts with different materials ("
                     + ", ".join(sorted(known.values())) + ") - cannot tell which one applies; do not merge")


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
        if shp.get("mirror") or g.chirality == "opposite":
            p.geo_relation = "mirror"
        elif shp and shp.get("excess50", 0) > th.shape_same_excess50 and g.max_rel > th.geo_exact:
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
        elif shp and (shp.get("excess50", 0) > th.shape_near_excess50 or shp.get("p95_rel", 0) > th.shape_near_p95):
            p.geo_relation = "different"
            p.reason = (f"properties within {_fmt_pct(g.max_rel)} but shapes differ (median surface distance "
                        f"{shp['excess50']:.1f}x sampling noise, p95 {shp['p95_rel']:.1%} of size)")
        else:
            p.confidence = round(max(0.5, 0.9 - 0.4 * g.max_rel / th.geo_near), 3)
            bits = [f"geometry within {_fmt_pct(g.max_rel)} (volume {_fmt_pct(g.d_volume)}, area {_fmt_pct(g.d_area)}, "
                    f"inertia {_fmt_pct(g.d_inertia)}, bbox {_fmt_pct(g.d_bbox)})"]
            if shp and shp.get("p95_rel") is not None:
                bits.append(f"aligned surface distance p95 {shp['p95_rel']:.2%} of size "
                            f"(median {shp['excess50']:.1f}x sampling noise)")
            bits.append(f"faces {a.fp.get('n_faces')} vs {b.fp.get('n_faces')}")
            p.reason = "; ".join(bits) + " - small design change or different export; review"
    if p.geo_relation == "mirror":
        p.confidence = 0.8
        how = []
        if g is not None and g.chirality == "opposite":
            how.append("opposite handedness (surface skewness)")
        if g is not None and (g.shape or {}).get("mirror"):
            how.append("a reflection aligns the surfaces, no rotation does")
        p.reason = ("same size and properties but mirror image (left/right-hand version?) - different parts; "
                    + ", ".join(how))

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
        p.category = "mirror"
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
    index = NameIndex(name_items, {fid: it.pn_key for fid, it in items.items() if it.pn_key}, k0=th.name_k0,
                      partial_factor=th.name_partial_factor)
    for a, b in blocking_pairs(name_items):
        m = best_match(items[a].sources, items[b].sources, index)
        if m and m.score >= th.name_candidate:
            get(a, b).name = m

    out: list[Pair] = []
    ordered = sorted(cand.items())
    for (a, b), p in ordered:
        ia, ib = items[a], items[b]
        if p.name is None and ia.sources and ib.sources:
            p.name = best_match(ia.sources, ib.sources, index)
        if use_geometry and not p.l1:
            p.geo = compare_geometry(ia.fp, ib.fp, th, scales.get((a, b), 1.0))
    if shape_check is not None:
        jobs = [(items[a], items[b], p.geo) for (a, b), p in ordered if needs_shape_check(p.geo)]
        if hasattr(shape_check, "prefetch"):
            shape_check.prefetch(jobs)  # parallel, results are kept by the checker
        for ia, ib, geo in jobs:
            geo.shape = shape_check(ia, ib, geo)
    for (a, b), p in ordered:
        classify(p, items[a], items[b], th)
        if p.category:
            out.append(p)
    enforce_material_consistency(out, items)
    return out


def needs_shape_check(g: "GeoMatch | None") -> bool:
    """L3b only where it can change the outcome: near candidates (reject coincidences, find mirrors) and
    property-identical pairs whose handedness the skewness test could not settle."""
    if g is None:
        return False
    if g.relation == "near":
        return True
    return g.relation in ("identical", "unit_scaled") and g.chirality == "undetermined"


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
