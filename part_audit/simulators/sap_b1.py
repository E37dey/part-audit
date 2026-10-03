"""SAP Business One Service Layer simulator (/b1s/v1, OData v3 style).

POST /Login {CompanyDB, UserName, Password} -> cookies B1SESSION + ROUTEID; 401 code 301 without them;
POST /Logout -> 204. Items (default page size 20, Prefer: odata.maxpagesize / B1S-PageSize, relative
odata.nextLink, $inlinecount=allpages -> odata.count), ItemGroups, ProductTrees. Booleans as tYES/tNO.
"""
from __future__ import annotations

import secrets
from functools import lru_cache

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, Response

from .data import DEMO_PASSWORD, DEMO_USER, FactoryData, factory
from .odata import FilterError, apply_filter, apply_orderby, apply_select

PREFIX = "/sim/b1/b1s/v1"
COMPANY = "SBODEMO_IL"
_SESSIONS: set[str] = set()
GROUP_NAMES = {100: "ברגים ואומים", 101: "מסבים", 102: "רכיבי קנייה", 103: "פרופילים", 200: "חלקי ייצור", 210: "חלקי פח",
               300: "מכלולים"}


def _group(fam: str) -> int:
    if fam in ("shcs", "hexscrew", "csk", "setscrew", "nut", "washer", "pin", "key"):
        return 100
    if fam == "bearing":
        return 101
    if fam == "profile":
        return 103
    if fam in ("sheetL", "sheetU", "sheetZ"):
        return 210
    if fam == "assembly":
        return 300
    if fam in ("foot", "handle", "corner", "shaftsupport", "linshaft", "collar", "roller"):
        return 102
    return 200


class _Data:
    def __init__(self, fd: FactoryData):
        self.items, self.trees = [], []
        whs = {"ראשי": "01", "צפון": "02", "דרום": "03"}
        for it in fd.erp_items:
            cost = it.get("unit_cost") or 0.0
            stock = it.get("stock") or {}
            self.items.append({
                "ItemCode": it["pn"], "ItemName": it["description"][:100], "ForeignName": it.get("description_en") or None,
                "ItemsGroupCode": _group(it.get("family") or ""), "ItemType": "itItems", "InventoryItem": "tYES",
                "SalesItem": "tYES" if it.get("family") == "assembly" else "tNO", "PurchaseItem": "tYES" if it["type"] == "R" else "tNO",
                "Valid": "tYES" if it["status"] == "פעיל" else "tNO", "Frozen": "tNO" if it["status"] == "פעיל" else "tYES",
                "InventoryUOM": it.get("unit") or "יח'", "QuantityOnStock": float(sum(stock.values())),
                "AvgStdPrice": round(cost, 4), "MovingAveragePrice": round(cost, 4), "Mainsupplier": None,
                "SupplierCatalogNo": None, "LeadTime": it.get("lead_time_days"),
                "ProcurementMethod": "bom_Make" if it["type"] == "P" else "bom_Buy",
                "TreeType": "iProductionTree" if it.get("family") == "assembly" else "iNotATree",
                "CreateDate": it["created"], "UpdateDate": it["created"], "U_Supplier": it.get("supplier"),
                "ItemPrices": [{"PriceList": 1, "Price": round(cost, 2), "Currency": "ILS"}],
                "ItemWarehouseInfoCollection": [{"WarehouseCode": whs.get(w, "01"), "InStock": float(q), "Committed": 0.0,
                                                 "Ordered": 0.0, "StandardAveragePrice": round(cost, 4), "Locked": "tNO",
                                                 "ItemCode": it["pn"]} for w, q in stock.items()]})
        for parent, lines in fd.erp_bom_by_parent.items():
            self.trees.append({"TreeCode": parent, "TreeType": "iProductionTree", "Quantity": 1.0,
                               "ProductTreeLines": [{"ItemCode": b["child"], "Quantity": float(b["qty"])} for b in lines]})


@lru_cache(maxsize=4)
def _data(root: str) -> _Data:
    return _Data(factory(root))


def _unauth():
    return JSONResponse({"error": {"code": 301, "message": {"lang": "en-us",
                                                            "value": "Invalid session or session already timeout."}}},
                        status_code=401)


def router(root: str) -> APIRouter:
    r = APIRouter(prefix=PREFIX)

    def ok(request: Request) -> bool:
        return request.cookies.get("B1SESSION") in _SESSIONS and bool(request.cookies.get("ROUTEID"))

    @r.post("/Login")
    async def login(request: Request):
        body = await request.json()
        if body.get("CompanyDB") != COMPANY:
            return JSONResponse({"error": {"code": -304, "message": {"lang": "en-us", "value": "Company database not found"}}},
                                status_code=401)
        if body.get("UserName") != DEMO_USER or body.get("Password") != DEMO_PASSWORD:
            return JSONResponse({"error": {"code": -304, "message": {"lang": "en-us",
                                                                     "value": "Fail to get DB Credentials from SLD server"}}},
                                status_code=401)
        sid = secrets.token_hex(12)
        _SESSIONS.add(sid)
        resp = JSONResponse({"odata.metadata": f"{PREFIX}/$metadata#B1Sessions/@Element", "SessionId": sid,
                             "Version": "1000250 (simulator)", "SessionTimeout": 30})
        resp.set_cookie("B1SESSION", sid, httponly=True)
        resp.set_cookie("ROUTEID", ".node1", path="/")
        return resp

    @r.post("/Logout")
    def logout(request: Request):
        _SESSIONS.discard(request.cookies.get("B1SESSION"))
        return Response(status_code=204)

    def page(request: Request, rows: list[dict], entity: str, prefer: str | None, b1s_page: str | None):
        q = request.query_params
        try:
            rows = apply_filter(rows, q.get("$filter"))
        except FilterError as exc:
            return JSONResponse({"error": {"code": -1, "message": {"lang": "en-us", "value": str(exc)}}}, status_code=400)
        rows = apply_orderby(rows, q.get("$orderby"))
        size = 20
        if b1s_page:
            size = int(b1s_page)
        if prefer and "odata.maxpagesize=" in prefer:
            size = int(prefer.split("odata.maxpagesize=")[1].split(",")[0])
        skip = int(q.get("$skip") or 0)
        top = int(q["$top"]) if q.get("$top") else None
        total = len(rows)
        limit = min(size, top) if (top and size) else (top or size or total)
        chunk = rows[skip:skip + limit]
        body = {"odata.metadata": f"{PREFIX}/$metadata#{entity}",
                "value": [apply_select(x, q.get("$select")) for x in chunk]}
        if q.get("$inlinecount") == "allpages":
            body["odata.count"] = str(total)
        end = skip + limit
        if size and end < (min(total, skip + top) if top else total):
            others = "&".join(f"{k}={v}" for k, v in q.multi_items() if k != "$skip")
            body["odata.nextLink"] = f"{entity}?{others + '&' if others else ''}$skip={end}"
        headers = {"Preference-Applied": f"odata.maxpagesize={size}"} if prefer else {}
        return JSONResponse(body, headers=headers)

    @r.get("/Items")
    def items(request: Request, prefer: str | None = Header(None), b1s_pagesize: str | None = Header(None)):
        if not ok(request):
            return _unauth()
        return page(request, _data(root).items, "Items", prefer, b1s_pagesize)

    @r.get("/ItemGroups")
    def groups(request: Request, prefer: str | None = Header(None)):
        if not ok(request):
            return _unauth()
        rows = [{"Number": k, "GroupName": v} for k, v in GROUP_NAMES.items()]
        return page(request, rows, "ItemGroups", prefer, None)

    @r.get("/ProductTrees")
    def trees(request: Request, prefer: str | None = Header(None), b1s_pagesize: str | None = Header(None)):
        if not ok(request):
            return _unauth()
        return page(request, _data(root).trees, "ProductTrees", prefer, b1s_pagesize)

    return r
