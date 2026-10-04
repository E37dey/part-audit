"""Applying the engineer's decisions to the proposed mapping (nothing here writes to any external system)."""
from __future__ import annotations

import hashlib

from .names import pn_key


def _gid(prefix: str, members) -> str:
    return prefix + hashlib.sha1("|".join(sorted(members)).encode()).hexdigest()[:8]


def chosen_target(group: dict, decision: dict | None, parts: dict) -> str:
    """Member whose part number stays: the one the engineer approved (a group approval that names another member
    with a part number), else the proposed one. A target picked together with 'review' or 'reject' is remembered
    in the decision but changes nothing until the group is approved."""
    d = decision or {}
    uid = d.get("master_uid") or ""
    if d.get("decision") == "approve" and uid in group["members"] and (parts.get(uid) or {}).get("pn"):
        return uid
    return group["master_uid"]


def effective_mapping(res: dict, decisions: dict) -> list[dict]:
    """Mapping rows after the engineer's choices.

    A group approval may name another member as the target part number. Then every other part number of the
    group maps to that one instead of the proposed one. Those rows get new ids (the target is part of the id), so
    an approval given to "X -> A" is never carried over to "X -> B".
    """
    parts = {p["uid"]: p for p in res["parts"]}
    groups = {g["id"]: g for g in res["groups"]}
    out = []
    replaced = set()
    for gid, g in groups.items():
        d = decisions.get(f"group:{gid}") or {}
        target = chosen_target(g, d, parts)
        if target == g["master_uid"]:
            continue
        replaced.add(gid)
        t = parts[target]
        user = d.get("user") or ""
        seen = set()
        for u in g["members"]:
            r = parts[u]
            if not r["pn"] or pn_key(r["pn"]) == pn_key(t["pn"]) or pn_key(r["pn"]) in seen:
                continue
            seen.add(pn_key(r["pn"]))
            pair = next((p for p in res["pairs"] if {p["a"], p["b"]} == {u, target}), None)
            out.append({"id": _gid("M", [gid, r["pn"], "target:" + t["pn"]]), "group_id": gid, "old_pn": r["pn"],
                        "old_uid": u, "old_name": r["name"], "old_source": r["source"], "new_pn": t["pn"],
                        "new_uid": target, "new_name": t["name"],
                        "reason_he": pair["reason_he"] if pair else g["reason_he"],
                        "why_target_he": f"היעד שאושר על ידי {user}" if user else "היעד שאושר על ידי המאשר",
                        "confidence": pair["confidence"] if pair else g["confidence"],
                        "where_used": sum(1 for x in g["where_used"] if x["via"] == r["pn"]),
                        "erp_stock": (r.get("erp") or {}).get("stock"), "status": "ממתין לאישור",
                        "target_overridden": True})
    return [m for m in res["mapping"] if m["group_id"] not in replaced] + out


def master_pn(res_index: dict, group: dict, decision: dict | None) -> str:
    """Part number that stays in a group: the approved choice if there is one, else the proposal."""
    uid = chosen_target(group, decision, res_index)
    return res_index[uid]["pn"] if uid != group["master_uid"] else group["master_pn"]


def made_after(a: dict, b: dict) -> bool:
    """True if decision a was recorded after decision b. The store's ids give the exact order (the times only
    have whole seconds, so two clicks in the same second would tie); without ids, the times decide."""
    ia, ib = a.get("id"), b.get("id")
    if isinstance(ia, int) and isinstance(ib, int):
        return ia > ib
    return (a.get("created") or "") > (b.get("created") or "")


def main_currency(currencies: list[str], default: str | None = None) -> str | None:
    """The most common currency; ties go to the default currency, then alphabetical order (stable everywhere)."""
    if not currencies:
        return None
    return sorted(set(currencies), key=lambda c: (-currencies.count(c), c != default, c))[0]


def group_impact(group: dict, target_pn: str, target_erp_pn: str | None = None) -> dict:
    """What merging the group into target_pn changes: part numbers dropped, stock held on them (only ERP rows in
    the group's main currency are added up; no conversion), BOM lines that point at a dropped part number.
    target_erp_pn is the ERP item the target is linked to, when the ERP writes the number differently."""
    keys = {k for k in (pn_key(target_pn or ""), pn_key(target_erp_pn or "")) if k}
    dropped = [e for e in group["erp"] if pn_key(e["pn"]) not in keys]
    main = main_currency([e.get("currency") for e in group["erp"] if e.get("currency")])
    value = sum(e["value"] or 0 for e in dropped if not main or not e.get("currency") or e.get("currency") == main)
    return {"redundant_pns": max(0, len(group["pns"]) - 1), "redundant_stock_value": round(value, 2),
            "bom_lines_to_update": sum(1 for u in group["where_used"]
                                       if keys and u["via"] and pn_key(u["via"]) not in keys),
            "currency": main}


def row_decision(row: dict, decisions: dict) -> dict:
    """Decision that applies to one mapping row: its own, or its group's, whichever was made last (a later group
    rejection cancels earlier row approvals; a later row decision is an exception to the group's)."""
    own = decisions.get(f"mapping:{row['id']}")
    grp = decisions.get(f"group:{row['group_id']}")
    pick, inherited = own, False
    if grp and (not own or made_after(grp, own)):
        pick, inherited = grp, True
    if not pick:
        return {"decision": "", "decision_by": "", "decision_at": "", "decision_note": "", "inherited": False}
    return {"decision": pick["decision"], "decision_by": pick.get("user", ""), "decision_at": pick.get("created", ""),
            "decision_note": pick.get("note", ""), "inherited": inherited}
