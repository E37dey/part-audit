"""SOLIDWORKS PDM Professional Web API simulator (REST, PDM 2022+ Web API shapes).

Implements the read endpoints the connector uses: authenticate, version/webapi, searchvariables,
folders/{id}/browse, files/{id}/{ver}/variables, files/{id}/versions, files/{id}/{ver}/info/extended,
files/{id}/{ver}/references, files/{id}/{ver}/whereused, files/{id}/bominfo,
bom/{type}/{file}/{ver}/{folder}/computed, files/{id}/{ver}/download (302 to content).
Model shapes follow the official "Sample Data" (ObjectInfo, ConfigInfo/VariableInfo, FileRevisionInfo,
FileRef, BOMInfo). Shapes the vendor does not publish (FileRef casing, computed BOM rows) are marked
in docs/research/pdm_plm_apis.md.
"""
from __future__ import annotations

import secrets
from functools import lru_cache

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from .data import DEMO_PASSWORD, DEMO_USER, FASTENER_FAMS, FactoryData, factory, token

VAULT = "EngVault"
_TOKENS: dict[str, str] = {}


class _Vault:
    """Folders and file objects of the simulated vault, built from the factory records."""

    def __init__(self, fd: FactoryData):
        self.fd = fd
        recs = [r for r in fd.by_system["swpdm"]]
        self.folders: dict[int, dict] = {1: {"id": 1, "path": "\\", "name": "", "parent": 0}}
        self._fid_by_path = {"\\": 1}
        # project folder per product (top assembly) from the BOM structure
        top = [r for r in recs if r["kind"] == "assembly" and not fd.parents.get(r["rid"])]
        home: dict[str, str] = {}
        for t in top:
            proj = t["name"].split()[-1]
            self._walk(t, f"\\פרויקטים\\{proj}\\", home)
        self.files: dict[int, dict] = {}
        for r in recs:
            if r["kind"] == "part" and r["rid"] not in home:
                if r["family"] in FASTENER_FAMS:
                    home[r["rid"]] = "\\ספריה\\ברגים ואומים\\"
                elif r["family"] == "bearing":
                    home[r["rid"]] = "\\ספריה\\מסבים\\"
                elif r["make_buy"] == "buy":
                    home[r["rid"]] = "\\ספריה\\רכיבי קנייה\\"
                elif r["family"] == "nist":
                    home[r["rid"]] = "\\מודלים לבדיקה\\"
                else:
                    home[r["rid"]] = "\\חלקים כלליים\\"
            elif r["rid"] not in home:
                home[r["rid"]] = "\\פרויקטים\\"
        self.by_rid: dict[str, dict] = {}
        for r in recs:
            folder = self._folder(home[r["rid"]])
            fid = r["native_id"] * 10
            obj = {"Id": fid, "Name": r["native_file"], "Size": 0, "ModifiedDate": r["modified"] + "T10:00:00+03:00",
                   "Version": r["version"], "State": r["state"], "StateId": _state_id(r["state"]),
                   "ParentFolderId": folder, "Path": self.folders[folder]["path"], "Type": 1, "IsLocked": 0,
                   "LockedBy": 0, "IsShared": 0, "IsToolbox": 1 if r["family"] in FASTENER_FAMS else 0, "IsDeleted": 0}
            self.files[fid] = {"obj": obj, "rec": r, "kind": "native"}
            self.by_rid[r["rid"]] = obj
            step = fd.step_file(r)
            if step is not None:
                stem = r["native_file"].rsplit(".", 1)[0]
                sobj = dict(obj, Id=fid + 1, Name=stem + ".STEP", Version=1, Size=step.stat().st_size, IsToolbox=0)
                self.files[fid + 1] = {"obj": sobj, "rec": r, "kind": "step", "path": step}

    def _walk(self, asm: dict, path: str, home: dict) -> None:
        if asm["rid"] in home:
            return
        home[asm["rid"]] = path
        for line in asm.get("bom", []):
            ch = self.fd.by_rid[line["child"]]
            if ch["kind"] == "assembly":
                self._walk(ch, path, home)
            elif ch["make_buy"] == "make":
                home.setdefault(ch["rid"], path)

    def _folder(self, path: str) -> int:
        if path in self._fid_by_path:
            return self._fid_by_path[path]
        parts = [p for p in path.split("\\") if p]
        cur = "\\"
        parent = 1
        for p in parts:
            cur = cur + p + "\\"
            if cur not in self._fid_by_path:
                nid = len(self.folders) + 1
                self.folders[nid] = {"id": nid, "path": cur, "name": p, "parent": parent}
                self._fid_by_path[cur] = nid
            parent = self._fid_by_path[cur]
        return parent

    def variables(self, f: dict) -> list[dict]:
        r = f["rec"]
        vals = {"Number": r["pn"], "Description": r["description"] or r["name"], "Revision": r["revision"],
                "Material": r.get("material_text", ""), "Weight": _fmt_mass(r.get("mass_recorded_kg")),
                "Finish": r.get("finish_text", ""), "Author": r["author"],
                "Source": "קנייה" if r["make_buy"] == "buy" else "ייצור"}
        if f["kind"] == "step":
            vals = {"Number": r["pn"], "Description": r["description"] or r["name"]}
        models = []
        for i, (k, v) in enumerate(vals.items(), start=1):
            if v in (None, ""):
                continue
            models.append({"VarId": i, "VarName": k, "VarValue": str(v), "VarType": 1, "Mandatory": k == "Number",
                           "VersionFree": False})
        cfgs = [{"ConfigurationName": "@", "ConfigurationId": 0, "Models": models}]
        if f["kind"] == "native" and r["kind"] == "part":
            cfgs.append({"ConfigurationName": "Default", "ConfigurationId": 2,
                         "Models": [m for m in models if m["VarName"] in ("Number", "Description")]})
        return cfgs


def _state_id(state: str) -> int:
    return {"In Work": 2, "Pending Approval": 3, "Released": 4, "Obsolete": 5}.get(state, 1)


def _fmt_mass(m) -> str:
    if m is None:
        return ""
    return f"{m:.4f}" if m < 1 else f"{m:.3f}"


@lru_cache(maxsize=4)
def _vault(root: str) -> _Vault:
    return _Vault(factory(root))


def router(root: str) -> APIRouter:
    r = APIRouter(prefix="/sim/swpdm")

    def v() -> _Vault:
        return _vault(root)

    def auth(authorization: str | None):
        if not authorization or not authorization.startswith("Bearer ") or authorization[7:] not in _TOKENS:
            raise HTTPException(401, "Authorization has been denied for this request.")

    def check_vault(vault: str):
        if vault != VAULT:
            raise HTTPException(404, f"Vault '{vault}' not found")

    @r.get("/api/version/webapi")
    def version():
        return {"SwCompany": "Dassault Systemes SolidWorks Corp. (simulator)", "SWCopyright": "",
                "ProdName": "SOLIDWORKS PDM Web API – simulator", "ProdAppVersion": "2024 SP3 (sim)",
                "ProdFileVersion": "32.3.0.0"}

    @r.post("/api/{vault}/authenticate")
    async def authenticate(vault: str, request: Request):
        check_vault(vault)
        body = await request.json()
        user = body.get("Username") or body.get("username")
        pw = body.get("Password") or body.get("password")
        if user != DEMO_USER or pw != DEMO_PASSWORD:
            return JSONResponse({"Success": False, "JwtString": None, "Message": "Invalid user name or password"}, 401)
        tok = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9." + secrets.token_urlsafe(24)
        _TOKENS[tok] = user
        return {"Success": True, "JwtString": tok, "UserInfo": {"UserId": 2, "UserName": user}}

    @r.get("/api/configuration/vaults")
    def vaults(authorization: str | None = Header(None)):
        auth(authorization)
        return [{"Name": VAULT, "DatabaseName": VAULT, "ArchiveServer": "pdm-archive", "ArchiveServerPort": 3030,
                 "DatabaseServer": "pdm-sql", "CommandTimeOut": 300, "IndexingUserId": 0}]

    @r.post("/api/{vault}/searchvariables")
    async def searchvariables(vault: str, request: Request, authorization: str | None = Header(None)):
        auth(authorization)
        check_vault(vault)
        body = await request.json()
        name = (body.get("Name") or "").lower()
        start = (body.get("StartPath") or "").strip("\\")
        crit = int(body.get("PathCriteria") or 3)
        out = []
        for f in v().files.values():
            o = f["obj"]
            if name and not _like(o["Name"].lower(), name):
                continue
            path = o["Path"].strip("\\")
            if start and crit == 1 and path != start:
                continue
            if start and crit == 2 and not (path == start or path.startswith(start + "\\")):
                continue
            ok = True
            for cond in body.get("Variables") or []:
                vals = {m["VarName"]: m["VarValue"] for c in v().variables(f) for m in c["Models"]}
                if not _like(str(vals.get(cond.get("VariableName"), "")).lower(), str(cond.get("SearchValue", "")).lower()):
                    ok = False
            if ok:
                out.append(o)
        return out

    @r.get("/api/{vault}/folders/{folder_id}/browse")
    def browse(vault: str, folder_id: int, authorization: str | None = Header(None)):
        auth(authorization)
        check_vault(vault)
        if folder_id not in v().folders:
            raise HTTPException(404, "Folder not found")
        out = []
        for f in v().folders.values():
            if f["parent"] == folder_id and f["id"] != folder_id:
                out.append({"Id": f["id"], "Name": f["name"], "Size": 0, "ModifiedDate": "2024-01-01T00:00:00+02:00",
                            "Version": 0, "State": "", "StateId": 0, "ParentFolderId": folder_id, "Path": f["path"],
                            "Type": 0, "IsLocked": 0, "LockedBy": 0, "IsShared": 0, "IsToolbox": 0, "IsDeleted": 0})
        out += [f["obj"] for f in v().files.values() if f["obj"]["ParentFolderId"] == folder_id]
        return out

    def get_file(fid: int) -> dict:
        f = v().files.get(fid)
        if not f:
            raise HTTPException(404, "File not found")
        return f

    @r.get("/api/{vault}/files/{fid}/{ver}/variables")
    def variables(vault: str, fid: int, ver: int, authorization: str | None = Header(None)):
        auth(authorization)
        check_vault(vault)
        return v().variables(get_file(fid))

    @r.get("/api/{vault}/files/{fid}/versions")
    def versions(vault: str, fid: int, authorization: str | None = Header(None)):
        auth(authorization)
        check_vault(vault)
        f = get_file(fid)
        out, last_rev = [], None
        for h in f["rec"].get("history", []):
            out.append({"InfoType": 0, "VersionNumber": h["version"], "Text": h.get("comment", ""), "Revision": "",
                        "FileSize": 0, "VersionDate": h["date"] + "T09:00:00+03:00"})
            if h["revision"] not in ("-", last_rev):
                out.append({"InfoType": 1, "VersionNumber": 0, "Text": "", "Revision": h["revision"], "FileSize": 0,
                            "VersionDate": h["date"] + "T09:05:00+03:00"})
                last_rev = h["revision"]
        return out

    @r.get("/api/{vault}/files/{fid}/{ver}/info/extended")
    def extended(vault: str, fid: int, ver: int, authorization: str | None = Header(None)):
        auth(authorization)
        o = get_file(fid)["obj"]
        return {"StateId": o["StateId"], "State": o["State"], "Workflow": "Engineering Workflow",
                "Category": "CAD", "ReplicatedTo": [], "Branches": []}

    def fileref(rid: str, refs: list) -> dict:
        o = v().by_rid[rid]
        folder = v().folders[o["ParentFolderId"]]
        return {"File": {"File": {"FileId": o["Id"], "FileName": o["Name"]},
                         "Folder": {"FolderId": folder["id"], "FolderPath": folder["path"]}, "Version": o["Version"],
                         "Config": {"ConfigurationName": "Default", "ConfigurationId": 2}},
                "IsCyclic": False, "IsToolbox": o["IsToolbox"], "ObjectType": 1, "Warnings": [], "References": refs}

    @r.get("/api/{vault}/files/{fid}/{ver}/references")
    def references(vault: str, fid: int, ver: int, authorization: str | None = Header(None)):
        auth(authorization)
        f = get_file(fid)
        rec = f["rec"]
        kids = [fileref(line["child"], []) for line in rec.get("bom", []) if line["child"] in v().by_rid]
        return fileref(rec["rid"], kids)

    @r.get("/api/{vault}/files/{fid}/{ver}/whereused")
    def whereused(vault: str, fid: int, ver: int, authorization: str | None = Header(None)):
        auth(authorization)
        f = get_file(fid)
        rec = f["rec"]
        parents = [fileref(p, []) for p, _ in v().fd.parents.get(rec["rid"], []) if p in v().by_rid]
        return fileref(rec["rid"], parents)

    @r.get("/api/{vault}/files/{fid}/bominfo")
    def bominfo(vault: str, fid: int, authorization: str | None = Header(None)):
        auth(authorization)
        o = get_file(fid)["obj"]
        folder = v().folders[o["ParentFolderId"]]
        return {"NamedBOM": {"BOMList": []},
                "ComputedBOM": {"BOMList": [{"Folder": {"FolderId": folder["id"], "FolderPath": folder["path"]},
                                             "Configs": [{"ConfigurationName": "Default", "ConfigurationId": 2}],
                                             "BOMId": 1, "BOMName": "BOM"}]},
                "WeldmentCutlistBOM": {"BOMList": []}, "WeldmentBOM": {"BOMList": []}}

    @r.get("/api/{vault}/bom/{bom_type}/{fid}/{ver}/{folder_id}/computed")
    def computed(vault: str, bom_type: int, fid: int, ver: int, folder_id: int, authorization: str | None = Header(None)):
        auth(authorization)
        f = get_file(fid)
        rec = f["rec"]
        cols = [{"ColumnNo": 0, "ColumnName": "Part Number"}, {"ColumnNo": 1, "ColumnName": "Description"},
                {"ColumnNo": 2, "ColumnName": "Quantity"}, {"ColumnNo": 3, "ColumnName": "File Name"}]

        def row(r, qty):
            o = v().by_rid[r["rid"]]
            return {"FileId": o["Id"], "FileName": o["Name"], "Version": o["Version"],
                    "Values": [r["pn"], r["description"] or r["name"], str(qty), o["Name"]]}
        refs = []
        for line in rec.get("bom", []):
            ch = v().fd.by_rid.get(line["child"])
            if ch and ch["rid"] in v().by_rid:
                refs.append({"File": row(ch, line["qty"]), "References": []})
        return {"Columns": cols, "File": {"File": row(rec, 1), "References": refs}}

    @r.get("/api/{vault}/files/{fid}/{ver}/download")
    def download(vault: str, fid: int, ver: int, request: Request, folderId: int = 0,
                 authorization: str | None = Header(None)):
        auth(authorization)
        f = get_file(fid)
        if f["kind"] != "step":
            raise HTTPException(409, "Native file content is not served by the simulator (only neutral STEP files)")
        sig = token("swpdm", fid, ver)[:16]
        return RedirectResponse(f"/sim/swpdm/content/{fid}/{ver}?sig={sig}", status_code=302)

    @r.get("/content/{fid}/{ver}")
    def content(fid: int, ver: int, sig: str = ""):
        if sig != token("swpdm", fid, ver)[:16]:
            raise HTTPException(403, "bad signature")
        f = get_file(fid)
        return FileResponse(f["path"], media_type="application/octet-stream", filename=f["obj"]["Name"])

    return r


def _like(value: str, pattern: str) -> bool:
    import fnmatch
    return fnmatch.fnmatchcase(value, pattern.replace("%", "*").replace("_", "?")) if pattern else True

