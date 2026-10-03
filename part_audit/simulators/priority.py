"""Priority ERP REST API (OData v4) simulator: /odata/Priority/{ini}/{company}/{FORM}.

Implements LOGPART (part catalogue), FAMILY_LOG, WARHSBAL (warehouse balances, top-level as used by
third-party connectors), PART with PARTARC_SUBFORM (BOM), GetPriorityVersion(), GetODataVersion().
$select / $filter (no substringof -> 400) / $orderby / $top / $skip / $expand; responses are silently
capped at MAXAPILINES (2000) without a next link, like the real server. Basic auth (user+password or
token:PAT). Fields marked UNCONFIRMED in docs/research/erp_apis.md (UNITNAME, SUPNAME, WARHSBAL field
names, PARTARC_SUBFORM) are configurable in the connector.
"""
from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from .data import FactoryData, basic_ok, factory
from .odata import FilterError, apply_filter, apply_orderby, apply_select, parse_inner_options, split_expand

PREFIX = "/sim/priority/odata/Priority"
MAXAPILINES = 2000
FAMILIES = {
    "shcs": ("101", "ברגי אלן"), "hexscrew": ("102", "ברגי משושה"), "csk": ("103", "ברגים שקועים"),
    "setscrew": ("104", "ברגי אל-ראש"), "nut": ("105", "אומים"), "washer": ("106", "דיסקיות"), "pin": ("107", "פינים"),
    "key": ("108", "שגמים"), "bearing": ("120", "מסבים"), "profile": ("130", "פרופילים"), "foot": ("140", "רכיבי קנייה"),
    "handle": ("140", "רכיבי קנייה"), "corner": ("140", "רכיבי קנייה"), "shaftsupport": ("140", "רכיבי קנייה"),
    "linshaft": ("141", "צירים ליניאריים"), "collar": ("140", "רכיבי קנייה"), "roller": ("142", "גלגלות מסוע"),
    "plate": ("200", "פלטות"), "angle": ("201", "תושבות"), "motormount": ("201", "תושבות"), "housing": ("202", "בתי מסב"),
    "shaft": ("203", "צירים"), "bushing": ("204", "תותבים ומרווחים"), "spacer": ("204", "תותבים ומרווחים"),
    "flange": ("205", "אוגנים"), "pulley": ("206", "גלגלות"), "gear": ("207", "גלגלי שיניים"), "clamp": ("208", "בלוקים"),
    "tube": ("209", "צינורות"), "sheetL": ("210", "חלקי פח"), "sheetU": ("210", "חלקי פח"), "sheetZ": ("210", "חלקי פח"),
    "assembly": ("300", "מכלולים"), "": ("0", "כללי"),
}


class _Data:
    def __init__(self, fd: FactoryData):
        self.logpart, self.balances, self.parts = [], [], []
        for i, it in enumerate(fd.erp_items):
            fam, famdes = FAMILIES.get(it.get("family") or "", ("0", "כללי"))
            self.logpart.append({"PARTNAME": it["pn"], "PARTDES": it["description"],
                                 "EPARTDES": it.get("description_en") or None, "BARCODE": None,
                                 "STATDES": it["status"], "TYPE": it["type"], "FAMILYNAME": fam, "FAMILYDES": famdes,
                                 "UNITNAME": it.get("unit") or "יח'", "LASTPRICE": it.get("unit_cost"),
                                 "SUPNAME": it.get("supplier") or None, "PART": 1000 + i, "EXTPART": 1000 + i})
            for wh, q in (it.get("stock") or {}).items():
                self.balances.append({"PARTNAME": it["pn"], "WARHSNAME": {"ראשי": "Main", "צפון": "N01",
                                                                         "דרום": "S01"}.get(wh, wh),
                                      "LOCNAME": "0", "BALANCE": float(q), "TBALANCE": float(q)})
        boms = fd.erp_bom_by_parent
        for p in self.logpart:
            p2 = {k: p[k] for k in ("PARTNAME", "PARTDES", "TYPE", "STATDES")}
            p2["PARTARC_SUBFORM"] = [{"SONNAME": b["child"], "SONDES": "", "SONQUANT": float(b["qty"]), "UNITNAME": "יח'",
                                      "COEF": 1.0, "OP": 0} for b in boms.get(p["PARTNAME"], [])]
            self.parts.append(p2)


@lru_cache(maxsize=4)
def _data(root: str) -> _Data:
    return _Data(factory(root))


def _collection(request: Request, rows: list[dict], form: str, ctx: str):
    q = request.query_params
    try:
        rows = apply_filter(rows, q.get("$filter"), allow_substringof=False)
    except FilterError as exc:
        return JSONResponse({"error": {"code": "", "message": f"Invalid filter: {exc}"}}, status_code=400)
    rows = apply_orderby(rows, q.get("$orderby"))
    skip = int(q.get("$skip") or 0)
    top = int(q["$top"]) if q.get("$top") else None
    rows = rows[skip:]
    rows = rows[:min(top, MAXAPILINES)] if top is not None else rows[:MAXAPILINES]
    expand = split_expand(q.get("$expand"))
    out = []
    for r in rows:
        x = apply_select({k: v for k, v in r.items() if not k.endswith("_SUBFORM")}, q.get("$select"))
        for sub, opts in expand.items():
            if sub in r:
                o = parse_inner_options(opts)
                x[sub] = [apply_select(s, o.get("$select")) for s in r[sub]]
                x[f"{sub}@odata.context"] = f"{ctx}/$metadata#{form}('{r.get('PARTNAME', '')}')/{sub}"
        out.append(x)
    sel = q.get("$select")
    return {"@odata.context": f"{ctx}/$metadata#{form}" + (f"({sel})" if sel else ""), "value": out}


def router(root: str) -> APIRouter:
    r = APIRouter(prefix=PREFIX)

    def guard(authorization):
        if not basic_ok(authorization):
            return JSONResponse({"error": {"code": "", "message": "Authorization is required"}}, status_code=401,
                                headers={"WWW-Authenticate": 'Basic realm="Priority"'})
        return None

    @r.get("/{ini}/{company}/GetPriorityVersion()")
    def version(ini: str, company: str, authorization: str | None = Header(None)):
        if (e := guard(authorization)):
            return e
        return {"@odata.context": "serviceroot/$metadata#Edm.String", "value": "23.1-20.0.0.119 (simulator)"}

    @r.get("/{ini}/{company}/GetODataVersion()")
    def odata_version(ini: str, company: str, authorization: str | None = Header(None)):
        if (e := guard(authorization)):
            return e
        return {"@odata.context": "serviceroot/$metadata#Edm.String", "value": "4.0"}

    @r.get("/{ini}/{company}/{form}")
    def form(ini: str, company: str, form: str, request: Request, authorization: str | None = Header(None)):
        if (e := guard(authorization)):
            return e
        if company != "demo":
            return JSONResponse({"error": {"code": "", "message": f"Company {company} does not exist"}}, status_code=404)
        d = _data(root)
        ctx = f"{request.url.scheme}://{request.url.netloc}{PREFIX}/{ini}/{company}"
        if form == "LOGPART":
            return _collection(request, d.logpart, "LOGPART", ctx)
        if form == "WARHSBAL":
            return _collection(request, d.balances, "WARHSBAL", ctx)
        if form == "PART":
            return _collection(request, d.parts, "PART", ctx)
        if form == "FAMILY_LOG":
            fams = sorted({v for v in FAMILIES.values()})
            return _collection(request, [{"FAMILYNAME": c, "FAMILYDESC": dsc, "EFAMILYDES": None} for c, dsc in fams],
                               "FAMILY_LOG", ctx)
        return JSONResponse({"error": {"code": "", "message": "The requested form or record does not exist"}},
                            status_code=404)

    return r
