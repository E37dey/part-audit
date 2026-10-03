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
