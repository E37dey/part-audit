"""Variety: how many different standard parts and part designs are in use, and how much each one is used - the
numbers a standardization (variety reduction) effort starts from. Everything here is counted from the scan; nothing
is estimated.

* Standard parts are grouped by kind (socket head cap screw, nut, bearing ...) and by specification (size, length,
  strength class, seal), with the part numbers that carry each specification.
* Designed parts are grouped into families by the main noun of their name in any language ("תושבת", "BRACKET" ->
  bracket). A duplicate group counts as one design; its usage and stock are the sum of its records.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from .explain import SPEC_KIND_HE
from .names import parse_name, pn_key

# the family of a designed part: the first of these words (in this order) found in its name
FAMILY_ORDER = ["plate", "collar", "bracket", "angle", "profile", "spacer", "bushing", "gear", "pulley", "roller",
                "flange", "block", "tube", "cover", "handle", "housing", "foot", "support", "hub", "sleeve", "ring",
                "disc", "cap", "frame", "beam", "rail", "guard", "panel", "body", "shaft", "rod", "pin", "key",
                "spring", "wheel"]
FAMILY_HE = {"plate": "פלטות", "collar": "טבעות נעילה", "bracket": "תושבות", "angle": "זוויתנים", "profile": "פרופילים",
             "spacer": "מרווחים", "bushing": "תותבים", "gear": "גלגלי שיניים", "pulley": "גלגלות", "roller": "גלילים",
             "flange": "אוגנים", "block": "בלוקים", "tube": "צינורות", "cover": "מכסים", "handle": "ידיות",
             "housing": "בתי מסב", "foot": "רגליות", "support": "תמיכות", "hub": "רכזות", "sleeve": "שרוולים",
             "ring": "טבעות", "disc": "דיסקות", "cap": "מכסים קטנים", "frame": "מסגרות", "beam": "קורות", "rail": "מסילות",
             "guard": "מגנים", "panel": "פאנלים", "body": "גופים", "shaft": "צירים", "rod": "מוטות", "pin": "פינים",
             "key": "שגמים", "spring": "קפיצים", "wheel": "גלגלים"}


def family_of(name: str) -> str:
    words = parse_name(name or "").words
    for w in FAMILY_ORDER:
        if w in words:
            return w
    return words[0] if words else ""


def _size(p: dict) -> tuple:
    b = p.get("bbox") or []
    return tuple(int(round(x)) for x in sorted(b, reverse=True)) if b else ()


def _erp(ps: list[dict], erp_use: Counter, currency: str) -> tuple[float, float | None, int]:
    """Stock, stock value (in the main currency only) and ERP BOM lines over the distinct ERP items of records."""
    seen, stock, value, lines = set(), 0.0, None, 0
    for p in ps:
        e = p.get("erp") or {}
        if not e.get("pn") or pn_key(e["pn"]) in seen:
            continue
        seen.add(pn_key(e["pn"]))
        stock += e.get("stock") or 0
        lines += erp_use.get(pn_key(e["pn"]), 0)
        if e.get("unit_cost") is not None and (e.get("currency") or currency) == currency:
            value = (value or 0.0) + (e.get("stock") or 0) * e["unit_cost"]
    return stock, (round(value, 2) if value is not None else None), lines


def _brief(p: dict) -> dict:
    return {k: p.get(k) for k in ("uid", "pn", "name", "source", "source_kind", "state_class", "material")}


def analyze(res: dict) -> dict:
    currency = res.get("summary", {}).get("currency") or "ILS"
    parts = [p for p in res["parts"] if p["kind"] == "part"]
    groups = {g["id"]: g for g in res.get("groups", [])}
    erp_use = Counter(pn_key(b["child"]) for b in res.get("erp_bom", []))

    # ---------------------------------------------------------------- standard parts: kind -> specification
    by_kind: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for p in parts:
        if p.get("spec_key"):
            kind, *rest = p["spec_key"].split("|")
            by_kind[kind]["|".join(rest)].append(p)
    kinds = []
    for kind, specs in by_kind.items():
        rows = []
        for key, ps in specs.items():
            size, length, grade, seal = (key.split("|") + ["", "", "", ""])[:4]
            stock, value, erp_lines = _erp(ps, erp_use, currency)
            pns = sorted({p["pn"] for p in ps if p["pn"]})
            rows.append({"spec": ps[0].get("spec") or key, "size": size, "length": length, "grade": grade, "seal": seal,
                         "records": len(ps), "pns": pns, "systems": sorted({p["source"] for p in ps}),
                         "used": sum(p.get("used_in") or 0 for p in ps) + erp_lines, "stock": stock, "value": value,
                         "group_ids": sorted({p["group_id"] for p in ps if p.get("group_id")}),
                         "records_list": [_brief(p) for p in ps]})
        rows.sort(key=lambda r: (_num(r["size"]), _num(r["length"]), r["grade"], r["seal"]))
        n_pns = sum(len(r["pns"]) for r in rows)
        kinds.append({"kind": kind, "kind_he": SPEC_KIND_HE.get(kind, kind), "specs": len(rows), "pns": n_pns,
                      "records": sum(r["records"] for r in rows), "extra_pns": n_pns - sum(1 for r in rows if r["pns"]),
                      "unused_specs": sum(1 for r in rows if not r["used"]), "used": sum(r["used"] for r in rows),
                      "value": round(sum(r["value"] or 0 for r in rows), 2), "rows": rows})
    kinds.sort(key=lambda k: (-k["specs"], k["kind"]))

    # ---------------------------------------------------------------- designed parts: family -> design
    fam: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for p in parts:
        if p.get("spec_key"):
            continue
        fam[family_of(p["name"]) or "?"][p.get("group_id") or p["uid"]].append(p)
    families = []
    for f, designs in fam.items():
        drows = []
        for key, ps in designs.items():
            g = groups.get(key)
            rep = next((p for p in ps if g and p["uid"] == g["master_uid"]), ps[0])
            stock, value, erp_lines = _erp(ps, erp_use, currency)
            drows.append({"key": key, "group_id": g["id"] if g else None, "name": rep["name"], "uid": rep["uid"],
                          "pns": sorted({p["pn"] for p in ps if p["pn"]}), "records": len(ps), "size": list(_size(rep)),
                          "volume_mm3": rep.get("volume_mm3"), "materials": sorted({p["material"] for p in ps if p.get("material")}),
                          "systems": sorted({p["source"] for p in ps}), "used": sum(p.get("used_in") or 0 for p in ps) + erp_lines,
                          "stock": stock, "value": value, "has_step": any(p.get("has_step") for p in ps)})
        drows.sort(key=lambda d: (d["size"] or [0], d["name"]))
        families.append({"family": f, "family_he": FAMILY_HE.get(f, "ללא שם תיאורי" if f == "?" else f),
                         "records": sum(d["records"] for d in drows),
                         "designs": len(drows), "sizes": len({tuple(d["size"]) for d in drows if d["size"]}),
                         "materials": len({p.get("material_key") or p["material"] for ps in designs.values() for p in ps
                                           if p.get("material")}),
                         "unused": sum(1 for d in drows if not d["used"]), "used": sum(d["used"] for d in drows),
                         "duplicated": sum(1 for d in drows if d["group_id"]), "rows": drows})
    families.sort(key=lambda x: (-x["designs"], x["family"]))
    std_specs = sum(k["specs"] for k in kinds)
    std_pns = sum(k["pns"] for k in kinds)
    return {"currency": currency,
            "summary": {"standard_kinds": len(kinds), "standard_specs": std_specs, "standard_pns": std_pns,
                        "standard_extra_pns": std_pns - sum(1 for k in kinds for r in k["rows"] if r["pns"]),
                        "standard_unused": sum(k["unused_specs"] for k in kinds),
                        "families": len(families), "designs": sum(f["designs"] for f in families),
                        "design_records": sum(f["records"] for f in families),
                        "designs_unused": sum(f["unused"] for f in families)},
            "standard": kinds, "families": families}


def _num(s: str) -> float:
    digits = "".join(ch for ch in str(s) if ch.isdigit() or ch == ".")
    try:
        return float(digits) if digits else 0.0
    except ValueError:
        return 0.0
