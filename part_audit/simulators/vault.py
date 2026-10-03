"""Autodesk Vault Data API (REST v2) simulator.

Implements: POST /sessions, GET /server-info, GET /vaults, property-definitions, file-versions (paged with
cursorState + host-relative pagination.nextUrl), file-versions/{id}, file-versions/{id}/content,
file-versions/{id}/uses, item-versions (paged), item-versions/{id}/bill-of-materials. Shapes follow the
published examples (FileVersion, ItemVersion, itemBomLinks, errors {statusCode,errorCode,title,detail}).
"""
from __future__ import annotations

import base64
import secrets
import uuid
from functools import lru_cache

from fastapi import APIRouter, Header, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from .data import DEMO_PASSWORD, DEMO_USER, FASTENER_FAMS, FactoryData, factory

BASE = "/sim/vault/AutodeskDM/Services/api/vault/v2"
VAULT_ID = "117"
VAULT_NAME = "Vault-North"
_SESSIONS: dict[str, str] = {}

PROPS = [("1", "Name", "Name", "String"), ("2", "Part Number", "PartNumber", "String"),
         ("3", "Description", "Description", "String"), ("4", "Material", "Material", "String"),
         ("5", "Mass", "Mass", "String"), ("6", "Revision", "Revision", "String"), ("7", "State", "State", "String"),
         ("8", "Title", "Title", "String"), ("9", "Designer", "Designer", "String"),
         ("10", "Category Name", "CategoryName", "String"), ("11", "Finish", "Finish", "String"),
         ("12", "Cost", "Cost", "Numeric"), ("13", "Stock Number", "StockNumber", "String")]


def _err(status: int, code: str, title: str, detail: str):
    return JSONResponse({"statusCode": status, "errorCode": code, "title": title, "detail": detail, "params": []},
                        status_code=status)


class _Data:
    def __init__(self, fd: FactoryData):
        self.fd = fd
        recs = fd.by_system["vault"]
        self.folders = {"1": "$", "2": "$/Designs", "3": "$/Libraries/Standard Parts", "4": "$/Libraries/Purchased",
                        "5": "$/Exports/STEP", "6": "$/Designs/General"}
        top = [r for r in recs if r["kind"] == "assembly" and not fd.parents.get(r["rid"])]
        home = {}
        for t in top:
            fid = str(len(self.folders) + 1)
            self.folders[fid] = f"$/Designs/{t['name'].split()[-1]}"
            self._walk(t, fid, home)
        self.fvs: list[dict] = []
        self.by_id: dict[str, dict] = {}
        nid = 1000
        for r in recs:
            folder = home.get(r["rid"]) or ("3" if r["family"] in FASTENER_FAMS or r["family"] == "bearing"
                                            else ("4" if r["make_buy"] == "buy" else "6"))
            nid += 3
            fv = self._fv(r, str(nid), str(nid - 1), r["native_file"], folder, "Assembly" if r["kind"] == "assembly"
                          else "Part")
            self.fvs.append(fv)
            step = fd.step_file(r)
            if step is not None:
                sfv = self._fv(r, str(nid + 1), str(nid - 2), r["native_file"].rsplit(".", 1)[0] + ".stp", "5", "Base",
                               size=step.stat().st_size)
                sfv["_path"] = str(step)
                sfv["_step"] = True
                self.fvs.append(sfv)
        self.by_id = {fv["id"]: fv for fv in self.fvs}
        self.native_by_rid = {fv["_rid"]: fv for fv in self.fvs if not fv.get("_step")}
        # item master: one item per native record
        self.items: list[dict] = []
        for i, r in enumerate(recs):
            iid = str(5000 + 2 * i)
            st = r["state"]
            self.items.append({"name": r["pn"], "id": iid, "revision": r["revision"] if r["revision"] != "-" else "",
                               "lastModifiedUserName": r["author"], "lastModifiedDate": r["modified"] + "T08:00:00Z",
                               "number": r["pn"], "title": r["name"], "description": r["description"], "comment": "",
                               "state": st, "stateColor": 0, "category": "Assembly" if r["kind"] == "assembly" else "Part",
                               "categoryColor": 0, "isReadOnly": False, "isCloaked": False,
                               "item": {"id": str(int(iid) - 1), "entityType": "Item",
                                        "url": f"{BASE}/vaults/{VAULT_ID}/items/{int(iid) - 1}"},
                               "version": r["version"], "entityType": "ItemVersion",
                               "url": f"{BASE}/vaults/{VAULT_ID}/item-versions/{iid}", "_rid": r["rid"]})
        self.item_by_rid = {it["_rid"]: it for it in self.items}
        self.item_by_id = {it["id"]: it for it in self.items}

    def _walk(self, asm, folder, home):
        if asm["rid"] in home:
            return
        home[asm["rid"]] = folder
        for line in asm.get("bom", []):
            ch = self.fd.by_rid[line["child"]]
            if ch["kind"] == "assembly":
                self._walk(ch, folder, home)
            elif ch["make_buy"] == "make":
                home.setdefault(ch["rid"], folder)

    def _fv(self, r, vid, master, name, folder, category, size=0) -> dict:
        api = BASE  # path as the real server reports it (/AutodeskDM/...)
        vals = {"1": name, "2": r["pn"], "3": r["description"] or r["name"], "4": r.get("material_text", ""),
                "5": (f"{r['mass_recorded_kg']:.3f} kg" if r.get("mass_recorded_kg") is not None else ""),
                "6": r["revision"] if r["revision"] != "-" else "", "7": r["state"], "8": r["name"], "9": r["author"],
                "10": category, "11": r.get("finish_text", ""), "13": r["pn"]}
        return {"name": name, "id": vid, "state": r["state"], "stateColor": 0, "revision": vals["6"],
                "category": category, "categoryColor": -2302756, "lastModifiedDate": r["modified"] + "T08:00:00Z",
                "isCheckedOut": False, "hasVisualizationAttachment": False, "size": size, "isCloaked": False,
                "checkinDate": r["modified"] + "T08:00:00Z", "checkoutDate": "0001-01-01T00:00:00Z", "isHidden": False,
                "isReadOnly": False, "parentFolderId": folder,
                "file": {"id": master, "entityType": "File", "url": f"{api}/vaults/{VAULT_ID}/files/{master}"},
                "isOnSite": True, "createDate": r["created"] + "T08:00:00Z", "createUserName": r["author"],
                "classification": "None", "visualizationAttachmentStatus": "NotSyncronized", "version": r["version"],
                "entityType": "FileVersion", "url": f"{api}/vaults/{VAULT_ID}/file-versions/{vid}",
                "_props": {k: v for k, v in vals.items() if v not in (None, "")}, "_rid": r["rid"]}

    def public(self, fv: dict, prop_ids: str | None, always: bool = False) -> dict:
        out = {k: v for k, v in fv.items() if not k.startswith("_")}
        if always or prop_ids:
            want = None if (always or prop_ids == "all") else set(prop_ids.split(","))
            props = []
            for pid, val in fv["_props"].items():
                if want is None or pid in want:
                    p = {"propertyDefinitionId": pid, "value": val}
                    if always:
                        d = next(x for x in PROPS if x[0] == pid)
                        p["definition"] = {"id": pid, "displayName": d[1], "systemName": d[2], "dataType": d[3],
                                           "isSystem": pid in ("1", "6", "7", "10"), "active": True}
                    props.append(p)
            out["properties"] = props
        return out


@lru_cache(maxsize=4)
def _data(root: str) -> _Data:
    return _Data(factory(root))


def _page(request: Request, rows: list, limit: int, cursor: str | None, path: str):
    start = int(base64.urlsafe_b64decode(cursor.encode()).decode()) if cursor else 0
    chunk = rows[start:start + limit]
    pag = {"limit": limit, "totalResults": len(rows), "indexingStatus": "IndexingComplete"}
    if start + limit < len(rows):
        nxt = base64.urlsafe_b64encode(str(start + limit).encode()).decode()
        q = [f"{k}={v}" for k, v in request.query_params.multi_items() if k not in ("cursorState",)]
        pag["nextUrl"] = f"{path}?{'&'.join(q + ['cursorState=' + nxt])}"
    return chunk, pag


def router(root: str) -> APIRouter:
    r = APIRouter(prefix=BASE)

    def auth(authorization):
        if not authorization or not authorization.startswith("Bearer ") or authorization[7:] not in _SESSIONS:
            return _err(401, "8000", "Vault error", "Invalid or expired session.")
        return None

    @r.get("/server-info")
    def server_info():
        return {"name": "vault-north (simulator)", "productVersion": "2025.2 (sim)", "apiVersion": "2.0.16"}

    @r.get("/vaults")
    def vaults():
        return {"pagination": {"limit": 100, "totalResults": 1, "indexingStatus": "NA"},
                "results": [{"id": VAULT_ID, "name": VAULT_NAME, "url": f"{BASE}/vaults/{VAULT_ID}"}]}

    @r.post("/sessions")
    async def sessions(request: Request):
        body = (await request.json()).get("input", {})
        if body.get("vault") != VAULT_NAME:
            return _err(400, "301", "Vault error", "The vault name is invalid.")
        if body.get("userName") != DEMO_USER or body.get("password") != DEMO_PASSWORD:
            return _err(400, "301", "Vault error", "The user name and/or password appears to be invalid; please try again.")
        sid = str(uuid.uuid4())
        _SESSIONS["V:" + sid] = body["userName"]
        return {"id": sid, "accessToken": "V:" + sid, "createDate": "2026-10-04T08:00:00Z",
                "vaultInformation": {"id": VAULT_ID, "name": VAULT_NAME, "url": f"{BASE}/vaults/{VAULT_ID}"},
                "userInformation": {"id": "65", "name": body["userName"], "email": "", "authTypes": "Vault",
                                    "isActive": True}, "url": f"{BASE}/sessions/{sid}"}

    @r.delete("/sessions/{sid}")
    def logout(sid: str, authorization: str | None = Header(None)):
        _SESSIONS.pop("V:" + sid, None)
        return Response(status_code=204)

    @r.get("/vaults/{vid}/property-definitions")
    def propdefs(vid: str, request: Request, limit: int = 100, cursorState: str | None = None,
                 authorization: str | None = Header(None)):
        if (e := auth(authorization)):
            return e
        rows = [{"id": i, "displayName": d, "systemName": s, "dataType": t, "isSystem": i in ("1", "6", "7", "10"),
                 "active": True, "url": f"{BASE}/vaults/{vid}/property-definitions/{i}"} for i, d, s, t in PROPS]
        chunk, pag = _page(request, rows, limit, cursorState, f"{BASE}/vaults/{vid}/property-definitions")
        return {"pagination": pag, "results": chunk}

    @r.get("/vaults/{vid}/file-versions")
    def file_versions(vid: str, request: Request, limit: int = 100, cursorState: str | None = None, q: str = "",
                      authorization: str | None = Header(None)):
        if (e := auth(authorization)):
            return e
        d = _data(root)
        props = request.query_params.get("option[propDefIds]")
        ext = request.query_params.get("option[extendedModels]") == "true"
        rows = [fv for fv in d.fvs if not q or q.lower() in fv["name"].lower()]
        chunk, pag = _page(request, rows, min(limit, 1000), cursorState, f"{BASE}/vaults/{vid}/file-versions")
        res = []
        for fv in chunk:
            x = d.public(fv, props)
            if ext:
                x["lifecycleState"] = {"id": "3", "name": fv["state"], "displayName": fv["state"],
                                       "isReleasedState": fv["state"] == "Released",
                                       "isObsoleteState": fv["state"] == "Obsolete"}
            res.append(x)
        folders = {fv["parentFolderId"] for fv in chunk}
        return {"pagination": pag, "results": res,
                "included": {"folder": {f: {"name": d.folders[f].split("/")[-1], "id": f, "fullName": d.folders[f],
                                            "entityType": "Folder"} for f in folders}}}

    @r.get("/vaults/{vid}/file-versions/{fid}")
    def file_version(vid: str, fid: str, authorization: str | None = Header(None)):
        if (e := auth(authorization)):
            return e
        fv = _data(root).by_id.get(fid)
        if not fv:
            return _err(404, "5004", "Vault error", f"Resource is not found for the given id {fid}.")
        return _data(root).public(fv, None, always=True)

    @r.get("/vaults/{vid}/file-versions/{fid}/content")
    def content(vid: str, fid: str, authorization: str | None = Header(None)):
        if (e := auth(authorization)):
            return e
        fv = _data(root).by_id.get(fid)
        if not fv:
            return _err(404, "5004", "Vault error", f"Resource is not found for the given id {fid}.")
        if not fv.get("_path"):
            return _err(401, "8000", "Vault error", "Native file content is not available in the simulator.")
        return FileResponse(fv["_path"], media_type="application/octet-stream", filename=fv["name"])

    @r.get("/vaults/{vid}/file-versions/{fid}/uses")
    def uses(vid: str, fid: str, authorization: str | None = Header(None)):
        if (e := auth(authorization)):
            return e
        d = _data(root)
        fv = d.by_id.get(fid)
        if not fv:
            return _err(404, "5004", "Vault error", f"Resource is not found for the given id {fid}.")
        rec = d.fd.by_rid[fv["_rid"]]
        res = []
        for line in rec.get("bom", []):
            ch = d.native_by_rid.get(line["child"])
            if ch:
                res.append({"parentFile": d.public(fv, None), "childFile": d.public(ch, None),
                            "fileAssocType": "Dependency"})
        return {"pagination": {"limit": 100, "totalResults": len(res), "indexingStatus": "NA"}, "results": res,
                "included": {"folder": {}}}

    @r.get("/vaults/{vid}/item-versions")
    def item_versions(vid: str, request: Request, limit: int = 100, cursorState: str | None = None,
                      authorization: str | None = Header(None)):
        if (e := auth(authorization)):
            return e
        d = _data(root)
        chunk, pag = _page(request, d.items, min(limit, 1000), cursorState, f"{BASE}/vaults/{vid}/item-versions")
        return {"pagination": pag, "results": [{k: v for k, v in it.items() if not k.startswith("_")} for it in chunk]}

    @r.get("/vaults/{vid}/item-versions/{iid}/bill-of-materials")
    def bom(vid: str, iid: str, authorization: str | None = Header(None)):
        if (e := auth(authorization)):
            return e
        d = _data(root)
        it = d.item_by_id.get(iid)
        if not it:
            return _err(404, "5004", "Vault error", f"Resource is not found for the given id {iid}.")
        rec = d.fd.by_rid[it["_rid"]]
        links, versions = [], [{k: v for k, v in it.items() if not k.startswith("_")}]
        for n, line in enumerate(rec.get("bom", []), start=1):
            ch = d.item_by_rid.get(line["child"])
            if not ch:
                continue
            versions.append({k: v for k, v in ch.items() if not k.startswith("_")})
            links.append({"id": secrets.token_hex(4), "parentItemId": it["id"], "childItemId": ch["id"],
                          "quantity": str(line["qty"]), "units": "Each", "unitSize": 1, "instCount": int(line["qty"]),
                          "positionNumber": str(n), "bomOrder": n, "cad": True, "included": True, "isStatic": False,
                          "childHasChildren": bool(d.fd.by_rid[ch["_rid"]].get("bom"))})
        return {"itemVersions": versions, "itemBomLinks": links, "referenceDesignatorsAvailable": False,
                "occurrences": [], "bomComponents": []}

    return r
