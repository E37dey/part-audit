"""Configuration control: what every product is made of, and what in it needs attention.

From one scan: every top-level product (an assembly that no other assembly uses) with its BOM tree from the
PDM / PLM, each item marked with what was found on it - another part number for the same part (a duplicate group,
with the part number that stays), near-identical parts, data issues, a lifecycle problem (an unreleased item in a
released assembly, an obsolete item still in use), a mismatch with the ERP - and the assembly's BOM compared line by
line with the ERP's BOM. Nothing here is estimated: every flag is a finding of the scan or a decision on record.
"""
from __future__ import annotations

from collections import defaultdict

from .decisions import chosen_target
from .names import pn_key

# what kind of attention a finding needs, in the order the screen lists them
FLAG_ORDER = ("duplicate", "state", "erp", "quality", "near")
FLAG_HE = {"duplicate": "כפילות", "state": "מצב / שחרור", "erp": "פער מול ERP", "quality": "בעיית נתונים",
           "near": "חלקים כמעט זהים"}
STATE_TYPES = {"bom_state", "obsolete_in_use"}
MAX_DEPTH = 12


def _parents(res: dict) -> dict[str, list[tuple[str, float]]]:
    out: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for parent, lines in res.get("bom", {}).items():
        for line in lines:
            out[line["child"]].append((parent, line.get("qty") or 0))
    return out


def products(res: dict) -> list[str]:
    """Top-level assemblies: in the BOM data as a parent, used by no other assembly."""
    idx = {p["uid"]: p for p in res["parts"]}
    used = _parents(res)
    return [u for u in res.get("bom", {}) if u in idx and not used.get(u)]


class Findings:
    """Everything the scan found on each record, and the decisions on record, ready to flag a BOM item."""

    def __init__(self, res: dict, decisions: dict | None = None):
        self.res, self.dec = res, decisions or {}
        self.idx = {p["uid"]: p for p in res["parts"]}
        self.groups = {g["id"]: g for g in res.get("groups", [])}
        self.issues: dict[str, list[dict]] = defaultdict(list)
        for q in res.get("quality", []) + res.get("erp_issues", []):
            for u in q.get("uids") or []:
                self.issues[u].append(q)
        self.near: dict[str, int] = defaultdict(int)
        for pr in res.get("pairs", []):
            if pr.get("category") in ("near_identical", "mirror", "identical_attr_conflict"):
                self.near[pr["a"]] += 1
                self.near[pr["b"]] += 1
        self.erp_bom: dict[str, list[dict]] = defaultdict(list)
        for b in res.get("erp_bom", []):
            self.erp_bom[pn_key(b["parent"])].append(b)
        self.erp_issue_types = {q["type"] for q in res.get("erp_issues", [])}

    def flags(self, uid: str) -> list[dict]:
        p = self.idx[uid]
        out = []
        g = self.groups.get(p.get("group_id") or "")
        if g:
            d = self.dec.get(f"group:{g['id']}") or {}
            t = self.idx[chosen_target(g, d, self.idx)]
            others = [x for x in g["pns"] if pn_key(x) != pn_key(p["pn"] or "")]
            approved = d.get("decision") == "approve"
            stays = pn_key(t["pn"] or "") == pn_key(p["pn"] or "")
            if stays:
                text = f"זה המק\"ט שנשאר. אותו חלק רשום גם בתור {', '.join(others[:4])}{'…' if len(others) > 4 else ''}."
            else:
                text = (f"אותו חלק רשום גם בתור {', '.join(others[:4])}{'…' if len(others) > 4 else ''}. "
                        + (f"אושר: {p['pn']} יוחלף ב-{t['pn']}." if approved else f"מוצע להחליף את {p['pn']} ב-{t['pn']}."))
            out.append({"type": "duplicate", "severity": "info" if stays else ("medium" if approved else "high"),
                        "title": "זה המק\"ט שנשאר" if stays else ("יוחלף – אושר" if approved else "כפילות – ממתין להחלטה"),
                        "text": text, "group_id": g["id"], "target_pn": t["pn"], "target_uid": t["uid"], "stays": stays,
                        "decision": d.get("decision") or "", "others": others})
        for q in self.issues.get(uid, []):
            if q.get("severity") == "info":
                continue
            kind = "state" if q["type"] in STATE_TYPES else ("erp" if q["type"] in self.erp_issue_types
                                                            or q["type"].startswith("erp_") else "quality")
            out.append({"type": kind, "severity": q.get("severity", "low"), "title": q.get("type_he") or q["type"],
                        "text": q.get("message") or "", "issue_id": q.get("id"), "issue_type": q["type"]})
        if self.near.get(uid):
            n = self.near[uid]
            out.append({"type": "near", "severity": "low", "title": "חלקים כמעט זהים",
                        "text": f"יש {'חלק אחד' if n == 1 else f'{n} חלקים'} בצורה כמעט זהה – אולי אפשר להשתמש בחלק אחד.",
                        "count": n})
        rank = {k: i for i, k in enumerate(FLAG_ORDER)}
        return sorted(out, key=lambda f: (rank.get(f["type"], 9), {"high": 0, "medium": 1, "low": 2}.get(f["severity"], 3)))

    def node(self, uid: str, qty: float | None = None) -> dict:
        p = self.idx[uid]
        e = p.get("erp") or {}
        return {"uid": uid, "pn": p["pn"], "name": p["name"], "kind": p["kind"], "qty": qty, "revision": p.get("revision"),
                "state": p.get("state"), "state_class": p.get("state_class"), "source": p["source"],
                "source_kind": p["source_kind"], "spec": p.get("spec"), "standard": bool(p.get("spec_key")),
                "make_buy": p.get("make_buy"), "has_step": bool(p.get("has_step")), "material": p.get("material"),
                "erp": {k: e.get(k) for k in ("pn", "description", "stock", "unit_cost", "currency", "status", "uom")} if e else None,
                "flags": self.flags(uid)}

    def erp_compare(self, uid: str) -> dict:
        """The assembly's BOM in the PDM / PLM next to its BOM in the ERP, line by line (by part number)."""
        p = self.idx[uid]
        parent_key = pn_key((p.get("erp") or {}).get("pn") or p["pn"] or "")
        erp_lines = self.erp_bom.get(parent_key, []) if parent_key else []
        rows: dict[str, dict] = {}
        for c in self.res.get("bom", {}).get(uid, []):
            ch = self.idx.get(c["child"])
            if not ch:
                continue
            key = pn_key((ch.get("erp") or {}).get("pn") or ch["pn"] or "") or c["child"]
            r = rows.setdefault(key, {"pn": ch["pn"], "erp_pn": None, "name": ch["name"], "uid": ch["uid"], "pdm_qty": 0.0,
                                      "erp_qty": None})
            r["pdm_qty"] += c.get("qty") or 0
        for b in erp_lines:
            key = pn_key(b["child"])
            r = rows.setdefault(key, {"pn": None, "erp_pn": b["child"], "name": self._erp_name(b["child"]), "uid": None,
                                      "pdm_qty": None, "erp_qty": 0.0})
            r["erp_pn"] = b["child"]
            r["erp_qty"] = (r["erp_qty"] or 0) + (b.get("qty") or 0)
        out = []
        for r in rows.values():
            if r["pdm_qty"] is None:
                r["status"] = "erp_only"
            elif r["erp_qty"] is None:
                r["status"] = "pdm_only"
            else:
                r["status"] = "same" if abs(r["pdm_qty"] - r["erp_qty"]) < 1e-9 else "qty"
            out.append(r)
        order = {"qty": 0, "pdm_only": 1, "erp_only": 2, "same": 3}
        out.sort(key=lambda r: (order[r["status"]], r["pn"] or r["erp_pn"] or ""))
        return {"has_erp_bom": bool(erp_lines), "erp_parent": (p.get("erp") or {}).get("pn"), "rows": out,
                "differences": sum(1 for r in out if r["status"] != "same") if erp_lines else None}

    def _erp_name(self, erp_pn: str) -> str:
        k = pn_key(erp_pn)
        for x in self.idx.values():
            e = x.get("erp") or {}
            if e.get("pn") and pn_key(e["pn"]) == k:
                return e.get("description") or x["name"]
        return ""

    def tree(self, uid: str, qty: float | None = None, path: tuple = ()) -> dict:
        n = self.node(uid, qty)
        kids = self.res.get("bom", {}).get(uid, [])
        if kids and len(path) < MAX_DEPTH and uid not in path:
            n["children"] = [self.tree(c["child"], c.get("qty"), path + (uid,)) for c in kids if c["child"] in self.idx]
            n["erp_bom"] = self.erp_compare(uid)
        return n


def _walk(n: dict):
    yield n
    for c in n.get("children", []):
        yield from _walk(c)


def health(tree: dict) -> dict:
    """Counted over the distinct items of the tree (an item used twice counts once)."""
    seen: dict[str, dict] = {}
    lines = 0
    for n in _walk(tree):
        lines += 1
        seen.setdefault(n["uid"], n)
    by = {k: 0 for k in FLAG_ORDER}
    attention = 0
    for n in seen.values():
        kinds = {f["type"] for f in n["flags"] if not (f["type"] == "duplicate" and f.get("stays"))}
        for k in kinds:
            by[k] += 1
        attention += 1 if kinds else 0
    asm = [n for n in seen.values() if n.get("erp_bom")]
    erp_diff = sum(1 for n in asm if n["erp_bom"]["has_erp_bom"] and n["erp_bom"]["differences"])
    no_erp_bom = sum(1 for n in asm if not n["erp_bom"]["has_erp_bom"])
    return {"items": len(seen), "lines": lines, "ok": len(seen) - attention, "attention": attention, "by_flag": by,
            "assemblies": len(asm), "erp_bom_differs": erp_diff, "erp_bom_missing": no_erp_bom}


def product_list(res: dict, decisions: dict | None = None) -> list[dict]:
    f = Findings(res, decisions)
    out = []
    for uid in products(res):
        t = f.tree(uid)
        p = f.idx[uid]
        out.append({"uid": uid, "pn": p["pn"], "name": p["name"], "source": p["source"], "source_kind": p["source_kind"],
                    "revision": p.get("revision"), "state": p.get("state"), "state_class": p.get("state_class"),
                    "erp_pn": (p.get("erp") or {}).get("pn"), "health": health(t)})
    out.sort(key=lambda x: (-x["health"]["attention"], x["name"]))
    return out


def product_tree(res: dict, uid: str, decisions: dict | None = None) -> dict | None:
    f = Findings(res, decisions)
    if uid not in f.idx or uid not in res.get("bom", {}):
        return None
    t = f.tree(uid)
    return {"tree": t, "health": health(t), "flag_he": FLAG_HE}


def learn_examples(res: dict, decisions: dict | None = None) -> dict:
    """Real examples from the scan for the "part numbers 101" screen: a released designed part that is used in
    more than one assembly, has a 3D model and an ERP item; a duplicate group across systems; a small product."""
    idx = {p["uid"]: p for p in res["parts"]}
    groups = {g["id"]: g for g in res.get("groups", [])}
    parents = _parents(res)

    def dup(p):          # how many different part numbers and systems the part's duplicate group has
        g = groups.get(p.get("group_id") or "")
        if not g:
            return 0, 0
        return len({pn_key(x) for x in g["pns"]}), len({idx[u]["source"] for u in g["members"] if u in idx})

    def part_score(p):
        e = p.get("erp") or {}
        npn, nsrc = dup(p)
        used = len(parents.get(p["uid"], []))
        return (npn >= 2, min(npn, 4), nsrc, used >= 2, p.get("state_class") == "released", bool(e.get("stock")),
                min(used, 4), e.get("stock") or 0, p["uid"])
    cands = [p for p in res["parts"] if p["kind"] == "part" and p.get("has_step") and p.get("erp") and p["pn"]]
    part = max(cands, key=part_score) if cands else None

    def group_score(g):
        ms = [idx[u] for u in g["members"] if u in idx]
        return (len({m["source"] for m in ms}), sum(1 for m in ms if m.get("has_step")), g.get("redundant_stock_value") or 0)
    gs = [g for g in groups.values() if len(g["members"]) >= 3]
    group = None
    if part and dup(part)[0] >= 2:
        group = groups[part["group_id"]]
    elif gs:
        group = max(gs, key=group_score)

    f = Findings(res, decisions)
    tops = products(res)
    sized = []
    for u in tops:
        t = f.tree(u)
        n = sum(1 for _ in _walk(t))
        depth = max(len(path) for path in _depths(t))
        has_part = part is not None and any(x["uid"] == part["uid"] for x in _walk(t))
        sized.append((not has_part, not (2 <= depth <= 4), n > 40, n, u))
    sized.sort()
    product = sized[0][-1] if sized else None
    dec = decisions or {}
    return {"available": True, "part_uid": part["uid"] if part else None, "group_id": group["id"] if group else None,
            "product_uid": product,
            "counts": {k: res.get("summary", {}).get(k) for k in ("parts", "groups", "redundant_pns", "redundant_stock_value",
                                                                  "currency", "near_pairs", "quality_issues", "erp_issues")}
            | {"approved_groups": sum(1 for g in groups if (dec.get(f"group:{g}") or {}).get("decision") == "approve"),
               "products": len(tops)}}


def _depths(n: dict, path: tuple = ()):
    path = path + (n["uid"],)
    kids = n.get("children") or []
    if not kids:
        yield path
    for c in kids:
        yield from _depths(c, path)
