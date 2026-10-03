"""Applying the engineer's decisions to the proposed mapping (nothing here writes to any external system)."""
from __future__ import annotations

import hashlib

from .names import pn_key


def _gid(prefix: str, members) -> str:
    return prefix + hashlib.sha1("|".join(sorted(members)).encode()).hexdigest()[:8]


def effective_mapping(res: dict, decisions: dict) -> list[dict]:
    """Mapping rows after the engineer's choices.

    A group decision may name another member as the target part number. Then every other part number of the
    group maps to that one instead of the proposed one. Those rows get new ids (the target is part of the id), so
    an approval given to "X -> A" is never carried over to "X -> B".
    """
    parts = {p["uid"]: p for p in res["parts"]}
    groups = {g["id"]: g for g in res["groups"]}
    out = []
    replaced = set()
    for gid, g in groups.items():
        d = decisions.get(f"group:{gid}") or {}
        target = d.get("master_uid") or ""
        if not target or target == g["master_uid"] or target not in g["members"] or not parts[target]["pn"]:
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
                        "why_target_he": f"נבחר על ידי {user}" if user else "נבחר על ידי המאשר",
                        "confidence": pair["confidence"] if pair else g["confidence"],
                        "where_used": sum(1 for x in g["where_used"] if x["via"] == r["pn"]),
                        "erp_stock": (r.get("erp") or {}).get("stock"), "status": "ממתין לאישור",
                        "target_overridden": True})
    return [m for m in res["mapping"] if m["group_id"] not in replaced] + out


def master_pn(res_index: dict, group: dict, decision: dict | None) -> str:
    """Part number that stays in a group: the engineer's choice if one was made, else the proposal."""
    uid = (decision or {}).get("master_uid") or ""
    if uid and uid in group["members"] and res_index.get(uid, {}).get("pn"):
        return res_index[uid]["pn"]
    return group["master_pn"]


def group_impact(group: dict, target_pn: str) -> dict:
    """What merging the group into target_pn changes: part numbers dropped, stock held on them (only ERP rows in
    the group's main currency are added up; no conversion), BOM lines that point at a dropped part number."""
    key = pn_key(target_pn or "")
    dropped = [e for e in group["erp"] if pn_key(e["pn"]) != key]
    currencies = [e.get("currency") for e in group["erp"] if e.get("currency")]
    main = max(set(currencies), key=currencies.count) if currencies else None
    value = sum(e["value"] or 0 for e in dropped if not main or not e.get("currency") or e.get("currency") == main)
    return {"redundant_pns": max(0, len(group["pns"]) - 1), "redundant_stock_value": round(value, 2),
            "bom_lines_to_update": sum(1 for u in group["where_used"] if key and u["via"] and pn_key(u["via"]) != key),
            "currency": main}


def row_decision(row: dict, decisions: dict) -> dict:
    """Decision that applies to one mapping row: its own, or its group's, whichever was made last (a later group
    rejection cancels earlier row approvals; a later row decision is an exception to the group's)."""
    own = decisions.get(f"mapping:{row['id']}")
    grp = decisions.get(f"group:{row['group_id']}")
    pick, inherited = own, False
    if grp and (not own or (grp.get("created") or "") > (own.get("created") or "")):
        pick, inherited = grp, True
    if not pick:
        return {"decision": "", "decision_by": "", "decision_at": "", "decision_note": "", "inherited": False}
    return {"decision": pick["decision"], "decision_by": pick.get("user", ""), "decision_at": pick.get("created", ""),
            "decision_note": pick.get("note", ""), "inherited": inherited}
