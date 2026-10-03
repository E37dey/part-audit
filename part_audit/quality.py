"""Engineering data-quality checks across PDM/PLM records, geometry and the ERP.

Every check reports what it measured; thresholds are settings. Material densities are
handbook values (g/cm3) used only to compare a recorded mass with volume x density.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from .names import extract_part_numbers, parse_name, pn_core, pn_key
from .scoring import material_key, materials_conflict

DENSITY = {"aluminum": 2.70, "steel": 7.85, "stainless": 7.93, "brass": 8.47, "bronze": 8.75, "copper": 8.96,
           "pom": 1.41, "nylon": 1.14, "titanium": 4.43, "abs": 1.05, "pvc": 1.38, "pc": 1.20, "peek": 1.32}
SEVERITY_HE = {"high": "גבוהה", "medium": "בינונית", "low": "נמוכה", "info": "מידע"}
CHECK_HE = {
    "missing_pn": "חסר מק\"ט",
    "missing_description": "חסר תיאור",
    "missing_material": "חסר חומר",
    "mass_mismatch": "משקל רשום לא תואם לגיאומטריה",
    "pn_format": "פורמט מק\"ט חריג",
    "filename_pn_mismatch": "שם הקובץ לא תואם למק\"ט",
    "no_step": "אין קובץ STEP (לא נבדקה גיאומטריה)",
    "bom_state": "מכלול משוחרר עם רכיב לא משוחרר",
    "obsolete_in_use": "חלק מבוטל בשימוש במכלול פעיל",
    "unit_error": "קובץ STEP ביחידות שגויות",
    "released_not_in_erp": "חלק משוחרר שלא קיים ב-ERP",
    "erp_without_cad": "פריט ERP פעיל בלי מודל CAD",
    "erp_description_mismatch": "תיאור שונה בין PDM ל-ERP",
    "erp_material_mismatch": "חומר שונה בין PDM ל-ERP",
    "erp_status_mismatch": "סטטוס שונה בין PDM ל-ERP",
    "erp_bom_mismatch": "עץ מוצר שונה בין PDM ל-ERP",
}


def density_of(material: str) -> float | None:
    k = material_key(material) if material else ""
    return DENSITY.get(k.split(" ")[0]) if k else None


def decimals(text: str) -> int | None:
    m = re.search(r"\d+(?:[.,](\d+))?", text or "")
    if not m:
        return None
    return len(m.group(1)) if m.group(1) else 0


def _containment(a, b) -> float:
    """Share of the shorter description's canonical words found in the other (extra words do not count)."""
    wa, wb = set(a.words), set(b.words)
    if not wa or not wb:
        return 1.0
    return len(wa & wb) / min(len(wa), len(wb))


def pn_signature(pn: str) -> str:
    s = re.sub(r"[0-9]", "9", pn or "")
    s = re.sub(r"[A-Z]", "A", s)
    return re.sub(r"[a-z]", "a", s)


def issue(kind: str, severity: str, uids: list[str], message: str, **details) -> dict:
    return {"type": kind, "type_he": CHECK_HE.get(kind, kind), "severity": severity,
            "severity_he": SEVERITY_HE[severity], "uids": uids, "message": message, "details": details}


def record_checks(parts: list, fps: dict, settings) -> list[dict]:
    """Checks on single PDM/PLM records (parts are model.PartRecord; fps: uid -> fingerprint)."""
    out: list[dict] = []
    by_source: dict[str, list] = defaultdict(list)
    for r in parts:
        by_source[r.source_id].append(r)
    for src, recs in by_source.items():
        is_folder = recs[0].source_kind == "folder"
        sigs = Counter(pn_signature(r.pn) for r in recs if r.pn)
        total = sum(sigs.values())
        common = {s for s, n in sigs.items() if n / max(total, 1) >= 0.05}
        for r in recs:
            if not r.pn:
                if not is_folder:
                    out.append(issue("missing_pn", "high", [r.uid], "לרשומה אין מק\"ט", file=r.native_file))
            elif not is_folder and total >= 20 and pn_signature(r.pn) not in common:
                top = ", ".join(s for s, _ in sigs.most_common(3))
                out.append(issue("pn_format", "medium", [r.uid], f"המק\"ט '{r.pn}' לא תואם לפורמטים המקובלים במקור ({top})",
                                 pn=r.pn, signature=pn_signature(r.pn), usual=top))
            if not is_folder and not (r.name or r.description).strip():
                out.append(issue("missing_description", "high", [r.uid], "לרשומה אין תיאור/שם"))
            if not is_folder and r.kind == "part" and r.make_buy != "buy" and not r.material.strip():
                out.append(issue("missing_material", "medium", [r.uid], "לא מוגדר חומר לחלק ייצור"))
            if not is_folder and r.native_file and r.pn:
                stem = re.sub(r"\.[A-Za-z0-9]+$", "", r.native_file)
                cands = extract_part_numbers(stem)
                key, core = pn_key(r.pn), pn_core(r.pn)
                if cands and all(pn_key(c) != key and pn_core(c) != core and pn_key(c) not in key for c in cands):
                    out.append(issue("filename_pn_mismatch", "medium", [r.uid],
                                     f"בשם הקובץ מופיע מק\"ט {cands[0]} אבל בכרטיס {r.pn}", file=r.native_file, card_pn=r.pn))
            fp = fps.get(r.uid)
            dens = density_of(r.material)
            if fp and fp.get("closed") and fp.get("volume") and r.mass_kg and dens:
                computed = abs(fp["volume"]) * dens / 1e6
                dec = decimals(r.mass_text)
                abs_tol = 0.5 * 10 ** (-dec) if dec is not None else 0.0
                diff = abs(r.mass_kg - computed)
                if diff > max(settings.mass_tolerance * computed, abs_tol * 1.01):
                    out.append(issue("mass_mismatch", "medium", [r.uid],
                                     f"משקל רשום {r.mass_kg:g} ק\"ג, מחושב מהגיאומטריה {computed:.4g} ק\"ג "
                                     f"({(r.mass_kg - computed) / computed:+.0%})",
                                     recorded_kg=r.mass_kg, computed_kg=round(computed, 6),
                                     deviation=round((r.mass_kg - computed) / computed, 4), material=r.material,
                                     density=dens))
            if r.kind == "part" and not r.step_path and not is_folder:
                out.append(issue("no_step", "info", [r.uid], r.step_note or "אין קובץ STEP", note=r.step_note))
    return out


def bom_checks(records: list, children_of: dict[str, list], by_uid: dict) -> list[dict]:
    out = []
    for a in records:
        if a.kind != "assembly":
            continue
        for ch_uid, qty in children_of.get(a.uid, []):
            ch = by_uid.get(ch_uid)
            if ch is None:
                continue
            if a.state_class == "released" and ch.state_class in ("in_work", "review"):
                out.append(issue("bom_state", "high", [a.uid, ch.uid],
                                 f"המכלול {a.pn} משוחרר אבל הרכיב {ch.pn} במצב '{ch.state}'",
                                 assembly=a.pn, child=ch.pn, child_state=ch.state))
            if ch.state_class == "obsolete" and a.state_class not in ("obsolete",):
                out.append(issue("obsolete_in_use", "high" if a.state_class == "released" else "low", [a.uid, ch.uid],
                                 f"החלק {ch.pn} מבוטל אבל משמש במכלול {a.pn} ({a.state or 'ללא מצב'})",
                                 assembly=a.pn, child=ch.pn))
    return out


def erp_checks(parts: list, assemblies: list, erp_items: list, erp_bom: list, items: dict, children_of: dict,
               by_uid: dict, parents_of: dict) -> list[dict]:
    """PDM/PLM vs ERP consistency (items: uid -> scoring.Item with .erp linked)."""
    out: list[dict] = []
    erp_by_key = {pn_key(e.pn): e for e in erp_items}
    if not erp_items:
        return out
    cad_keys = {pn_key(r.pn) for r in parts + assemblies if r.pn}
    for r in parts + assemblies:
        if r.source_kind == "folder" or not r.pn:
            continue
        e = erp_by_key.get(pn_key(r.pn))
        if e is None:
            if r.state_class == "released":
                out.append(issue("released_not_in_erp", "high", [r.uid], f"{r.pn} משוחרר ב-PDM אבל אין לו פריט ב-ERP",
                                 pn=r.pn, state=r.state))
            continue
        if e.pn != r.pn:
            out.append(issue("pn_format", "low", [r.uid], f"המק\"ט נכתב אחרת ב-ERP: '{e.pn}' לעומת '{r.pn}'",
                             pn=r.pn, erp_pn=e.pn))
        if r.name and e.description:
            mine = [parse_name(t) for t in (r.name, r.description, r.name_en) if t]
            theirs = parse_name(e.description)
            sim = max((_containment(x, theirs) for x in mine), default=1.0)
            same_numbers = any(sorted(x.numbers) == sorted(theirs.numbers) and x.numbers for x in mine)
            if sim < 0.5 and not same_numbers:
                out.append(issue("erp_description_mismatch", "medium", [r.uid],
                                 f"PDM: '{r.name}' | ERP: '{e.description}'", pdm=r.name, erp=e.description,
                                 similarity=round(sim, 3)))
        erp_mats = parse_name(e.description).materials
        if r.material and erp_mats:
            ka, kb = material_key(r.material), material_key(" ".join(erp_mats))
            if materials_conflict(ka, kb):
                out.append(issue("erp_material_mismatch", "high", [r.uid],
                                 f"חומר ב-PDM: {r.material} | תיאור ה-ERP: '{e.description}'",
                                 pdm=r.material, erp=" ".join(erp_mats)))
        if r.state_class == "obsolete" and e.active and e.stock_total > 0:
            out.append(issue("erp_status_mismatch", "medium", [r.uid],
                             f"{r.pn} מבוטל ב-PDM אבל פעיל ב-ERP עם מלאי {e.stock_total:g}", stock=e.stock_total))
        if not e.active and r.state_class == "released":
            users = [by_uid[p] for p, _ in parents_of.get(r.uid, []) if p in by_uid and by_uid[p].state_class == "released"]
            if users:
                out.append(issue("erp_status_mismatch", "high", [r.uid] + [u.uid for u in users],
                                 f"{r.pn} לא פעיל ב-ERP אבל משמש ב-{len(users)} מכלולים משוחררים",
                                 assemblies=[u.pn for u in users]))
    for e in erp_items:
        if e.active and pn_key(e.pn) not in cad_keys:
            out.append(issue("erp_without_cad", "low" if e.make_buy == "buy" else "medium", [],
                             f"{e.pn} – '{e.description}' פעיל ב-ERP אך לא נמצא באף מערכת PDM/PLM",
                             pn=e.pn, description=e.description, stock=e.stock_total, make_buy=e.make_buy))
    erp_children: dict[str, dict[str, float]] = defaultdict(dict)
    for b in erp_bom:
        erp_children[pn_key(b.parent)][pn_key(b.child)] = erp_children[pn_key(b.parent)].get(pn_key(b.child), 0) + b.qty
    for a in assemblies:
        if not a.pn or pn_key(a.pn) not in erp_children:
            continue
        pdm = defaultdict(float)
        for ch_uid, qty in children_of.get(a.uid, []):
            ch = by_uid.get(ch_uid)
            if ch is not None and ch.pn:
                pdm[pn_key(ch.pn)] += qty
        erp = erp_children[pn_key(a.pn)]
        diffs = []
        for k in sorted(set(pdm) | set(erp)):
            if abs(pdm.get(k, 0) - erp.get(k, 0)) > 1e-9:
                diffs.append({"child": k, "pdm_qty": pdm.get(k, 0), "erp_qty": erp.get(k, 0)})
        if diffs:
            out.append(issue("erp_bom_mismatch", "medium", [a.uid],
                             f"עץ המוצר של {a.pn} שונה בין PDM ל-ERP ב-{len(diffs)} שורות", assembly=a.pn, diffs=diffs))
    return out
