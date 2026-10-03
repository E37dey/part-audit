"""Hebrew explanations of audit findings, built from the structured evidence of each pair."""
from __future__ import annotations

import math

CATEGORY_HE = {
    "identical": "כפילות – אותה גיאומטריה",
    "standard_part": "אותו חלק תקני",
    "identical_attr_conflict": "גיאומטריה זהה, מפרט שונה",
    "near_identical": "כמעט זהים",
    "conflict": "אותו מק\"ט – גיאומטריה שונה",
    "conflict_unverified": "אותו מק\"ט בשתי רשומות",
    "name_similar": "שמות דומים",
    "mirror": "תמונת מראה (ימין/שמאל)",
}
CATEGORY_HINT_HE = {
    "identical": "מומלץ לאחד למק\"ט אחד (באישור מהנדס)",
    "standard_part": "מומלץ לאחד – אותו פריט קנייה",
    "identical_attr_conflict": "לא לאחד – פריטים שונים למרות צורה זהה",
    "near_identical": "לבדוק: אפשר לתקנן לחלק אחד?",
    "conflict": "לבדוק: איזו גרסה נכונה?",
    "conflict_unverified": "לבדוק ידנית",
    "name_similar": "לבדוק: חשד לכפילות לפי שם",
    "mirror": "חלקים שונים (ימין/שמאל) – לא לאחד",
}
SPEC_KIND_HE = {"shcs": "בורג אלן", "hex_screw": "בורג ראש משושה", "hex_bolt": "בורג משושה", "csk": "בורג שקוע",
                "set_screw": "בורג אל-ראש", "set_screw_cup": "בורג אל-ראש", "nut": "אום", "lock_nut": "אום נעילה",
                "washer": "דיסקית", "spring_washer": "דיסקית קפיצית", "pin": "פין", "key": "שגם", "bearing": "מסב",
                "linear_shaft": "ציר ליניארי", "shaft_support": "תושבת ציר", "shaft_collar": "טבעת נעילה",
                "leveling_foot": "רגלית מתכווננת", "conveyor_roller": "גלגלת מסוע"}


def pct(x: float | None) -> str:
    if x is None or x == math.inf:
        return "—"
    if x < 1e-6:
        return "פחות מ-0.0001%"
    if x < 0.001:
        return f"{100 * x:.3f}%"
    return f"{100 * x:.2f}%"


def mm(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{x:.2f} מ\"מ" if x < 10 else f"{x:.1f} מ\"מ"


def pair_reason_he(p, a=None, b=None) -> str:
    """Short Hebrew explanation of why a pair was flagged (p: scoring.Pair)."""
    bits: list[str] = []
    g = p.geo
    if p.l1 == "raw":
        bits.append("הקבצים זהים לחלוטין (בייט-לבייט)")
    elif p.l1 == "norm":
        bits.append("אותו מודל בדיוק – רק כותרת הקובץ, תאריך היצוא או השמות בקובץ שונים")
    if p.category == "standard_part":
        bits.append(f"אותו חלק תקני: {_spec_he(a)}" + (" (סוג אטימה/חוזק מצוין רק בצד אחד)" if p.spec_note else ""))
        if p.geo_relation == "near":
            bits.append("הבדלים קטנים בפרטי המודל (ספריות CAD שונות)")
        elif p.geo_relation == "unknown":
            bits.append("גיאומטריה לא הושוותה (אין קובץ STEP לאחד הצדדים)")
    if p.category == "identical_attr_conflict" and p.spec_relation == "spec_conflict":
        bits.append(f"צורה זהה אבל מפרט שונה ({p.spec_note}) – אלה פריטי קנייה שונים")
    if g is not None and not p.l1:
        if p.geo_relation in ("identical", "unit_scaled"):
            bits.append(f"גיאומטריה זהה (הפרש מרבי בתכונות {pct(g.max_rel)})")
            if g.relation == "unit_scaled":
                bits.append(f"אחד הקבצים מוגדל פי {max(g.scale, 1 / g.scale):.4g} – כנראה שגיאת יחידות (אינץ'/מ\"מ) ביצוא")
            if not g.topo_same:
                bits.append("חלוקת הפאות שונה (יוצא ממערכת CAD אחרת או שורטט מחדש)")
        elif p.geo_relation == "near":
            shp = g.shape or {}
            bits.append(f"גיאומטריה כמעט זהה: הפרש נפח {pct(g.d_volume)}, שטח פנים {pct(g.d_area)}"
                        + (", מספר פאות שונה" if not g.topo_same else ""))
        elif p.geo_relation == "mirror":
            bits.append("אותם ממדים, אבל תמונת מראה – גרסת ימין/שמאל")
        elif p.geo_relation == "different" and p.category in ("conflict", "name_similar"):
            bits.append("הגיאומטריה שונה")
    if p.category == "mirror" and p.geo_relation != "mirror":
        bits.insert(0, "השמות מציינים גרסת ימין ושמאל (ההבדל קטן מכדי שבדיקת הגיאומטריה תאשר תמונת מראה)")
    if p.category == "conflict":
        bits.insert(0, "אותו מק\"ט מופיע עם גיאומטריה שונה")
    if p.category == "conflict_unverified":
        bits.insert(0, "אותו מק\"ט מופיע בשתי רשומות; לא ניתן להשוות גיאומטריה")
    for issue in p.attr_issues or []:
        if issue.startswith("material differs"):
            bits.append("החומר שונה: " + issue.split("(", 1)[-1].rstrip(")"))
    if p.name is not None and p.category in ("name_similar", "identical", "near_identical", "standard_part"):
        if p.name.pn_relation == "same":
            bits.append("אותו מק\"ט")
        elif p.name.pn_relation == "core":
            bits.append("אותן ספרות מק\"ט בפורמט שונה")
        elif p.name.score >= 0.9:
            bits.append(f"השמות כמעט זהים (דמיון {p.name.score:.0%})")
        elif p.name.score >= 0.7:
            bits.append(f"השמות דומים (דמיון {p.name.score:.0%})")
    return "; ".join(dict.fromkeys(b for b in bits if b))


def _spec_he(it) -> str:
    sp = getattr(it, "spec", None)
    if sp is None:
        return ""
    kind = SPEC_KIND_HE.get(sp.kind, sp.kind)
    return f"{kind} {sp.label}"
