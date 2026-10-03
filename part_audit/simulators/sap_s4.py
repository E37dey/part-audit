"""SAP S/4HANA OData v2 simulator (API_PRODUCT_SRV, API_MATERIAL_STOCK_SRV, API_BILL_OF_MATERIAL_SRV;v=0002,
API_INFORECORD_PROCESS_SRV). Wire format: {"d":{"results":[...],"__count","__next"}}, __metadata on every
entry, decimals as strings, dates as /Date(ms)/, server-driven paging with $skiptoken when $top is absent.
Basic auth; sap-client header/parameter accepted.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from .data import FactoryData, basic_ok, factory
from .odata import FilterError, apply_filter, apply_orderby, apply_select, split_expand

PREFIX = "/sim/s4/sap/opu/odata/sap"
PAGE = 1000
PLANTS = {"ראשי": ("1000", "0001"), "צפון": ("2000", "0001"), "דרום": ("3000", "0001")}
GROUPS = {"shcs": "FAST", "hexscrew": "FAST", "csk": "FAST", "setscrew": "FAST", "nut": "FAST", "washer": "FAST",
          "pin": "FAST", "key": "FAST", "bearing": "BEAR", "profile": "PROF", "assembly": "ASSY"}


def _date(s: str) -> str:
    d = dt.datetime.fromisoformat(s[:10]).replace(tzinfo=dt.timezone.utc)
    return f"/Date({int(d.timestamp() * 1000)})/"


class _Data:
    def __init__(self, fd: FactoryData):
        self.product, self.desc, self.valuation, self.plant, self.stock, self.bomitem, self.inforec = [], [], [], [], [], [], []
        for i, it in enumerate(fd.erp_items):
            pn = it["pn"]
            plant = PLANTS.get(next(iter(it.get("stock") or {"ראשי": 0})), ("1000", "0001"))[0]
            inactive = it["status"] != "פעיל"
            self.product.append({"Product": pn, "ProductType": "FERT" if it["family"] == "assembly" else
                                 ("HALB" if it["type"] == "P" else "ROH"), "ProductGroup": GROUPS.get(it["family"], "MECH"),
                                 "BaseUnit": "PC", "CrossPlantStatus": "02" if inactive else "",
                                 "IsMarkedForDeletion": False, "ProductOldID": "", "MaterialRevisionLevel": "",
                                 "CreationDate": _date(it["created"]), "LastChangeDate": _date(it["created"]),
                                 "GrossWeight": "0.000", "NetWeight": "0.000", "WeightUnit": "KG"})
            self.desc.append({"Product": pn, "Language": "HE", "ProductDescription": it["description"][:40]})
            if it.get("description_en"):
                self.desc.append({"Product": pn, "Language": "EN", "ProductDescription": it["description_en"][:40]})
            cost = it.get("unit_cost") or 0.0
            self.valuation.append({"Product": pn, "ValuationArea": plant, "ValuationType": "",
                                   "StandardPrice": f"{cost:.3f}", "MovingAveragePrice": f"{cost:.3f}",
                                   "PriceUnitQty": "1", "Currency": "ILS",
                                   "InventoryValuationProcedure": "S" if it["type"] == "P" else "V"})
            self.plant.append({"Product": pn, "Plant": plant, "ProcurementType": "E" if it["type"] == "P" else "F",
                               "MRPType": "PD", "IsMarkedForDeletion": False})
            for wh, q in (it.get("stock") or {}).items():
                pl, sl = PLANTS.get(wh, ("1000", "0001"))
                self.stock.append({"Material": pn, "Plant": pl, "StorageLocation": sl, "Batch": "", "Supplier": "",
                                   "Customer": "", "WBSElementInternalID": "000000000000000000000000",
                                   "SDDocument": "", "SDDocumentItem": "0", "InventorySpecialStockType": "",
                                   "InventoryStockType": "01", "MaterialBaseUnit": "PC",
                                   "MatlWrhsStkQtyInMatlBaseUnit": f"{float(q):.3f}"})
            if it.get("supplier") and it["type"] == "R":
                self.inforec.append({"PurchasingInfoRecord": f"53{i:08d}", "Supplier": f"V{abs(hash(it['supplier'])) % 10**6:06d}",
                                     "Material": pn, "SupplierMaterialNumber": "", "IsRegularSupplier": True,
                                     "PurchasingInfoRecordDesc": it["supplier"], "IsDeleted": False})
        n = 0
        for parent, lines in fd.erp_bom_by_parent.items():
            for j, b in enumerate(lines, start=1):
                n += 1
                self.bomitem.append({"BillOfMaterial": f"{n:08d}", "BillOfMaterialCategory": "M", "BillOfMaterialVariant": "1",
                                     "BillOfMaterialVersion": "", "EngineeringChangeDocument": "", "Material": parent,
                                     "Plant": "1000", "BillOfMaterialItemNodeNumber": str(j), "HeaderChangeDocument": "",
                                     "BillOfMaterialComponent": b["child"], "BillOfMaterialItemQuantity": f"{float(b['qty']):.3f}",
                                     "BillOfMaterialItemUnit": "PC", "BillOfMaterialItemNumber": f"{j * 10:04d}",
                                     "IsDeleted": False})


@lru_cache(maxsize=4)
def _data(root: str) -> _Data:
    return _Data(factory(root))


def _err(status, code, msg):
    return JSONResponse({"error": {"code": code, "message": {"lang": "en", "value": msg}}}, status_code=status)


def _coll(request: Request, svc: str, entity: str, rows: list[dict], keys: tuple, nav: dict | None = None):
    q = request.query_params
    try:
        rows = apply_filter(rows, q.get("$filter"))
    except FilterError as exc:
        return _err(400, "SY/530", f"Invalid filter: {exc}")
    rows = apply_orderby(rows, q.get("$orderby"))
    total = len(rows)
    skip = int(q.get("$skiptoken") or q.get("$skip") or 0)
    if q.get("$top"):
        chunk, nxt = rows[skip:skip + int(q["$top"])], None
    else:
        chunk = rows[skip:skip + PAGE]
        nxt = skip + PAGE if skip + PAGE < total else None
    base = f"{request.url.scheme}://{request.url.netloc}{PREFIX}/{svc}"
    expand = split_expand(q.get("$expand"))
    out = []
    for r in chunk:
        k = ",".join(f"{kk}='{r[kk]}'" for kk in keys) if len(keys) > 1 else f"'{r[keys[0]]}'"
        uri = f"{base}/{entity}({k})"
        x = {"__metadata": {"id": uri, "uri": uri, "type": f"{svc.split(';')[0]}.{entity}Type"}}
        x.update(apply_select(r, q.get("$select")))
        for nname, fn in (nav or {}).items():
            if nname in expand:
                x[nname] = {"results": [dict({"__metadata": {"type": f"{svc}.Nav"}}, **c) for c in fn(r)]}
            elif not q.get("$select") or nname in q.get("$select", ""):
                x[nname] = {"__deferred": {"uri": f"{uri}/{nname}"}}
        out.append(x)
    d = {"results": out}
    if q.get("$inlinecount") == "allpages":
        d["__count"] = str(total)
    if nxt is not None:
        others = "&".join(f"{kk}={v}" for kk, v in q.multi_items() if kk not in ("$skiptoken",))
        d["__next"] = f"{base}/{entity}?{others + '&' if others else ''}$skiptoken={nxt}"
    return {"d": d}


def router(root: str) -> APIRouter:
    r = APIRouter(prefix=PREFIX)

    def guard(a):
        if not basic_ok(a):
            return JSONResponse({"error": {"code": "/IWFND/CM_CONSUMER/101", "message": {"lang": "en", "value":
                                 "Unauthorized"}}}, status_code=401, headers={"WWW-Authenticate": 'Basic realm="SAP"'})
        return None

    @r.get("/API_PRODUCT_SRV/A_Product")
    def products(request: Request, authorization: str | None = Header(None)):
        if (e := guard(authorization)):
            return e
        d = _data(root)
        by = {}
        for x in d.desc:
            by.setdefault(x["Product"], []).append(x)
        return _coll(request, "API_PRODUCT_SRV", "A_Product", d.product, ("Product",),
                     nav={"to_Description": lambda row: by.get(row["Product"], [])})

    @r.get("/API_PRODUCT_SRV/A_ProductDescription")
    def descriptions(request: Request, authorization: str | None = Header(None)):
        if (e := guard(authorization)):
            return e
        return _coll(request, "API_PRODUCT_SRV", "A_ProductDescription", _data(root).desc, ("Product", "Language"))

    @r.get("/API_PRODUCT_SRV/A_ProductValuation")
    def valuation(request: Request, authorization: str | None = Header(None)):
        if (e := guard(authorization)):
            return e
        return _coll(request, "API_PRODUCT_SRV", "A_ProductValuation", _data(root).valuation,
                     ("Product", "ValuationArea", "ValuationType"))

    @r.get("/API_PRODUCT_SRV/A_ProductPlant")
    def plants(request: Request, authorization: str | None = Header(None)):
        if (e := guard(authorization)):
            return e
        return _coll(request, "API_PRODUCT_SRV", "A_ProductPlant", _data(root).plant, ("Product", "Plant"))

    @r.get("/API_MATERIAL_STOCK_SRV/A_MatlStkInAcctMod")
    def stock(request: Request, authorization: str | None = Header(None)):
        if (e := guard(authorization)):
            return e
        return _coll(request, "API_MATERIAL_STOCK_SRV", "A_MatlStkInAcctMod", _data(root).stock,
                     ("Material", "Plant", "StorageLocation"))

    @r.get("/API_BILL_OF_MATERIAL_SRV;v=0002/MaterialBOMItem")
    def bom_items(request: Request, authorization: str | None = Header(None)):
        if (e := guard(authorization)):
            return e
        return _coll(request, "API_BILL_OF_MATERIAL_SRV;v=0002", "MaterialBOMItem", _data(root).bomitem,
                     ("BillOfMaterial", "BillOfMaterialItemNodeNumber"))

    @r.get("/API_INFORECORD_PROCESS_SRV/A_PurchasingInfoRecord")
    def inforec(request: Request, authorization: str | None = Header(None)):
        if (e := guard(authorization)):
            return e
        return _coll(request, "API_INFORECORD_PROCESS_SRV", "A_PurchasingInfoRecord", _data(root).inforec,
                     ("PurchasingInfoRecord",))

    return r
