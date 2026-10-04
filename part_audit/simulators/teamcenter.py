"""Siemens Teamcenter JSON REST (SOA over HTTP) simulator.

POST /tc/JsonRestServices/<Library>-<YYYY>-<MM>-<Service>/<operation> with {"header":{...},"body":{...}}.
Implements: Core-2011-06-Session/login, Core-2006-03-Session/logout, Core-2007-01-Session/getTCSessionInfo,
Query-2006-03-SavedQuery/getSavedQueries, Query-2008-06-SavedQuery/executeSavedQueries,
Core-2006-03-DataManagement/getProperties, Core-2007-09-DataManagement/expandGRMRelationsForPrimary,
Core-2006-03-FileManagement/getFileReadTickets, Cad-2007-01-StructureManagement/createBOMWindows,
expandPSOneLevel, closeBOMWindows; FMS download GET /fms/<file>?ticket=...
ServiceData/modelObjects/props{dbValues,uiValues} follow the community-verified shapes; JSON encodings
the vendor does not publish (ticket maps) are marked in docs/research/pdm_plm_apis.md.
"""
from __future__ import annotations

import secrets
from functools import lru_cache

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from .data import DEMO_PASSWORD, DEMO_USER, FactoryData, factory

PREFIX = "/sim/teamcenter"
_SESSIONS: set[str] = set()
_TICKETS: dict[str, str] = {}
_WINDOWS: dict[str, str] = {}


def _ref(uid: str, cls: str, typ: str | None = None) -> dict:
    return {"uid": uid, "className": cls, "type": typ or cls}


def _prop(db, ui=None) -> dict:
    db = db if isinstance(db, list) else [db]
    ui = ui if ui is not None else db
    ui = ui if isinstance(ui, list) else [ui]
    return {"dbValues": ["" if x is None else str(x) for x in db], "uiValues": ["" if x is None else str(x) for x in ui]}


class _Data:
    def __init__(self, fd: FactoryData):
        self.fd = fd
        self.objects: dict[str, dict] = {}   # uid -> {"cls","type","props":{name: (db, ui)}}
        self.rev_of_rid: dict[str, str] = {}
        self.files: dict[str, tuple[str, str]] = {}
        users = {}
        for r in fd.by_system["teamcenter"]:
            n = r["native_id"]
            item, rev = f"Ixq{n}TCpp", f"Rxq{n}TCpp"
            uname = r["author"]
            if uname not in users:
                uid = f"Uxq{len(users) + 1}TCpp"
                users[uname] = uid
                self.objects[uid] = {"cls": "User", "type": "User",
                                     "props": {"user_id": f"u{len(users)}", "user_name": uname}}
            st_uid = ""
            if r["state"]:
                st_uid = f"Sxq{n}TCpp"
                self.objects[st_uid] = {"cls": "ReleaseStatus", "type": "ReleaseStatus",
                                        "props": {"object_name": r["state"], "name": r["state"]}}
            ds = []
            native_ds, native_file = f"Dxq{n}TCpp", f"Fxq{n}TCpp"
            self.objects[native_file] = {"cls": "ImanFile", "type": "ImanFile",
                                         "props": {"original_file_name": r["native_file"], "file_size": "0"}}
            self.objects[native_ds] = {"cls": "Dataset", "type": "UGMASTER",
                                       "props": {"object_name": r["pn"], "object_type": "UGMASTER",
                                                 "ref_list": ([native_file], [r["native_file"]])}}
            ds.append(native_ds)
            step = fd.step_file(r)
            if step is not None:
                sds, sfile = f"Dsq{n}TCpp", f"Fsq{n}TCpp"
                fname = f"{r['pn']}_{r['revision']}.stp" if r["revision"] != "-" else f"{r['pn']}.stp"
                self.objects[sfile] = {"cls": "ImanFile", "type": "ImanFile",
                                       "props": {"original_file_name": fname, "file_size": str(step.stat().st_size)}}
                self.objects[sds] = {"cls": "Dataset", "type": "STEP",
                                     "props": {"object_name": fname, "object_type": "STEP", "ref_list": ([sfile], [fname])}}
                self.files[sfile] = (str(step), fname)
                ds.append(sds)
            self.objects[item] = {"cls": "Item", "type": "Item", "props": {"item_id": r["pn"], "object_name": r["name"]}}
            bvr = [f"Vxq{n}TCpp"] if r.get("bom") else []
            self.objects[rev] = {"cls": "ItemRevision", "type": "ItemRevision", "rid": r["rid"], "item": item, "props": {
                "item_id": r["pn"], "object_name": r["name"], "object_desc": r["description"],
                "item_revision_id": r["revision"] if r["revision"] != "-" else "A",
                "release_status_list": ([st_uid], [r["state"]]) if st_uid else ([], []),
                "owning_user": ([users[uname]], [f"{uname} (u{list(users).index(uname) + 1})"]),
                "creation_date": (r["created"] + "T08:00:00+03:00", r["created"]),
                "last_mod_date": (r["modified"] + "T08:00:00+03:00", r["modified"]),
                "object_type": "ItemRevision", "items_tag": ([item], [r["pn"]]),
                "structure_revisions": (bvr, bvr), "IMAN_specification": (ds, ds),
                "u4_material": r.get("material_text", ""),
                "u4_mass": "" if r.get("mass_recorded_kg") is None else f"{r['mass_recorded_kg']:.4f}",
                "u4_finish": r.get("finish_text", ""),
                "u4_make_buy": "Buy" if r["make_buy"] == "buy" else "Make",
            }}
            self.rev_of_rid[r["rid"]] = rev

    def model_object(self, uid: str, attrs: list[str] | None) -> dict:
        o = self.objects[uid]
        props = {}
        for k, v in o["props"].items():
            if attrs is not None and k not in attrs:
                continue
            props[k] = _prop(*v) if isinstance(v, tuple) else _prop(v)
        return {"objectID": uid, "uid": uid, "className": o["cls"], "type": o["type"], "props": props}


@lru_cache(maxsize=4)
def _data(root: str) -> _Data:
    return _Data(factory(root))


def _qname(lib: str, name: str) -> str:
    return f"http://teamcenter.com/Schemas/{lib}.{name}"


def router(root: str) -> APIRouter:
    r = APIRouter(prefix=PREFIX)

    def d() -> _Data:
        return _data(root)

    def policy_attrs(header: dict) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for t in ((header or {}).get("policy") or {}).get("types", []) or []:
            out[t.get("name")] = [p.get("name") for p in t.get("properties", [])]
        return out

    def service_data(uids, attrs_by_type=None, plain=None) -> dict:
        mos = {}
        for u in uids:
            if u in d().objects:
                cls = d().objects[u]["cls"]
                attrs = None if attrs_by_type is None else attrs_by_type.get(cls, attrs_by_type.get("*", []))
                mos[u] = d().model_object(u, attrs)
        return {"plain": plain or list(uids), "modelObjects": mos}

    def error(status: int, msg: str, code: int = 515024):
        return JSONResponse({".QName": "http://teamcenter.com/Schemas/Soa/2006-03/Exceptions.InvalidUserException",
                             "code": code, "level": 3, "message": msg}, status_code=status)

    @r.post("/tc/JsonRestServices/{op:path}")
    async def soa(op: str, request: Request):
        try:
            payload = await request.json()
        except Exception:
            return error(400, "Request body is not valid JSON")
        header, body = payload.get("header") or {}, payload.get("body") or {}
        if op == "Core-2011-06-Session/login":
            cred = body.get("credentials") or {}
            if cred.get("user") != DEMO_USER or cred.get("password") != DEMO_PASSWORD:
                return error(401, "The login attempt failed: either the user ID or the password is invalid.")
            sid = secrets.token_hex(16)
            _SESSIONS.add(sid)
            resp = JSONResponse({".QName": _qname("Core/2011-06/Session", "LoginResponse"),
                                 "serverInfo": {"DisplayVersion": "14.3 (simulator)", "HostName": "tc-sim",
                                                "Locale": "he_IL", "UserID": cred.get("user"),
                                                "Version": "V14000.3.0 (sim)"}, "PartialErrors": {}},
                                media_type="text/json")
            resp.set_cookie("JSESSIONID", sid, httponly=True)
            return resp
        if request.cookies.get("JSESSIONID") not in _SESSIONS:
            return error(401, "Invalid or expired session; log in again.", code=515114)
        if op == "Core-2006-03-Session/logout":
            _SESSIONS.discard(request.cookies.get("JSESSIONID"))
            return {".QName": _qname("Soa/2006-03/Base", "ServiceData"), "plain": []}
        if op == "Core-2007-01-Session/getTCSessionInfo":
            return {".QName": _qname("Core/2007-01/Session", "GetTCSessionInfoResponse"), "serverVersion": "V14000.3.0",
                    "extraInfo": {"DisplayVersion": "14.3 (simulator)", "TCServerLocale": "he_IL"}, "ServiceData": {}}
        if op == "Query-2006-03-SavedQuery/getSavedQueries":
            return {".QName": _qname("Query/2006-03/SavedQuery", "GetSavedQueriesResponse"), "queries": [
                {"name": "Item Revision...", "description": "Find item revisions", "query": _ref("Qxq1TCpp", "ImanQuery")},
                {"name": "Item...", "description": "Find items", "query": _ref("Qxq2TCpp", "ImanQuery")},
                {"name": "General...", "description": "General search", "query": _ref("Qxq3TCpp", "ImanQuery")}],
                "ServiceData": {}}
        if op == "Query-2008-06-SavedQuery/executeSavedQueries":
            results = []
            for inp in body.get("input", []):
                if (inp.get("query") or {}).get("uid") != "Qxq1TCpp":
                    results.append({"objects": [], "objectUIDS": []})
                    continue
                pat = dict(zip(inp.get("entries", []), inp.get("values", []))).get("Item ID", "*")
                import fnmatch
                revs = [u for u, o in d().objects.items() if o["cls"] == "ItemRevision"
                        and fnmatch.fnmatchcase(o["props"]["item_id"], pat)]
                mx = int(inp.get("maxNumToReturn") or 0)
                if mx:
                    revs = revs[:mx]
                results.append({"objects": [_ref(u, "ItemRevision") for u in revs], "objectUIDS": revs})
            return {".QName": _qname("Query/2008-06/SavedQuery", "ExecuteSavedQueriesResponse"),
                    "arrayOfResults": results, "ServiceData": {"plain": [], "modelObjects": {}}}
        if op == "Core-2011-06-Session/getTypeDescriptions2":
            names = sorted({k for o in d().objects.values() if o["cls"] == "ItemRevision" for k in o["props"]})
            types = [{"name": t, "displayName": t, "propertyDescriptors": {
                k: {"name": k, "displayName": k.replace("_", " ").title(), "valueType": 8} for k in names}}
                for t in body.get("typeNames", []) if t == "ItemRevision"]
            return {".QName": _qname("Core/2011-06/Session", "GetTypeDescriptionsResponse"), "types": types,
                    "ServiceData": {"plain": [], "modelObjects": {}}}
        if op == "Core-2006-03-DataManagement/getProperties":
            uids = [o.get("uid") for o in body.get("objects", [])]
            attrs = body.get("attributes") or []
            sd = service_data(uids, {"*": attrs})
            return {".QName": _qname("Soa/2006-03/Base", "ServiceData"), **sd}
        if op == "Core-2007-09-DataManagement/expandGRMRelationsForPrimary":
            rel_names = [i.get("relationTypeName") for i in ((body.get("pref") or {}).get("info") or [])] or \
                        ["IMAN_specification"]
            outs, uids = [], []
            for prim in body.get("primaryObjects", []):
                o = d().objects.get(prim.get("uid"))
                rd = []
                for rel in rel_names:
                    others = (o or {}).get("props", {}).get(rel, ([], []))[0] if o else []
                    rd.append({"relationName": rel, "relationshipObjects": [
                        {"otherSideObject": _ref(x, "Dataset", d().objects[x]["type"]),
                         "relation": _ref(f"Rel{x}", "ImanRelation", rel)} for x in others]})
                    uids.extend(others)
                outs.append({"inputObject": prim, "relationshipData": rd})
            pol = policy_attrs(header) or {"Dataset": ["object_name", "object_type", "ref_list"]}
            return {".QName": _qname("Core/2007-09/DataManagement", "ExpandGRMRelationsResponse"), "output": outs,
                    "ServiceData": service_data(uids, pol)}
        if op == "Core-2006-03-FileManagement/getFileReadTickets":
            keys, vals = [], []
            for f in body.get("files", []):
                uid = f.get("uid")
                if uid in d().files:
                    t = secrets.token_urlsafe(24)
                    _TICKETS[t] = uid
                    keys.append(_ref(uid, "ImanFile"))
                    vals.append(t)
            return {".QName": _qname("Core/2006-03/FileManagement", "FileTicketsResponse"), "tickets": [keys, vals],
                    "ServiceData": {}}
        if op == "Cad-2007-01-StructureManagement/createBOMWindows":
            outs = []
            for info in body.get("info", []):
                rev = (info.get("itemRev") or {}).get("uid")
                if not rev:  # item given: use its (only) revision
                    item = (info.get("item") or {}).get("uid")
                    rev = next((u for u, o in d().objects.items() if o.get("item") == item), None)
                if rev not in d().objects:
                    continue
                win = f"BOM::{secrets.randbelow(10**6)}"
                _WINDOWS[win] = rev
                outs.append({"clientId": info.get("clientId", ""), "bomWindow": _ref(win, "BOMWindow"),
                             "bomLine": _ref(f"SR::N::BOMLine..{rev}..top", "BOMLine")})
            return {".QName": _qname("Cad/2007-01/StructureManagement", "CreateBOMWindowsResponse"), "output": outs,
                    "ServiceData": {"created": [o["bomWindow"]["uid"] for o in outs]}}
        if op in ("Cad-2007-01-StructureManagement/expandPSOneLevel", "Cad-2008-06-StructureManagement/expandPSOneLevel"):
            outs, mos = [], {}
            for line in (body.get("input") or {}).get("parentBomLines", []):
                line_uid = line if isinstance(line, str) else line.get("uid")
                rev = line_uid.split("..")[1] if ".." in line_uid else ""
                o = d().objects.get(rev)
                if not o:
                    continue
                rec = d().fd.by_rid[o["rid"]]
                kids = []
                for i, b in enumerate(rec.get("bom", []), start=1):
                    crev = d().rev_of_rid.get(b["child"])
                    if not crev:
                        continue
                    bl = f"SR::N::BOMLine..{crev}..{rev}..{i}"
                    kids.append({"bomLine": _ref(bl, "BOMLine"), "itemRevOfBOMLine": _ref(crev, "ItemRevision")})
                    mos[bl] = {"objectID": bl, "uid": bl, "className": "BOMLine", "type": "BOMLine",
                               "props": {"bl_quantity": _prop(str(b["qty"])), "bl_item_item_id": _prop(
                                   d().objects[crev]["props"]["item_id"])}}
                outs.append({"parent": {"bomLine": _ref(line_uid, "BOMLine"), "itemRevOfBOMLine": _ref(rev, "ItemRevision")},
                             "children": kids})
            return {".QName": _qname("Cad/2007-01/StructureManagement", "ExpandPSOneLevelResponse"), "output": outs,
                    "ServiceData": {"plain": [], "modelObjects": mos}}
        if op == "Cad-2007-01-StructureManagement/closeBOMWindows":
            for w in body.get("bomWindows", []):
                _WINDOWS.pop(w if isinstance(w, str) else w.get("uid"), None)
            return {".QName": _qname("Cad/2007-01/StructureManagement", "CloseBOMWindowsResponse"),
                    "ServiceData": {"deleted": body.get("bomWindows", [])}}
        return error(404, f"Service operation {op} is not available in the simulator", code=214000)

    @r.get("/fms/{name:path}")
    def fms(name: str, ticket: str = ""):
        uid = _TICKETS.get(ticket)
        if not uid or uid not in d().files:
            return JSONResponse({"error": "invalid or expired ticket"}, status_code=403)
        path, fname = d().files[uid]
        return FileResponse(path, media_type="application/octet-stream", filename=fname)

    return r
