"""PTC Windchill connector (Windchill REST Services / WRS, OData v4)."""
from __future__ import annotations

from urllib.parse import quote

from ..model import PartRecord, classify_state
from .base import STEP_EXT, Collected, Connector, Field, mass_to_kg
from .http import ConnectorError, ReadOnlyHttp

_SELECT = ("ID,Number,Name,Version,Revision,State,Source,AssemblyMode,View,CreatedOn,LastModified,CreatedBy,"
           "ModifiedBy,FolderLocation,DefaultUnit")


class WindchillWrs(Connector):
    kind = "windchill"
    role = "pdm"
    title = "PTC Windchill"
    vendor = "PTC"
    interface = "Windchill REST Services (OData v4)"
    description = ("קריאת WTParts (מק\"ט, שם, גרסה, מצב מחזור חיים, ייצור/קנייה), מאפיינים (IBA), "
                   "מסמכי CAD, ייצוגים (Representations) עם קבצי STEP, ועץ מוצר (Uses).")
    fields = [
        Field("base_url", "כתובת שירות ה-OData", default="https://windchill.company.local/Windchill/servlet/odata",
              required=True, help="בדרך כלל https://<שרת>/Windchill/servlet/odata"),
        Field("username", "שם משתמש", required=True),
        Field("password", "סיסמה", type="password", required=True),
        Field("domain_version", "גרסת דומיין ProdMgmt", default="", group="advanced",
              help="ריק = ברירת המחדל של השרת; למשל v6"),
        Field("verify_tls", "אימות תעודת אבטחה (TLS)", type="bool", default=True, group="advanced"),
        Field("attr_description", "מאפיין תיאור (IBA)", default="DESCRIPTION", group="mapping"),
        Field("attr_material", "מאפיין חומר (IBA)", default="PTC_MATERIAL_NAME", group="mapping"),
        Field("attr_mass", "מאפיין משקל (IBA)", default="PRO_MP_MASS", group="mapping"),
        Field("attr_finish", "מאפיין גימור (IBA)", default="FINISH", group="mapping"),
        Field("filter", "סינון ($filter)", default="", group="advanced", help="למשל startswith(Number,'00000')"),
        Field("page_size", "גודל עמוד", type="number", default=1000, group="advanced"),
    ]
    unconfirmed = ["שמות מאפייני ה-IBA (חומר/משקל) מוגדרים אצל כל לקוח – יש לעדכן במיפוי",
                   "פורמט STEP בייצוגים (Representations) תלוי בהגדרות WVS באתר"]

    def _http(self) -> ReadOnlyHttp:
        return ReadOnlyHttp(self.cfg["base_url"].rstrip("/") + "/", auth=(self.cfg["username"], self.cfg["password"]),
                            verify=bool(self.cfg.get("verify_tls", True)), headers={"Accept": "application/json"})

    def _dom(self, name: str) -> str:
        v = (self.cfg.get("domain_version") or "").strip()
        return f"{v}/{name}" if v else name

    def test(self) -> dict:
        h = self._http()
        try:
            r = h.get("PTC/GetWindchillVersion()")
            if r.status_code == 401:
                raise ConnectorError("שם משתמש או סיסמה שגויים", status=401)
            ver = r.json().get("value", "—") if r.status_code == 200 else "—"
            data = h.json("GET", f"{self._dom('ProdMgmt')}/Parts", params={"$top": 1, "$count": "true",
                                                                          "$select": "ID,Number"})
            return {"ok": True, "message": "מחובר ל-PTC Windchill",
                    "details": {"גרסת שרת": ver, "WTParts": data.get("@odata.count", "—"), "קריאות API": h.calls}}
        except ConnectorError as exc:
            return {"ok": False, "message": str(exc), "details": {"status": exc.status}}
        finally:
            h.close()

    def collect(self) -> Collected:
        out = Collected()
        c = self.cfg
        h = self._http()
        try:
            self.progress("מתחבר ל-PTC Windchill", 0, 0)
            extra = [c["attr_description"], c["attr_material"], c["attr_mass"], c["attr_finish"]]
            params = {"$select": _SELECT + "," + ",".join(a for a in extra if a), "ptc.search.latestversion": "true",
                      "$count": "true"}
            if c.get("filter"):
                params["$filter"] = c["filter"]
            parts, url, first = [], f"{self._dom('ProdMgmt')}/Parts", True
            hdr = {"Prefer": f"odata.maxpagesize={int(c.get('page_size') or 1000)}"}
            while url:
                data = h.json("GET", url, params=params if first else None, headers=hdr)
                first = False
                parts.extend(data.get("value", []))
                self.progress("קורא WTParts מ-Windchill", len(parts), data.get("@odata.count") or len(parts))
                url = data.get("@odata.nextLink")
            for i, p in enumerate(parts):
                if self.stopped():
                    break
                self.progress("קורא מסמכי CAD וקבצי STEP", i, len(parts))
                st = p.get("State") or {}
                state = st.get("Display") or st.get("Value") or ""
                source = ((p.get("Source") or {}).get("Value") if isinstance(p.get("Source"), dict)
                          else p.get("Source")) or ""
                key = quote(p["ID"], safe=":")
                cad = None
                try:
                    assoc = h.json("GET", f"{self._dom('ProdMgmt')}/Parts('{key}')/PartDocAssociations",
                                   params={"$expand": "RelatedCADDoc"})
                    for a in assoc.get("value", []):
                        if a.get("RelatedCADDoc"):
                            cad = a["RelatedCADDoc"]
                            break
                except ConnectorError:
                    pass
                cat = ((cad or {}).get("Category") or {}).get("Value", "")
                is_asm = cat == "CADASSEMBLY" or (cad is None and (p.get("AssemblyMode") or {}).get("Value") == "separable")
                rec = PartRecord(
                    uid=self.uid(p["ID"]), source_id=self.source_id, source_kind=self.kind, native_id=p["ID"],
                    kind="assembly" if is_asm else "part", pn=str(p.get("Number") or ""), name=str(p.get("Name") or ""),
                    description=str(p.get(c["attr_description"]) or ""), revision=str(p.get("Revision") or ""),
                    version=str(p.get("Version") or ""), state=state, state_class=classify_state(state),
                    material=str(p.get(c["attr_material"]) or ""), mass_kg=mass_to_kg(p.get(c["attr_mass"])),
                    mass_text="" if p.get(c["attr_mass"]) is None else str(p.get(c["attr_mass"])),
                    finish=str(p.get(c["attr_finish"]) or ""), make_buy=source if source in ("make", "buy") else "",
                    author=str(p.get("CreatedBy") or ""), created=str(p.get("CreatedOn") or "")[:10],
                    modified=str(p.get("LastModified") or "")[:10], native_file=str((cad or {}).get("FileName") or ""),
                    folder=str(p.get("FolderLocation") or ""), cad_app="Creo" if cad else "",
                    props={k: v for k, v in p.items() if not k.startswith("@") and v not in (None, "")})
                if not is_asm:
                    self._step(h, rec, cad)
                else:
                    uses = h.json("GET", f"{self._dom('ProdMgmt')}/Parts('{key}')/Uses",
                                  params={"$expand": "Uses($select=ID,Number)"})
                    for u in uses.get("value", []):
                        child = u.get("Uses") or {}
                        if child.get("ID"):
                            rec.children.append({"child": self.uid(child["ID"]), "qty": float(u.get("Quantity") or 1),
                                                 "by": "uid"})
                out.records.append(rec)
            out.stats = {"parts": len(parts), "records": len(out.records), "api_calls": h.calls}
        finally:
            h.close()
        return out

    def _step(self, h: ReadOnlyHttp, rec: PartRecord, cad: dict | None) -> None:
        if not cad:
            rec.step_note = "לא נמצא מסמך CAD משויך ל-WTPart"
            return
        try:
            reps = h.json("GET", f"{self._dom('CADDocumentMgmt')}/CADDocuments('{quote(cad['ID'], safe=':')}')/Representations")
        except ConnectorError as exc:
            rec.step_note = f"לא ניתן לקרוא ייצוגים: {exc}"
            return
        for rep in reps.get("value", []):
            for f in rep.get("AdditionalFiles") or []:
                name = str(f.get("FileName") or f.get("Label") or "")
                if str(f.get("Format", "")).upper() == "STEP" or name.lower().endswith(STEP_EXT):
                    dest = self.step_cache_path(cad["ID"], cad.get("Version", ""), name or "model.stp")
                    if not dest.exists():
                        try:
                            h.download(f["URL"], dest)
                        except ConnectorError as exc:
                            rec.step_note = f"הורדת קובץ ה-STEP נכשלה: {exc}"
                            return
                    rec.step_path, rec.step_name = str(dest), name
                    return
        rec.step_note = "אין קובץ STEP בייצוג ברירת המחדל (ניתן להגדיר פרסום STEP ב-WVS)"
