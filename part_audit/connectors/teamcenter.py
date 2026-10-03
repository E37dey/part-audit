"""Siemens Teamcenter connector (JSON REST interface of the SOA services, web tier /tc/JsonRestServices)."""
from __future__ import annotations

from urllib.parse import quote

from ..model import PartRecord, classify_state
from .base import STEP_EXT, Collected, Connector, Field, mass_to_kg
from .http import ConnectorError, ReadOnlyHttp

READ_OPS = [
    "Core-2011-06-Session/login", "Core-2006-03-Session/logout", "Core-2007-01-Session/getTCSessionInfo",
    "Query-2006-03-SavedQuery/getSavedQueries", "Query-2008-06-SavedQuery/executeSavedQueries",
    "Core-2006-03-DataManagement/getProperties", "Core-2007-09-DataManagement/expandGRMRelationsForPrimary",
    "Core-2006-03-FileManagement/getFileReadTickets", "Cad-2007-01-StructureManagement/createBOMWindows",
    "Cad-2007-01-StructureManagement/expandPSOneLevel", "Cad-2007-01-StructureManagement/closeBOMWindows",
]
REV_PROPS = ["item_id", "object_name", "object_desc", "item_revision_id", "release_status_list", "owning_user",
             "creation_date", "last_mod_date", "structure_revisions", "IMAN_specification"]


def _db(mo: dict, name: str) -> list[str]:
    return ((mo.get("props") or {}).get(name) or {}).get("dbValues") or []


def _ui(mo: dict, name: str) -> list[str]:
    return ((mo.get("props") or {}).get(name) or {}).get("uiValues") or []


def _first(values: list[str]) -> str:
    return values[0] if values else ""


class TeamcenterRest(Connector):
    kind = "teamcenter"
    role = "pdm"
    title = "Siemens Teamcenter"
    vendor = "Siemens"
    interface = "JSON REST של שירותי ה-SOA (Web tier)"
    description = ("קריאת Item Revisions (מק\"ט, שם, רוויזיה, סטטוס שחרור), מאפיינים, Datasets וקבצי STEP דרך FMS, "
                   "ועץ מוצר דרך חלונות BOM.")
    fields = [
        Field("base_url", "כתובת ה-Web tier", default="http://tc-web:7001/tc", required=True,
              help="הכתובת שמתחתיה נמצא JsonRestServices, למשל http://server:7001/tc"),
        Field("fms_url", "כתובת שרת FMS", default="", help="ריק = <שרת>/fms (כמו בשער Active Workspace)"),
        Field("username", "שם משתמש", required=True),
        Field("password", "סיסמה", type="password", required=True),
        Field("group", "קבוצה (Group)", default="", group="advanced"),
        Field("role", "תפקיד (Role)", default="", group="advanced"),
        Field("query_name", "שאילתה שמורה", default="Item Revision...", group="mapping"),
        Field("query_entry", "שדה בשאילתה", default="Item ID", group="mapping"),
        Field("query_value", "ערך לחיפוש", default="*", group="mapping"),
        Field("prop_material", "מאפיין חומר", default="u4_material", group="mapping"),
        Field("prop_mass", "מאפיין משקל", default="u4_mass", group="mapping"),
        Field("prop_finish", "מאפיין גימור", default="u4_finish", group="mapping"),
        Field("prop_make_buy", "מאפיין ייצור/קנייה", default="u4_make_buy", group="mapping"),
        Field("verify_tls", "אימות תעודת אבטחה (TLS)", type="bool", default=True, group="advanced"),
    ]
    unconfirmed = ["קידוד JSON של מפת הכרטיסים (tickets) – נתמכים כמה פורמטים",
                   "שם מאפיין הכמות בשורת BOM (bl_quantity)", "שמות מאפייני חומר/משקל מוגדרים אצל כל לקוח"]

    def _http(self) -> ReadOnlyHttp:
        base = self.cfg["base_url"].rstrip("/") + "/"
        allowed = [("POST", "/JsonRestServices/" + op.replace(".", r"\.") + "$") for op in READ_OPS]
        return ReadOnlyHttp(base, allowed=allowed, verify=bool(self.cfg.get("verify_tls", True)),
                            headers={"Accept": "application/json"})

    def _soa(self, h: ReadOnlyHttp, op: str, body: dict | None = None, policy: dict | None = None) -> dict:
        r = h.post(f"JsonRestServices/{op}", json={"header": {"state": {}, "policy": policy or {}}, "body": body or {}})
        try:
            data = r.json()
        except ValueError:
            raise ConnectorError(f"תשובה לא תקינה מ-{op}", status=r.status_code, detail=r.text[:300])
        if r.status_code != 200 or "Exception" in str(data.get(".QName", "")):
            raise ConnectorError(data.get("message") or f"השירות {op} נכשל", status=r.status_code)
        return data

    def _login(self, h: ReadOnlyHttp) -> dict:
        try:
            return self._soa(h, "Core-2011-06-Session/login", {"credentials": {
                "user": self.cfg["username"], "password": self.cfg["password"], "role": self.cfg.get("role") or "",
                "descrimator": "", "locale": "", "group": self.cfg.get("group") or ""}})
        except ConnectorError as exc:
            raise ConnectorError(f"ההתחברות ל-Teamcenter נכשלה: {exc}", status=exc.status)

    def test(self) -> dict:
        h = self._http()
        try:
            info = self._login(h).get("serverInfo", {})
            qs = self._soa(h, "Query-2006-03-SavedQuery/getSavedQueries").get("queries", [])
            names = [q.get("name") for q in qs]
            found = self.cfg["query_name"] in names
            self._soa(h, "Core-2006-03-Session/logout")
            return {"ok": found, "message": "מחובר ל-Siemens Teamcenter" if found else
                    f"מחובר, אך השאילתה '{self.cfg['query_name']}' לא נמצאה",
                    "details": {"גרסת שרת": info.get("DisplayVersion", "—"), "שאילתות שמורות": len(names),
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
            self.progress("מתחבר ל-Siemens Teamcenter", 0, 0)
            self._login(h)
            qs = self._soa(h, "Query-2006-03-SavedQuery/getSavedQueries").get("queries", [])
            q = next((x for x in qs if x.get("name") == c["query_name"]), None)
            if not q:
                raise ConnectorError(f"השאילתה השמורה '{c['query_name']}' לא נמצאה")
            res = self._soa(h, "Query-2008-06-SavedQuery/executeSavedQueries", {"input": [{
                "query": q["query"], "entries": [c["query_entry"]], "values": [c["query_value"]], "maxNumToReturn": 0,
                "maxNumToInflate": 0, "limitListCount": 0, "limitList": []}]})
            revs = [o for r in res.get("arrayOfResults", []) for o in r.get("objects", [])]
            attrs = REV_PROPS + [c["prop_material"], c["prop_mass"], c["prop_finish"], c["prop_make_buy"]]
            mos: dict[str, dict] = {}
            for i in range(0, len(revs), 200):
                self.progress("קורא מאפייני Item Revisions", i, len(revs))
                sd = self._soa(h, "Core-2006-03-DataManagement/getProperties",
                               {"objects": revs[i:i + 200], "attributes": attrs})
                mos.update(sd.get("modelObjects", {}))
            # datasets (IMAN_specification) -> ImanFiles -> STEP
            ds_of: dict[str, list[str]] = {}
            ds_mos: dict[str, dict] = {}
            for i in range(0, len(revs), 200):
                g = self._soa(h, "Core-2007-09-DataManagement/expandGRMRelationsForPrimary", {
                    "primaryObjects": revs[i:i + 200], "pref": {"expItemRev": False, "returnRelations": False,
                                                                "info": [{"relationTypeName": "IMAN_specification",
                                                                          "otherSideObjectTypes": []}]}},
                    policy={"types": [{"name": "Dataset", "properties": [{"name": "object_name"},
                                                                         {"name": "ref_list"}]}]})
                ds_mos.update((g.get("ServiceData") or {}).get("modelObjects", {}))
                for o in g.get("output", []):
                    uid = (o.get("inputObject") or {}).get("uid")
                    ds_of[uid] = [ro["otherSideObject"]["uid"] for rd in o.get("relationshipData", [])
                                  for ro in rd.get("relationshipObjects", [])]
            file_uids = sorted({f for mo in ds_mos.values() for f in _db(mo, "ref_list")})
            file_names: dict[str, str] = {}
            for i in range(0, len(file_uids), 200):
                sd = self._soa(h, "Core-2006-03-DataManagement/getProperties", {
                    "objects": [{"uid": u, "className": "ImanFile", "type": "ImanFile"} for u in file_uids[i:i + 200]],
                    "attributes": ["original_file_name"]})
                for u, mo in sd.get("modelObjects", {}).items():
                    file_names[u] = _first(_db(mo, "original_file_name"))
            step_of: dict[str, tuple[str, str]] = {}
            for rev_uid, dss in ds_of.items():
                for ds in dss:
                    for f in _db(ds_mos.get(ds, {}), "ref_list"):
                        name = file_names.get(f, "")
                        if name.lower().endswith(STEP_EXT):
                            step_of[rev_uid] = (f, name)
            tickets = self._tickets(h, [f for f, _ in step_of.values()])
            fms = (c.get("fms_url") or c["base_url"].rstrip("/").rsplit("/", 1)[0] + "/fms").rstrip("/") + "/"
            asm_revs = []
            for i, ref in enumerate(revs):
                if self.stopped():
                    break
                self.progress("מוריד קבצי STEP מ-FMS", i, len(revs))
                mo = mos.get(ref["uid"], {})
                status = ", ".join(x for x in _ui(mo, "release_status_list") if x)
                is_asm = bool([x for x in _db(mo, "structure_revisions") if x])
                mb = _first(_db(mo, c["prop_make_buy"])).lower()
                rec = PartRecord(
                    uid=self.uid(ref["uid"]), source_id=self.source_id, source_kind=self.kind, native_id=ref["uid"],
                    kind="assembly" if is_asm else "part", pn=_first(_db(mo, "item_id")),
                    name=_first(_db(mo, "object_name")), description=_first(_db(mo, "object_desc")),
                    revision=_first(_db(mo, "item_revision_id")), version="", state=status or "Working",
                    state_class=classify_state(status) if status else "in_work",
                    material=_first(_db(mo, c["prop_material"])), mass_kg=mass_to_kg(_first(_db(mo, c["prop_mass"]))),
                    mass_text=_first(_db(mo, c["prop_mass"])), finish=_first(_db(mo, c["prop_finish"])),
                    make_buy="buy" if mb in ("buy", "purchased", "קנייה") else ("make" if mb in ("make", "ייצור") else ""),
                    author=_first(_ui(mo, "owning_user")).split(" (")[0], created=_first(_db(mo, "creation_date"))[:10],
                    modified=_first(_db(mo, "last_mod_date"))[:10], cad_app="NX",
                    props={k: _first(_ui(mo, k)) for k in (mo.get("props") or {}) if _first(_ui(mo, k))})
                for ds in ds_of.get(ref["uid"], []):
                    for f in _db(ds_mos.get(ds, {}), "ref_list"):
                        nm = file_names.get(f, "")
                        if nm and not nm.lower().endswith(STEP_EXT):
                            rec.native_file = nm
                if ref["uid"] in step_of:
                    f, name = step_of[ref["uid"]]
                    t = tickets.get(f)
                    if t:
                        dest = self.step_cache_path(f, rec.revision, name)
                        if not dest.exists():
                            try:
                                h.download(f"{fms}{quote(name)}", dest, params={"ticket": t})
                            except ConnectorError as exc:
                                rec.step_note = f"הורדת קובץ ה-STEP נכשלה: {exc}"
                        if dest.exists():
                            rec.step_path, rec.step_name = str(dest), name
                elif not is_asm:
                    rec.step_note = "אין Dataset של STEP ל-Item Revision הזה"
                if is_asm:
                    asm_revs.append((rec, ref))
                out.records.append(rec)
            self._boms(h, asm_revs)
            out.stats = {"revisions": len(revs), "records": len(out.records), "step_files": len(step_of),
                         "api_calls": h.calls}
            try:
                self._soa(h, "Core-2006-03-Session/logout")
            except ConnectorError:
                pass
        finally:
            h.close()
        return out

    def _tickets(self, h: ReadOnlyHttp, files: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for i in range(0, len(files), 200):
            data = self._soa(h, "Core-2006-03-FileManagement/getFileReadTickets",
                             {"files": [{"uid": f, "className": "ImanFile", "type": "ImanFile"} for f in files[i:i + 200]]})
            t = data.get("tickets")
            if isinstance(t, list) and len(t) == 2 and isinstance(t[0], list):      # [[keys], [values]]
                for k, v in zip(t[0], t[1]):
                    out[k.get("uid") if isinstance(k, dict) else k] = v
            elif isinstance(t, dict):                                               # {uid: ticket}
                out.update(t)
            elif isinstance(t, list):                                               # [{key, value}]
                for e in t:
                    k = e.get("key")
                    out[k.get("uid") if isinstance(k, dict) else k] = e.get("value")
        return out

    def _boms(self, h: ReadOnlyHttp, asm_revs: list) -> None:
        if not asm_revs:
            return
        rule = {"clientId": "", "revRule": "", "props": {"unitNo": -1, "date": "0001-01-01T00:00:00", "today": True,
                                                         "endItem": "", "endItemRevision": ""}}
        win = self._soa(h, "Cad-2007-01-StructureManagement/createBOMWindows", {"info": [
            {"clientId": rec.uid, "itemRev": ref, "revRuleConfigInfo": rule} for rec, ref in asm_revs]})
        outs = win.get("output", [])
        try:
            by_client = {o.get("clientId"): o for o in outs}
            lines = [by_client[rec.uid]["bomLine"]["uid"] for rec, _ in asm_revs if rec.uid in by_client]
            exp = self._soa(h, "Cad-2007-01-StructureManagement/expandPSOneLevel",
                            {"input": {"parentBomLines": lines, "excludeFilter": "None"},
                             "pref": {"expItemRev": False, "info": []}},
                            policy={"types": [{"name": "BOMLine", "properties": [{"name": "bl_quantity"}]}]})
            mos = (exp.get("ServiceData") or {}).get("modelObjects", {})
            rec_by_line = {by_client[rec.uid]["bomLine"]["uid"]: rec for rec, _ in asm_revs if rec.uid in by_client}
            for o in exp.get("output", []):
                rec = rec_by_line.get(((o.get("parent") or {}).get("bomLine") or {}).get("uid"))
                if not rec:
                    continue
                for ch in o.get("children", []):
                    rev = (ch.get("itemRevOfBOMLine") or {}).get("uid")
                    q = _first(_db(mos.get((ch.get("bomLine") or {}).get("uid"), {}), "bl_quantity"))
                    try:
                        qty = float(q) if q else 1.0
                    except ValueError:
                        qty = 1.0
                    if rev:
                        rec.children.append({"child": self.uid(rev), "qty": qty, "by": "uid"})
        finally:
            self._soa(h, "Cad-2007-01-StructureManagement/closeBOMWindows",
                      {"bomWindows": [o["bomWindow"]["uid"] for o in outs if o.get("bomWindow")]})
