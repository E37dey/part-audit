"""PTC Windchill REST Services (WRS, OData v4) simulator.

Implements: service root, PTC/GetCSRFToken(), PTC/GetWindchillVersion(), ProdMgmt/Parts (with $select,
$filter, $top/$skip, $count, ptc.search.latestversion, Prefer: odata.maxpagesize, @odata.nextLink),
Parts('id'), Parts('id')/Uses ($expand=Uses), Parts('id')/UsedBy, Parts('id')/PartDocAssociations
($expand=RelatedCADDoc), CADDocumentMgmt/CADDocuments('id'), CADDocuments('id')/Representations
(AdditionalFiles with STEP), and the content URL of an AdditionalFile. HTTP Basic on every request.
Shapes follow the WRS guide samples (Part JSON with {Value, Display} enums, PartUse with Quantity).
"""
from __future__ import annotations

import re
import secrets
from functools import lru_cache
from urllib.parse import quote

from fastapi import APIRouter, Header, Request
from fastapi.responses import FileResponse, JSONResponse

from .data import FactoryData, basic_ok, factory
from .odata import FilterError, apply_filter, apply_orderby, apply_select, split_expand

ROOT = "/sim/windchill/Windchill/servlet/odata"
GW = "/sim/windchill/Windchill/servlet/WindchillAuthGW/com.ptc.windchill.enterprise.wvs.saveWVSObject.utils.SaveWVSObjectHelper/saveWVSObject"
_NONCES: set[str] = set()


def _unauth():
    return JSONResponse({"error": {"code": "401", "message": "Authentication required"}}, status_code=401,
                        headers={"WWW-Authenticate": 'Basic realm="Windchill"'})


def _odata_error(status: int, msg: str):
    return JSONResponse({"error": {"code": str(status), "message": msg}}, status_code=status)


class _Data:
    def __init__(self, fd: FactoryData):
        self.fd = fd
        recs = fd.by_system["windchill"]
        self.parts: list[dict] = []
        self.by_id: dict[str, dict] = {}
        self.cad: dict[str, dict] = {}
        self.cad_by_part: dict[str, dict] = {}
        self.files: dict[str, tuple[str, str]] = {}
        top = {r["rid"]: r["name"].split()[-1] for r in recs if r["kind"] == "assembly" and not fd.parents.get(r["rid"])}
        for r in recs:
            n = r["native_id"]
            pid = f"OR:wt.part.WTPart:{n * 7 + 100000}"
            st = r["state"]
            st_val, st_disp = (st if isinstance(st, list) else [st, st])
            rev = r["revision"] if r["revision"] != "-" else "A"
            proj = top.get(r["rid"]) or "Library"
            part = {
                "ID": pid, "Number": r["pn"], "Name": r["name"],
                "Identity": f"{r['pn']}, {r['name']}, Demo Group, {rev} (Design)",
                "EndItem": r["kind"] == "assembly" and r["rid"] in top,
                "AssemblyMode": ({"Value": "separable", "Display": "Separable"} if r["kind"] == "assembly"
                                 else {"Value": "component", "Display": "Component"}),
                "DefaultUnit": {"Value": "ea", "Display": "each"},
                "Source": ({"Value": "buy", "Display": "Buy"} if r["make_buy"] == "buy"
                           else {"Value": "make", "Display": "Make"}),
                "View": "Design", "CheckoutState": "Checked in", "State": {"Value": st_val, "Display": st_disp},
                "LifeCycleTemplateName": "Basic", "VersionID": f"VR:wt.part.WTPart:{n * 7 + 100001}",
                "Revision": rev, "Version": f"{rev}.{r['version']} (Design)", "Latest": True,
                "FolderLocation": f"/Default/Product/{proj}", "OrganizationName": "Demo Group",
                "CreatedOn": r["created"] + "T06:00:00Z", "LastModified": r["modified"] + "T06:00:00Z",
                "CreatedBy": r["author"], "ModifiedBy": r["author"],
                "DESCRIPTION": r["description"] or None,
                "PTC_MATERIAL_NAME": r.get("material_text") or None,
                "PRO_MP_MASS": r.get("mass_recorded_kg"),
                "FINISH": r.get("finish_text") or None,
                "_rid": r["rid"],
            }
            self.parts.append(part)
            self.by_id[pid] = part
            cid = f"OR:wt.epm.EPMDocument:{n * 7 + 200000}"
            cad = {"ID": cid, "Number": r["native_file"].upper(), "Name": r["native_file"],
                   "FileName": r["native_file"], "Version": part["Version"], "Revision": rev,
                   "Identity": f"{r['native_file'].upper()}, {r['native_file']}, {rev}",
                   "Category": {"Value": "CADASSEMBLY" if r["kind"] == "assembly" else "CADCOMPONENT",
                                "Display": "Assembly" if r["kind"] == "assembly" else "Part"},
                   "AuthoringApplication": {"Value": "PROE", "Display": "Creo"},
                   "CreatedBy": r["author"], "ModifiedBy": r["author"], "LastModified": part["LastModified"],
                   "_rid": r["rid"]}
            self.cad[cid] = cad
            self.cad_by_part[pid] = cad
            step = fd.step_file(r)
            if step is not None:
                appid = f"OR:wt.content.ApplicationData:{n * 7 + 300000}"
                fname = r["native_file"].rsplit(".", 1)[0] + ".stp"
                self.files[appid] = (str(step), fname)
                cad["_rep"] = {"ID": f"OR:wt.viewmarkup.DerivedImage:{n * 7 + 400000}", "Name": fname.rsplit(".", 1)[0],
                               "Description": "Default representation", "DefaultRepresentation": True,
                               "CreoViewURL": None, "AdditionalFiles": [{
                                   "URL": f"{GW}/{quote(appid)}/{quote(fname)}", "Label": fname,
                                   "FileSize": float(step.stat().st_size), "MimeType": "application/step",
                                   "Format": "STEP", "ID": appid, "FileName": fname,
                                   "LastModified": part["LastModified"], "CreatedOn": part["CreatedOn"],
                                   "Description": None, "Comments": None}]}
        self.pid_by_rid = {p["_rid"]: p["ID"] for p in self.parts}


@lru_cache(maxsize=4)
def _data(root: str) -> _Data:
    return _Data(factory(root))


def _public(p: dict) -> dict:
    return {k: v for k, v in p.items() if not k.startswith("_")}


def _key(text: str) -> str:
    m = re.match(r"^\('(.+)'\)$", text)
    return m.group(1).replace("''", "'") if m else text


def router(root: str) -> APIRouter:
    r = APIRouter()

    def d() -> _Data:
        return _data(root)

    @r.get(ROOT + "/")
    def service_root(authorization: str | None = Header(None)):
        if not basic_ok(authorization):
            return _unauth()
        return {"@odata.context": f"{ROOT}/$metadata", "value": [
            {"name": n, "url": n} for n in ("ProdMgmt", "CADDocumentMgmt", "DocMgmt", "PTC", "Visualization",
                                             "ChangeMgmt", "PrincipalMgmt", "NavCriteria")]}

    @r.get(ROOT + "/PTC/GetCSRFToken()")
    def csrf(authorization: str | None = Header(None)):
        if not basic_ok(authorization):
            return _unauth()
        v = secrets.token_urlsafe(30)
        _NONCES.add(v)
        return {"@odata.context": f"{ROOT}/v1/PTC/$metadata#CSRFToken", "NonceKey": "CSRF_NONCE", "NonceValue": v}

    @r.get(ROOT + "/PTC/GetWindchillVersion()")
    def version(authorization: str | None = Header(None)):
        if not basic_ok(authorization):
            return _unauth()
        return {"@odata.context": f"{ROOT}/PTC/$metadata#Edm.String", "value": "13.0.2.0 (simulator)"}

    @r.get(ROOT + "/ProdMgmt/Parts")
    def parts(request: Request, authorization: str | None = Header(None), prefer: str | None = Header(None)):
        if not basic_ok(authorization):
            return _unauth()
        q = request.query_params
        rows = d().parts
        try:
            rows = apply_filter(rows, q.get("$filter"))
        except FilterError as exc:
            return _odata_error(400, f"Invalid $filter: {exc}")
        rows = apply_orderby(rows, q.get("$orderby"))
        total = len(rows)
        skip = int(q.get("$skiptoken") or q.get("$skip") or 0)
        page = 25
        m = re.search(r"odata\.maxpagesize=(\d+)", prefer or "")
        if m:
            page = min(int(m.group(1)), 2000)
        top = int(q["$top"]) if q.get("$top") else None
        n = min(page, top) if top else page
        chunk = rows[skip:skip + n]
        body = {"@odata.context": f"{ROOT}/v6/ProdMgmt/$metadata#Parts",
                "value": [apply_select(_public(p), q.get("$select"), keep=("ID",)) for p in chunk]}
        if q.get("$count") == "true":
            body["@odata.count"] = total
        end = skip + n
        if end < (min(total, skip + top) if top else total) and not (top and n >= top):
            others = "&".join(f"{k}={quote(v)}" for k, v in q.multi_items() if k not in ("$skiptoken", "$skip"))
            body["@odata.nextLink"] = f"{request.url.scheme}://{request.url.netloc}{ROOT}/ProdMgmt/Parts?" \
                                      f"{others + '&' if others else ''}$skiptoken={end}"
        headers = {"Preference-Applied": f"odata.maxpagesize={page}"} if m else {}
        return JSONResponse(body, headers=headers)

    @r.get(ROOT + "/ProdMgmt/Parts{key}")
    def part(key: str, authorization: str | None = Header(None)):
        if not basic_ok(authorization):
            return _unauth()
        p = d().by_id.get(_key(key))
        if not p:
            return _odata_error(404, "Part not found")
        return {"@odata.context": f"{ROOT}/v6/ProdMgmt/$metadata#Parts/$entity", **_public(p)}

    @r.get(ROOT + "/ProdMgmt/Parts{key}/Uses")
    def uses(key: str, request: Request, authorization: str | None = Header(None)):
        if not basic_ok(authorization):
            return _unauth()
        p = d().by_id.get(_key(key))
        if not p:
            return _odata_error(404, "Part not found")
        expand = split_expand(request.query_params.get("$expand"))
        rec = d().fd.by_rid[p["_rid"]]
        out = []
        for i, line in enumerate(rec.get("bom", []), start=1):
            cid = d().pid_by_rid.get(line["child"])
            if not cid:
                continue
            use = {"ID": f"OR:wt.part.WTPartUsageLink:{abs(hash((p['ID'], cid))) % 10**7}", "Quantity": float(line["qty"]),
                   "Unit": {"Value": "ea", "Display": "each"}, "FindNumber": str(i * 10), "LineNumber": i * 10,
                   "TraceCode": {"Value": "0", "Display": "Untraced"}}
            if "Uses" in expand:
                use["Uses"] = _public(d().by_id[cid])
            out.append(use)
        return {"@odata.context": f"{ROOT}/v6/ProdMgmt/$metadata#PartUses", "value": out}

    @r.get(ROOT + "/ProdMgmt/Parts{key}/UsedBy")
    def used_by(key: str, authorization: str | None = Header(None)):
        if not basic_ok(authorization):
            return _unauth()
        p = d().by_id.get(_key(key))
        if not p:
            return _odata_error(404, "Part not found")
        parents = [d().by_id[d().pid_by_rid[par]] for par, _ in d().fd.parents.get(p["_rid"], [])
                   if par in d().pid_by_rid]
        return {"@odata.context": f"{ROOT}/v6/ProdMgmt/$metadata#Parts", "value": [_public(x) for x in parents]}

    @r.get(ROOT + "/ProdMgmt/Parts{key}/PartDocAssociations")
    def assoc(key: str, request: Request, authorization: str | None = Header(None)):
        if not basic_ok(authorization):
            return _unauth()
        p = d().by_id.get(_key(key))
        if not p:
            return _odata_error(404, "Part not found")
        cad = d().cad_by_part.get(p["ID"])
        if not cad:
            return {"value": []}
        a = {"ID": f"OR:wt.epm.build.EPMBuildRule:{abs(hash(p['ID'])) % 10**7}",
             "AssociationType": {"Value": "OWNER", "Display": "Owner"}}
        if "RelatedCADDoc" in split_expand(request.query_params.get("$expand")):
            a["RelatedCADDoc"] = _public(cad)
        return {"@odata.context": f"{ROOT}/v6/ProdMgmt/$metadata#PartDocAssociations", "value": [a]}

    @r.get(ROOT + "/CADDocumentMgmt/CADDocuments{key}")
    def caddoc(key: str, authorization: str | None = Header(None)):
        if not basic_ok(authorization):
            return _unauth()
        c = d().cad.get(_key(key))
        if not c:
            return _odata_error(404, "CAD document not found")
        return {"@odata.context": f"{ROOT}/v3/CADDocumentMgmt/$metadata#CADDocuments/$entity", **_public(c)}

    @r.get(ROOT + "/CADDocumentMgmt/CADDocuments{key}/Representations")
    def reps(key: str, authorization: str | None = Header(None)):
        if not basic_ok(authorization):
            return _unauth()
        c = d().cad.get(_key(key))
        if not c:
            return _odata_error(404, "CAD document not found")
        return {"@odata.context": f"{ROOT}/v3/CADDocumentMgmt/$metadata#Representations",
                "value": [c["_rep"]] if c.get("_rep") else []}

    @r.get(GW + "/{appid}/{fname}")
    def content(appid: str, fname: str, authorization: str | None = Header(None)):
        if not basic_ok(authorization):
            return _unauth()
        f = d().files.get(appid)
        if not f:
            return _odata_error(404, "Content not found")
        return FileResponse(f[0], media_type="application/step", filename=f[1])

    return r
