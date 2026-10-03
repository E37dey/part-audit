"""ERP connectors (read-only): Priority (OData v4), SAP S/4HANA (OData v2), SAP Business One (Service Layer)."""
from __future__ import annotations

import re

from ..model import BomLine, ErpItem
from .base import Collected, Connector, Field, to_float
from .http import ConnectorError, ReadOnlyHttp

INACTIVE_DEFAULT = "לא פעיל, מבוטל, מוקפא, Inactive, Obsolete, Not In Use"


def _inactive_rx(text: str) -> re.Pattern:
    words = [re.escape(w.strip()) for w in (text or "").split(",") if w.strip()]
    return re.compile("|".join(words) if words else r"(?!x)x", re.I)


# =========================================================================================== Priority


class PriorityErp(Connector):
    kind = "priority"
    role = "erp"
    title = "Priority"
    vendor = "Priority Software"
    interface = "Priority REST API (OData v4)"
    description = "קריאת כרטיסי פריט (LOGPART), יתרות מלאי (WARHSBAL), עץ מוצר (PARTARC) ומחיר אחרון."
    fields = [
        Field("service_root", "כתובת שירות (Service Root)", required=True,
              default="https://priority.company.local/odata/Priority/tabula.ini/demo",
              help="כפי שמופיע ב'הפקת קישור להפעלת תוכנית' – https://<שרת>/odata/Priority/<קובץ ini>/<חברה>"),
        Field("username", "שם משתמש API / טוקן (PAT)", required=True, secret=True,
              help="עם טוקן אישי (PAT): הטוקן כאן, ובסיסמה המילה PAT"),
        Field("password", "סיסמה (או PAT עבור טוקן)", type="password", required=True),
        Field("app_id", "X-App-Id (רישוי לפי אפליקציה)", default="", group="advanced"),
        Field("app_key", "X-App-Key", type="password", default="", group="advanced"),
        Field("page_size", "גודל עמוד ($top)", type="number", default=500, group="advanced",
              help="חייב להיות קטן או שווה ל-MAXAPILINES בשרת (ברירת מחדל 2000)"),
        Field("f_desc_en", "שדה תיאור באנגלית", default="EPARTDES", group="mapping"),
        Field("f_unit", "שדה יחידה", default="UNITNAME", group="mapping"),
        Field("f_supplier", "שדה ספק מועדף", default="SUPNAME", group="mapping"),
        Field("f_price", "שדה מחיר/עלות", default="LASTPRICE", group="mapping"),
        Field("inactive", "סטטוסים שנחשבים לא פעילים", default=INACTIVE_DEFAULT, group="mapping"),
        Field("stock_form", "טופס יתרות מלאי", default="WARHSBAL", group="mapping", help="ריק = לא לקרוא מלאי"),
        Field("stock_qty_field", "שדה כמות ביתרות", default="BALANCE", group="mapping"),
        Field("bom", "לקרוא עץ מוצר (PART / PARTARC_SUBFORM)", type="bool", default=True, group="mapping"),
        Field("verify_tls", "אימות תעודת אבטחה (TLS)", type="bool", default=True, group="advanced"),
    ]
    unconfirmed = ["שמות השדות UNITNAME / SUPNAME ומבנה WARHSBAL לא מתועדים פומבית – ניתנים לשינוי במיפוי",
                   "כל קריאה נספרת כטרנזקציית API ברישוי Priority"]

    def _http(self) -> ReadOnlyHttp:
        headers = {"Accept": "application/json"}
        if self.cfg.get("app_id"):
            headers["X-App-Id"] = self.cfg["app_id"]
            headers["X-App-Key"] = self.cfg.get("app_key") or ""
        return ReadOnlyHttp(self.cfg["service_root"].rstrip("/") + "/", auth=(self.cfg["username"], self.cfg["password"]),
                            verify=bool(self.cfg.get("verify_tls", True)), headers=headers)

    def _pages(self, h: ReadOnlyHttp, form: str, params: dict, order: str):
        n = int(self.cfg.get("page_size") or 500)
        skip = 0
        while True:
            data = h.json("GET", form, params={**params, "$top": n, "$skip": skip, "$orderby": order})
            rows = data.get("value", [])
            yield rows
            if len(rows) < n:  # Priority documents client-side paging only ($top/$skip)
                return
            skip += n

    def test(self) -> dict:
        h = self._http()
        try:
            r = h.get("GetPriorityVersion()")
            if r.status_code == 401:
                raise ConnectorError("שם משתמש / טוקן או סיסמה שגויים", status=401)
            ver = r.json().get("value", "—") if r.status_code == 200 else "—"
            data = h.json("GET", "LOGPART", params={"$top": 1, "$select": "PARTNAME,PARTDES"})
            return {"ok": True, "message": "מחובר ל-Priority",
                    "details": {"גרסה": ver, "דוגמה": (data.get("value") or [{}])[0].get("PARTNAME", "—"),
                                "קריאות API": h.calls}}
        except ConnectorError as exc:
            return {"ok": False, "message": str(exc), "details": {"status": exc.status}}
        finally:
            h.close()

    def collect(self) -> Collected:
        out = Collected()
        c = self.cfg
        h = self._http()
        rx = _inactive_rx(c.get("inactive", INACTIVE_DEFAULT))
        try:
            fields = ["PARTNAME", "PARTDES", "STATDES", "TYPE", "FAMILYNAME", "FAMILYDES"] + \
                     [c[k] for k in ("f_desc_en", "f_unit", "f_supplier", "f_price") if c.get(k)]
            items: dict[str, ErpItem] = {}
            for rows in self._pages(h, "LOGPART", {"$select": ",".join(fields)}, "PARTNAME"):
                for r in rows:
                    pn = str(r.get("PARTNAME") or "").strip()
                    if not pn:
                        continue
                    st = str(r.get("STATDES") or "")
                    items[pn] = ErpItem(source_id=self.source_id, pn=pn, description=str(r.get("PARTDES") or ""),
                                        description_en=str(r.get(c["f_desc_en"]) or ""), uom=str(r.get(c["f_unit"]) or ""),
                                        family=str(r.get("FAMILYDES") or r.get("FAMILYNAME") or ""), status=st,
                                        active=not rx.search(st), make_buy={"P": "make", "R": "buy"}.get(r.get("TYPE"), ""),
                                        unit_cost=to_float(r.get(c["f_price"])), currency="ILS",
                                        supplier=str(r.get(c["f_supplier"]) or ""), props={"TYPE": r.get("TYPE")})
                self.progress("קורא כרטיסי פריט מ-Priority", len(items), 0)
            if c.get("stock_form"):
                qf = c.get("stock_qty_field") or "BALANCE"
                try:
                    for rows in self._pages(h, c["stock_form"], {"$select": f"PARTNAME,WARHSNAME,{qf}"}, "PARTNAME"):
                        for r in rows:
                            it = items.get(str(r.get("PARTNAME") or ""))
                            q = to_float(r.get(qf))
                            if it and q is not None:
                                wh = str(r.get("WARHSNAME") or "")
                                it.stock[wh] = it.stock.get(wh, 0.0) + q
                                it.stock_total += q
                except ConnectorError as exc:
                    out.errors.append(f"לא ניתן לקרוא יתרות מלאי מ-{c['stock_form']}: {exc}")
            if c.get("bom"):
                try:
                    for rows in self._pages(h, "PART", {"$select": "PARTNAME", "$expand": "PARTARC_SUBFORM"}, "PARTNAME"):
                        for r in rows:
                            for s in r.get("PARTARC_SUBFORM") or []:
                                out.bom.append(BomLine(self.source_id, r["PARTNAME"], str(s.get("SONNAME") or ""),
                                                       to_float(s.get("SONQUANT")) or 1.0))
                except ConnectorError as exc:
                    out.errors.append(f"לא ניתן לקרוא עצי מוצר (PARTARC): {exc}")
            out.erp_items = list(items.values())
            out.stats = {"items": len(out.erp_items), "bom_lines": len(out.bom), "api_calls": h.calls}
        finally:
            h.close()
        return out


# =========================================================================================== SAP S/4HANA


def _sap_date(v) -> str:
    m = re.match(r"/Date\((-?\d+)", str(v or ""))
    if not m:
        return ""
    import datetime as dt
    return dt.datetime.fromtimestamp(int(m.group(1)) / 1000, dt.timezone.utc).date().isoformat()


class SapS4(Connector):
    kind = "sap_s4"
    role = "erp"
    title = "SAP S/4HANA"
    vendor = "SAP"
    interface = "OData v2 (API_PRODUCT_SRV ועוד)"
    description = "קריאת אב מוצר (A_Product), תיאורים בעברית/אנגלית, עלות תקן, מלאי, עץ מוצר ורשומות מידע לרכש."
    fields = [
        Field("host", "כתובת השרת", default="https://s4.company.local:44300", required=True),
        Field("sap_client", "Client (sap-client)", default="", help="נדרש במערכות עם כמה Clients"),
        Field("username", "משתמש תקשורת", required=True),
        Field("password", "סיסמה", type="password", required=True),
        Field("lang_primary", "שפת תיאור ראשית", default="HE", group="mapping"),
        Field("lang_secondary", "שפת תיאור משנית", default="EN", group="mapping"),
        Field("stock_types", "סוגי מלאי לסיכום", default="01", group="mapping", help="01 = מלאי חופשי"),
        Field("base_path", "נתיב שירותים", default="/sap/opu/odata/sap", group="advanced"),
        Field("verify_tls", "אימות תעודת אבטחה (TLS)", type="bool", default=True, group="advanced"),
    ]
    unconfirmed = ["קוד שפה לעברית (HE)", "משמעות ProcurementType (E=ייצור, F=קנייה) וסוגי מלאי"]

    def _http(self) -> ReadOnlyHttp:
        headers = {"Accept": "application/json"}
        if self.cfg.get("sap_client"):
            headers["sap-client"] = str(self.cfg["sap_client"])
        return ReadOnlyHttp(self.cfg["host"].rstrip("/") + self.cfg["base_path"].rstrip("/") + "/",
                            auth=(self.cfg["username"], self.cfg["password"]),
                            verify=bool(self.cfg.get("verify_tls", True)), headers=headers)

    def _all(self, h: ReadOnlyHttp, path: str, params: dict) -> list[dict]:
        out, url, first = [], path, True
        while url:
            data = h.json("GET", url, params={**params, "$format": "json"} if first else None)
            first = False
            d = data.get("d", {})
            out.extend(d.get("results", []))
            url = d.get("__next")
        return out

    def test(self) -> dict:
        h = self._http()
        try:
            data = h.json("GET", "API_PRODUCT_SRV/A_Product", params={"$top": 1, "$inlinecount": "allpages",
                                                                       "$select": "Product", "$format": "json"})
            return {"ok": True, "message": "מחובר ל-SAP S/4HANA",
                    "details": {"מוצרים": data.get("d", {}).get("__count", "—"), "קריאות API": h.calls}}
        except ConnectorError as exc:
            return {"ok": False, "message": str(exc), "details": {"status": exc.status}}
        finally:
            h.close()

    def collect(self) -> Collected:
        out = Collected()
        c = self.cfg
        h = self._http()
        try:
            self.progress("קורא אב מוצר מ-SAP", 0, 0)
            prods = self._all(h, "API_PRODUCT_SRV/A_Product", {
                "$select": "Product,ProductType,ProductGroup,BaseUnit,CrossPlantStatus,IsMarkedForDeletion,CreationDate,"
                           "MaterialRevisionLevel,to_Description", "$expand": "to_Description"})
            items: dict[str, ErpItem] = {}
            for p in prods:
                descs = {d.get("Language"): d.get("ProductDescription", "") for d in (p.get("to_Description") or {})
                         .get("results", [])}
                inactive = bool(p.get("IsMarkedForDeletion")) or bool(p.get("CrossPlantStatus"))
                items[p["Product"]] = ErpItem(source_id=self.source_id, pn=p["Product"],
                                              description=descs.get(c["lang_primary"]) or descs.get(c["lang_secondary"], ""),
                                              description_en=descs.get(c["lang_secondary"], ""), uom=p.get("BaseUnit", ""),
                                              family=p.get("ProductGroup", ""),
                                              status=("חסום/מסומן למחיקה" if inactive else "פעיל"), active=not inactive,
                                              created=_sap_date(p.get("CreationDate")), props={"ProductType": p.get("ProductType")})
            self.progress("קורא עלויות, מלאי ועץ מוצר", 1, 4)
            for v in self._all(h, "API_PRODUCT_SRV/A_ProductValuation",
                               {"$select": "Product,StandardPrice,MovingAveragePrice,PriceUnitQty,Currency,InventoryValuationProcedure"}):
                it = items.get(v["Product"])
                if it and it.unit_cost is None:
                    price = to_float(v.get("StandardPrice") if v.get("InventoryValuationProcedure") == "S"
                                     else v.get("MovingAveragePrice"))
                    per = to_float(v.get("PriceUnitQty")) or 1.0
                    it.unit_cost = None if price is None else price / per
                    it.currency = v.get("Currency", "")
            for pl in self._all(h, "API_PRODUCT_SRV/A_ProductPlant", {"$select": "Product,Plant,ProcurementType"}):
                it = items.get(pl["Product"])
                if it and not it.make_buy:
                    it.make_buy = {"E": "make", "F": "buy"}.get(pl.get("ProcurementType", ""), "")
            types = {t.strip() for t in (c.get("stock_types") or "01").split(",") if t.strip()}
            for s in self._all(h, "API_MATERIAL_STOCK_SRV/A_MatlStkInAcctMod",
                               {"$select": "Material,Plant,StorageLocation,InventoryStockType,MatlWrhsStkQtyInMatlBaseUnit"}):
                it = items.get(s["Material"])
                if it and (not types or s.get("InventoryStockType") in types):
                    q = to_float(s.get("MatlWrhsStkQtyInMatlBaseUnit")) or 0.0
                    wh = f"{s.get('Plant')}/{s.get('StorageLocation')}"
                    it.stock[wh] = it.stock.get(wh, 0.0) + q
                    it.stock_total += q
            try:
                for ir in self._all(h, "API_INFORECORD_PROCESS_SRV/A_PurchasingInfoRecord",
                                    {"$select": "Material,Supplier,SupplierMaterialNumber,IsRegularSupplier,PurchasingInfoRecordDesc"}):
                    it = items.get(ir.get("Material", ""))
                    if it and (not it.supplier or ir.get("IsRegularSupplier")):
                        it.supplier = ir.get("PurchasingInfoRecordDesc") or ir.get("Supplier", "")
                        it.supplier_pn = ir.get("SupplierMaterialNumber", "")
            except ConnectorError as exc:
                out.errors.append(f"רשומות מידע לרכש לא נקראו: {exc}")
            try:
                for b in self._all(h, "API_BILL_OF_MATERIAL_SRV;v=0002/MaterialBOMItem",
                                   {"$select": "Material,BillOfMaterialComponent,BillOfMaterialItemQuantity,IsDeleted"}):
                    if not b.get("IsDeleted"):
                        out.bom.append(BomLine(self.source_id, b["Material"], b["BillOfMaterialComponent"],
                                               to_float(b.get("BillOfMaterialItemQuantity")) or 1.0))
            except ConnectorError as exc:
                out.errors.append(f"עצי מוצר לא נקראו: {exc}")
            out.erp_items = list(items.values())
            out.stats = {"items": len(out.erp_items), "bom_lines": len(out.bom), "api_calls": h.calls}
        finally:
            h.close()
        return out


# =========================================================================================== SAP Business One


class SapB1(Connector):
    kind = "sap_b1"
    role = "erp"
    title = "SAP Business One"
    vendor = "SAP"
    interface = "Service Layer (REST/OData)"
    description = "קריאת פריטים (Items), קבוצות פריטים, מלאי לפי מחסן, עלות ממוצעת ועצי מוצר (ProductTrees)."
    fields = [
        Field("base_url", "כתובת Service Layer", default="https://b1-server:50000/b1s/v1", required=True),
        Field("company_db", "מסד נתונים של החברה (CompanyDB)", required=True, default="SBODEMO_IL"),
        Field("username", "שם משתמש", required=True),
        Field("password", "סיסמה", type="password", required=True),
        Field("supplier_field", "שדה ספק", default="Mainsupplier", group="mapping",
              help="Mainsupplier או שדה משתמש (U_...)"),
        Field("page_size", "גודל עמוד", type="number", default=200, group="advanced"),
        Field("verify_tls", "אימות תעודת אבטחה (TLS)", type="bool", default=True, group="advanced",
              help="שרתי Service Layer רבים משתמשים בתעודה עצמית – עדיף להוסיף אותה לאמון מאשר לבטל אימות"),
    ]
    unconfirmed = ["ערכי ProcurementMethod (bom_Make / bom_Buy)", "משמעות Valid/Frozen לסטטוס פעיל"]

    def _http(self) -> ReadOnlyHttp:
        base = self.cfg["base_url"].rstrip("/") + "/"
        return ReadOnlyHttp(base, allowed=[("POST", r"/Login$"), ("POST", r"/Logout$")],
                            verify=bool(self.cfg.get("verify_tls", True)), headers={"Accept": "application/json"})

    def _login(self, h: ReadOnlyHttp) -> dict:
        r = h.post("Login", json={"CompanyDB": self.cfg["company_db"], "UserName": self.cfg["username"],
                                  "Password": self.cfg["password"]})
        if r.status_code != 200:
            msg = ""
            try:
                msg = r.json()["error"]["message"]["value"]
            except Exception:
                pass
            raise ConnectorError(f"ההתחברות ל-SAP Business One נכשלה{': ' + msg if msg else ''}", status=r.status_code)
        return r.json()

    def _all(self, h: ReadOnlyHttp, entity: str, params: dict) -> list[dict]:
        out, url, first = [], entity, True
        hdr = {"Prefer": f"odata.maxpagesize={int(self.cfg.get('page_size') or 200)}"}
        while url:
            data = h.json("GET", url, params=params if first else None, headers=hdr)
            first = False
            out.extend(data.get("value", []))
            url = data.get("odata.nextLink") or data.get("@odata.nextLink")
        return out

    def test(self) -> dict:
        h = self._http()
        try:
            s = self._login(h)
            data = h.json("GET", "Items", params={"$top": 1, "$select": "ItemCode", "$inlinecount": "allpages"})
            h.post("Logout")
            return {"ok": True, "message": "מחובר ל-SAP Business One",
                    "details": {"גרסה": s.get("Version", "—"), "פריטים": data.get("odata.count", "—"),
                                "קריאות API": h.calls}}
        except ConnectorError as exc:
            return {"ok": False, "message": str(exc), "details": {"status": exc.status}}
        finally:
            h.close()

    def collect(self) -> Collected:
        out = Collected()
        c = self.cfg
        h = self._http()
        try:
            self._login(h)
            groups = {g["Number"]: g.get("GroupName", "") for g in self._all(h, "ItemGroups", {"$select": "Number,GroupName"})}
            sup = c.get("supplier_field") or "Mainsupplier"
            rows = self._all(h, "Items", {"$select": ",".join([
                "ItemCode", "ItemName", "ForeignName", "ItemsGroupCode", "InventoryUOM", "Valid", "Frozen", "QuantityOnStock",
                "AvgStdPrice", "SupplierCatalogNo", "LeadTime", "ProcurementMethod", "CreateDate",
                "ItemWarehouseInfoCollection", sup])})
            for r in rows:
                active = r.get("Valid", "tYES") == "tYES" and r.get("Frozen", "tNO") != "tYES"
                it = ErpItem(source_id=self.source_id, pn=str(r["ItemCode"]), description=str(r.get("ItemName") or ""),
                             description_en=str(r.get("ForeignName") or ""), uom=str(r.get("InventoryUOM") or ""),
                             family=groups.get(r.get("ItemsGroupCode"), str(r.get("ItemsGroupCode") or "")),
                             status="פעיל" if active else "לא פעיל", active=active,
                             make_buy={"bom_Make": "make", "bom_Buy": "buy"}.get(r.get("ProcurementMethod"), ""),
                             unit_cost=to_float(r.get("AvgStdPrice")), currency="ILS", supplier=str(r.get(sup) or ""),
                             supplier_pn=str(r.get("SupplierCatalogNo") or ""), lead_time_days=to_float(r.get("LeadTime")),
                             created=str(r.get("CreateDate") or "")[:10])
                for w in r.get("ItemWarehouseInfoCollection") or []:
                    q = to_float(w.get("InStock")) or 0.0
                    it.stock[str(w.get("WarehouseCode"))] = q
                it.stock_total = sum(it.stock.values()) if it.stock else (to_float(r.get("QuantityOnStock")) or 0.0)
                out.erp_items.append(it)
            for t in self._all(h, "ProductTrees", {"$select": "TreeCode,Quantity,ProductTreeLines"}):
                base = to_float(t.get("Quantity")) or 1.0
                for line in t.get("ProductTreeLines") or []:
                    out.bom.append(BomLine(self.source_id, t["TreeCode"], str(line.get("ItemCode")),
                                           (to_float(line.get("Quantity")) or 1.0) / base))
            out.stats = {"items": len(out.erp_items), "bom_lines": len(out.bom), "api_calls": h.calls}
            try:
                h.post("Logout")
            except ConnectorError:
                pass
        finally:
            h.close()
        return out

