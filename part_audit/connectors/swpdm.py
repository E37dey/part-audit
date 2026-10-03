"""SOLIDWORKS PDM Professional connectors: Web API (REST, PDM 2022+) and COM API (Windows client)."""
from __future__ import annotations

from pathlib import Path

from ..model import PartRecord, classify_state
from .base import CAD_ASM_EXT, CAD_PART_EXT, STEP_EXT, Collected, Connector, Field, mass_to_kg, stem_key
from .http import ConnectorError, ReadOnlyHttp

_VAR_FIELDS = [
    Field("var_number", "משתנה מק\"ט בכרטיס", default="Number", group="mapping"),
    Field("var_description", "משתנה תיאור", default="Description", group="mapping"),
    Field("var_material", "משתנה חומר", default="Material", group="mapping"),
    Field("var_revision", "משתנה רוויזיה", default="Revision", group="mapping"),
    Field("var_mass", "משתנה משקל", default="Weight", group="mapping", help="מספר בק\"ג, או ערך עם יחידה (g / kg)"),
    Field("var_finish", "משתנה גימור", default="Finish", group="mapping"),
    Field("var_author", "משתנה מתכנן", default="Author", group="mapping"),
    Field("var_source", "משתנה ייצור/קנייה", default="Source", group="mapping"),
    Field("config", "תצורה לקריאת משתנים", default="@", group="mapping", help="@ = לשונית הקובץ (Custom)"),
    Field("bom_qty_column", "שם עמודת כמות ב-BOM", default="Quantity", group="mapping"),
]


class SwPdmWeb(Connector):
    kind = "swpdm_web"
    role = "pdm"
    title = "SOLIDWORKS PDM"
    vendor = "Dassault Systèmes"
    interface = "Web API (REST) – PDM Professional 2022 ומעלה"
    description = "קריאת קבצים, משתני כרטיס נתונים, מצבי Workflow, גרסאות, עץ מוצר וקבצי STEP דרך שרת ה-Web API."
    fields = [
        Field("base_url", "כתובת שרת Web API", default="http://pdm-server:65453/api/", required=True,
              help="כתובת השרת כפי שהוגדרה בכלי הניהול (Web API Servers), כולל /api/"),
        Field("vault", "שם הכספת (Vault)", default="EngVault", required=True),
        Field("username", "שם משתמש", required=True),
        Field("password", "סיסמה", type="password", required=True),
        Field("start_path", "תיקיית התחלה", default="", help="ריק = כל הכספת"),
        Field("verify_tls", "אימות תעודת אבטחה (TLS)", type="bool", default=True, group="advanced"),
        *_VAR_FIELDS,
    ]
    unconfirmed = ["מבנה שורת BOM מחושב (BOMRow) לא מפורסם – הכמות נקראת לפי שם העמודה שבהגדרות",
                   "מבנה FileRef (references/whereused) לא מפורסם – נקרא באופן סלחני"]

    def _http(self) -> ReadOnlyHttp:
        base = self.cfg["base_url"].rstrip("/") + "/"
        vault = self.cfg["vault"]
        return ReadOnlyHttp(base, allowed=[("POST", rf"/{vault}/authenticate$"), ("POST", rf"/{vault}/searchvariables$"),
                                           ("POST", rf"/{vault}/search$"), ("POST", rf"/{vault}/files/info(frompath)?$")],
                            verify=bool(self.cfg.get("verify_tls", True)), headers={"Accept": "application/json"})

    def _login(self, h: ReadOnlyHttp) -> None:
        r = h.post(f"{self.cfg['vault']}/authenticate",
                   json={"Username": self.cfg["username"], "Password": self.cfg["password"]})
        if r.status_code == 404:
            raise ConnectorError(f"הכספת '{self.cfg['vault']}' לא נמצאה בשרת ה-Web API", status=404)
        if r.status_code != 200 or not (r.json() or {}).get("JwtString"):
            raise ConnectorError("ההתחברות ל-SOLIDWORKS PDM נכשלה – בדקו שם משתמש וסיסמה", status=r.status_code)
        h.client.headers["Authorization"] = f"Bearer {r.json()['JwtString']}"

    def test(self) -> dict:
        h = self._http()
        try:
            ver = h.get("version/webapi")
            info = ver.json() if ver.status_code == 200 else {}
            self._login(h)
            files = self._list(h, limit_hint=True)
            n_parts = sum(1 for f in files if f["Name"].lower().endswith(CAD_PART_EXT))
            n_step = sum(1 for f in files if f["Name"].lower().endswith(STEP_EXT))
            return {"ok": True, "message": f"מחובר ל-SOLIDWORKS PDM, כספת {self.cfg['vault']}",
                    "details": {"גרסת שרת": info.get("ProdAppVersion", "—"), "קבצי חלקים": n_parts,
                                "קבצי STEP": n_step, "קריאות API": h.calls}}
        except ConnectorError as exc:
            return {"ok": False, "message": str(exc), "details": {"status": exc.status}}
        finally:
            h.close()

    def _list(self, h: ReadOnlyHttp, limit_hint: bool = False) -> list[dict]:
        body = {"Name": "", "ObjectTypeCriteria": 1, "StartPath": self.cfg.get("start_path") or "",
                "PathCriteria": 2 if self.cfg.get("start_path") else 3, "VersionCriteria": 1, "SearchOperand": 0,
                "Variables": []}
        r = h.post(f"{self.cfg['vault']}/searchvariables", json=body)
        if r.status_code == 404:  # server older than 2024: walk the folder tree instead
            return self._walk(h)
        if r.status_code != 200:
            raise ConnectorError("החיפוש בכספת נכשל", status=r.status_code, detail=r.text[:300])
        seen, out = set(), []
        for o in r.json():
            if o.get("Type", 1) == 1 and o["Id"] not in seen and not o.get("IsDeleted"):
                seen.add(o["Id"])
                out.append(o)
        return out

    def _walk(self, h: ReadOnlyHttp) -> list[dict]:
        out, stack = [], [1]
        while stack:
            fid = stack.pop()
            for o in h.json("GET", f"{self.cfg['vault']}/folders/{fid}/browse"):
                if o.get("Type") == 0:
                    stack.append(o["Id"])
                elif o.get("Type") == 1:
                    out.append(o)
        return out

    def _vars(self, h: ReadOnlyHttp, o: dict) -> dict:
        cfgs = h.json("GET", f"{self.cfg['vault']}/files/{o['Id']}/{o['Version']}/variables")
        want = self.cfg.get("config") or "@"
        chosen = next((c for c in cfgs if c.get("ConfigurationName") == want), None) or (cfgs[0] if cfgs else {})
        vals = {m.get("VarName"): m.get("VarValue") for m in chosen.get("Models", [])}
        for c in cfgs:  # values missing on the file tab may live on a configuration
            for m in c.get("Models", []):
                vals.setdefault(m.get("VarName"), m.get("VarValue"))
        return vals

    def collect(self) -> Collected:
        out = Collected()
        h = self._http()
        try:
            self.progress("מתחבר ל-SOLIDWORKS PDM", 0, 0)
            self._login(h)
            files = self._list(h)
            native = [o for o in files if o["Name"].lower().endswith(CAD_PART_EXT + CAD_ASM_EXT)]
            steps = [o for o in files if o["Name"].lower().endswith(STEP_EXT)]
            step_by_key = {(o["ParentFolderId"], stem_key(o["Name"])): o for o in steps}
            step_by_stem = {}
            for o in steps:
                step_by_stem.setdefault(stem_key(o["Name"]), []).append(o)
            c = self.cfg
            for i, o in enumerate(native):
                if self.stopped():
                    break
                self.progress("קורא כרטיסי נתונים מ-SOLIDWORKS PDM", i, len(native))
                vals = self._vars(h, o)
                is_asm = o["Name"].lower().endswith(CAD_ASM_EXT)
                rec = PartRecord(
                    uid=self.uid(o["Id"]), source_id=self.source_id, source_kind=self.kind, native_id=str(o["Id"]),
                    kind="assembly" if is_asm else "part", pn=str(vals.get(c["var_number"]) or "").strip(),
                    name=str(vals.get(c["var_description"]) or "").strip(), description="",
                    revision=str(vals.get(c["var_revision"]) or ""), version=str(o.get("Version", "")),
                    state=o.get("State", ""), state_class=classify_state(o.get("State", "")),
                    material=str(vals.get(c["var_material"]) or ""), finish=str(vals.get(c["var_finish"]) or ""),
                    mass_kg=mass_to_kg(vals.get(c["var_mass"])), mass_text=str(vals.get(c["var_mass"]) or ""),
                    author=str(vals.get(c["var_author"]) or ""),
                    make_buy=_make_buy(vals.get(c["var_source"])), modified=str(o.get("ModifiedDate", ""))[:10],
                    native_file=o["Name"], folder=o.get("Path", ""), cad_app="SOLIDWORKS",
                    props={k: v for k, v in vals.items() if v not in (None, "")} | {"IsToolbox": o.get("IsToolbox", 0)})
                if o.get("IsToolbox") and not rec.make_buy:
                    rec.make_buy = "buy"
                if not is_asm:
                    s = step_by_key.get((o["ParentFolderId"], stem_key(o["Name"])))
                    if s is None:
                        cands = step_by_stem.get(stem_key(o["Name"]), [])
                        s = cands[0] if len(cands) == 1 else None
                    if s is not None:
                        dest = self.step_cache_path(s["Id"], s["Version"], s["Name"])
                        if not dest.exists():
                            h.download(f"{c['vault']}/files/{s['Id']}/{s['Version']}/download",
                                       dest, params={"folderId": s["ParentFolderId"]})
                        rec.step_path, rec.step_name = str(dest), s["Name"]
                    else:
                        rec.step_note = "אין קובץ STEP בכספת לחלק הזה (ניתן להפיק ב-Convert Task של PDM)"
                try:
                    hist = h.json("GET", f"{c['vault']}/files/{o['Id']}/versions", params={"folderId": o["ParentFolderId"]})
                    rec.history = _history(hist)
                except ConnectorError:
                    pass
                if is_asm:
                    rec.children = self._bom(h, o)
                out.records.append(rec)
            out.stats = {"files": len(files), "native": len(native), "step_files": len(steps),
                         "records": len(out.records), "api_calls": h.calls}
        finally:
            h.close()
        return out

    def _bom(self, h: ReadOnlyHttp, o: dict) -> list[dict]:
        c = self.cfg
        try:
            info = h.json("GET", f"{c['vault']}/files/{o['Id']}/bominfo", params={"folderId": o["ParentFolderId"]})
            lst = ((info or {}).get("ComputedBOM") or {}).get("BOMList") or []
            if lst:
                bom_id = lst[0].get("BOMId", 1)
                data = h.json("GET", f"{c['vault']}/bom/{bom_id}/{o['Id']}/{o['Version']}/{o['ParentFolderId']}/computed",
                              params={"configId": -1, "latest": "true"})
                cols = {col.get("ColumnName", "").lower(): col.get("ColumnNo") for col in data.get("Columns", [])}
                qcol = cols.get(str(c.get("bom_qty_column") or "quantity").lower())
                kids = []
                for ref in (data.get("File") or {}).get("References", []):
                    row = ref.get("File") or {}
                    vals = row.get("Values") or []
                    qty = 1.0
                    if qcol is not None and qcol < len(vals):
                        try:
                            qty = float(vals[qcol])
                        except (TypeError, ValueError):
                            qty = 1.0
                    if row.get("FileId") is not None:
                        kids.append({"child": self.uid(row["FileId"]), "qty": qty, "by": "uid"})
                if kids:
                    return kids
        except ConnectorError:
            pass
        refs = h.json("GET", f"{c['vault']}/files/{o['Id']}/{o['Version']}/references",
                      params={"configId": -1, "folderId": o["ParentFolderId"]})
        kids = []
        for ref in refs.get("References", []):
            f = (ref.get("File") or {}).get("File") or {}
            fid = f.get("FileId") or f.get("FileID")
            if fid is not None:
                kids.append({"child": self.uid(fid), "qty": 1.0, "by": "uid"})
        return kids


def _make_buy(v) -> str:
    s = str(v or "").strip().lower()
    if s in ("קנייה", "קניה", "buy", "purchased", "purchase", "רכש"):
        return "buy"
    if s in ("ייצור", "make", "manufactured", "יצור"):
        return "make"
    return ""


def _history(rows: list[dict]) -> list[dict]:
    out, rev = [], ""
    for row in sorted(rows, key=lambda x: (x.get("VersionDate") or "", x.get("InfoType", 0))):
        if row.get("InfoType") == 1:
            rev = row.get("Revision") or rev
            if out:
                out[-1]["revision"] = rev
        elif row.get("InfoType") == 0:
            out.append({"version": row.get("VersionNumber"), "revision": rev, "date": (row.get("VersionDate") or "")[:10],
                        "comment": row.get("Text", "")})
    return out


class SwPdmCom(Connector):
    """COM API of the PDM client (Windows only, pywin32). Used when the Web API server is not installed."""
    kind = "swpdm_com"
    role = "pdm"
    title = "SOLIDWORKS PDM (COM)"
    vendor = "Dassault Systèmes"
    interface = "COM API של לקוח PDM (Windows בלבד)"
    description = ("לשימוש כשאין שרת Web API: קורא דרך לקוח ה-PDM המותקן במחשב (נדרש Windows, לקוח PDM ו-pywin32). "
                   "קבצי STEP מועתקים מהכספת לתיקיית מטמון מקומית בלבד.")
    fields = [
        Field("vault", "שם הכספת (Vault)", default="EngVault", required=True),
        Field("vault_path", "נתיב תצוגת הכספת", default=r"C:\PDM\EngVault", required=True),
        Field("start_folder", "תת-תיקייה לסריקה", default=""),
        *_VAR_FIELDS,
    ]
    verification = ("נכתב לפי תיעוד ה-API הרשמי (IEdmVault5 / IEdmFile5). דורש מחשב Windows עם לקוח PDM; "
                    "לא ניתן לבדוק אותו מול הסימולטור ולכן טרם נבדק.")
    unconfirmed = ["החזרת ערכי ByRef ב-pywin32 (GetVar) – לפי דוגמאות קהילה", "ProgID ConisioLib.EdmVault – לפי דוגמאות קהילה"]

    def _vault(self):
        try:
            import win32com.client as w32  # type: ignore
        except ImportError as exc:
            raise ConnectorError("חיבור COM דורש Windows עם pywin32 ולקוח SOLIDWORKS PDM מותקן") from exc
        vault = w32.Dispatch("ConisioLib.EdmVault")
        if not vault.IsLoggedIn:
            vault.LoginAuto(self.cfg["vault"], 0)
        return vault

    def test(self) -> dict:
        try:
            vault = self._vault()
            root = vault.GetFolderFromPath(self.cfg["vault_path"])
            return {"ok": root is not None, "message": "מחובר דרך לקוח PDM" if root else "תיקיית הכספת לא נמצאה",
                    "details": {}}
        except Exception as exc:  # COM errors are not typed
            return {"ok": False, "message": f"החיבור נכשל: {exc}", "details": {}}

    def collect(self) -> Collected:
        out = Collected()
        vault = self._vault()
        base = Path(self.cfg["vault_path"]) / (self.cfg.get("start_folder") or "")
        folder = vault.GetFolderFromPath(str(base))
        stack = [folder]
        files = []
        while stack:
            f = stack.pop()
            pos = f.GetFirstFilePosition()
            while not pos.IsNull:
                files.append((f, f.GetNextFile(pos)))
            pos = f.GetFirstSubFolderPosition()
            while not pos.IsNull:
                stack.append(f.GetNextSubFolder(pos))
        steps = {}
        for fold, fl in files:
            if fl.Name.lower().endswith(STEP_EXT):
                steps[(fold.ID, stem_key(fl.Name))] = (fold, fl)
        c = self.cfg
        for i, (fold, fl) in enumerate(files):
            name = fl.Name
            if not name.lower().endswith(CAD_PART_EXT + CAD_ASM_EXT):
                continue
            self.progress("קורא קבצים דרך לקוח PDM", i, len(files))
            ev = fl.GetEnumeratorVariable("")
            vals = {}
            for key in ("var_number", "var_description", "var_material", "var_revision", "var_mass", "var_finish",
                        "var_author", "var_source"):
                res = ev.GetVar(c[key], c.get("config") or "@")
                found, value = (res if isinstance(res, tuple) else (True, res))
                if found and value not in (None, ""):
                    vals[c[key]] = value
            is_asm = name.lower().endswith(CAD_ASM_EXT)
            state = fl.CurrentState.Name if fl.CurrentState else ""
            rec = PartRecord(uid=self.uid(fl.ID), source_id=self.source_id, source_kind=self.kind,
                             native_id=str(fl.ID), kind="assembly" if is_asm else "part",
                             pn=str(vals.get(c["var_number"], "")), name=str(vals.get(c["var_description"], "")),
                             revision=str(fl.CurrentRevision or vals.get(c["var_revision"], "")),
                             version=str(fl.CurrentVersion), state=state, state_class=classify_state(state),
                             material=str(vals.get(c["var_material"], "")), mass_kg=mass_to_kg(vals.get(c["var_mass"])),
                             mass_text=str(vals.get(c["var_mass"], "")),
                             finish=str(vals.get(c["var_finish"], "")), author=str(vals.get(c["var_author"], "")),
                             make_buy=_make_buy(vals.get(c["var_source"])), native_file=name, folder=fold.LocalPath,
                             cad_app="SOLIDWORKS", props={k: str(v) for k, v in vals.items()})
            s = steps.get((fold.ID, stem_key(name)))
            if s and not is_asm:
                sf, sfile = s
                dest = self.step_cache_path(sfile.ID, sfile.CurrentVersion, sfile.Name)
                if not dest.exists():
                    sfile.GetFileCopy(0, 0, str(dest.parent) + "\\", 0, dest.name)
                rec.step_path, rec.step_name = str(dest), sfile.Name
            elif not is_asm:
                rec.step_note = "אין קובץ STEP בכספת לחלק הזה"
            if is_asm:
                tree = fl.GetReferenceTree(fold.ID, 0)
                try:  # IEdmReference10 (current); older clients only have the obsolete variant
                    pos = tree.GetFirstChildPosition4("", True, True, False, 0, "", 0)
                    pos = pos[0] if isinstance(pos, tuple) else pos
                except AttributeError:
                    pos = tree.GetFirstChildPosition("", True, True, 0)
                while not pos.IsNull:
                    ref = tree.GetNextChild(pos)
                    rec.children.append({"child": self.uid(ref.FileID), "qty": 1.0, "by": "uid"})
            out.records.append(rec)
        out.stats = {"records": len(out.records)}
        return out
