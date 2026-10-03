"""Autodesk Vault Professional connector (Vault Data API, REST v2 – server 2025.2 and later)."""
from __future__ import annotations

from ..model import PartRecord, classify_state
from .base import CAD_ASM_EXT, CAD_PART_EXT, STEP_EXT, Collected, Connector, Field, mass_to_kg, stem_key
from .http import ConnectorError, ReadOnlyHttp


class VaultRest(Connector):
    kind = "vault"
    role = "pdm"
    title = "Autodesk Vault"
    vendor = "Autodesk"
    interface = "Vault Data API (REST v2) – Vault Professional 2025.2 ומעלה"
    description = "קריאת קבצים, מאפייני iProperties, מצבי מחזור חיים, Item Master, עץ מוצר (BOM) וקבצי STEP."
    fields = [
        Field("server_url", "כתובת שרת Vault", default="https://vault-server", required=True,
              help="למשל https://vault.company.local – הנתיב /AutodeskDM/Services/api/vault/v2 נוסף אוטומטית"),
        Field("api_path", "נתיב ה-API", default="/AutodeskDM/Services/api/vault/v2", group="advanced"),
        Field("vault", "שם הכספת", default="Vault", required=True),
        Field("username", "שם משתמש", required=True),
        Field("password", "סיסמה", type="password", required=True),
        Field("verify_tls", "אימות תעודת אבטחה (TLS)", type="bool", default=True, group="advanced"),
        Field("prop_number", "מאפיין מק\"ט", default="Part Number", group="mapping"),
        Field("prop_description", "מאפיין תיאור", default="Description", group="mapping"),
        Field("prop_title", "מאפיין כותרת", default="Title", group="mapping"),
        Field("prop_material", "מאפיין חומר", default="Material", group="mapping"),
        Field("prop_mass", "מאפיין משקל", default="Mass", group="mapping"),
        Field("prop_designer", "מאפיין מתכנן", default="Designer", group="mapping"),
        Field("prop_finish", "מאפיין גימור", default="Finish", group="mapping"),
        Field("page_size", "גודל עמוד", type="number", default=500, group="advanced"),
    ]
    unconfirmed = ["מבנה תשובת uses/parents (אין דוגמה רשמית) – משמש רק כגיבוי כשאין Item Master"]

    def _http(self) -> ReadOnlyHttp:
        base = self.cfg["server_url"].rstrip("/") + "/" + self.cfg["api_path"].strip("/") + "/"
        return ReadOnlyHttp(base, allowed=[("POST", r"/sessions$"), ("POST", r":advanced-search$"),
                                           ("DELETE", r"/sessions/[^/]+$")],
                            verify=bool(self.cfg.get("verify_tls", True)), headers={"Accept": "application/json"})

    def _login(self, h: ReadOnlyHttp) -> tuple[str, str]:
        r = h.post("sessions", json={"input": {"vault": self.cfg["vault"], "userName": self.cfg["username"],
                                               "password": self.cfg["password"], "appCode": "PartAudit"}})
        if r.status_code != 200:
            detail = ""
            try:
                detail = r.json().get("detail", "")
            except ValueError:
                pass
            raise ConnectorError(f"ההתחברות ל-Vault נכשלה{': ' + detail if detail else ''}", status=r.status_code)
        s = r.json()
        h.client.headers["Authorization"] = f"Bearer {s['accessToken']}"
        return s["id"], s.get("vaultInformation", {}).get("id", "")

    def _logout(self, h: ReadOnlyHttp, sid: str) -> None:
        try:
            h.delete(f"sessions/{sid}")
        except Exception:
            pass

    def _pages(self, h: ReadOnlyHttp, path: str, params: dict):
        url, first = path, True
        while url:
            data = h.json("GET", url, params=params if first else None)
            first = False
            yield data
            url = (data.get("pagination") or {}).get("nextUrl")

    def test(self) -> dict:
        h = self._http()
        try:
            info = {}
            r = h.get("server-info")
            if r.status_code == 200:
                info = r.json()
            sid, vid = self._login(h)
            data = h.json("GET", f"vaults/{vid}/file-versions", params={"limit": 1})
            total = (data.get("pagination") or {}).get("totalResults")
            self._logout(h, sid)
            return {"ok": True, "message": f"מחובר ל-Autodesk Vault, כספת {self.cfg['vault']}",
                    "details": {"גרסת שרת": info.get("productVersion", "—"), "קבצים בכספת": total,
                                "קריאות API": h.calls}}
        except ConnectorError as exc:
            msg = str(exc)
            if exc.status == 404:
                msg = "ה-REST API לא נמצא – נדרש Vault Server 2025.2 ומעלה (בגרסאות קודמות יש להשתמש ב-SDK)"
            return {"ok": False, "message": msg, "details": {"status": exc.status}}
        finally:
            h.close()

    def collect(self) -> Collected:
        out = Collected()
        h = self._http()
        c = self.cfg
        sid = ""
        try:
            self.progress("מתחבר ל-Autodesk Vault", 0, 0)
            sid, vid = self._login(h)
            defs = {}
            for page in self._pages(h, f"vaults/{vid}/property-definitions", {"limit": 1000}):
                for d in page.get("results", []):
                    defs[d["id"]] = d.get("displayName") or d.get("systemName")
            fvs = []
            for page in self._pages(h, f"vaults/{vid}/file-versions",
                                    {"limit": int(c.get("page_size") or 500), "option[propDefIds]": "all",
                                     "option[extendedModels]": "true", "option[latestOnly]": "true"}):
                fvs.extend(page.get("results", []))
                self.progress("קורא רשימת קבצים מ-Vault", len(fvs), (page.get("pagination") or {}).get("totalResults", 0))
            native = [f for f in fvs if f["name"].lower().endswith(CAD_PART_EXT + CAD_ASM_EXT)]
            steps = {}
            for f in fvs:
                if f["name"].lower().endswith(STEP_EXT):
                    steps.setdefault(stem_key(f["name"]), []).append(f)
            items_by_number = {}
            try:
                for page in self._pages(h, f"vaults/{vid}/item-versions", {"limit": 1000}):
                    for it in page.get("results", []):
                        items_by_number[str(it.get("number", ""))] = it
            except ConnectorError:
                pass
            for i, f in enumerate(native):
                if self.stopped():
                    break
                self.progress("ממפה מאפיינים וקבצי STEP", i, len(native))
                props = {defs.get(p["propertyDefinitionId"], p["propertyDefinitionId"]): p.get("value")
                         for p in f.get("properties", [])}
                is_asm = f["name"].lower().endswith(CAD_ASM_EXT)
                state = f.get("state") or (f.get("lifecycleState") or {}).get("displayName", "")
                pn = str(props.get(c["prop_number"]) or "").strip()
                rec = PartRecord(
                    uid=self.uid(f["file"]["id"]), source_id=self.source_id, source_kind=self.kind,
                    native_id=str(f["file"]["id"]), kind="assembly" if is_asm else "part", pn=pn,
                    name=str(props.get(c["prop_description"]) or props.get(c["prop_title"]) or "").strip(),
                    description=str(props.get(c["prop_title"]) or ""), revision=str(f.get("revision") or ""),
                    version=str(f.get("version", "")), state=state, state_class=classify_state(state),
                    material=str(props.get(c["prop_material"]) or ""), mass_kg=mass_to_kg(props.get(c["prop_mass"])),
                    mass_text=str(props.get(c["prop_mass"]) or ""),
                    finish=str(props.get(c["prop_finish"]) or ""), author=str(props.get(c["prop_designer"]) or
                                                                              f.get("createUserName", "")),
                    created=str(f.get("createDate", ""))[:10], modified=str(f.get("lastModifiedDate", ""))[:10],
                    native_file=f["name"], folder=str(f.get("parentFolderId", "")), cad_app="Inventor",
                    props={k: v for k, v in props.items() if v not in (None, "")})
                if not is_asm:
                    cands = steps.get(stem_key(f["name"]), [])
                    s = cands[0] if cands else None
                    if s is not None:
                        dest = self.step_cache_path(s["id"], s.get("version", ""), s["name"])
                        if not dest.exists():
                            h.download(f"vaults/{vid}/file-versions/{s['id']}/content", dest)
                        rec.step_path, rec.step_name = str(dest), s["name"]
                    else:
                        rec.step_note = "אין קובץ STEP בכספת (ניתן להפיק עם Job Processor)"
                else:
                    item = items_by_number.get(pn)
                    if item:
                        bom = h.json("GET", f"vaults/{vid}/item-versions/{item['id']}/bill-of-materials",
                                     params={"option[oneLevel]": "true"})
                        num_by_item = {iv["id"]: iv.get("number") for iv in bom.get("itemVersions", [])}
                        for link in bom.get("itemBomLinks", []):
                            if link.get("parentItemId") != item["id"]:
                                continue
                            try:
                                q = float(link.get("quantity") or 1)
                            except ValueError:
                                q = 1.0
                            num = num_by_item.get(link.get("childItemId"))
                            if num:
                                rec.children.append({"child": num, "qty": q, "by": "pn"})
                    else:
                        uses = h.json("GET", f"vaults/{vid}/file-versions/{f['id']}/uses")
                        for u in uses.get("results", []):
                            ch = (u.get("childFile") or {}).get("file", {}).get("id")
                            if ch and u.get("fileAssocType", "Dependency") == "Dependency":
                                rec.children.append({"child": self.uid(ch), "qty": 1.0, "by": "uid"})
                out.records.append(rec)
            out.stats = {"file_versions": len(fvs), "native": len(native), "step_files": sum(len(v) for v in steps.values()),
                         "items": len(items_by_number), "records": len(out.records), "api_calls": h.calls}
        finally:
            if sid:
                self._logout(h, sid)
            h.close()
        return out
