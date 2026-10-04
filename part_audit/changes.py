"""What changed between two scans: new and resolved duplicate groups, records added / removed / changed, findings
that appeared or were fixed, and the change in every summary number. Works on two finished results (result.json);
nothing here reads from any system."""
from __future__ import annotations

import math

# summary numbers compared between two scans (money only when both scans count it in the same currency)
SUMMARY_KEYS = ["parts", "assemblies", "with_step", "erp_items", "erp_linked", "groups", "groups_cross_source",
                "parts_in_groups", "redundant_pns", "redundant_stock_value", "bom_lines_to_update", "near_pairs",
                "mirror_pairs", "spec_conflicts", "pn_conflicts", "name_findings", "quality_issues", "quality_high",
                "erp_issues"]
# record fields whose change is reported (geometry by its computed volume)
FIELDS_HE = {"pn": "מק\"ט", "name": "שם", "revision": "רוויזיה", "state": "מצב", "material": "חומר", "finish": "גימור",
             "mass_kg": "משקל רשום", "make_buy": "ייצור/קנייה", "has_step": "קובץ STEP", "volume_mm3": "נפח המודל",
             "erp_pn": "פריט ERP מקושר"}
MAX_ROWS = 200


def _part_brief(p: dict) -> dict:
    return {k: p.get(k) for k in ("uid", "pn", "name", "source", "source_kind", "kind", "state", "state_class",
                                  "created", "modified", "has_step")}


def _value(p: dict, field: str):
    if field == "erp_pn":
        return (p.get("erp") or {}).get("pn")
    return p.get(field)


def _differs(field: str, a, b) -> bool:
    if field in ("volume_mm3", "mass_kg"):
        if a is None or b is None:
            return (a is None) != (b is None)
        return abs(a - b) > 1e-6 * max(abs(a), abs(b), 1e-9)
    return (a or "") != (b or "") if not isinstance(a, bool) else a != b


def _group_brief(g: dict, idx: dict) -> dict:
    return {"id": g["id"], "name": g.get("name") or "", "category": g["category"], "pns": g["pns"],
            "sources": g["sources"], "master_pn": g.get("master_pn"), "members": len(g["members"]),
            "redundant_pns": g.get("redundant_pns", 0), "redundant_stock_value": g.get("redundant_stock_value", 0),
            "currency": g.get("currency"), "spec": g.get("spec") or ""}


def _issue_key(q: dict) -> tuple:
    """The same finding in two scans: its type and the records it is about (its message may carry numbers that move)."""
    return (q.get("type"), tuple(sorted(q.get("uids") or [])))


def unavailable_sources(res: dict) -> set[str]:
    """Sources that could not be read in a scan (an error and nothing read): their records are not 'removed'."""
    return {s["id"] for s in res.get("sources", [])
            if s.get("errors") and not (s.get("stats", {}).get("records") or s.get("stats", {}).get("erp_items"))}


def compare_runs(old: dict, new: dict) -> dict:
    """old, new: two scan results (the earlier one first). A source that could not be read in the new scan is left
    out: its records are counted as 'not read', never as removed, and its groups and findings as unknown."""
    old_parts = {p["uid"]: p for p in old["parts"]}
    new_parts = {p["uid"]: p for p in new["parts"]}
    unread = unavailable_sources(new)

    def not_read(u: str) -> bool:
        return u not in new_parts and u in old_parts and old_parts[u].get("source_id") in unread
    # ---------------------------------------------------------------- records
    added = [_part_brief(new_parts[u]) for u in new_parts if u not in old_parts]
    removed = [_part_brief(old_parts[u]) for u in old_parts if u not in new_parts and not not_read(u)]
    n_not_read = sum(1 for u in old_parts if not_read(u))
    changed = []
    for u, p in new_parts.items():
        q = old_parts.get(u)
        if q is None:
            continue
        diffs = [{"field": f, "field_he": he, "before": _value(q, f), "after": _value(p, f)}
                 for f, he in FIELDS_HE.items() if _differs(f, _value(q, f), _value(p, f))]
        if diffs:
            changed.append(dict(_part_brief(p), changes=diffs))
    # ---------------------------------------------------------------- duplicate groups
    old_of = {u: g["id"] for g in old["groups"] for u in g["members"]}
    old_groups = {g["id"]: g for g in old["groups"]}
    touched_old: set[str] = set()
    g_new, g_grown, g_shrunk, g_same = [], [], [], 0
    for g in new["groups"]:
        overlap = {old_of[u] for u in g["members"] if u in old_of}
        touched_old |= overlap
        before = set().union(*(old_groups[o]["members"] for o in overlap)) if overlap else set()
        joined = [u for u in g["members"] if u not in before]
        left = sorted(u for u in before - set(g["members"]) if not not_read(u))
        row = dict(_group_brief(g, new_parts),
                   joined=[dict(_part_brief(new_parts[u]), new_record=u not in old_parts) for u in joined],
                   left=[dict(_part_brief(old_parts[u]), removed=u not in new_parts) for u in left])
        if not overlap:
            g_new.append(row)
        elif joined:
            g_grown.append(row)
        elif left:
            g_shrunk.append(row)
        else:
            g_same += 1
    resolved, g_unknown = [], 0
    for gid, g in old_groups.items():
        if gid in touched_old:
            continue
        if any(not_read(u) for u in g["members"]):
            g_unknown += 1
            continue
        members = [dict(_part_brief(old_parts[u]), removed=u not in new_parts) for u in g["members"]]
        resolved.append(dict(_group_brief(g, old_parts), members_then=members,
                             how="records_removed" if any(m["removed"] for m in members) else "no_longer_matching"))
    # ---------------------------------------------------------------- findings
    findings = {}
    for kind in ("quality", "erp_issues", "names"):
        a = {_issue_key(q): q for q in old.get(kind, []) if q.get("severity", "") != "info"}
        b = {_issue_key(q): q for q in new.get(kind, []) if q.get("severity", "") != "info"}
        findings[kind] = {"new": [_issue_row(b[k], new_parts) for k in b if k not in a],
                          "resolved": [_issue_row(a[k], old_parts) for k in a if k not in b
                                       and not any(not_read(u) for u in a[k].get("uids") or [])]}
    near_cats = ("near_identical", "mirror", "identical_attr_conflict", "conflict")
    pa = {(p["a"], p["b"], p["category"]): p for p in old["pairs"] if p["category"] in near_cats}
    pb = {(p["a"], p["b"], p["category"]): p for p in new["pairs"] if p["category"] in near_cats}
    findings["pairs"] = {"new": [_pair_row(pb[k], new_parts) for k in pb if k not in pa],
                         "resolved": [_pair_row(pa[k], old_parts) for k in pa if k not in pb
                                      and not not_read(pa[k]["a"]) and not not_read(pa[k]["b"])]}
    # ---------------------------------------------------------------- summary numbers
    so, sn = old.get("summary", {}), new.get("summary", {})
    delta = {}
    for k in SUMMARY_KEYS:
        a, b = so.get(k), sn.get(k)
        if k == "redundant_stock_value" and so.get("currency") != sn.get("currency"):
            a = None                       # different currencies are never subtracted
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not (isinstance(a, float) and math.isnan(a)):
            delta[k] = {"before": a, "after": b, "delta": round(b - a, 2)}
        else:
            delta[k] = {"before": a, "after": b, "delta": None}
    out = {
        "from": {"run_id": old.get("run_id"), "created": old.get("created")},
        "to": {"run_id": new.get("run_id"), "created": new.get("created")},
        "currency": sn.get("currency"),
        "summary": delta,
        "groups": {"new": g_new, "grown": g_grown, "shrunk": g_shrunk, "resolved": resolved, "unchanged": g_same,
                   "unknown": g_unknown},
        "records": {"added": added[:MAX_ROWS], "removed": removed[:MAX_ROWS], "changed": changed[:MAX_ROWS],
                    "n_added": len(added), "n_removed": len(removed), "n_changed": len(changed),
                    "n_not_read": n_not_read},
        "unread_sources": sorted(s["name"] for s in new.get("sources", []) if s["id"] in unread),
        "findings": {k: {"new": v["new"][:MAX_ROWS], "resolved": v["resolved"][:MAX_ROWS], "n_new": len(v["new"]),
                         "n_resolved": len(v["resolved"])} for k, v in findings.items()},
    }
    out["headline"] = headline(out)
    out["alert"] = bool(g_new or g_grown or findings["quality"]["new"] or findings["erp_issues"]["new"])
    return out


def _issue_row(q: dict, parts: dict) -> dict:
    return {"type": q.get("type"), "type_he": q.get("type_he"), "severity": q.get("severity", ""),
            "message": q.get("message", "") or " / ".join(q.get("names") or []), "pn": q.get("pn", ""),
            "parts": [_part_brief(parts[u]) for u in q.get("uids", []) if u in parts]}


def _pair_row(p: dict, parts: dict) -> dict:
    return {"id": p["id"], "category": p["category"], "category_he": p.get("category_he", p["category"]),
            "confidence": p.get("confidence"), "reason_he": p.get("reason_he", ""),
            "a": _part_brief(parts[p["a"]]) if p["a"] in parts else None,
            "b": _part_brief(parts[p["b"]]) if p["b"] in parts else None}


def _n(n: int, one: str, many: str) -> str:
    return one if n == 1 else f"{n} {many}"


def headline(c: dict) -> str:
    """One or two sentences in plain Hebrew: the change that matters most first."""
    text = _headline(c)
    if c.get("unread_sources"):
        names = ", ".join(c["unread_sources"])
        text += f" שימו לב: {names} לא {'היה זמין' if len(c['unread_sources']) == 1 else 'היו זמינים'} בסריקה הזו, ולכן השינויים שם לא נספרו."
    return text


def _headline(c: dict) -> str:
    g, f, r = c["groups"], c["findings"], c["records"]
    bits = []
    if g["new"]:
        bits.append(_n(len(g["new"]), "כפילות חדשה אחת", "כפילויות חדשות"))
    if g["grown"]:
        bits.append(_n(len(g["grown"]), "קבוצת כפילות אחת קיבלה רשומה נוספת", "קבוצות כפילות קיבלו רשומות נוספות"))
    if g["resolved"]:
        bits.append(_n(len(g["resolved"]), "קבוצת כפילות אחת נפתרה", "קבוצות כפילות נפתרו"))
    nq = f["quality"]["n_new"] + f["erp_issues"]["n_new"]
    rq = f["quality"]["n_resolved"] + f["erp_issues"]["n_resolved"]
    if nq:
        bits.append(_n(nq, "ממצא נתונים חדש אחד", "ממצאי נתונים חדשים"))
    if rq:
        bits.append(_n(rq, "ממצא נתונים אחד תוקן", "ממצאי נתונים תוקנו"))
    if not bits:
        if r["n_added"] or r["n_removed"] or r["n_changed"]:
            return (f"אין כפילויות או ממצאים חדשים. ברשומות: {r['n_added']} נוספו, {r['n_removed']} הוסרו, "
                    f"{r['n_changed']} השתנו.")
        return "לא השתנה דבר מאז הסריקה הקודמת."
    if len(bits) == 1:
        return bits[0] + "."
    last = bits[-1]
    return ", ".join(bits[:-1]) + (" ו-" if last[:1].isdigit() else " ו") + last + "."
