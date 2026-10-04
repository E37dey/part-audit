"""Field discovery for a pilot on a real system (read-only).

A connector reads a small sample of records (no file downloads); this module lists every property it saw, with
how often it is filled and example values, and suggests which property fits each mapping field of the connector
(part number, description, material, mass, finish ...). The suggestion uses the property name (Hebrew and English
aliases) and whether the values look right (a material word, a number with a mass unit ...). Nothing is changed
until the user applies a suggestion.
"""
from __future__ import annotations

import re
from collections import Counter

from rapidfuzz import fuzz

from .connectors.base import mass_to_kg, to_float
from .names import parse_name
from .scoring import finish_key

# semantic targets of mapping fields: aliases of the property name, and a check of one value
_PN = re.compile(r"^(?=.*\d)[A-Za-z0-9א-ת][A-Za-z0-9א-ת\-_./ ]{2,30}$")


def _is_pn(v: str) -> bool:
    return bool(_PN.match(v)) and len(v.split()) <= 2


def _is_text(v: str) -> bool:
    return len(v) >= 4 and bool(re.search(r"[A-Za-zא-ת]{2}", v))


def _is_latin_text(v: str) -> bool:
    return _is_text(v) and not re.search(r"[א-ת]", v)


def _is_material(v: str) -> bool:
    return bool(parse_name(v).materials)


def _is_mass(v: str) -> bool:
    m = mass_to_kg(v)
    return m is not None and 0 < m < 100000


def _is_finish(v: str) -> bool:
    return bool(finish_key(v))


def _is_rev(v: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{1,2}|\d{1,3}|[A-Z]\d{1,2}|-", v.strip().upper()))


def _is_person(v: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-zא-ת][A-Za-zא-ת.' \-]{1,40}", v.strip())) and not _is_material(v)


def _is_make_buy(v: str) -> bool:
    return v.strip().lower() in {"make", "buy", "m", "b", "p", "r", "ייצור", "קנייה", "רכש", "purchased", "manufactured",
                                 "bom_make", "bom_buy", "e", "f"}


def _is_unit(v: str) -> bool:
    return v.strip().lower() in {"ea", "pc", "pcs", "st", "kg", "g", "m", "mm", "l", "set", "יח", "יח'", "יחידה", "ק\"ג",
                                 "מטר", "each", "unit", "units", "יחידות", "סט"}


def _is_number(v: str) -> bool:
    return to_float(v) is not None


TARGETS: dict[str, dict] = {
    "pn": {"he": "מק\"ט", "aliases": ["part number", "partnumber", "number", "pn", "item id", "item number", "itemcode",
                                     "partname", "material number", "מק\"ט", "מקט", "קוד פריט", "מספר פריט"], "check": _is_pn},
    "description": {"he": "תיאור", "aliases": ["description", "desc", "partdes", "object_desc", "itemname", "תיאור",
                                              "תאור", "תיאור פריט"], "check": _is_text},
    "title": {"he": "שם / כותרת", "aliases": ["title", "name", "object_name", "שם", "כותרת"], "check": _is_text},
    "material": {"he": "חומר", "aliases": ["material", "material name", "ptc_material_name", "mat", "raw material",
                                          "חומר", "חומר גלם"], "check": _is_material},
    "mass": {"he": "משקל", "aliases": ["mass", "weight", "pro_mp_mass", "sw-mass", "net weight", "gross weight", "משקל"],
             "check": _is_mass},
    "finish": {"he": "גימור", "aliases": ["finish", "coating", "surface", "surface treatment", "treatment", "גימור",
                                         "ציפוי", "טיפול שטח"], "check": _is_finish},
    "revision": {"he": "רוויזיה", "aliases": ["revision", "rev", "item_revision_id", "רוויזיה", "גרסה"], "check": _is_rev},
    "author": {"he": "מתכנן", "aliases": ["author", "designer", "drawn by", "drawnby", "created by", "owner", "מתכנן",
                                         "שרטט", "יוצר"], "check": _is_person},
    "make_buy": {"he": "ייצור / קנייה", "aliases": ["source", "make buy", "make/buy", "procurement", "make_buy",
                                                  "procurementmethod", "ייצור/קנייה", "ייצור קנייה", "רכש"], "check": _is_make_buy},
    "description_en": {"he": "תיאור באנגלית", "aliases": ["english description", "epartdes", "desc en", "description en",
                                                         "תיאור באנגלית", "תיאור אנגלית"], "check": _is_latin_text},
    "unit": {"he": "יחידת מידה", "aliases": ["unit", "uom", "unitname", "base unit", "inventoryuom", "יחידה", "יחידת מידה"],
             "check": _is_unit},
    "supplier": {"he": "ספק", "aliases": ["supplier", "vendor", "supname", "mainsupplier", "main supplier", "ספק",
                                         "ספק מועדף"], "check": _is_text},
    "price": {"he": "מחיר / עלות", "aliases": ["price", "cost", "lastprice", "last price", "standardprice", "avgprice",
                                              "עלות", "מחיר"], "check": _is_number},
}
# mapping field name (connector field) -> target: the part after the first '_' (var_material, prop_mass, f_unit ...)
_SUFFIX = {"number": "pn", "description": "description", "title": "title", "material": "material", "mass": "mass",
           "finish": "finish", "revision": "revision", "author": "author", "designer": "author", "source": "make_buy",
           "make_buy": "make_buy", "desc_en": "description_en", "unit": "unit", "supplier": "supplier", "price": "price",
           "field": "supplier"}


def target_of(field_name: str) -> str | None:
    if "_" not in field_name:
        return None
    return _SUFFIX.get(field_name.split("_", 1)[1])


def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-zא-ת]+", " ", str(s).lower().replace("״", '"')).strip()


def name_score(prop: str, aliases: list[str]) -> float:
    p = _norm(prop)
    if not p:
        return 0.0
    best = 0.0
    for a in aliases:
        a = _norm(a)
        if p == a or p.replace(" ", "") == a.replace(" ", ""):
            return 1.0
        if len(a) >= 3 and (a in p or (len(p) >= 3 and p in a)):
            best = max(best, 0.8)
        else:
            best = max(best, 0.7 * fuzz.ratio(p, a) / 100.0)
    return best


def _text(v) -> str:
    if isinstance(v, dict):                     # OData enums {Value, Display}
        v = v.get("Display") or v.get("Value") or ""
    if isinstance(v, (list, tuple)):
        v = ", ".join(str(x) for x in v if x not in (None, ""))
    return "" if v is None else str(v).strip()


def profile(rows: list[dict]) -> dict[str, dict]:
    """Every property seen in the sample: how often filled, distinct values, examples."""
    n = max(1, len(rows))
    out: dict[str, dict] = {}
    keys = []
    for r in rows:
        for k in r:
            if k not in out and not str(k).startswith("@odata"):
                out[k] = {"name": k, "values": []}
                keys.append(k)
    for k in keys:
        vals = [_text(r.get(k)) for r in rows]
        filled = [v for v in vals if v]
        cnt = Counter(filled)
        out[k].update({"fill": round(len(filled) / n, 3), "distinct": len(cnt),
                       "examples": [v[:60] for v, _ in cnt.most_common(4)], "values": filled})
    return out


def score(prop: dict, target: str) -> dict:
    t = TARGETS[target]
    ns = name_score(prop["name"], t["aliases"])
    vals = prop["values"]
    vs = (sum(1 for v in vals if t["check"](v)) / len(vals)) if vals else 0.0
    fill = prop["fill"]
    total = 0.5 * ns + 0.5 * vs * min(1.0, fill * 1.5)
    return {"property": prop["name"], "score": round(total, 3), "name_score": round(ns, 2), "value_score": round(vs, 2),
            "fill": fill}


def analyze(connector_cls, cfg: dict, sample: dict) -> dict:
    """Profile a sample and suggest a property for every mapping field of the connector."""
    rows = sample.get("rows") or []
    props = profile(rows)
    fields = []
    for f in connector_cls.fields:
        if f.group != "mapping" or f.type not in ("text",):
            continue
        tgt = target_of(f.name)
        if not tgt:
            continue
        current = str(cfg.get(f.name, f.default) or "")
        ranked = sorted((score(p, tgt) for p in props.values()), key=lambda s: -s["score"])
        cur = next((s for s in ranked if s["property"] == current), None)
        best = ranked[0] if ranked else None
        suggest = None
        if best and best["score"] >= 0.5 and best["property"] != current and \
                (cur is None or cur["fill"] == 0 or best["score"] > cur["score"] + 0.1):
            suggest = best
        fields.append({"field": f.name, "label": f.label, "target": tgt, "target_he": TARGETS[tgt]["he"],
                       "current": current, "current_found": cur is not None,
                       "current_fill": cur["fill"] if cur else 0.0,
                       "current_examples": props[current]["examples"] if current in props else [],
                       "suggested": suggest["property"] if suggest else "",
                       "suggested_fill": suggest["fill"] if suggest else None,
                       "suggested_examples": props[suggest["property"]]["examples"] if suggest else [],
                       "confidence": ("high" if suggest and suggest["score"] >= 0.75 else "medium") if suggest else "",
                       "alternatives": [s["property"] for s in ranked[1:4] if s["score"] >= 0.4]})
    listing = sorted(({k: v for k, v in p.items() if k != "values"} for p in props.values()),
                     key=lambda p: (-p["fill"], p["name"].lower()))
    warnings = []
    for f in fields:
        if not f["current_found"] and not f["suggested"]:
            warnings.append(f"לא נמצא מאפיין עבור \"{f['label']}\" ({f['current'] or 'ריק'}) – בדקו את השם בהגדרות המערכת")
    step = sample.get("step")
    if step and step.get("checked"):
        share = step["found"] / step["checked"]
        if share < 0.5:
            warnings.append(f"רק ל-{step['found']} מתוך {step['checked']} החלקים במדגם נמצא קובץ STEP – "
                            "ההשוואה הגיאומטרית תהיה חלקית. כדאי להפעיל המרה אוטומטית ל-STEP במערכת.")
    return {"records": len(rows), "properties": listing, "mapping": fields, "step": step,
            "notes": sample.get("notes") or [], "warnings": warnings, "api_calls": sample.get("api_calls")}
