# PDM/PLM read-only API research (part-audit connectors and simulators)

Researched 2026-10-03 from public sources only (vendor help, vendor doc CDNs, official Postman/sample files, community forums, public GitHub). Nothing was signed up for, submitted, or uploaded.

Scope: read-only connectors (Python `requests`/`httpx`) that (1) list parts / CAD documents with metadata, (2) download a neutral CAD file (STEP) when one exists, (3) read BOM / where-used. Also: exact request/response shapes for local simulator servers.

## 0. Conventions

| Tag | Meaning |
|---|---|
| **CONFIRMED** | Seen verbatim in an official vendor document, official sample, or official Postman/spec artifact. Source id in brackets, e.g. `[P4]`. |
| **CONFIRMED-COMMUNITY** | Seen verbatim in a public non-vendor artifact (forum post, reseller blog, public GitHub code or Postman collection run against a real server). Usually right but version-specific. |
| **UNCONFIRMED** | Not found in any reachable public source. "(inferred)" means derived from a naming convention or adjacent confirmed facts. Treat as configurable in connectors; make simulators lenient. |

Values in "illustrative" JSON blocks are made up; only the field names carry the stated confidence. Blocks labelled "verbatim" are copied from the cited source (whitespace normalised, long arrays trimmed with `...`).

### 0.1 Pages that could not be read (alternatives used)

- `stackoverflow.com`: blocked for fetch. Used the Tencent Cloud mirror of SO question 60325854 `[C32]`.
- `forum.solidworks.com`: curl gets Akamai 403. Only WebFetch summaries were possible, so SQL snippets from these threads are CONFIRMED-COMMUNITY with lower confidence.
- Siemens Teamcenter Services Reference (`support.industrysoftware.automation.siemens.com/.../services_reference/...`): redirects to the Siemens Webkey login. **Not accessed** (no login per rules). Third-party mirror `help.aviacons.ru` did not resolve.
- `community.sw.siemens.com` Q&A pages: JavaScript-only, so no content was retrievable.
- PTC knowledge-base articles on `ptc.com/en/support/article/CS...`: robots-disallowed or empty. WRS 1.5 guide on community.ptc.com returned HTML, not a PDF. Used the WRS 1.2 User's Guide PDF on ptc.com `[W21]` and current help pages instead.
- APS (Autodesk) doc pages are a single-page app. Their content was fetched from the APS doc CDN (`developer.doc.autodesk.com/bPlouYTd/vault-vault-api-spec-main-747837/...`), the same source the site loads.
- SOLIDWORKS PDM installation-guide PDF: curl returned an empty reply. WebFetch got partial content `[P33]`.

### 0.2 Summary matrix

| | SOLIDWORKS PDM Professional | Autodesk Vault Professional | PTC Windchill (WRS) | Siemens Teamcenter |
|---|---|---|---|---|
| Interface for connector | REST Web API (2022+), else COM, else SQL | Vault Data API REST v2 (server 2025.2+), else SOAP/.NET SDK | OData v4 (WRS) | JSON-over-HTTP SOA ("JsonRestServices") |
| Auth | `POST api/{vault}/authenticate` gives `JwtString`; send `Authorization: Bearer <jwt>` | `POST /sessions` gives `accessToken` (`V:<guid>`); send `Authorization: Bearer V:<guid>` | HTTP Basic on every request (or OAuth Bearer via `/Windchill/oauth/servlet/odata`). CSRF nonce needed for **any POST**, including read-only actions | `POST .../Core-2011-06-Session/login`, then session cookie (`JSESSIONID`). Via the AW gateway also `XSRF-TOKEN` cookie echoed as `X-XSRF-TOKEN` |
| List parts/files | `POST searchvariables` (2024+), `GET folders/{id}/browse`, `POST search` | `GET file-versions`, `GET item-versions`, `GET search-results`, `POST :advanced-search` | `GET ProdMgmt/Parts`, `GET CADDocumentMgmt/CADDocuments` | Saved query (`Query-2008-06-SavedQuery/executeSavedQueries`) or `Query-2012-10-Finder/performSearch` |
| Metadata | `files/{id}/{ver}/variables`, `.../datacard` | `option[propDefIds]=all` + `property-definitions` | entity properties incl. soft attributes (IBAs) | `Core-2006-03-DataManagement/getProperties` + object property policy |
| File download | `GET files/{id}/{ver}/download` (redirect) | `GET file-versions/{id}/content` (Range ok), `GET .../signedurl` | URLs in `AllPrimaryContents`, `Attachments`, `Representations(...).AdditionalFiles` | `getFileReadTickets`, then `GET {fsc}/{original_file_name}?ticket=...` |
| BOM | `GET bom/{bomTypeId}/{fileId}/{ver}/{folderId}/computed`, `references`, `allreferences` | `GET item-versions/{id}/bill-of-materials`, `GET file-versions/{id}/uses` | `GET Parts('id')/Uses`; `POST Parts('id')/PTC.ProdMgmt.GetPartStructure` | `createBOMWindows`, then `expandPSOneLevel`/`expandPSAllLevels`, then `closeBOMWindows` |
| Where-used | `GET files/{id}/{ver}/{cfg}/{folderId}/whereused` | `GET file-versions/{id}/parents`, `GET item-versions/{id}/parents` | `GET Parts('id')/UsedBy` | `whereUsed` exists but its JSON shape is UNCONFIRMED. Recommend inverting collected BOM edges |
| Pagination | none documented | `limit` + `cursorState`, follow `pagination.nextUrl` | `@odata.nextLink` (`$skiptoken`), `Prefer: odata.maxpagesize=N` | Finder: `startIndex`/`maxToLoad`/`maxToReturn`; saved query: `maxNumToReturn` |

---

## 1. SOLIDWORKS PDM

### 1.0 Editions and which interface to use

- **Web API is PDM Professional only.** "SOLIDWORKS PDM Web API Server (SOLIDWORKS PDM Professional only)" (CONFIRMED `[P1][P31][P33]`). First release: 2022. Release notes list 2022, 2023, 2024 and 2025 Web API changes; the 2026 notes are unchanged from 2025 (CONFIRMED `[P3]`).
- Why it exists: "EXALEAD® OnePart users can use a Web API server to index and retrieve SOLIDWORKS PDM data." (CONFIRMED `[P31][P33]`). OnePart is Dassault's part-reuse/duplicate-finder product, so this API was built for exactly this use case.
- **COM API**: PDM Professional. "SOLIDWORKS PDM Standard does not have an API" (CONFIRMED-COMMUNITY, Blue Byte's CADOverflow `[C34]`).
- **SQL**: technically readable on any edition. See the EULA note in 1.c.
- "Web2" (browser client) is not an API. No public REST surface for Web2 was found (UNCONFIRMED that none exists).

### 1.a SOLIDWORKS PDM Pro Web API (REST)

#### Hosting and base URL

- ASP.NET Web API on IIS, via OWIN (CONFIRMED `[P1]`). IIS site `SWPDMWebAPI`, app pool `SOLIDWORKS PDM WebAPI`, install path example `C:\inetpub\wwwroot\SOLIDWORKSPDM\WebApi` (CONFIRMED `[P1]`).
- Setup in the Administration tool: Web API Servers, then Add Web API Server (name, host URL, port 0-65535, HTTP/HTTPS), then add a vault, then configure the vault (CONFIRMED `[P1][P32]`).
- Base URL: `http(s)://<host>:<port>/api/` (CONFIRMED, official Python sample `basicUrl = "http://machine_name:port/api/"` `[P4]`).
- Port is configurable. `65453` appears in the official Postman environment (`host = http://localhost:65453/`, `basicURL = http://LP15-J4M-DSA:65453/api/JEB2024_SP01/`) `[P27]` and in Blue Byte's guide `[P34]`. That it is the *default* is UNCONFIRMED. The official C# sample uses `8082` `[P4]`.
- JSON and XML are both supported (`application/json, text/json`, `application/xml, text/xml`). Send `Accept: application/json` (CONFIRMED `[P4]`).
- Root folder id is `1`: official samples call `folders/1/browse` and the Postman env has `folderId = 1` (CONFIRMED `[P4][P27]`).

#### Authentication

```
POST /api/{vaultName}/authenticate
Content-Type: application/json;charset=UTF-8
version: 30.0          <- present in the official Python sample; purpose undocumented [P4]

{"Username": "Admin", "Password": "..."}
```

- Request body `{"Username": "...", "Password": "..."}` (CONFIRMED `[P4][P28]`). The official JS sample sends lowercase `username`/`password` and works, so binding is case-insensitive (CONFIRMED by sample `[P30]`).
- Response contains `JwtString` (CONFIRMED `[P4][P28][P30]`) and `Success` (CONFIRMED by the official Postman test `pm.test(jsonData.Success===true)` `[P28]`). The body also contains the text `UserId` (Postman test `pm.expect(pm.response.text()).to.include("UserId")` `[P28]`). The full schema is **UNCONFIRMED**: no JSON sample is published, and the doc only describes an `HttpResponseMessage` wrapper (`Version`, `Content`, `StatusCode`, `ReasonPhrase`, `Headers`, `RequestMessage`, `IsSuccessStatusCode`) `[P4]`.
- Later calls send `Authorization: Bearer <JwtString>` (CONFIRMED `[P4]`).
- JWT (HS256) claims, decoded from the token in the official Postman env `[P27]` (CONFIRMED):
  `{"Username":"Admin","UserID":"2","VaultName":"2_24_2021","VaultVersion":"2903","Role":"","Session":"1f649644-...","IndexingUserId":"0","iss":"SolidWorksPDM","aud":"PDMApiURL","exp":1616112931,"nbf":1616069731}`
  In that sample `exp - nbf` = 43200 s (12 h). Whether the lifetime is configurable is UNCONFIRMED. Blue Byte: "there is no way to determine when the access token expires", so keep the token until you get 401, then re-authenticate (CONFIRMED-COMMUNITY `[P34]`).

Simulator response suggestion (only `JwtString`/`Success` are confirmed; `UserInfo` mirrors the `UserInfo{UserName,UserId}` class in the official C# sample and is UNCONFIRMED here):
```json
{"Success": true, "JwtString": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9....", "UserInfo": {"UserId": 2, "UserName": "Admin"}}
```

#### Read-only endpoints

Release-note version tags: "2022" means available since the 2022 Web API; "2024" means added in 2024 (CONFIRMED `[P3]`). The 2022 forms use query parameters. 2024 added `/{folderId}` path variants. **Use the 2022 forms for maximum compatibility.** All need the Bearer token unless noted.

| Verb | Path (relative to `/api/`) | Since | Returns | Ref |
|---|---|---|---|---|
| GET | `version/webapi` | 2022 | `WebAPIVersionModel {SwCompany, SWCopyright, ProdName, ProdAppVersion, ProdFileVersion}`. Whether auth is needed is UNCONFIRMED | `[P26]` |
| GET | `configuration/vaults?vaultName={vaultName}` | 2022 | `VaultProperties[] {Name, DatabaseName, ArchiveServer, ArchiveServerPort, DatabaseServer, CommandTimeOut, IndexingUserId}` | `[P24]` |
| GET | `{vault}` or `{vault}/info` | 2022 | vault properties (shape not fetched, UNCONFIRMED) | `[P2]` |
| GET | `{vault}/folders/{folderId}` or `/info` | 2022 | `FolderInfo {Folder{FolderId, FolderPath}, FolderName, ParentFolderId}` | `[P25]` |
| GET | `{vault}/folders/{folderId}/browse` | 2022 | `ObjectInfo[]` (files and sub-folders, one level) | `[P7]` |
| GET | `{vault}/search` | 2022 | `VaultObject[] {Id, Type}` ("Gets objects in the specified vault"; no parameters documented) | `[P6]` |
| POST | `{vault}/search` | 2022 | body: a JSON **string** (`"bracket"`), returns `VaultObject[]` | `[P6]` |
| POST | `{vault}/searchvariables` | **2024** | `SearchVariablesModel`, returns `ObjectInfo[]` (see below) | `[P5][P3]` |
| GET | `{vault}/files/{fileId}/{version}/info` (2024 adds `?folderId=` and `/{folderId}/info`) | 2022 | `ObjectInfo` (doc sample shows an array) | `[P8]` |
| POST | `{vault}/files/info` | 2022 | body `[1, 2]` (file ids), returns `ObjectInfo[]` | `[P21]` |
| POST | `{vault}/files/infofrompath` | 2023 | body: a JSON string, vault-relative path (doc example `\\Test1\Test2\\File1.txt`), returns `ObjectInfo[]` | `[P22]` |
| GET | `{vault}/files/{fileId}/{version}/info/extended` | 2022 | `VersionInfoExtended {StateId, State, Workflow, Category, ReplicatedTo, Branches}` | `[P20]` |
| GET | `{vault}/files/{fileId}/{version}/configurations` | 2022 | `Config[] {ConfigurationName, ConfigurationId}` | `[P23]` |
| GET | `{vault}/files/{fileId}/{version}/variables` | 2022 | `ConfigInfo[] {ConfigurationName, ConfigurationId, Models: VariableInfo[]}` | `[P9]` |
| GET | `{vault}/files/{fileId}/{version}/datacard?folderId=` | 2022 | `DataCard` (see below) | `[P10]` |
| GET | `{vault}/files/{fileId}/versions?folderId=` | 2022 | `FileRevisionInfo[]` | `[P11]` |
| GET | `{vault}/files/{fileId}/{version}/references?configId=&folderId=` (configId default -1) | 2022 | top-level `FileRef` | `[P12]` |
| GET | `{vault}/files/{fileId}/{version}/allreferences?configId=&folderId=&includeSubParents=` | 2022 | full reference tree `FileRef` | `[P13]` |
| GET | `{vault}/files/{fileId}/{version}/whereused?configId=&folderId=&anyVersion=` (2024 adds `files/{fileId}/{version}/{configId}/whereused?folderId=&anyVersion=` and `files/{fileId}/{version}/{configId}/{folderId}/whereused?anyVersion=`; configId default -1, anyVersion default false) | 2022 | parents as `FileRef` | `[P14][P3]` |
| GET | `{vault}/files/{fileId}/bominfo?folderId=` | 2022 | `BOMInfo` (lists the BOMs available for the file) | `[P17]` |
| GET | `{vault}/bom/{bomTypeId}/{fileId}/{version}/{folderId}/computed?configId=&latest=` | 2022 | `ComputedBOM` | `[P16]` |
| GET | `{vault}/bom/{bomTypeId}/{fileId}/{version}/{folderId}/weldmentcutlist?configId=&latest=` | 2022 | `ComputedBOM` | `[P16]` |
| GET | `{vault}/bom/{bomDocumentId}/{version}/{folderId}/named` | 2022 | `NamedBOM {Columns[]{ColumnNo, ColumnName}, Values[]{RowNo, ColumnNo, Value}}` | `[P18]` |
| GET | `{vault}/files/{fileId}/{version}/download` (2024 adds `?folderId=` and `/{folderId}/download`) | 2022 | `RedirectResult {Location, Request}`, i.e. an HTTP redirect to the content | `[P15]` |
| GET | `{vault}/files/{fileId}/{version}/thumbnails` | 2022 | thumbnail (not detailed) | `[P2]` |
| GET | `{vault}/workflows` | 2022 | `WorkflowList` (see below) | `[P19]` |
| GET | `{vault}/users` | 2022 | users (used by the official C# sample) | `[P4][P3]` |

Write or side-effect endpoints exist. A read-only connector must never call them; whitelist instead:
- `POST .../datacard`
- `POST files/CheckOut`, `UndoCheckOut`, `buildtree/*`
- `DELETE files/...`, `DELETE folders/...`, `PUT folders/...`
- `stage`, `checkin/*`, `changeset/*`
- `state/.../changestate`
- `configuration/hooks/*`, `configuration/fileserverroot`
- `delete/computetree`
- the generic `api/{uri}` GET/POST/PUT/PATCH/DELETE ("Default" group)
- `notifications/markRead`

Read-only POSTs that are safe: `search`, `searchvariables`, `files/info`, `files/infofrompath`, `folders/info` (CONFIRMED list `[P2][P3]`).

#### Models (official "Sample Data", verbatim, placeholder values)

`ObjectInfo` (search, browse, info) `[P5][P7][P8]`:
```json
{
 "Id": 1, "Name": "sample string 2", "Size": 3,
 "ModifiedDate": "2024-11-27T09:51:59.716492-05:00",
 "Version": 5, "State": "sample string 6", "StateId": 7,
 "ParentFolderId": 8, "Path": "sample string 9", "Type": 0,
 "IsLocked": 10, "LockedBy": 11, "IsShared": 12, "IsToolbox": 13, "IsDeleted": 14
}
```
- `Type`: `Folder = 0`, `File = 1`, `Bom = 3`. Flags are integers. `Path` is the folder path (CONFIRMED `[P5]`).
- The official C# sample class adds `UserInfo`, `FullName`, `Initials` to `ObjectInfo` (used for `/users`) `[P4]`.

`ConfigInfo`/`VariableInfo` (`.../variables`) `[P9]`:
```json
[{"Models": [{"VarId": 1, "VarName": "sample string 2", "VarValue": "sample string 3", "VarType": 0, "Mandatory": true, "VersionFree": true}],
  "ConfigurationName": "sample string 1", "ConfigurationId": 2}]
```
`VarType` values: `VarTypeNone=0, VarTypeText=1, VarTypeInt=2, VarTypeFloat=3, VarTypeBool=4, VarTypeDate=5` (CONFIRMED `[P9]`). Values are strings (`VarValue`).

`DataCard` (`.../datacard`) `[P10]`:
```json
{
 "VariablesWithWriteAllConfigs": [1, 2],
 "ConfigVarInfo": [
  {"Models": [{"ReadOnly": true, "Multiline": true, "VarId": 3, "VarName": "sample string 4", "VarValue": "sample string 5", "VarType": 0, "Mandatory": true, "VersionFree": true}],
   "ConfigurationName": "sample string 1", "ConfigurationId": 2}
 ],
 "CardVariableInfo": [{"VariableId": 1, "VariableValueOptions": ["sample string 1", "sample string 2"]}]
}
```

`FileRevisionInfo` (`.../versions`) `[P11]`:
```json
[{"InfoType": 0, "VersionNumber": 1, "Text": "sample string 2", "Revision": "sample string 3", "FileSize": 4, "VersionDate": "2024-11-27T09:52:30.3340279-05:00"}]
```
- `InfoType`: `Version=0`, `Revision=1`, `Label=2`.
- `VersionNumber` is valid only for InfoType 0, `Revision` only for 1, `Text` only for 2 (CONFIRMED `[P11]`).
- So the current revision is the latest entry with `InfoType=1`. That is an inference, UNCONFIRMED.

`FileRef` (`references`, `allreferences`, `whereused`): **no JSON sample is published.** The parameter tables give these names (CONFIRMED as names, nesting per table) `[P12][P13][P14]`:
- `File` (FileInfo):
  - `File {FileId, FileName}`. The doc spells it "File Name" in one place and "FileID/FileName" in another, so exact key casing is UNCONFIRMED.
  - `Folder {FolderId, FolderPath}`
  - `Version`
  - `Config {ConfigurationName, ConfigurationId}`
- `IsCyclic` (bool)
- `IsToolbox` (int)
- `ObjectType`: `ObjType_NoObject=0, ObjType_File=1, ObjType_InternalComponent=2, ObjType_SavedBOM=3, ObjType_Item=4, ObjType_CutListItem=5`
- `Warnings[] {Message, IsBlocking, IsError}`
- `References[]` (recursive `FileRef`)

Simulator shape (UNCONFIRMED casing):
```json
{"File": {"File": {"FileId": 12, "FileName": "bracket.sldprt"}, "Folder": {"FolderId": 4, "FolderPath": "\\Parts\\"}, "Version": 3,
          "Config": {"ConfigurationName": "Default", "ConfigurationId": 2}},
 "IsCyclic": false, "IsToolbox": 0, "ObjectType": 1, "Warnings": [], "References": []}
```
- Quantity is not documented on `FileRef` (UNCONFIRMED). For quantities use the computed BOM, or `XRefs.RefCount` in SQL (1.c).

`BOMInfo` (`bominfo`) `[P17]`, verbatim with arrays trimmed:
```json
{
 "NamedBOM": {"BOMList": [{"Folder": {"FolderId": 1, "FolderPath": "sample string 2"}, "Config": {"ConfigurationName": "sample string 1", "ConfigurationId": 2}, "BOMId": 1, "BOMName": "sample string 2", "VersionNo": 3, "SavedBOM": true}]},
 "ComputedBOM": {"BOMList": [{"Folder": {"FolderId": 1, "FolderPath": "sample string 2"}, "Configs": [{"ConfigurationName": "sample string 1", "ConfigurationId": 2}], "BOMId": 1, "BOMName": "sample string 2"}]},
 "WeldmentCutlistBOM": {"BOMList": []},
 "WeldmentBOM": {"BOMList": []}
}
```
- `ComputedBOM` (`.../computed`): `{ "Columns": [{"ColumnNo": int, "ColumnName": str}], "File": BOMRef }`, where `BOMRef = { "File": BOMRow, "References": [BOMRef] }` (CONFIRMED names `[P16]`).
- **The `BOMRow` fields are not documented and no JSON sample is published** (UNCONFIRMED).
- Using `ComputedBOM.BOMList[].BOMId` from `bominfo` as `{bomTypeId}` is an inference (UNCONFIRMED). The official Postman env has `asmBOMtype = 1` and `weldBOMtype = 4` `[P27]`.

`WorkflowList` (`workflows`) `[P19]`:
```json
{"Workflows": [{"WorkflowId": 1, "WorkflowName": "sample string 2", "States": [{"StateId": 1, "StateName": "sample string 2", "IgnorePreviousPermissions": 3}]}]}
```

#### `searchvariables` (2024+): the main listing call

Request model `SearchVariablesModel` `[P5]`:
```json
{
 "Name": "sample string 1",
 "ObjectTypeCriteria": 1,
 "StartPath": "sample string 2",
 "PathCriteria": 1,
 "VersionCriteria": 1,
 "SearchOperand": 0,
 "Variables": [{"VariableName": "sample string 1", "SearchValue": "sample string 2"}]
}
```

| Field | Values (CONFIRMED `[P5]`) |
|---|---|
| `Name` | file or folder name, may be empty; supports `%` wildcard |
| `ObjectTypeCriteria` | `1` Files, `2` Folders, `3` Files and folders |
| `StartPath` | relative folder path; empty means vault root. Official Postman uses both `"TestSearch"` and `"\\TestSearch\\"` `[P28]` |
| `PathCriteria` | `1` current folder, `2` current folder and subfolders, `3` all folders |
| `VersionCriteria` | `1` latest version, `2` all versions |
| `SearchOperand` | `0` None, `1` AND, `2` OR (combines `Variables`) |
| `Variables` | list of `{VariableName, SearchValue}`; `SearchValue` supports `%` (Postman: `"Mag%"`) `[P28]` |

- Remarks `[P5]`: name and variables are combined. If both are empty, it returns everything matching the other criteria. That is a usable full listing: `{"Name":"","ObjectTypeCriteria":1,"StartPath":"","PathCriteria":3,"VersionCriteria":1,"SearchOperand":0,"Variables":[]}` (inferred from the remarks, untested).
- Response: `ObjectInfo[]`. It does **not** include variable values, so fetch `.../variables` or `.../datacard` per file.
- Official Postman example (verbatim) `[P28]`:
```json
{"ObjectTypeCriteria":1,"StartPath":"\\TestSearch\\","PathCriteria":2,"VersionCriteria":2,"SearchOperand":0,
 "Variables":[{"VariableName":"Project Number","SearchValue":"456"}]}
```

#### Pagination, download, gotchas

- **No pagination** is documented for `search`, `searchvariables` or `browse`; they return full arrays. The only paged endpoint is `notifications?all=&pageNo=&pageSize=` (CONFIRMED `[P3]`). For big vaults, partition by folder (`PathCriteria=1`, walk folders) or by name prefix (inferred).
- Enumerating everything (inferred, UNCONFIRMED at scale): `GET {vault}/search` gives `VaultObject[] {Id, Type}`; then `POST files/info` with batches of ids gives `ObjectInfo[]`.
- **Download** returns `RedirectResult {Location, Request}`, so expect an HTTP 3xx (inferred from the documented return type `[P15]`). With `requests`, keep `allow_redirects=True`. `requests` drops the `Authorization` header on cross-host redirects; same-host redirects keep it.
- `folderId` exists because a file can be shared into several folders. Pass `ObjectInfo.ParentFolderId`. Many endpoints document "folderId default 0" (CONFIRMED `[P8]`).
- `{version}` is required in most paths. Whether `0` means latest is UNCONFIRMED: `info` documents "default value is 0" without semantics. Use `ObjectInfo.Version` from a `VersionCriteria=1` search.
- With `VersionCriteria=2` you get one row per version. De-duplicate by `Id`.
- CORS (IIS CORS module plus a `web.config` `<cors>` block) only matters for browser clients `[P1]`.
- Feature-detect via `GET version/webapi`, or handle 404 for 2024-only endpoints such as `searchvariables`.

#### Python sketch (requests)

```python
import requests
BASE, VAULT = "http://pdm-web:65453/api", "MyVault"
s = requests.Session()
s.headers["Accept"] = "application/json"
tok = s.post(f"{BASE}/{VAULT}/authenticate", json={"Username": USER, "Password": PWD}).json()["JwtString"]
s.headers["Authorization"] = f"Bearer {tok}"
files = s.post(f"{BASE}/{VAULT}/searchvariables", json={
    "Name": "%.sldprt", "ObjectTypeCriteria": 1, "StartPath": "", "PathCriteria": 3,
    "VersionCriteria": 1, "SearchOperand": 0, "Variables": []}).json()
for f in files:
    fid, ver, fold = f["Id"], f["Version"], f["ParentFolderId"]
    cfgs = s.get(f"{BASE}/{VAULT}/files/{fid}/{ver}/variables").json()   # 2022 form
    parents = s.get(f"{BASE}/{VAULT}/files/{fid}/{ver}/whereused",
                    params={"configId": -1, "folderId": fold, "anyVersion": "false"}).json()
# STEP: PDM stores STEP as ordinary files (e.g. *.step/*.stp) -> search by Name "%.st%p" and download:
r = s.get(f"{BASE}/{VAULT}/files/{fid}/{ver}/download", params={"folderId": fold}, stream=True)
```

### 1.b COM API (EdmVault5 via pywin32/comtypes)

#### Installation, ProgID, bitness

- Interop assemblies: `EPDM.Interop.epdm.dll` and `EPDM.Interop.EPDMResultCode.dll` in the top folder of the PDM install. "32-bit interops are shipped with the 32-bit version ... 64-bit interops are shipped with the 64-bit version" (CONFIRMED `[C28]`). .NET stand-alone apps should target **Any CPU** and **deselect Prefer 32-bit** (CONFIRMED `[C28]`).
  - So the process must match the client's bitness. For Python, use **64-bit CPython plus 64-bit pywin32** on a 64-bit client (inferred from `[C28]`).
  - The doc also warns that methods passing **arrays of structures** need `Embed Interop Types = False` in .NET `[C28]`. Python COM marshalling of struct arrays (e.g. `IEdmBomView.GetColumns`, which returns `EdmBomColumn[]`) may therefore fail (UNCONFIRMED).
- Type library renamed `ConisioLib` to `EdmLib` in 6.5; interface names unchanged (CONFIRMED `[C29]`).
- ProgID `"ConisioLib.EdmVault"` (CONFIRMED-COMMUNITY: CATI VBScript `CreateObject("ConisioLib.EdmVault")` `[C30]`; CodeStack VB.NET `Type.GetTypeFromProgID("ConisioLib.EdmVault")` `[C31]`). Versioned form `"ConisioLib.EdmVault.1"` (CONFIRMED-COMMUNITY `[C32]`). Not found in official help (UNCONFIRMED officially).
- pywin32 caveats (CONFIRMED-COMMUNITY `[C32]`):
  - makepy-generated classes can lack methods on interfaces returned by `CreateUtility`.
  - Working alternative: `comtypes.client.GetModule(r'C:\Program Files (x86)\SOLIDWORKS PDM\EdmInterface.dll')` then `comtypes.client.CreateObject('ConisioLib.EdmVault.1')`. The path shown is from that user's install; on 64-bit clients it may differ (UNCONFIRMED).
  - With makepy (early binding), ByRef outputs come back as a tuple, e.g. `vault.GetFileFromPath(file_path, folder)[0]`.

#### Login

| Call | Signature | Notes |
|---|---|---|
| `IEdmVault5.LoginAuto` | `(bsVaultName: str, hParentWnd: int)` | Logs in as the user already logged into the vault view / client. Shows a login dialog if nobody is. "properly consumes a license". Errors: `E_EDM_ALREADY_LOGGED_IN`, `E_EDM_CANT_OPEN_DATABASE`, `E_EDM_CANCELLED_BY_USER` (CONFIRMED `[C1]`) |
| `IEdmVault5.Login` | `(bsUserName, bsPasswd, bsVaultName)` | Custom apps that log in, use a vault view, **"or directly accesses a vault database"** must first call `IEdmVault13::LoginEx` or `LoginAuto` to comply with the EULA (CONFIRMED `[C2]`) |

#### Files, folders, objects

- `IEdmVault5` (CONFIRMED `[C3][C27]`):
  - `RootFolder`, `RootFolderID`, `RootFolderPath`, `IsLoggedIn`
  - `GetFolderFromPath(path)`
  - `GetFileFromPath(bsFilePath, out ppoRetParentFolder) -> IEdmFile5` (null if missing)
  - `GetObject(EdmObjectType, id)`, with `EdmObject_File = 1`, `EdmObject_Folder = 2`, `EdmObject_State = 3` (CONFIRMED `[C26]`). `IEdmVault9::GetObjects` is the batch variant `[C27]`.
- `IEdmFolder5` (CONFIRMED `[C19]`):
  - Properties: `ID`, `Name`, `LocalPath`, `ParentFolder`
  - `GetFirstFilePosition()`, then `GetNextFile(pos) -> IEdmFile5`
  - `GetFirstSubFolderPosition()`, then `GetNextSubFolder(pos)`
  - Loop while `not pos.IsNull` (`IEdmPos5.IsNull`). `GetNextFile` returns `E_EDM_END_OF_LIST` past the end.
- `IEdmFile5 : IEdmObject5`:
  - Properties: `ID`, `Name`, `CurrentVersion` (int), `CurrentRevision` (string), `CurrentState` (returns `IEdmState5 : IEdmObject5`, so `.Name` and `.ID`), `IsLocked`, `LockedByUser`
  - Methods: `GetConfigurations(version)`, `GetLocalPath(folderId)`, `GetFirstFolderPosition`/`GetNextFolder`, `GetEnumeratorVariable`, `GetFileCopy`, `GetReferenceTree`
  - (CONFIRMED `[C4][C27]`, IEdmState5 inheritance confirmed on its interface page)

#### Search

- Creating a search object (CONFIRMED `[C3][C9][C26]`):
  - `IEdmVault21.CreateSearch2()` (2020+), returns `IEdmSearch5`; cast to `IEdmSearch9` for advanced syntax.
  - `IEdmVault5.CreateSearch` is **obsolete**.
  - `IEdmVault7.CreateUtility(EdmUtil_Search = 1)` creates a regular search.
- `IEdmSearch5` (CONFIRMED `[C5]`):
  - Properties: `FileName`, `FindFiles`, `FindFolders`, `FindHistoricStates`, `FindLockedFiles`, `FindUnlockedFiles`, `Recursive`, `StartFolderID`, `State`, `VersionComment`
  - Methods: `Clear()`, `GetFirstResult()`, `GetNextResult()`
- `IEdmSearch6.SetToken(EdmSearchToken eTok, object oValue)` and `GetToken`. **"For every search you must explicitly set `Edmstok_AllVersions` to either true or false. If you leave it unset, unexpected search results can occur."** (CONFIRMED `[C6]`)
  - Token values (CONFIRMED `[C7]`): `Edmstok_Recursive=1`, `Edmstok_AllVersions=2`, `Edmstok_Name=3`, `Edmstok_FolderPath=4`, `Edmstok_FolderID=5`, `Edmstok_StateName=14`, `Edmstok_StateID=15`, `Edmstok_FindFiles=31`, `Edmstok_FindFolders=32`, `Edmstok_WorkflowName=35`, `Edmstok_Category=44`, `Edmstok_RevisionNo=46`.
- `IEdmSearch8.AddVariable2(ref poIdOrName, ref poValue, int lEdmVarOp)` (2018+). Wildcards `%` (any run) and `_` (one character). With `CreateSearch2`, `poValue` uses the search syntax and `lEdmVarOp` must be null. `BeginAND`/`BeginOR`/`EndAND`/`EndOR` group conditions. Error `E_EDM_KEY_NOT_FOUND` means an unknown variable (CONFIRMED `[C8]`).
- `IEdmSearchResult5 : IEdmObject5` has `ID`, `Name`, `ObjectType`, `Path`, `ParentFolderID`, `Version`, `StateName`, `FileDate`, `FileSize`, `LockedByUserID`, `LockedByUserName`, `LockedOnComputer`, `LockPath`. If the result is a file, cast it to `IEdmFile5` (CONFIRMED `[C10]`).

#### Data-card variables

- `IEdmFile5.GetEnumeratorVariable(bsOptionalPath="")` returns `IEdmEnumeratorVariable5`. The optional path is the full file path; "if not specified, uses location where this file is checked out" (CONFIRMED `[C14]`).
- `IEdmEnumeratorVariable5.GetVar(bsVarName, bsCfgName, out poRetValue) -> bool`:
  - `bsCfgName` is the configuration or layout name; use an empty string for folders and for file types without configurations.
  - Returns `S_FALSE` / `False` if the variable is not found (CONFIRMED `[C11]`).
  - Get configuration names via `IEdmFile5.GetConfigurations` `[C11]`.
- `"@"` configuration: GoEngineer, "The @ tab or CustomProperty tab ... does not correspond to any individual configuration but instead the whole file" (CONFIRMED-COMMUNITY `[C33]`). Passing `"@"` as `bsCfgName` for file-level values is common practice but UNCONFIRMED in official docs.
- In pywin32 with makepy, expect `found, value = ev.GetVar("Description", "@")` (inferred from `[C32]`'s tuple behaviour, UNCONFIRMED).

#### Local copy

`IEdmFile5.GetFileCopy(lParentWnd, ref poVersionNoOrRevisionName, ref poPathOrFolderID, lEdmGetFlags, bsNewName)` (CONFIRMED `[C12]`):
- Version: `0` or `""` means latest.
- `poPathOrFolderID`: `0` copies to **all** folders the file is shared in. A folder path must end with `\`.
- Flags default to `EdmGet_MakeReadOnly = 1`. Others: `EdmGet_Simple = 0`, `EdmGet_Refs = 4`, `EdmGet_RefsVerLatest = 16` `[C26]`.
- Errors include `E_EDM_PERMISSION_DENIED`, `E_EDM_FILE_NOT_FOUND`.
- For many files, `IEdmBatchGet` (`EdmUtil_BatchGet = 12`) is more efficient `[C12][C26]`.
- Writing to a non-vault temp folder via a path argument is documented. It does not modify the vault, but it does populate local files.

#### References, BOM and where-used

- `IEdmFile5.GetReferenceTree(lParentFolderID, lVersionNo=0) -> IEdmReference5` (CONFIRMED `[C13]`).
- Children:
  - `IEdmReference10.GetFirstChildPosition4(out pbsProjectName, bIsTopParent, bPermitReadLocal, bGetSuppressedComponent, lEdmRefFlags, bsConfiguration, lVersion=0) -> IEdmPos5`, then `IEdmReference5.GetNextChild(pos) -> IEdmReference5` (CONFIRMED `[C16][C18]`).
  - Older `GetFirstChildPosition`, `...2` and `...3` are obsolete `[C15]`.
  - Keep passing the same `pbsProjectName` string down the tree `[C16]`.
  - An empty `bsConfiguration` means the file's common configuration `[C16]`.
  - `IEdmReference6::RefCount` gives the reference count / quantity (named in remarks `[C16]`).
- Where-used: `IEdmReference7.GetFirstParentPosition2(lVersionOrZero, bGetAllParentVersions, lEdmRefFlags) -> IEdmPos5`, then `IEdmReference5.GetNextParent(pos)` (CONFIRMED `[C17][C15]`).
- `IEdmReference5` properties: `File`, `FileID`, `Folder`, `FolderID`, `FoundPath`, `Name`, `ReferencedAs`, `VersionLocal`, `VersionRef`, `IsLocked` (CONFIRMED `[C15]`).
- `EdmRefFlags` is documented as *item* reference types (`EdmRef_File=1, EdmRef_Item=2, EdmRef_Dynamic=4, EdmRef_Static=8`) `[C26]`. The value to pass for plain file-to-file references is UNCONFIRMED; test 0 and 1.
- Computed BOM (CONFIRMED `[C20][C21][C22][C23][C24][C25]`):
  1. `IEdmVault7.CreateUtility(EdmUtil_BomMgr = 24)` gives `IEdmBomMgr`. `IEdmBomMgr2.GetBomLayouts2(out EdmBomLayout2[])` (2020+) lists the layouts.
  2. `IEdmFile7.GetComputedBOM(oBomLayoutNameOrID, lVersionNo, bsConfiguration, lEdmBomFlags) -> IEdmBomView`. `lVersionNo` 0 or -1 means latest. Flags: `EdmBf_AsBuilt = 1`, `EdmBf_ShowSelected = 2`.
  3. `IEdmBomView.GetColumns(out EdmBomColumn[])`. Fields: `mbsCaption, meType, mlColumnID, mlFlags, mlVariableID, mlVariableType, mlWidth`.
  4. `IEdmBomView.GetRows(out object[])`, one `IEdmBomCell` per row.
  5. `IEdmBomCell.GetVar(lVariableID, eColumn, out poValue, out poComputedValue, out pbsConfiguration, out pbReadOnly)`. Also `GetTreeLevel()`, `GetPathName()`, `GetItemID()`.
  - `EdmBomColumnType` values: `EdmBomCol_Variable=0, _Name=1, _FileSize=2, _Date=3, _LatestVersion=4, _Path=5, _State=6, _RefCount=11, _Configuration=21, _ID=23, _PartNumber=24, _RefCountNoBomQty=25`.

```python
# pywin32 sketch (needs a 64-bit Python on a PDM client; untested)
import win32com.client as w32
vault = w32.gencache.EnsureDispatch("ConisioLib.EdmVault")   # or w32.Dispatch(...)
vault.LoginAuto("MyVault", 0)
folder = vault.GetFolderFromPath(r"C:\PDM\MyVault\Parts")
pos = folder.GetFirstFilePosition()
while not pos.IsNull:
    f = folder.GetNextFile(pos)
    ev = f.GetEnumeratorVariable("")
    found, desc = ev.GetVar("Description", "@")              # tuple return: UNCONFIRMED
    print(f.ID, f.Name, f.CurrentVersion, f.CurrentRevision, f.CurrentState.Name, desc)
```

### 1.c Read-only SQL on the vault database

**Licensing**: the official `Login` remarks say custom applications that **directly access a vault database** must call `IEdmVault13::LoginEx` or `IEdmVault5::LoginAuto` first to comply with the EULA (CONFIRMED `[C2]`). Have the customer confirm their licensing before using SQL-only access. Use a SQL login with `db_datareader` only.

Tables and columns (all names below seen verbatim in the cited queries):

| Table | Columns seen | Meaning | Confidence |
|---|---|---|---|
| `Documents` | `DocumentID`, `Filename`, `LatestRevisionNo`, `CurrentStatusID`, `Deleted`, `ObjectTypeID`, `DocTypeID`, `Shared`, `UserID`, `LockProject` | one row per file; `LatestRevisionNo` = latest **version** number | CONFIRMED-COMMUNITY `[Q3][Q7][Q8][Q9][Q12]` |
| `DocumentsInProjects` | `DocumentID`, `ProjectID`, `Deleted` | file-to-folder link (several rows for shared files) | CONFIRMED-COMMUNITY `[Q3][Q8]` |
| `Projects` | `ProjectID`, `Path`, `Name` | folders; `Path` like `\Projects\` (leading and trailing `\`); queries concatenate `p.path + d.Filename` | CONFIRMED (official) `[Q1]`, CONFIRMED-COMMUNITY `[Q5][Q6]` |
| `ProjectTree` | `ProjectID`, `ChildProject` | folder hierarchy | CONFIRMED `[Q1]` |
| `Status` | `StatusID`, `Name` | workflow states (join `Documents.CurrentStatusID`) | CONFIRMED-COMMUNITY `[Q7][Q8]`, table purpose `[Q2]` |
| `Variable` | `VariableID`, `VariableName` | data-card variables | CONFIRMED `[Q1]` |
| `VariableValue` | `DocumentID`, `VariableID`, `ProjectID`, `RevisionNo` (= version), `ConfigurationID`, `ValueText`, `ValueCache` | values per file, version and configuration | `ValueCache`/`VariableID`: CONFIRMED `[Q1]`; others CONFIRMED-COMMUNITY `[Q5][Q6][Q9][Q10]` |
| `DocumentConfiguration` | `ConfigurationID`, `ConfigurationName` | configuration names (`@` = file level: inferred from `[C33]`) | CONFIRMED-COMMUNITY `[Q5][Q6]` |
| `ObjectType` | `ObjectTypeID`, `Description` | file vs. internal component and similar | CONFIRMED-COMMUNITY `[Q5][Q6]` |
| `XRefs` | `DocumentID` (parent), `XRefDocument` (child), `RevNr` (parent version), `RefCount` (quantity) | file references, usable for BOM and where-used | CONFIRMED-COMMUNITY `[Q10]` (+ `[Q5]` uses `XRefDocument` as child) |
| `UserRevs` | `DocumentID`, `RevNr`, `Comment` | revision history; a community query aliases `Comment AS 'Revision'` (meaning UNCONFIRMED) | CONFIRMED-COMMUNITY `[Q11]` |
| `Users` | `UserID`, `Username`, `FullName`, `Email` | users | CONFIRMED-COMMUNITY `[Q8]` |
| `Revisions`, `TransitionHistory`, `Transitions`, `Workflows`, `Groups`, `GroupMembers`, `Attribute`, `HistoryRename` | (no columns verified) | named in GoEngineer's list | CONFIRMED (names) `[Q2][Q4]` |

UNCONFIRMED semantics to check against a real vault before relying on them:
- `Documents.ObjectTypeID = 1` = ordinary file. Community queries treat `!= 1` as internal components without a folder path `[Q5][Q6]`.
- `VariableValue.ProjectID`: community duplicate-finder queries filter file values with `vv.ProjectID = 2` and folder-card values with `DocumentID = 1` `[Q5][Q6]`. **Do not hard-code**. The query below doesn't filter on it.
- `ValueText` vs `ValueCache`: the official example uses `ValueCache` for comparisons `[Q1]`. Community queries `CAST(vv.ValueText AS nvarchar(max))` for display `[Q5]` (the column may be `ntext`).

Read-only query: latest version, path, state and selected data-card variables. Composed from the columns above and **untested**:
```sql
-- Parameters: configuration name for values ('@' = file-level tab, inferred); variable names to pivot.
DECLARE @cfg nvarchar(255) = N'@';

WITH vals AS (
    SELECT vv.DocumentID, v.VariableName,
           CAST(vv.ValueText AS nvarchar(max)) AS ValueText,
           ROW_NUMBER() OVER (PARTITION BY vv.DocumentID, vv.VariableID, vv.ConfigurationID
                              ORDER BY vv.RevisionNo DESC) AS rn          -- latest version that wrote the value
    FROM dbo.VariableValue vv
    JOIN dbo.Variable v              ON v.VariableID = vv.VariableID
    JOIN dbo.DocumentConfiguration dc ON dc.ConfigurationID = vv.ConfigurationID
    WHERE v.VariableName IN (N'Number', N'Description', N'Revision', N'Material')
      AND dc.ConfigurationName = @cfg
)
SELECT d.DocumentID,
       MIN(p.Path + d.Filename)            AS VaultPath,     -- shared files: several folders, keep one
       COUNT(DISTINCT dip.ProjectID)       AS FolderCount,
       d.LatestRevisionNo                  AS LatestVersion,
       s.Name                              AS State,
       MAX(CASE WHEN x.VariableName = N'Number'      THEN x.ValueText END) AS [Number],
       MAX(CASE WHEN x.VariableName = N'Description' THEN x.ValueText END) AS [Description],
       MAX(CASE WHEN x.VariableName = N'Revision'    THEN x.ValueText END) AS [Revision],
       MAX(CASE WHEN x.VariableName = N'Material'    THEN x.ValueText END) AS [Material]
FROM dbo.Documents d
JOIN dbo.DocumentsInProjects dip ON dip.DocumentID = d.DocumentID AND dip.Deleted = 0
JOIN dbo.Projects p              ON p.ProjectID = dip.ProjectID
LEFT JOIN dbo.Status s           ON s.StatusID = d.CurrentStatusID
LEFT JOIN vals x                 ON x.DocumentID = d.DocumentID AND x.rn = 1
WHERE d.Deleted = 0
  AND d.ObjectTypeID = 1                    -- ordinary files (UNCONFIRMED semantics)
GROUP BY d.DocumentID, d.LatestRevisionNo, s.Name;
```

BOM children and where-used from `XRefs` (latest parent version). Columns are CONFIRMED-COMMUNITY `[Q10]`; untested:
```sql
-- children of @doc
SELECT c.DocumentID, c.Filename, x.RefCount
FROM dbo.XRefs x
JOIN dbo.Documents par ON par.DocumentID = x.DocumentID AND x.RevNr = par.LatestRevisionNo
JOIN dbo.Documents c   ON c.DocumentID = x.XRefDocument
WHERE par.DocumentID = @doc;

-- where-used of @doc (parents whose latest version references it)
SELECT par.DocumentID, par.Filename, x.RefCount
FROM dbo.XRefs x
JOIN dbo.Documents par ON par.DocumentID = x.DocumentID AND x.RevNr = par.LatestRevisionNo
WHERE x.XRefDocument = @doc;
```
- The referenced *child* version column in `XRefs` is UNCONFIRMED.
- For a ready-made "same value in several files" query (duplicate part numbers), see the DPS/Solidwise query `[Q5][Q6]`. It picks `MAX(RevisionNo)` per (Document, Variable, Configuration) and `EXISTS` another document with an equal `ValueCache`. This is directly relevant to the audit.
- Folder ids in PDM are `ProjectID` and file ids are `DocumentID`. The CodeStack `conisio://` URL uses `projectid=folder.ID&documentid=file.ID` (CONFIRMED-COMMUNITY `[C31]`). So SQL ids and COM/Web API ids are interchangeable (inferred).

---

## 2. Autodesk Vault

### 2.a Vault Data API (REST v2)

#### Availability

- Initial public release v2.0.16 on 2024-11-12. "Requires Vault server version 2025.2 and later." (CONFIRMED `[V6]`).
- Forum: earlier servers (including 2025.0) return 404 at `/AutodeskDM/Services/api/vault/v2` (CONFIRMED-COMMUNITY `[V26]`).
- v2.1.0 (2026-08-04) adds endpoints "available starting from Vault 2027.1": lifecycle reads (`lifecycle-definitions`, `lifecycle-states`), state-update writes, ext-sync tasks (CONFIRMED `[V6][V1]`).
- Scope: "Read-First with Targeted Writes" (CONFIRMED `[V1]`). WIIP describes it for "Autodesk Vault Professional Server" 2025.2+ `[V28]`. Support on Basic/Workgroup is UNCONFIRMED.
- Permissions: "The Data API gives users the same permissions as if they logged on to Vault using the client" (CONFIRMED-COMMUNITY `[V27]`).

#### Base URL

- Direct: `http(s)://<vault-server-name-or-ip>/AutodeskDM/Services/api/vault/v2` (CONFIRMED `[V2]`).
- Via the Vault Gateway: `https://<id>.vg.autodesk.com/AutodeskDM/Services/api/vault/v2` (CONFIRMED `[V2]`).
- OpenAPI spec: `GET /openapi-spec.yml` (relative to the base), no auth (CONFIRMED `[V7][V25]`). **Download it from a real server to generate exact simulator schemas.**
- No-auth endpoints: `GET /server-info`, `GET /vaults`, `GET /vaults/{id}`, `POST /sessions` (CONFIRMED "No security required" `[V8][V9]`; server-info `[V28]`).

#### Authentication

Request (verbatim `[V3][V8]`):
```
POST /AutodeskDM/Services/api/vault/v2/sessions
Content-Type: application/json
Accept: application/json

{"input": {"vault": "Vault", "userName": "TestAccount", "password": "Test123456!", "appCode": "TC"}}
```
`appCode` is "The application name to use for server-side audit logging."

Response (verbatim `[V3][V8]`):
```json
{
 "id": "aac1705d-8956-4fba-962c-4d2b6bfaf398",
 "accessToken": "V:aac1705d-8956-4fba-962c-4d2b6bfaf398",
 "createDate": "2024-10-21T07:56:45.2277149Z",
 "vaultInformation": {"id": "117", "name": "Vault", "url": "/AutodeskDM/Services/api/vault/v2/vaults/117"},
 "userInformation": {"id": "65", "name": "TestAccount", "email": "VaultAPITest@outlook.com", "authTypes": "Vault, Autodesk",
                     "createDate": "2024-06-27T06:29:20.183Z", "isActive": true, "url": "/AutodeskDM/Services/api/vault/v2/users/65"},
 "url": "/AutodeskDM/Services/api/vault/v2/sessions/aac1705d-8956-4fba-962c-4d2b6bfaf398"
}
```
- Later calls send `Authorization: Bearer V:aac1705d-...` (CONFIRMED `[V3]`).
- Windows/AD login: `POST /sessions/win-auth` with body `{"input":{"vault":"Vault","appCode":"TC"}}` and an NTLM challenge (`curl --ntlm -u 'domain\user:pwd'`) (CONFIRMED `[V3]`). In Python, use `requests-ntlm` (inferred).
- Autodesk Account: send an APS three-legged token as `Bearer` (CONFIRMED `[V3]`).
- `GET /sessions/{id}` and `DELETE /sessions/{id}` (logout) (CONFIRMED `[V7]`).
- Login failure (verbatim `[V4]`):
  ```json
  {"statusCode": 400, "errorCode": "301", "title": "Vault error", "detail": "The user name and/or password appears to be invalid; please try again.", "params": []}
  ```
  The session endpoint documents 401 for rejected sign-in `[V8]`. A forum post mentions error code 8011 for auth failure (CONFIRMED-COMMUNITY `[V26]`).

#### Read endpoints (all under `/AutodeskDM/Services/api/vault/v2`)

All CONFIRMED in the Quick Reference `[V7]`; detail pages as cited.

| Verb | Path | Purpose / key params |
|---|---|---|
| GET | `/vaults` | list knowledge vaults `{pagination, results:[{id, name, url}]}` `[V9]` |
| GET | `/vaults/{vaultId}/property-definitions` | `filter[entityClassId]=FILE\|FLDR\|ITEM\|CO`, `filter[systemNames]=`, `filter[propDefIds]=`, `option[extendedModels]`, `option[includeBOMAssociationProperty]` `[V19]` |
| GET | `/vaults/{vaultId}/file-versions` | `q`, `filter[CheckoutUserName\|CreateUserName\|CategoryName\|state]`, `option[latestOnly]` (default **true**), `option[releasedFilesOnly]`, `option[extendedModels]`, `option[propDefIds]=all\|1,2,3`, `sort=Revision desc,Name asc`, `limit`, `cursorState` `[V10]` |
| GET | `/vaults/{vaultId}/file-versions/{id}` | one version, **always with all properties** `[V22]` |
| GET | `/vaults/{vaultId}/files/{id}` | file master `{id, url, versionType, fileVersion}` |
| GET | `/vaults/{vaultId}/files/{id}/versions` | version history |
| GET | `/vaults/{vaultId}/file-versions/{id}/content` | binary download; `Range: bytes=0-999` gives 206; `Accept-Ranges: bytes`; 416 if unsatisfiable; `allowSync`, `contentDisposition` `[V11]` |
| HEAD | `/vaults/{vaultId}/file-versions/{id}/content` | metadata; on error `x-vault-error-code`, `x-vault-error-detail` headers `[V4]` |
| GET | `/vaults/{vaultId}/file-versions/{id}/signedurl` | `{"id": "43", "url": "https://...?sig=...&expires=..."}`; `expirationTime` max **180 s** `[V12]` |
| GET | `/vaults/{vaultId}/file-versions/{id}/uses` | children: `option[includeHidden]`, `option[includeRelatedDocuments]`, `option[releaseBiased]` (default true), `option[releasedOnly]`, `option[getLatestAssocs]` (default true), `option[recurse]` (default false), `option[propDefIds]`, `limit`, `cursorState` `[V13]` |
| GET | `/vaults/{vaultId}/file-versions/{id}/parents` | where-used, same options (`option[recurse]` = all levels of parents) `[V14]` |
| GET | `/vaults/{vaultId}/file-versions/{id}/item-versions` | items for the file version |
| GET | `/vaults/{vaultId}/file-versions/{id}/visualization-attachments` | DWF etc. |
| GET | `/vaults/{vaultId}/folders/{id}` / `/contents` / `/sub-folders` | `contents`: `q`, `option[searchSubFolders]`, `option[includeFolders]` (default true), `option[latestOnly]`, `option[propDefIds]`, `sort`, `limit`, `cursorState`. Root folder id is **1** (CONFIRMED-COMMUNITY `[V28]`) `[V24]` |
| GET | `/vaults/{vaultId}/items`, `/items/{id}`, `/items/{id}/versions` | item masters |
| GET | `/vaults/{vaultId}/item-versions` | `q`, `option[propDefIds]`, `option[releasedItemsOnly]`, `option[latestOnly]` (default true), `sort`, `limit`, `cursorState` `[V15]` |
| GET | `/vaults/{vaultId}/item-versions/{id}` | one item version |
| GET | `/vaults/{vaultId}/item-versions/{id}/bill-of-materials` | `option[bomType]=Latest\|Tip\|Historic\|Effective`, `option[date]`, `option[rolledUp]`, `option[oneLevel]`, `option[referenceDesignators]`, `option[occurrences]`, `option[excludedBOMLinks]`, `option[unassignedComponents]`, `option[includeBOMAssociationProperty]` `[V16]` |
| GET | `/vaults/{vaultId}/item-versions/{id}/parents` | item where-used (same response structure as the BOM) `[V17]` |
| GET | `/vaults/{vaultId}/item-versions/{id}/associated-files` | `itemAssociationType`: `Primary`, `Secondary`, `Tertiary`, `StandardComponent`, `PrimarySub`, `SecondarySub`, `PinnedAttachment`, `NotPinnedAttachment`, ... `[V18]` |
| GET | `/vaults/{vaultId}/search-results` | basic search: `q`, `option[searchContent]`, `option[searchSubFolders]`, `option[releasedFilesOnly]`, `option[releasedItemsOnly]`, `option[latestOnly]`, `option[propDefIds]`, `sort`, `limit`, `cursorState` `[V20]` |
| POST | `/vaults/{vaultId}:advanced-search` | read-only POST; body below `[V21]` |
| GET | `/vaults/{vaultId}/lifecycle-definitions`, `/lifecycle-states` | **Vault 2027.1+** `[V6]` |

Write endpoints exist; never call them:
- `POST files:update-states`, `files:update-lifecycle-definitions`
- `POST items:update-states`, `items:update-lifecycle-definitions`
- `POST folders:update-states`, `folders:update-lifecycle-definitions`
- `POST /jobs`, `/ext-sync-tasks*`, `system-options`/`vault-options` (POST/PATCH/DELETE)

Advanced search request body: the schema uses camelCase `entityTypesToSearch`, `foldersToSearch`, `searchCriterias[] {propertyDefinitionUrl, operator, searchString}`, `sortCriterias[] {propertyDefinitionUrl, ascending}`. Operators: `Unknown, Contains, DoesNotContain, IsExactly, IsEmpty, IsNotEmpty, GreaterThan, GreaterThanOrEqualTo, LessThan, LessThanOrEqualTo, NotEqualTo` (CONFIRMED `[V21]`). The official example uses PascalCase, so binding is case-insensitive (inferred). Verbatim:
```json
{"EntityTypesToSearch": ["file", "folder"], "FoldersToSearch": [], "SearchCriterias": [], "SortCriterias": null}
```

#### Pagination (CONFIRMED `[V9][V10]`)

- `limit`: default 100. The hard cap is the ADMS setting "Global Setting -> Page size configuration". Examples show the server reporting `"limit": 1000`.
- Response `pagination`: `limit`, `totalResults`, `nextUrl`, `indexingStatus` (`IndexingComplete`, `IndexingProperties`, `IndexingContent`, `NA`). If indexing is still in progress, search results are incomplete.
- `nextUrl` is **host-relative** (`/AutodeskDM/Services/api/...&cursorState=...`) and carries the cursor. "A page may be empty but still include a next page URL. Continue paging until this attribute is null or absent."
- Collections can include an `included` map for de-duplicated related objects, e.g. `included.folder["2"]` and `included.propertyDefinition["29"]`. Resolve `parentFolderId` through it `[V10][V22]`.

#### JSON examples (verbatim, trimmed to one element)

`GET /vaults/117/file-versions?limit=2` `[V10]`:
```json
{
 "pagination": {"limit": 2, "totalResults": 7,
   "nextUrl": "/AutodeskDM/Services/api/vault/v2/vaults/117/file-versions?limit=2&cursorState=PD94bWwg...",
   "indexingStatus": "IndexingComplete"},
 "results": [
  {"name": "Test1.ipt", "id": "40", "state": "", "stateColor": 0, "revision": "", "category": "Base", "categoryColor": -2302756,
   "lastModifiedDate": "2024-10-17T18:46:33.497Z", "isCheckedOut": false, "hasVisualizationAttachment": true, "size": 209920,
   "isCloaked": false, "checkinDate": "2024-10-17T19:17:46.297Z", "checkoutDate": "2024-10-17T18:45:51.907Z",
   "isHidden": false, "isReadOnly": false, "parentFolderId": "2",
   "file": {"id": "31", "entityType": "File", "url": "/AutodeskDM/Services/api/vault/v2/vaults/117/files/31"},
   "isOnSite": true, "createDate": "2024-10-17T19:17:46.297Z", "createUserName": "TestAccount", "classification": "None",
   "visualizationAttachmentStatus": "NotSyncronized", "version": 2, "entityType": "FileVersion",
   "url": "/AutodeskDM/Services/api/vault/v2/vaults/117/file-versions/40"}
 ],
 "included": {"folder": {"2": {"name": "ColinTest", "id": "2", "fullName": "$/ColinTest", "category": "Folder", "categoryColor": -2302756,
   "stateColor": 0, "subfolderCount": 0, "isLibrary": false, "isCloaked": false, "isReadOnly": false,
   "createDate": "2024-10-11T07:04:11.723Z", "createUserName": "TestAccount", "entityType": "Folder",
   "url": "/AutodeskDM/Services/api/vault/v2/vaults/117/folders/2"}}}
}
```
- `id` = version (iteration) id; `file.id` = master id. IDs are **strings** (CONFIRMED `[V10]`).
- `checkinDate` is `0001-01-01T00:00:00Z` while checked out.
- `classification` values: `None, DesignVisualization, DesignDocument, ConfigurationMember, ConfigurationFactory, ElectricalProject, DesignSubstitute, DesignRepresentation, DesignPresentation` `[V10]`.
- `option[extendedModels]=true` returns `FileVersionExtended`, which adds `checkoutUser`, `lifecycleState {id, name, displayName, isReleasedState, isObsoleteState, ...}` and `parent` (folder) `[V10]`.

Properties with `option[propDefIds]=21,29` (collections) or always (single entity) `[V22]`:
```json
"properties": [{"propertyDefinitionId": "29", "value": "$/xDMS"}, {"propertyDefinitionId": "21", "value": false}]
```
- On single-entity GETs each property also carries `"definition": {"id","displayName","systemName","dataType","isSystem","active","url"}`.
- `dataType`: `String, Numeric, Bool, DateTime, Image`.
- Values are JSON-typed (bool, string). Map `systemName` to `id` once via `/property-definitions` `[V19]`.

`GET /vaults/117/property-definitions?limit=2` `[V19]`:
```json
{"pagination": {"limit": 2, "totalResults": 108, "nextUrl": "/AutodeskDM/Services/api/vault/v2/vaults/117/property-definitions?limit=2&cursorState=SQBkAEMAdQByAHMAbwByAC0AdgAxADoAMgA_", "indexingStatus": "NA"},
 "results": [{"id": "1", "displayName": "Classification", "systemName": "Classification", "dataType": "String", "isSystem": true, "active": true, "url": "/AutodeskDM/Services/api/vault/v2/vaults/117/property-definitions/1"},
             {"id": "2", "displayName": "Version", "systemName": "VersionNumber", "dataType": "Numeric", "isSystem": true, "active": true, "url": "/AutodeskDM/Services/api/vault/v2/vaults/117/property-definitions/2"}]}
```

`GET /vaults/117/item-versions` (one result) `[V15]`:
```json
{"name": "Assembly1", "id": "57", "revision": "A", "lastModifiedUserName": "TestAccount", "lastModifiedDate": "2024-10-22T08:21:31.65Z",
 "number": "Assembly1", "title": "Assembly1", "description": "", "comment": "", "state": "Work in Progress", "stateColor": -12859030,
 "category": "Assembly", "categoryColor": -10188850, "isReadOnly": false, "isCloaked": false,
 "item": {"id": "55", "entityType": "Item", "url": "/AutodeskDM/Services/api/vault/v2/vaults/117/items/55"},
 "version": 2, "entityType": "ItemVersion", "url": "/AutodeskDM/Services/api/vault/v2/vaults/117/item-versions/57"}
```

`GET /vaults/117/item-versions/57/bill-of-materials`, verbatim, an item with no children `[V16]`:
```json
{"itemVersions": [{"name": "Assembly1", "id": "57", "revision": "A", "number": "Assembly1", "title": "Assembly1", "state": "Work in Progress",
   "item": {"id": "55", "entityType": "Item", "url": "/AutodeskDM/Services/api/vault/v2/vaults/117/items/55"}, "version": 2,
   "entityType": "ItemVersion", "url": "/AutodeskDM/Services/api/vault/v2/vaults/117/item-versions/57"}],
 "itemBomLinks": [], "referenceDesignatorsAvailable": false, "occurrences": [], "bomComponents": []}
```
`itemBomLinks[]` fields (CONFIRMED schema `[V16]`):
- `id`, `parentItemId`, `childItemId`, `quantity` (string), `units`, `unitSize`, `instCount`, `positionNumber`, `bomOrder`
- `cad` (bool), `included`, `isStatic`, `bomLinkMasterId`, `childHasChildren`, `groupedRow`, `groupId`, `refDesId`, `bomComponentId`, `properties[]`

The schema table spells it `bOMComponents` but the example JSON shows `bomComponents`. Accept both (discrepancy in the docs).

Where-used / uses response (`/file-versions/{id}/uses` and `/parents`) schema: `pagination`, `results[] {parentFile: FileVersion, childFile: FileVersion, fileAssocType: "Dependency"|"Attachment"}`, `included {folder, propertyDefinition}` (CONFIRMED schema `[V13][V14]`). **No example response is published.** Simulator (illustrative):
```json
{"pagination": {"limit": 100, "totalResults": 1, "indexingStatus": "NA"},
 "results": [{"parentFile": {"id": "43", "name": "Assembly2.iam", "version": 3, "file": {"id": "37", "entityType": "File", "url": "..."}, "entityType": "FileVersion", "url": "..."},
              "childFile": {"id": "40", "name": "Test1.ipt", "version": 2, "file": {"id": "31", "entityType": "File", "url": "..."}, "entityType": "FileVersion", "url": "..."},
              "fileAssocType": "Dependency"}],
 "included": {"folder": {}}}
```

Errors (verbatim `[V4]`):
```json
{"statusCode": 404, "errorCode": "5004", "title": "Vault error", "detail": "Resource is not found for the given id dABlAHMAdAA_.", "params": ["dABlAHMAdAA_"]}
{"statusCode": 401, "errorCode": "8000", "title": "Vault error", "detail": "You currently do not have permissions to download this file. Contact your admin for support.", "params": []}
```

#### STEP download strategy (inferred)

Vault stores STEP as ordinary files (`.stp`/`.step`). Options:
- `GET /file-versions?q=.stp` or `filter[Name]=` (systemName filter syntax `filter[<systemName>]=value` is CONFIRMED `[V23]`; whether `Name` supports a suffix match is UNCONFIRMED).
- Check `uses?option[includeRelatedDocuments]=true` attachments (`fileAssocType = "Attachment"`) of the CAD file.
- Then `GET .../content`.

#### Gotchas

- The Vault Gateway rate limit is 40,000 requests per 5 min across all APIs (HTTP 429). Payload quota ~37.5 MB returns HTTP 500. A direct server has no rate limits (CONFIRMED `[V5]`).
- Search results depend on the indexer (`indexingStatus`).
- CORS is configured via `web.config <restapi><cors .../>` (CONFIRMED `[V25]`).

#### Python sketch

```python
import requests
HOST = "https://vault.example.com"; BASE = HOST + "/AutodeskDM/Services/api/vault/v2"
s = requests.Session(); s.headers["Accept"] = "application/json"
sess = s.post(f"{BASE}/sessions", json={"input": {"vault": "Vault", "userName": U, "password": P, "appCode": "PARTAUDIT"}}).json()
s.headers["Authorization"] = f"Bearer {sess['accessToken']}"
vid = sess["vaultInformation"]["id"]
url = f"{BASE}/vaults/{vid}/file-versions?limit=1000&option[propDefIds]=all"
while url:
    page = s.get(url if url.startswith("http") else HOST + url).json()
    for fv in page["results"]: ...
    url = page.get("pagination", {}).get("nextUrl")
s.delete(f"{BASE}/sessions/{sess['id']}")
```

### 2.b Legacy SOAP / .NET SDK (servers older than 2025.2)

- Web services are SOAP at `http://server/AutodeskDM/Services/v<NN>/DocumentService.svc`; the forum example is `.../v24/DocumentService.svc` (CONFIRMED-COMMUNITY `[V31]`). The version folder changes per release.
- The supported client is the .NET SDK (`Autodesk.Connectivity.WebServices` + VDF). From Python this would need pythonnet or a small C# helper exe (inferred).
- Search: `WebServiceManager.DocumentService.FindFilesBySearchConditions(SrchCond[] conditions, SrchSort[] sort, long[] folderIds, bool recurseFolders, bool latestOnly, ref string bookmark, out SrchStatus status)` returns `File[]`. Page by passing `bookmark` back until you have `status.TotalHits` files.
  - Known pitfall: the bookmark wraps around near the end, so count the results you have received and stop at `TotalHits` (CONFIRMED-COMMUNITY `[V29]`).
- Download (VDF): `new AcquireFilesSettings(conn)`, then `AddFileToAcquire(fileIteration, AcquisitionOption.Download)`, then `conn.FileManager.AcquireFiles(settings)` (CONFIRMED-COMMUNITY Autodesk dev blog `[V30]`).
- `VDF ConnectionManager.LogIn(...)` is named for non-UI login; its signature is UNCONFIRMED `[V30]`.
- Items, BOM and properties via `ItemService` and `PropertyService`: names known, signatures UNCONFIRMED here.

---

## 3. PTC Windchill REST Services (WRS, OData v4)

### 3.1 URLs, domains, versions

- REST root `https://<server>/Windchill/servlet/odata/`. A GET there lists the domains. `.../odata/<Domain>/` lists the entity sets; `.../odata/<Domain>/$metadata` returns the CSDL (CONFIRMED `[W12]`).
- Domains seen in current docs:
  - `ProdMgmt`, `CADDocumentMgmt`, `DocMgmt`, `PTC` (common: `GetCSRFToken()`, `GetWindchillVersion()`, `DownloadContentAsZip`)
  - `Visualization`, `ChangeMgmt`, `PrincipalMgmt`, `DataAdmin`, `NavCriteria`
  - BOM Transformation, Reporting, Product Platform Mgmt, Manufacturing Process Mgmt, Supplier Mgmt
  - (CONFIRMED by mention `[W5][W12][W14][W18]`)
- Domain API version (CONFIRMED `[W11]`):
  - In the URL: `.../odata/v1/ProdMgmt/`
  - Or in the header: `Accept: application/json;version=1`
  - Without either you get the domain's `defaultVersion` (normally the latest).
- Deprecations (CONFIRMED `[W18][W5]`): "Starting with WRS 2.6, the API versions 1, 2, 3, 4, and 5 of ProdMgmt are deprecated", so v6+ is current; a doc nextLink shows `/v6/ProdMgmt/` `[W8b]`. CADDocumentMgmt v1-3 are deprecated `[W5]`. Pin a version after reading `$metadata`.
- WRS 2.7 ships with Windchill 13.0.1.0, 13.0.0.4, 12.1.2.7, 12.0.2.16 (CONFIRMED `[W14]`). In 13.1.x, WRS docs live inside the Windchill Help Center (`WCRESTFramework`) `[W2][W15][W16]`.

### 3.2 Authentication and CSRF

- **HTTP Basic**: send `Authorization: Basic ...` on every request, including POSTs that carry `CSRF_NONCE` (CONFIRMED-COMMUNITY `[W23]`; implied by `[W3]`).
- **`Accept: application/json` is required**. Without it `GetCSRFToken()` returned HTTP 400 from a Java client (CONFIRMED-COMMUNITY `[W24]`).
- OAuth (CONFIRMED `[W13]`):
  - Authorization-code flow against the CAS (e.g. PingFederate), `scope=WINDCHILL_READ`.
  - Call **`/Windchill/oauth/servlet/odata/...`** (note the `oauth` prefix) with `Authorization: Bearer <token>`.
  - Token response example: `{"access_token": "...", "refresh_token": "...", "scope": "WINDCHILL_READ", "token_type": "Bearer", "expires_in": 3600}`.
- CSRF nonce: `GET /Windchill/servlet/odata/PTC/GetCSRFToken()` (CONFIRMED `[W3]`). Response verbatim:
  ```json
  {"@odata.context": "https://windchill.ptc.com/Windchill/servlet/odata/v1/PTC/$metadata#CSRFToken", "NonceKey": "CSRF_NONCE", "NonceValue": "8q87WtSxvWkSH9FMtsQUboOI5TtCS7gWh8RUb4OG ="}
  ```
  - Send it as header `CSRF_NONCE: <NonceValue>`. "REST clients must provide the token while creating, updating, or deleting" `[W3]`.
  - **Gotcha for a read-only connector:** the official examples also send `CSRF_NONCE` on read-only **POST actions**: `GetPartStructure` `[W1]`, `GetBOM` `[W21]` and CAD `GetStructure` `[W7e]`. Always fetch a nonce before any POST.
  - Keep cookies in one `requests.Session` so the nonce and the session belong together. That nonce-session binding is inferred, UNCONFIRMED.
- Windchill 13.1.1.0 adds a `PTC.ReadOnly` annotation to read-only actions in `$metadata` (CONFIRMED `[W16]`). Use it to whitelist safe POST actions.

### 3.3 Parts (`ProdMgmt/Parts`)

- `GET /Windchill/servlet/odata/ProdMgmt/Parts`
- `GET .../Parts('OR:wt.part.WTPart:280403')` (CONFIRMED `[W2]`)
- The key is the object reference string `OR:wt.part.WTPart:<id>`; `VR:` version refs also appear (CONFIRMED `[W12][W21]`). URL-encode the `:`s if your client needs to.

Verbatim Part JSON (WRS 1.2 guide, domain v1-era) `[W21]`:
```json
{"@odata.context":"$metadata#Parts","ID":"OR:wt.part.WTPart:601168","Name":"BatchPart1",
"Number":"0000019103","EndItem":false,"TypeIcon":{"Path":"https://windchill.ptc.com/Windchill/wtcore/images/part.gif","Tooltip":"Part"},
"Identity":"0000019103, BatchPart1, Demo Organization, A","GeneralStatus":null,"ShareStatus":null,"ChangeStatus":null,"Supersedes":null,
"AssemblyMode":{"Value":"separable","Display":"Separable"},"DefaultUnit":{"Value":"ea","Display":"each"},
"DefaultTraceCode":{"Value":"0","Display":"Untraced"},"Source":{"Value":"make","Display":"Make"},
"ConfigurableModule":{"Value":"standard","Display":"No"},"GatheringPart":false,"PhantomManufacturingPart":false,"BOMType":null,
"AlternateNumber":null,"View":"","CheckoutState":"Checked in","CheckOutStatus":"","Comments":null,
"State":{"Value":"INWORK","Display":"In Work"},"LifeCycleTemplateName":"Basic","VersionID":"VR:wt.part.WTPart:601167",
"Revision":"A","Version":"A.0","Latest":true,"FolderName":null,"CabinetName":"Default","FolderLocation":"/Default",
"OrganizationName":"Demo Organization","CreatedOn":"2010-04-20T08:32:51Z","LastModified":"2010-04-20T08:32:51Z"}
```
A second sample in the same guide (domain **v2** context, `.../v2/ProdMgmt/$metadata#Parts`) has `"DefaultUnit": "ea"`, `"Source": "make"`, `"view": "Design"` (lower-case key!), `"Version": "A.1 (Design)"`, `"Identity": "GC000019, LOWER_SUPPORT, A (Design)"` `[W21]`. **Shapes differ by domain version.** Current docs send `DefaultUnit`, `DefaultTraceCode`, `Source`, `ConfigurableModule` as `{Value, Display}` and `"View": "Design"` (CONFIRMED request bodies `[W19]`).

Field checklist for the connector and simulator:

| Field | Status |
|---|---|
| `ID`, `Number`, `Name`, `Version` (e.g. `"A.1 (Design)"` = revision.iteration (view)), `Revision`, `Latest`, `State {Value, Display}`, `View`, `DefaultUnit`, `Source`, `CreatedOn`, `LastModified`, `VersionID`, `Identity`, `FolderLocation`, `OrganizationName`, `CheckoutState`, `LifeCycleTemplateName` | CONFIRMED `[W21][W19]` |
| `CreatedBy`, `ModifiedBy` (strings like `'Demo, User'`; filterable and sortable) | CONFIRMED `[W8a][W8b]` |
| `ObjectType` (e.g. `"Electrical Part"`) | CONFIRMED in a RelatedPart sample `[W7f]` |
| separate `Iteration` property | UNCONFIRMED (parse it from `Version`) |
| Custom IBAs / soft attributes | exposed as properties named after the attribute's internal name. 13.1 adds `renameDuplicateProperties`: a custom `LastModified` becomes `LastModifiedDuplicate` (CONFIRMED `[W15]`). Filter example `$filter=contains(CustomAttribute,'value')` `[W21]`. Old WRS needed an entity-JSON extension for soft attributes `[W21]`; whether all IBAs auto-appear in your version: check `$metadata` |
| Subtypes | appear as derived entities named from the internal name without the domain prefix, first letter upper-cased (`com.ptc.demo` becomes `Demo`). Query with a type-cast segment: `Parts/PTC.ProdMgmt.ElectricalPart` (CONFIRMED `[W19][W21]`) |

Filtering and query options (CONFIRMED `[W8a][W8b][W17][W16]`):
- `$filter` supports `eq ne gt lt ge le`, `and or not`, `startswith endswith contains`, `isof`, and `in` (13.1).
- Not allowed on non-persisted or server-calculated properties (listed in `FilterRestrictions`, e.g. `VersionID`, `ChangeStatus`, `CabinetName` on Parts).
- `contains` and friends are not supported on `ID`.
- DateTimeOffset filters compare **date only**, in UTC (`$filter=CreatedOn eq 2018-01-20T00:00:00Z`) `[W21]`.
- **Latest only**: custom query option `ptc.search.latestversion=true`. `false` returns the latest iteration of each revision. Unset means the Windchill preference applies, default "No". 13.1.1 adds the value `absolute` (CONFIRMED `[W17][W16]`). Whether `$filter=Latest eq true` works is UNCONFIRMED; `Latest` is probably non-filterable.
- Wildcards: header `PTC-WildcardSearch: true`, then `$filter=Name eq 'Golf*'` (only `eq ne startswith endswith contains`) (CONFIRMED `[W8b]`).
- `$select` is recommended for performance. Avoid `$orderby` unless needed (CONFIRMED `[W6]`).

Pagination (CONFIRMED `[W4][W6][W8b]`):
- Default page size **25**. `Prefer: odata.maxpagesize=N` raises it to at most **2000** (WRS 2.5 docs; the 1.2 guide said 200).
- The server echoes the applied preference.
- Follow `@odata.nextLink` (e.g. `...$skiptoken=25`).
- `$top`/`$skip`/`$count=true` are supported (`"@odata.count": n`).
- PTC best practice: use `maxpagesize=2000` for large sets because "pagination may rerun the query for each page".

### 3.4 BOM and where-used for parts

- **GET navigation (no CSRF)**: `GET .../ProdMgmt/Parts('OR:...')/Uses` returns `PartUse` links (CONFIRMED `[W8a][W8b]`).
  - `$expand=Uses($expand=Occurrences)` (CONFIRMED `[W28]`).
  - `PartUse` fields: `Quantity`, `Unit {Value, Display}`, `FindNumber`, `LineNumber`, `TraceCode {Value, Display}`, `Occurrences[] {ReferenceDesignator, Location{...}}`. Its child-part navigation is named `Uses`: the create-link example binds `"Uses@odata.bind": "Parts('OR:wt.part.WTPart:48796415')"` (CONFIRMED `[W21]`).
  - So `Parts('id')?$expand=Uses($expand=Uses($select=ID,Number,Name,Version))` should return child parts. That is inferred from the bind; which iteration is resolved is UNCONFIRMED.
- **Where-used**: `GET .../Parts('OR:...')/UsedBy` returns parent `Part`s; supports `$count=true` and `$expand=UsedBy($count=true)` (CONFIRMED `[W8b]`).
  - Community report: `UsedBy` returns several revisions of the same parent ("All Revisions" behaviour). The suggested fix is `ptc.search.latestversion=true`, but whether it applies inside `$expand` is unresolved (CONFIRMED-COMMUNITY `[W22]`). De-duplicate client-side by `Number`.
- **Actions (POST plus CSRF_NONCE)**, verbatim `[W1]`:
  ```
  POST /Windchill/servlet/odata/ProdMgmt/Parts('OR:wt.part.WTPart:191559')/PTC.ProdMgmt.GetPartStructure?$expand=Components($levels=max)
  Content-Type: application/json
  CSRF_NONCE: <nonce>
  {}
  ```
  Response (verbatim, trimmed):
  ```json
  {"@odata.context": "$metadata#PartStructureItems", "PartId": "OR:wt.part.WTPart:191559", "HasChildren": true, "PartUseId": null,
   "PartName": "Top_WTPart", "PartNumber": "0000000007", "PathId": null, "Resolved": true, "HasUnresolvedObjectsByAccessRights": true,
   "PVTreeId": "/", "PVParentTreeId": null, "@PTC.AppliedContainerContext.LocalTimeZone": "Asia/Kolkata",
   "Components": [{"HasChildren": true, "PartName": "Child1", "PartNumber": "0000000008", "Resolved": true, "HasUnresolvedObjectsByAccessRights": null,
                   "Components": [{"HasChildren": false, "PartName": "Child1_A1", "PartNumber": "0000000010", "Resolved": false, "HasUnresolvedObjectsByAccessRights": null}]}]}
  ```
  - Optional body: `{"NavigationCriteria": {...}}` with `ConfigSpecs` (e.g. `#PTC.NavCriteria.EPMDocStandardConfigSpec`) `[W1]`.
  - Richer expand: `Components($expand=Part($select=Identity;...),PartUse,Occurrence...;$levels=max)` `[W1]`.
  - `GetBOM`: `POST .../Parts('...')/PTC.ProdMgmt.GetBOM?$expand=Components($expand=Part($select=Name,Number),PartUse,Occurrences;$levels=max)`, body `{"navigationCriteriaId": "OR:wt.filter.NavigationCriteria:..."}` `[W21]`.
  - `GetPartsList` (flat list): `POST .../PTC.ProdMgmt.GetPartsList?$expand=Part,PartUses` `[W8a]`.
  - PTC recommends these actions over navigation for structures `[W6]`.

### 3.5 CAD documents (`CADDocumentMgmt`)

- Entities (CONFIRMED `[W5]`):
  - `CADDocument` (a version of an EPMDocument)
  - `CADDocumentUse` (EPMMemberLink: quantity, unit, location)
  - `CADDocumentReference` (EPMReferenceLink)
  - `DerivedSource`
  - `PartDocAssociation`
  - `CADStructure` (returned by the `GetStructure` action)
- Requests (CONFIRMED `[W7b][W7c][W7d][W7g]`):
  - `GET .../CADDocumentMgmt/CADDocuments('OR:wt.epm.EPMDocument:167183')`
  - `?$expand=Uses`
  - `?$filter=FileName eq 'ABC.prt'`
  - `$filter=(Category/Value eq 'CADASSEMBLY' and contains(CreatedBy,'demo'))`
  - `$filter=(AuthoringApplication/Value eq 'PROE' and ...)`
  - `$select=FileName,Version`, `$top/$skip/$count`
  - `?$select=Identity&$expand=Drawings($select=Identity,Name,FileName,Version)`
- Properties seen: `ID, Name, Number, FileName, Version, Identity, CreatedBy, ModifiedBy, LastModified, Category {Value} (CADASSEMBLY, CADDRAWING, ...), AuthoringApplication {Value} (PROE, ...)` (CONFIRMED `[W7d][W7g][W8b]`).
  - `CADName`: UNCONFIRMED (not seen).
  - `State`, `Revision`, `Latest` on CADDocument: UNCONFIRMED (confirmed on Part only).
- `CADDocuments('id')/Uses` (CADDocumentUse) fields from a community response (CONFIRMED-COMMUNITY `[W26]`): `ID, CreatedOn, LastModified, ComponentName, DepType, FeatureID, FeatureNumber, HasFixedConstraint, LayerID, Location, ObjectType, Placed, Quantity, Required, Suppressed, Unit, UseInfo {FileName, Category, SubCategory, AuthoringApplication}`.
- Structure action (POST plus CSRF) `[W7e]`: `POST .../CADDocuments('OR:wt.epm.EPMDocument:196704')/PTC.CADDocumentMgmt.GetStructure?$expand=Components($levels=max)` with body `{}`. Response (verbatim, trimmed):
  ```json
  {"@odata.context": "$metadata#CADStructures", "CADDocumentID": "OR:wt.epm.EPMDocument:196704", "HasChildren": true, "CADDocumentUseID": null,
   "CADDocumentName": "top_caddoc.asm", "CADDocumentNumber": "TOP_CADDOC.ASM", "CADDocumentFileName": "top_caddoc.asm", "Resolved": true,
   "HasUnresolvedObjectsByAccessRights": true, "PVTreeId": "/", "PVParentTreeId": null,
   "Components": [{"HasChildren": false, "CADDocumentName": "child2.asm", "CADDocumentNumber": "CHILD2.ASM", "Resolved": true,
                   "HasUnresolvedObjectsByAccessRights": null,
                   "CADDocument": {"@odata.id": "http://<host>:<port>/Windchill/servlet/odata/v2/CADDocumentMgmt/CADDocuments('OR:wt.epm.EPMDocument:195955')",
                                   "ID": "OR:wt.epm.EPMDocument:195955", "Name": "child2.asm", "Number": "CHILD2.ASM"},
                   "Components": []}]}
  ```
  - Unresolved children (no access, or filtered by the navigation criteria) have `"Resolved": false, "CADDocument": null`.
  - Documented expand: `Components($expand=CADDocument($select=Identity;$expand=Representations($select=AdditionalFiles),Attachments);$levels=max)`. This confirms that `Representations` and `Attachments` navigations exist on CADDocument `[W7e]`.
- Part to CAD links: `GET .../CADDocuments('...')/PartDocAssociations?$expand=RelatedPart($select=Name,Version,Number,ObjectType)` gives `{"PartDocAssociations": [{"ID": "...", "AssociationType": {"Value": "CONTRIBUTING_CONTENT"|"CALCULATED"|..., "Display": "..."}, "RelatedPart": {...}}]}` (CONFIRMED `[W7f]`). The same navigation exists on Parts: `Parts('<OID>')/PartDocAssociations?$expand=RelatedCADDoc(...)` `[W8b]`.

### 3.6 File content and STEP

- `CADDocument` navigation **`AllPrimaryContents`** returns download URLs for "primary content that is directly downloaded in Windchill". Content that opens in other applications (e.g. **Creo assemblies**) is not returned (`"AllPrimaryContents": []`). **`PrimaryContent` is not supported for CADDocument.** (CONFIRMED `[W5]`)
  - Community: "If the primary content is Creo native type, then nothing is returned"; PDF primary content is returned (CONFIRMED-COMMUNITY `[W25]`).
- `Attachments` navigation on CADDocument and Parts (CONFIRMED `[W7e][W8b]`).
  - Use `PTC.ApplicationData/<attr>` in `$select`/`$filter` for `Content, FileName, FileSize, Format, MimeType` (CONFIRMED `[W8b]`).
  - The JSON nesting of `Content` (hyperlink with `URL`) is UNCONFIRMED.
- **Representations** (Visualization domain) (CONFIRMED `[W9][W10]`):
  - `GET /Windchill/servlet/odata/Visualization/Representations('OR:wt.viewmarkup.DerivedImage:786687')`, or navigate `CADDocuments('...')/Representations` (seen in community URLs `[W27]`).
  - Returns `CreoViewURL`, `3DThumbnailURL`, `2DThumbnailURL` and `AdditionalFiles` ("non-native Creo View files associated with the representation").
  - `AdditionalFiles` items (verbatim `[W8b]`):
  ```json
  {"URL": "https://<Windchill>/Windchill/servlet/WindchillAuthGW/com.ptc.windchill.enterprise.wvs.saveWVSObject.utils.SaveWVSObjectHelper/saveWVSObject/...",
   "Label": "golf_cart_de.xml", "FileSize": 108461.0, "MimeType": "text/xml", "Format": "XML", "ID": "OR:wt.content.ApplicationData:127656",
   "FileName": "golf_cart_de.xml", "LastModified": "2023-12-08T01:39:45-03:30", "CreatedOn": "2023-12-08T01:39:45-03:30", "Description": null, "Comments": null}
  ```
  - 13.1.0.0 adds an `AdditionalFilesData` navigation with filtering (CONFIRMED `[W15]`).
  - `GetPVZ(IncludeAnnotations=true,Fidelity='Low Fidelity')` returns the PVZ bundle `[W10]`.
- `PTC` domain v4 (WRS 2.7) adds the unbound action `DownloadContentAsZip` (zip stream of application-data content for one or more content holders) (CONFIRMED `[W14]`). It is a POST, so CSRF applies. Its request shape is UNCONFIRMED.
- **STEP strategy** (inferred; depends on the site's configuration):
  1. STEP managed as its own CAD document: filter `FileName` ending `.stp`/`.step` (`endswith(FileName,'.stp')`), then `AllPrimaryContents`.
  2. STEP published by WVS as a representation additional file: `Representations?$expand=...` and pick `AdditionalFiles` with `Format`/`FileName` = STEP.
  3. STEP as an attachment: `Attachments`.
  4. Download each URL with a GET using the same Basic auth (inferred; the URLs point at `/Windchill/servlet/WindchillAuthGW/...`).

### 3.7 Python sketch

```python
import requests
WC = "https://plm.example.com/Windchill/servlet/odata"
s = requests.Session(); s.auth = (U, P); s.headers.update({"Accept": "application/json"})
url = f"{WC}/ProdMgmt/Parts?$select=ID,Number,Name,Version,Revision,State,View,CreatedOn,LastModified,CreatedBy,ModifiedBy&ptc.search.latestversion=true"
while url:
    page = s.get(url, headers={"Prefer": "odata.maxpagesize=2000"}).json()
    for p in page["value"]: ...
    url = page.get("@odata.nextLink")
nonce = s.get(f"{WC}/PTC/GetCSRFToken()").json()["NonceValue"]
bom = s.post(f"{WC}/ProdMgmt/Parts('{pid}')/PTC.ProdMgmt.GetPartStructure?$expand=Components($levels=max)",
             json={}, headers={"CSRF_NONCE": nonce, "Content-Type": "application/json"}).json()
parents = s.get(f"{WC}/ProdMgmt/Parts('{pid}')/UsedBy?$select=ID,Number,Version").json()["value"]
```

---

## 4. Siemens Teamcenter

### 4.a JSON REST interface for SOA services

#### Endpoint pattern

- `POST http(s)://<web-tier-host>:<port>/tc/JsonRestServices/<Library>-<YYYY>-<MM>-<Service>/<operation>` (CONFIRMED-COMMUNITY: Postman collection run against TC 13.3 on port 7001 `[T1]`). Operation names in this form are used by Siemens' own Mendix Teamcenter Connector (`"ServiceOperation": "Core-2011-06-Session/login"`) (CONFIRMED `[T2][T4]`).
- Violet docs give `http://yourteamcenter.yourdomain.com:8080/tc/JsonRestServices`, default TCP 8080, "enabled by default in most implementations" (CONFIRMED-COMMUNITY `[T11]`).
- Via the Active Workspace gateway (port 3000 in the example): `/tc/RestServices/<op>` and `/tc/JsonRestServices/<op>` both appear (CONFIRMED-COMMUNITY `[T1]`).
  - The gateway sets an `XSRF-TOKEN` cookie; the client must echo it as header `X-XSRF-TOKEN`. The collection reads `postman.getResponseCookie('XSRF-TOKEN')` after login and sends `X-Xsrf-Token` `[T1]`.
  - Gateway cookies per Siemens' SLM install guide: `XSRF-TOKEN`, `_csrf`, `JSESSIONID`, `TcSS-JSESSIONID` (CONFIRMED `[T10]`).
- Session: cookie-based (`JSESSIONID`). Use one `requests.Session` (cookie jar). The cookie name is CONFIRMED for the AW gateway `[T10]`; for the plain web tier it is inferred (the collection relies on Postman's cookie jar `[T1]`).
- Responses are `Content-Type: text/json` (CONFIRMED-COMMUNITY saved headers `[T1]`).
- Official service signatures (Teamcenter Services Reference) require a Siemens Webkey login and were **not accessed** `[T14]`. Request field names below come from working community requests. Where none was available, they are inferred from the Java/C# structure names under the convention that **JSON body keys = operation parameter names** (verified for `login`, `getProperties`, `getItemFromId`, `createBOMWindows`, `expandPSAllLevels`, `closeBOMWindows` `[T1][T6]`).

#### Envelope

```json
{"header": {"state": {}, "policy": {}}, "body": { ...operation parameters... }}
```
- Some calls send `state` keys `formatProperties`, `stateless`, `unloadObjects`, `enableServerStateHeaders`, `locale`. Their semantics are not publicly documented (UNCONFIRMED).
- `policy` is the object property policy (verbatim style `[T1]`):
  ```json
  {"useRefCount": false,
   "types": [{"name": "ItemRevision", "properties": [{"name": "item_id"}, {"name": "item_revision_id"}, {"name": "object_name"},
              {"name": "release_status_list", "modifiers": [{"name": "withProperties", "Value": "true"}]}]}]}
  ```
  Note the capital `"Value"` as used in the collection. Properties listed in the policy come back in `ServiceData.modelObjects[uid].props`.

#### Login and session

Request (verbatim `[T1]`; the misspelling `descrimator` is genuine):
```
POST /tc/JsonRestServices/Core-2011-06-Session/login
{"header": {"state": {}, "policy": {}},
 "body": {"credentials": {"user": "user3", "password": "...", "role": "", "descrimator": "", "locale": "", "group": ""}}}
```
Response (verbatim `[T1]`):
```json
{".QName": "http://teamcenter.com/Schemas/Core/2011-06/Session.LoginResponse",
 "serverInfo": {"DisplayVersion": "13.3:20211122.00", "HostName": "ff22tc133", "Locale": "en_US", "LogFile": "tcserver.exe1f60cdf7.syslog",
                "SiteLocale": "en_US", "TcServerID": "tcserver00009@PoolA@5228@FF22TC133", "UserID": "user3", "Version": "V13000.3.0.20211122.00"},
 "PartialErrors": {}}
```
- Logout: `Core-2006-03-Session/logout` (name CONFIRMED `[T4]`; body `{"header":..., "body":{}}` UNCONFIRMED).
- Session info: `Core-2007-01-Session/getTCSessionInfo` with only a header. It returns `serverVersion`, `user`/`group`/`role`/`site` refs `{uid, className, type}`, `extraInfo {DisplayVersion, TCServerLocale, TcServerID, TransportSchema, hostName, syslogFile, systemType}` and `ServiceData` (CONFIRMED-COMMUNITY verbatim `[T1]`).
- SSO: Teamcenter Security Services (`/tcssol/weblogin/login_redirect`); out of scope here `[T3]`.

#### Response conventions (CONFIRMED-COMMUNITY verbatim `[T1]`)

- Top-level `.QName` names the response type, e.g. `http://teamcenter.com/Schemas/Cad/2007-01/StructureManagement.CreateBOMWindowsResponse`.
- Object references look like `{"uid": "wfhZwhTFppgr6D", "className": "ItemRevision", "type": "ItemRevision"}`.
- `ServiceData`: `plain` (uids of the "main" objects), `modelObjects` (map uid to object), `created`, `deleted`.
  - Model object: `{"objectID", "uid", "className", "type", "props": {"<name>": {"dbValues": [...], "uiValues": [...]}}}`.
  - Values are **always string arrays**: dates are ISO in `dbValues` and localised in `uiValues`; references are uids in `dbValues` with a display string in `uiValues`.
- Some operations (e.g. `getProperties`) return a bare ServiceData (`".QName": "http://teamcenter.com/Schemas/Soa/2006-03/Base.ServiceData"`) with `plain`/`modelObjects` at top level.
- Partial errors: login shows `"PartialErrors": {}`. The structure of populated partial errors and of service exceptions is UNCONFIRMED; treat any `.QName` containing `Exception` as an error (inferred).

#### Operations needed by the connector

| Purpose | Operation | Request body | Status |
|---|---|---|---|
| list saved queries | `Query-2006-03-SavedQuery/getSavedQueries` | header only | CONFIRMED-COMMUNITY `[T1]`; response `{"queries":[{"name","description","query":{uid,className:"ImanQuery",type}}]}` |
| run saved query | `Query-2008-06-SavedQuery/executeSavedQueries` | `{"input":[{"query":{uid,...},"entries":["Item ID"],"values":["*"],"maxNumToReturn":0,"maxNumToInflate":0,"limitListCount":0,"limitList":[]}]}` | op name CONFIRMED `[T4]`. Field names `query, entries, values, maxNumToReturn, maxNumToInflate, limitListCount, limitList` and result `arrayOfResults[i].objects` CONFIRMED-COMMUNITY via Java `[T7]`. JSON key `input`: UNCONFIRMED (inferred). An older variant (Query-2007-09 `QueryResults`) returns `ObjectUIDS`, then `loadObjects` (C# `[T9]`) |
| search via AW Finder | `Query-2012-10-Finder/performSearch` (Siemens connector uses `Query-2014-11-Finder/performSearch` `[T4]`) | see below | CONFIRMED-COMMUNITY `[T1]` |
| AW internal search | `Internal-AWS2-2019-06-Finder/performSearchViewModel4` | same `searchInput`; returns `searchResultsJSON` (a JSON **string**) | CONFIRMED-COMMUNITY `[T1]`; internal API, may change |
| item by id | `Core-2007-01-DataManagement/getItemFromId` | `{"infos":[{"itemId":"88.88.88","revIds":["A"]}],"nRev":1,"pref":{}}` | CONFIRMED-COMMUNITY `[T1]`; returns `output[].item`, `output[].itemRevOutput[].itemRevision` |
| properties | `Core-2006-03-DataManagement/getProperties` | `{"objects":[{uid,className,type}],"attributes":["item_id","object_name"]}` | CONFIRMED-COMMUNITY `[T1]`; op listed by Siemens `[T4]` |
| load by uid | `Core-2007-09-DataManagement/loadObjects` | `{"uids":[...]}` | Java `dm.loadObjects(new String[]{uid})` returns ServiceData (CONFIRMED-COMMUNITY `[T5][T9]`); JSON key `uids` UNCONFIRMED (inferred) |
| related datasets | `Core-2007-09-DataManagement/expandGRMRelationsForPrimary` | `{"primaryObjects":[...],"pref":{"info":[{"relationTypeName":"IMAN_specification","otherSideObjectTypes":[]}]}}` | op name and keys `primaryObjects`, `info`, response `relationshipObjects[].otherSideObject` CONFIRMED (Siemens Mendix doc `[T2]`). `pref` nesting and `relationTypeName`/`otherSideObjectTypes`, plus response path `output[].relationshipData[].relationshipObjects[]`: UNCONFIRMED (low-confidence repo `[T16]`) |
| file tickets | `Core-2006-03-FileManagement/getFileReadTickets` | `{"files":[{uid,className:"ImanFile",type:"ImanFile"}]}` | op name CONFIRMED `[T4]`. Java `getFileReadTickets(ImanFile[])` returns `FileTicketsResponse.tickets` (a **map** ImanFile to ticket string) (CONFIRMED-COMMUNITY `[T5]`). JSON key `files` and the JSON map encoding: UNCONFIRMED |
| BOM window | `Cad-2007-01-StructureManagement/createBOMWindows` | verbatim below | CONFIRMED-COMMUNITY `[T1]`; Siemens connector shows the same input keys `[T2]` |
| expand | `Cad-2007-01-StructureManagement/expandPSAllLevels` / `expandPSOneLevel` (also `Cad-2008-06-...` variants with `...Response2`) | `{"input":{"parentBomLines":["<bomLine uid>"],"excludeFilter":"None"},"pref":{"expItemRev":false}}` | CONFIRMED-COMMUNITY `[T1]`; Java uses `excludeFilter = "None2"` with the 2008-06 variant `[T6]` |
| close window | `Cad-2007-01-StructureManagement/closeBOMWindows` | `{"bomWindows":["BOM::64838"]}` | CONFIRMED-COMMUNITY `[T1]` |
| revision rules | `Cad-2007-01-StructureManagement/getRevisionRules` | header only | CONFIRMED-COMMUNITY `[T1]` |
| where-used | `Core-2007-01-DataManagement/whereUsed` | likely `{"objects":[...],"numLevels":1,"whereUsedPrecise":false,"rule":{}}` | **UNCONFIRMED** (no public JSON or signature found) |

`performSearch` request body (verbatim; `searchCriteria` keys after `totalObjectsFoundReportedToClient` are the saved query's entry names) `[T1]`:
```json
{"header": {"state": {}, "policy": {"useRefCount": false, "types": [{"name": "ItemRevision", "properties": [{"name": "item_id"}, {"name": "object_name"}]}]}},
 "body": {"searchInput": {"maxToLoad": 500, "maxToReturn": 500, "providerName": "Awp0SavedQuerySearchProvider",
   "searchCriteria": {"queryUID": "QwnF92$rppgr6D", "searchID": "", "typeOfSearch": "ADVANCED_SEARCH", "utcOffset": "-420",
                      "lastEndIndex": "", "totalObjectsFoundReportedToClient": "", "ItemID": "*", "Type": "ItemRevision"},
   "searchFilterFieldSortType": "Priority", "startIndex": 0, "searchFilterMap6": {}, "searchSortCriteria": [],
   "attributesToInflate": [], "inflateProperties": false, "focusObjUid": "", "pagingType": ""}}}
```
- Response (verbatim, empty result): `{".QName": "http://teamcenter.com/Schemas/Query/2012-10/Finder.SearchResponse", "totalFound": 0, "totalLoaded": 0, "defaultFilterFieldDisplayCount": 10, "searchFilterCategories": [], "ServiceData": {}}` `[T1]`.
- With results, the collection reads `totalFound`, `searchFilterMap.SAVED_QUERY_RESULT_TYPES[0].stringValue` and iterates `ServiceData.modelObjects` `[T1]`. The name of the ordered result list (e.g. `searchResults`) is UNCONFIRMED.
- Paging: increase `startIndex` by `totalLoaded` until it reaches `totalFound` (inferred from field names, UNCONFIRMED).
- `Awp0SavedQuerySearchProvider` requires Active Workspace server components (`Awp0` prefix) (inferred).

`createBOMWindows` request and response (verbatim `[T1]`):
```json
{"header": {"state": {"formatProperties": true, "stateless": true, "unloadObjects": false, "enableServerStateHeaders": true, "locale": "en_US"}, "policy": {}},
 "body": {"info": [{"clientId": "", "item": "<item uid>",
   "revRuleConfigInfo": {"clientId": "", "revRule": "", "props": {"unitNo": -1, "date": "0001-01-01T00:00:00", "today": true, "endItem": "", "endItemRevision": ""}}}]}}
```
```json
{".QName": "http://teamcenter.com/Schemas/Cad/2007-01/StructureManagement.CreateBOMWindowsResponse",
 "output": [{"clientId": "", "bomWindow": {"uid": "BOM::64838", "className": "BOMWindow", "type": "BOMWindow"},
             "bomLine": {"uid": "SR::N::BOMLine..7.6Br3ciBWuq$NAD.wmuZwlmDppgr6D..BkkZwhTFppgr6D..0..", "className": "BOMLine", "type": "BOMLine"}}],
 "ServiceData": {"created": ["BOM::64838", "SR::N::BOMLine..."], "modelObjects": {"BOM::64838": {"uid": "BOM::64838", "className": "BOMWindow", "type": "BOMWindow"}}}}
```
- The Siemens Mendix sample also shows `itemRev`, `bomView`, `objectForConfigure`, `activeAssemblyArrangement` and `revRuleConfigInfo.props.overrideFolders[{ruleEntry, folder}]` in `info[]` (CONFIRMED `[T2]`).
- An empty `revRule` used the default rule in the example. To be explicit, pass a rule uid from `getRevisionRules`, e.g. "Latest Working" (inferred).

`expandPSAllLevels` response (verbatim, trimmed `[T1]`):
```json
{".QName": "http://teamcenter.com/Schemas/Cad/2007-01/StructureManagement.ExpandPSAllLevelsResponse",
 "output": [{"parent": {"bomLine": {"uid": "SR::N::BOMLine...", "className": "BOMLine", "type": "BOMLine"},
                        "itemRevOfBOMLine": {"uid": "BclZwhTFppgr6D", "className": "ItemRevision", "type": "ItemRevision"}},
             "children": [{"bomLine": {"uid": "SR::N::BOMLine...", "className": "BOMLine", "type": "BOMLine"},
                           "itemRevOfBOMLine": {"uid": "hUnZwhTFppgr6D", "className": "ItemRevision", "type": "ItemRevision"}}]}],
 "ServiceData": {"created": [...], "plain": [...], "modelObjects": {
   "BJhZwhTFppgr6D": {"objectID": "BJhZwhTFppgr6D", "uid": "BJhZwhTFppgr6D", "className": "ItemRevision", "type": "ItemRevision",
     "props": {"item_revision_id": {"dbValues": ["A"], "uiValues": ["A"]}, "item_id": {"dbValues": ["000116"], "uiValues": ["000116"]},
               "object_name": {"dbValues": ["Door"], "uiValues": ["Door"]},
               "last_mod_date": {"dbValues": ["2024-03-30T03:57:22-07:00"], "uiValues": ["30-Mar-2024 03:57"]},
               "owning_user": {"dbValues": ["QAiF927kppgr6D"], "uiValues": ["infodba (infodba)"]}}}}}}
```
- Output is a flat list of (parent, children) pairs for every expanded line. Build edges from `itemRevOfBOMLine` uids.
- Quantity lives on BOMLine properties. Names such as `bl_quantity`, `bl_item_item_id` are UNCONFIRMED; add a policy for type `BOMLine` and check.
- BOMLine and BOMWindow uids (`SR::N::...`, `BOM::...`) are runtime handles. Always `closeBOMWindows`; the response lists `ServiceData.deleted` `[T1]`.

#### Files (STEP) via FMS

1. Get the item revision's datasets: `expandGRMRelationsForPrimary` with relation `IMAN_specification`. That relation is CONFIRMED-COMMUNITY as the relation used to attach a PDF dataset `[T1]`; `IMAN_Rendering` is UNCONFIRMED.
2. Dataset property `ref_list` gives the named references (`ImanFile`). `ImanFile` property `original_file_name` (CONFIRMED-COMMUNITY: Java policy `PolicyType("Dataset", {"ref_list"}, WITH_PROPERTIES)` and `PolicyType("ImanFile", {"original_file_name"})` `[T5]`; `ref_list` `[T8]`).
3. `getFileReadTickets(files)` returns a ticket per ImanFile (`[T5]`).
4. HTTP GET `"{fms_url}/{original_file_name}?ticket={ticket}"`. The Java tool formats it as `String.format("%s//%s?ticket=%s", fmsUrl, originalFileName, ticket)` (CONFIRMED-COMMUNITY `[T5]`). The FMS server-cache URL comes from preference `Fms_BootStrap_Urls` (CONFIRMED-COMMUNITY `[T8]`).
   - Through the AW gateway, FMS is proxied under `/fms/`. Upload is `/fms/fmsupload` with form fields `fmsTicket`, `fmsFile` (CONFIRMED-COMMUNITY `[T1]`). A gateway *download* path (e.g. `/fms/fmsdownload/...`) is UNCONFIRMED.
5. Dataset types:
   - `PDF` with named reference `PDF_Reference` (CONFIRMED-COMMUNITY `[T1]`)
   - `UGMASTER` (CONFIRMED-COMMUNITY mention `[T17]`)
   - `UGPART`, `DirectModel` (JT): UNCONFIRMED (search snippets only)
   - **STEP has no confirmed out-of-the-box dataset type.** NX export maps file types to dataset types via preference `TC_NX_Exchange_Dataset_Preferences` (CONFIRMED-COMMUNITY `[T13]`). Detect STEP by `original_file_name` extension (`.stp/.step/.p21`) rather than by dataset type.

#### Typical properties

| Property | Status |
|---|---|
| `item_id`, `item_revision_id`, `object_name`, `owning_user`, `last_mod_date` | CONFIRMED-COMMUNITY with values `[T1]` |
| `object_desc`, `creation_date`, `date_released`, `release_status_list`, `checked_out_user`, `checked_out_date`, `object_string`, `items_tag`, `fnd0InProcess`, `is_vi` | CONFIRMED-COMMUNITY as policy names `[T1]` |
| object type | use the model object's `type`/`className` (CONFIRMED). The `object_type` property is UNCONFIRMED |
| User: `user_id`, `person`, `os_username`, `last_login_time`, `volume`, `home_folder` | CONFIRMED-COMMUNITY `[T1]` |
| Dataset `ref_list`; ImanFile `original_file_name` | CONFIRMED-COMMUNITY `[T5][T8]` |

#### Where-used (practical recommendation)

`Core-2007-01-DataManagement/whereUsed` exists in Teamcenter, but no public JSON or signature could be verified (UNCONFIRMED). For an audit, compute where-used **offline**: expand the BOMs of the top assemblies (or all assemblies) found by query, store the `(parent rev, child rev)` edges, and invert. The simulator then only needs the four BOM operations above.

#### Python sketch

```python
import requests
TC = "http://tc-web:7001/tc/JsonRestServices"
s = requests.Session()
def soa(op, body=None, policy=None, state=None):
    r = s.post(f"{TC}/{op}", json={"header": {"state": state or {}, "policy": policy or {}}, "body": body or {}})
    r.raise_for_status(); data = r.json()
    if "Exception" in data.get(".QName", ""): raise RuntimeError(data)   # error shape UNCONFIRMED
    return data
soa("Core-2011-06-Session/login", {"credentials": {"user": U, "password": P, "role": "", "descrimator": "", "locale": "", "group": ""}})
pol = {"types": [{"name": "ItemRevision", "properties": [{"name": n} for n in
        ("item_id", "item_revision_id", "object_name", "object_desc", "owning_user", "last_mod_date", "release_status_list")]}]}
rev = soa("Core-2007-01-DataManagement/getItemFromId", {"infos": [{"itemId": "000116", "revIds": ["A"]}], "nRev": 1, "pref": {}})
win = soa("Cad-2007-01-StructureManagement/createBOMWindows", {"info": [{"clientId": "", "item": rev["output"][0]["item"]["uid"],
          "revRuleConfigInfo": {"clientId": "", "revRule": "", "props": {"unitNo": -1, "date": "0001-01-01T00:00:00", "today": True, "endItem": "", "endItemRevision": ""}}}]})
out = win["output"][0]
try:
    bom = soa("Cad-2007-01-StructureManagement/expandPSAllLevels",
              {"input": {"parentBomLines": [out["bomLine"]["uid"]], "excludeFilter": "None"}, "pref": {"expItemRev": False}}, policy=pol)
finally:
    soa("Cad-2007-01-StructureManagement/closeBOMWindows", {"bomWindows": [out["bomWindow"]["uid"]]})
```

### 4.b Newer or other "REST" options

- **Active Workspace gateway microservices**: routes like `tc/micro/<service>/...`. The segment `micro` (or `sd`) comes from the gateway `config.json`; the Siemens SLM app uses `tc/micro/tcslmassetmgmt/coc` (CONFIRMED `[T10]`). These are product-specific microservices, not a general documented data API.
- **Siemens developer portal**: lists "Teamcenter (X) Product Cost Management REST API" and the Mendix Teamcenter Connector. No general Teamcenter data REST API is listed (CONFIRMED `[T12]`). TcPCM is cost management, not PDM data.
- **"Teamcenter Gateway"** is the T4x integration product family (SAP etc.), not a generic REST API. That characterisation is inferred; no Siemens page was read for it.
- So for on-prem Teamcenter, the de-facto REST surface is JsonRestServices (web tier) or the AW gateway's `RestServices`/`JsonRestServices`.

---

## 5. Cross-system canonical mapping (inferred, built only from confirmed field names)

| Canonical | SOLIDWORKS PDM (Web API) | Vault (Data API) | Windchill (WRS) | Teamcenter |
|---|---|---|---|---|
| system id | `ObjectInfo.Id` (+ `ParentFolderId`) | file-version `id`, master `file.id` | `ID` (`OR:wt.part.WTPart:n`), `VersionID` | `uid` |
| part number | data-card var (e.g. `Number`) via `variables` | item `number` / file property via `option[propDefIds]` | `Number` | `item_id` |
| name / description | file `Name`; var `Description` | `name`, `title`, `description` | `Name` | `object_name`, `object_desc` |
| revision | `FileRevisionInfo` (InfoType 1) or var | `revision` | `Revision` | `item_revision_id` |
| version / iteration | `Version` | `version` | parse `Version` (`A.1`) | n/a (revision-based) |
| state | `State`, `StateId` | `state`, `lifecycleState` | `State.Value/Display` | `release_status_list` |
| created / modified | `ModifiedDate` | `createDate`, `lastModifiedDate`, `createUserName` | `CreatedOn`, `LastModified`, `CreatedBy`, `ModifiedBy` | `creation_date`, `last_mod_date`, `owning_user` |
| file name | `Name` | `name` | `FileName` (CAD doc) | `original_file_name` (ImanFile) |
| children | `references` / computed BOM | `uses`, item BOM `itemBomLinks` | `Uses` / `GetPartStructure` | `expandPS*` output |
| parents | `whereused` | `parents` | `UsedBy` | invert BOM edges |

## 6. Simulator checklist (what to emulate exactly)

- **PDM**:
  - `POST /api/{v}/authenticate` returns `{JwtString, Success}`; 401 without a Bearer token.
  - `POST searchvariables` and `GET folders/{id}/browse` return `ObjectInfo[]` (PascalCase keys, integer flags).
  - `GET files/{id}/{ver}/variables` returns `ConfigInfo[]`; `GET .../whereused` and `GET .../references` return `FileRef`.
  - `GET .../download` returns 302 to a content URL.
  - No pagination.
- **Vault**:
  - `POST /sessions`; `Authorization: Bearer V:<guid>` on all calls except `/vaults` and `/server-info`.
  - String ids. Every collection is `{pagination:{limit,totalResults,nextUrl?,indexingStatus}, results:[...], included?}` with a cursor in a host-relative `nextUrl`; sometimes emit an empty page that still has a `nextUrl`.
  - `option[propDefIds]` controls `properties`; single-entity GETs always include them with `definition`.
  - Errors as `{statusCode,errorCode,title,detail,params}`.
  - `content` supports `Range`/206.
- **Windchill**:
  - Basic auth.
  - Return 400 if `Accept` is missing? (Observed for one client `[W24]`; optional.)
  - OData collections as `{"@odata.context", "value":[...], "@odata.nextLink"?}`; default page 25; honour `Prefer: odata.maxpagesize` (max 2000) and echo `Preference-Applied`. The header name `Preference-Applied` is the OData standard; WRS says it "sends back the prefer header", so the exact header name is UNCONFIRMED.
  - `$filter` subset, `ptc.search.latestversion`.
  - `GET PTC/GetCSRFToken()`; reject POST without `CSRF_NONCE`.
  - `{Value, Display}` enums.
- **Teamcenter**:
  - Single POST handler at `/tc/JsonRestServices/<op>`, `Content-Type: text/json`, `JSESSIONID` cookie set on login and required afterwards.
  - Envelope `{header:{state,policy}, body}`; responses with `.QName`.
  - `ServiceData{plain, modelObjects{uid:{objectID,uid,className,type,props{p:{dbValues,uiValues}}}}}`; honour `policy.types[].properties[].name`.
  - BOM window lifecycle: create, expand, close (invalidate uids).
  - FMS endpoint `GET /{name}?ticket=...` on a second port.

---

## 7. Sources

SOLIDWORKS PDM Web API (official help, 2025; the 2026 pages are identical):
- [P1] Getting Started: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/GettingStarted.html
- [P2] PDM Pro API Web Service (operation list): https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws.html ; File group: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~g-0e45981b-3619-4486-b05d-cc362f26dd7c.html
- [P3] Release Notes: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/ReleaseNotes.html (2026: https://help.solidworks.com/2026/english/api/pdmprowebapihelp/ReleaseNotes.html)
- [P4] authenticate: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-%7BvaultName%7D-authenticate~o-HttpPost.html
- [P5] searchvariables: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-%7BvaultName%7D-searchvariables~o-HttpPost.html
- [P6] search GET: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-%7BvaultName%7D-search~o-HttpGet.html ; POST: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-%7BvaultName%7D-search~o-HttpPost.html
- [P7] folders browse: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-%7BvaultName%7D-folders-%7BfolderId%7D-browse~o-HttpGet.html
- [P8] file info: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-%7BvaultName%7D-files-%7BfileId%7D-%7Bversion%7D-%7BfolderId%7D-info~o-HttpGet.html
- [P9] variables: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-%7BvaultName%7D-files-%7BfileId%7D-%7Bversion%7D-%7BfolderId%7D-variables~o-HttpGet.html
- [P10] datacard: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-%7BvaultName%7D-files-%7BfileId%7D-%7Bversion%7D-datacard-folderId=%7BfolderId%7D~o-HttpGet.html
- [P11] versions: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-%7BvaultName%7D-files-%7BfileId%7D-%7BfolderId%7D-versions~o-HttpGet.html
- [P12] references: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-%7BvaultName%7D-files-%7BfileId%7D-%7Bversion%7D-%7BfolderId%7D-references-configId=%7BconfigId%7D~o-HttpGet.html
- [P13] allreferences: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-%7BvaultName%7D-files-%7BfileId%7D-%7Bversion%7D-%7BfolderId%7D-allreferences-configId=%7BconfigId%7D-includeSubParents=%7BincludeSubParents%7D~o-HttpGet.html
- [P14] whereused: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-%7BvaultName%7D-files-%7BfileId%7D-%7Bversion%7D-%7BconfigId%7D-%7BfolderId%7D-whereused-anyVersion=%7BanyVersion%7D~o-HttpGet.html
- [P15] download: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-%7BvaultName%7D-files-%7BfileId%7D-%7Bversion%7D-%7BfolderId%7D-download~o-HttpGet.html
- [P16] computed BOM: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-%7BvaultName%7D-bom-%7BbomTypeId%7D-%7BfileId%7D-%7Bversion%7D-%7BfolderId%7D-computed-configId=%7BconfigId%7D-latest=%7Blatest%7D~o-HttpGet.html
- [P17] bominfo: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-%7BvaultName%7D-files-%7BfileId%7D-%7BfolderId%7D-bominfo~o-HttpGet.html
- [P18] named BOM: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-%7BvaultName%7D-bom-%7BbomDocumentId%7D-%7Bversion%7D-%7BfolderId%7D-named~o-HttpGet.html
- [P19] workflows: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-%7BvaultName%7D-workflows~o-HttpGet.html
- [P20] info/extended: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-%7BvaultName%7D-files-%7BfileId%7D-%7Bversion%7D-%7BfolderId%7D-info-extended~o-HttpGet.html
- [P21] files/info: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-%7BvaultName%7D-files-info~o-HttpPost.html
- [P22] infofrompath: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-%7BvaultName%7D-files-infofrompath~o-HttpPost.html
- [P23] configurations: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-%7BvaultName%7D-files-%7BfileId%7D-%7Bversion%7D-%7BfolderId%7D-configurations~o-HttpGet.html
- [P24] configuration/vaults: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-configuration-vaults-vaultName=%7BvaultName%7D~o-HttpGet.html
- [P25] folder info: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-%7BvaultName%7D-folders-%7BfolderId%7D~o-HttpGet.html
- [P26] version/webapi: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/PDM%20Pro%20API_ws~r-api-version-webapi~o-HttpGet.html
- [P27] official Postman environment: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/WebAPI.postman_environment.json
- [P28] official Postman "Use Search Variables": https://help.solidworks.com/2025/english/api/pdmprowebapihelp/Use%20Search%20Variables.postman_collection.json
- [P29] official Postman "Modify File Datacards": https://help.solidworks.com/2025/english/api/pdmprowebapihelp/Modify%20File%20Datacards.postman_collection.json
- [P30] JS authentication example: https://help.solidworks.com/2025/english/api/pdmprowebapihelp/index.html
- [P31] Administering Web API Servers: https://help.solidworks.com/2022/english/EnterprisePDM/Admin/c_administering_web_api_servers.htm
- [P32] Adding a Web API Server: https://help.solidworks.com/2026/english/EnterprisePDM/admin/t_adding_web_api_server.htm
- [P33] Installation Guide 2026 (partial via WebFetch): https://files.solidworks.com/Supportfiles/PDMWorks_Ent_Installation/2026/English/Installation%20Guide.pdf
- [P34] Blue Byte quickstart (community): https://bluebyte.biz/pdm-api-tips/a-quickstart-guide-with-the-solidworks-pdm-web-api/

SOLIDWORKS PDM COM API (official help 2025 unless noted; base https://help.solidworks.com/2025/english/api/epdmapi/):
- [C1] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmVault5~LoginAuto.html
- [C2] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmVault5~Login.html
- [C3] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmVault5_members.html
- [C4] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmFile5_members.html
- [C5] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmSearch5_members.html
- [C6] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmSearch6~SetToken.html
- [C7] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.EdmSearchToken.html
- [C8] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmSearch8~AddVariable2.html ; members: https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmSearch8_members.html
- [C9] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmVault21~CreateSearch2.html
- [C10] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmSearchResult5.html ; members: https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmSearchResult5_members.html
- [C11] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmEnumeratorVariable5~GetVar.html
- [C12] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmFile5~GetFileCopy.html
- [C13] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmFile5~GetReferenceTree.html
- [C14] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmFile5~GetEnumeratorVariable.html
- [C15] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmReference5_members.html
- [C16] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmReference10~GetFirstChildPosition4.html
- [C17] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmReference7~GetFirstParentPosition2.html
- [C18] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmReference5~GetNextChild.html
- [C19] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmFolder5_members.html ; https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmFolder5~GetNextFile.html ; https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmPos5_members.html
- [C20] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmFile7~GetComputedBOM.html
- [C21] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmBomMgr.html ; https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmBomMgr2~GetBomLayouts2.html
- [C22] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmBomView~GetRows.html ; https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmBomView~GetColumns.html
- [C23] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmBomCell~GetVar.html ; https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmBomCell_members.html
- [C24] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.EdmBomColumn_members.html
- [C25] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.EdmBomFlag.html ; https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.EdmBomColumnType.html
- [C26] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.EdmUtility.html ; https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.EdmObjectType.html ; https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.EdmGetFlag.html ; https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.EdmRefFlags.html
- [C27] https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmVault5~GetFileFromPath.html ; https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmVault5~GetObject.html ; https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmFile5~CurrentState.html ; https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmFile5~CurrentRevision.html ; https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmVault7~CreateUtility.html ; https://help.solidworks.com/2025/english/api/epdmapi/EPDM.Interop.epdm~EPDM.Interop.epdm.IEdmState5.html
- [C28] https://help.solidworks.com/2025/english/api/epdmapi/Using_NET_Framework_in_Applications.htm ; https://help.solidworks.com/2025/english/api/epdmapi/GettingStarted-epdmapi.html
- [C29] https://help.solidworks.com/2019/english/api/epdmapi/ReleaseNotes-epdmapi.html
- [C30] CATI blog (community): https://www.cati.com/blog/pdm-search-from-the-command-line/
- [C31] CodeStack (community): https://www.codestack.net/solidworks-pdm-api/files/get-file-hyperlink/ ; code: https://raw.githubusercontent.com/xarial/codestack/master/solidworks-pdm-api/files/get-file-hyperlink/get-url.ps1
- [C32] Mirror of StackOverflow Q60325854 (community; SO itself blocked for fetch): https://cloud.tencent.com/developer/ask/sof/108298073
- [C33] GoEngineer, configuration properties / "@" tab (community): https://www.goengineer.com/blog/configuration-properties-solidworks-pdm-data-cards
- [C34] CADOverflow, "Does SOLIDWORKS PDM Standard have an API?" (community): https://www.cadoverflow.com/t/does-solidworks-pdm-standard-have-an-api/14

SOLIDWORKS PDM SQL:
- [Q1] Official "SQL Query Examples" (2015): https://help.solidworks.com/2015/english/enterprisepdm/admin/c_SQL_query_examples.htm
- [Q2] GoEngineer tables: https://www.goengineer.com/blog/solidworks-pdm-sql-tables-commonly-used-in-queries
- [Q3] GoEngineer query planning: https://www.goengineer.com/blog/solidworks-pdm-database-query-planning
- [Q4] GoEngineer table diagrams: https://www.goengineer.com/blog/querying-solidworks-pdm-database-sql-table-diagrams
- [Q5] DPS Software duplicate-value query: https://servicenews.dps-software.de/index.php/2017/09/06/pdm-eindeutige-variable-kann-nicht-geaendert-werden-da-doppelte-werte-existieren-wie-koennen-diese-ermittelt-werden/
- [Q6] Solidwise duplicate-value query: https://www.solidwise.com/tips/policydetail_1124.shtml
- [Q7] forum thread 228998: https://forum.solidworks.com/thread/228998
- [Q8] forum thread 65115: https://forum.solidworks.com/thread/65115
- [Q9] forum thread 199213: https://forum.solidworks.com/thread/199213
- [Q10] forum thread 64735 (XRefs BOM query): https://forum.solidworks.com/thread/64735
- [Q11] forum thread 160331 (UserRevs): https://forum.solidworks.com/thread/160331
- [Q12] forum thread 186175 (LatestRevisionNo = version): https://forum.solidworks.com/thread/186175

Autodesk Vault Data API (official APS docs; page content fetched from the APS doc CDN base https://developer.doc.autodesk.com/bPlouYTd/vault-vault-api-spec-main-747837/vaultdataapi/):
- [V1] Overview: https://aps.autodesk.com/en/docs/vaultdataapi/v2/developers_guide/overview/
- [V2] Base URL: https://aps.autodesk.com/en/docs/vaultdataapi/v2/developers_guide/api_basics/base_url/
- [V3] Authentication: https://aps.autodesk.com/en/docs/vaultdataapi/v2/developers_guide/api_basics/authentication/
- [V4] Error handling: https://aps.autodesk.com/en/docs/vaultdataapi/v2/developers_guide/error_handling/
- [V5] Rate limits: https://aps.autodesk.com/en/docs/vaultdataapi/v2/developers_guide/rate_limits/
- [V6] Changelog: https://aps.autodesk.com/en/docs/vaultdataapi/v2/change_history/changelog/ (CDN: .../vaultdataapi/_change_history/changelog.html)
- [V7] Quick reference: https://aps.autodesk.com/en/docs/vaultdataapi/v2/reference/http/quick_reference/
- [V8] Create session: https://aps.autodesk.com/en/docs/vaultdataapi/v2/reference/http/createsession-POST/
- [V9] Get vaults: https://aps.autodesk.com/en/docs/vaultdataapi/v2/reference/http/getvaults-GET/
- [V10] Get file versions: https://aps.autodesk.com/en/docs/vaultdataapi/v2/reference/http/getfileversions-GET/
- [V11] File version content: https://aps.autodesk.com/en/docs/vaultdataapi/v2/reference/http/getfileversioncontent-GET/
- [V12] Signed URL: https://aps.autodesk.com/en/docs/vaultdataapi/v2/reference/http/getfileversionsignedurl-GET/
- [V13] Uses: https://aps.autodesk.com/en/docs/vaultdataapi/v2/reference/http/getfileversionuses-GET/
- [V14] Parents (where used): https://aps.autodesk.com/en/docs/vaultdataapi/v2/reference/http/getfileversionwhereused-GET/
- [V15] Item versions: https://aps.autodesk.com/en/docs/vaultdataapi/v2/reference/http/getitemversions-GET/
- [V16] Item BOM: https://aps.autodesk.com/en/docs/vaultdataapi/v2/reference/http/getitemversionbom-GET/
- [V17] Item where used: https://aps.autodesk.com/en/docs/vaultdataapi/v2/reference/http/getitemversionwhereused-GET/
- [V18] Item associated files: https://aps.autodesk.com/en/docs/vaultdataapi/v2/reference/http/getitemversionassociatedfiles-GET/
- [V19] Property definitions: https://aps.autodesk.com/en/docs/vaultdataapi/v2/reference/http/getpropertydefinitions-GET/
- [V20] Basic search: https://aps.autodesk.com/en/docs/vaultdataapi/v2/reference/http/search-GET/
- [V21] Advanced search: https://aps.autodesk.com/en/docs/vaultdataapi/v2/reference/http/advancedsearch-POST/
- [V22] Tutorial, retrieve properties: https://aps.autodesk.com/en/docs/vaultdataapi/v2/tutorials/endpoint-retrieve-properties/
- [V23] Tutorial, filtering: https://aps.autodesk.com/en/docs/vaultdataapi/v2/tutorials/endpoint-filtering/
- [V24] Folder contents: https://aps.autodesk.com/en/docs/vaultdataapi/v2/reference/http/getfoldercontents-GET/
- [V25] Official samples repo README: https://github.com/autodesk-platform-services/vault-data-api-samples
- [V26] Autodesk forum, 2025.2 requirement: https://forums.autodesk.com/t5/vault-customization-forum/fail-to-connect-to-vault-through-rest-api/td-p/13318162
- [V27] Autodesk forum, permissions: https://forums.autodesk.com/t5/vault-customization-forum/2025-2-rest-data-api/td-p/13332979
- [V28] WIIP blog (root folder id 1): https://wiip.fr/en/blog/vault-data-api
- [V29] Autodesk forum, FindFilesBySearchConditions bookmark: https://forums.autodesk.com/t5/vault-customization-forum/findfilesbysearchconditions-repeated-bookmark-resulting-in/td-p/10186085
- [V30] Autodesk developer blog, acquire files: https://blog.autodesk.io/how-to-acquire-files/
- [V31] Autodesk forum, SOAP service URL: https://forums.autodesk.com/t5/vault-customization-forum/get-services-security-version-or-folder-name-through-vault-api/td-p/9548219

PTC Windchill REST Services (official PTC help unless noted):
- [W1] Retrieving the Part Structure: https://support.ptc.com/help/windchill_rest_services/r2.5/en/windchill_rest_services/wccg_restapiaccessexamples_ProdMgmt_getPartstructure.html
- [W2] Retrieving Parts (13.1.2.0): https://support.ptc.com/help/windchill/r13.1.2.0/en/Windchill_Help_Center/WCRESTFramework/example_prodmgmt_retrieve_parts.html
- [W3] Nonce token function: https://support.ptc.com/help/windchill_rest_services/r2.6/en/windchill_rest_services/WCCG_RESTAPIsNonceTokenFunction.html
- [W4] OData Prefer headers: https://support.ptc.com/help/windchill_rest_services/r2.5/en/windchill_rest_services/WCCG_RESTAPIsODataPreferHeader.html
- [W5] CAD Document Management domain (13.1.2.0): https://support.ptc.com/help/windchill/plus/r13.1.2.0/en/Windchill_Help_Center/WCRESTFramework/CADdocumentmgmtdomain.html
- [W6] Performance best practices: https://support.ptc.com/help/windchill_rest_services/r2.4/en/windchill_rest_services/WCCG_RESTAPIsBestPractices_WindchillRestServices_Performance.html
- [W7] CAD examples: landing https://support.ptc.com/help/windchill_rest_services/r2.7/en/windchill_rest_services/examples_lp_CADDocumentMgmt.html ; [W7b] https://support.ptc.com/help/windchill_rest_services/r2.7/en/windchill_rest_services/wccg_restapiaccessexamples_CADDocumentMgmt_getaspecificCADdocument.html ; [W7c] https://support.ptc.com/help/windchill_rest_services/r2.7/en/windchill_rest_services/wccg_restapiaccessexamples_CADDocumentMgmt_getaspecificCADdocumentwithexpand.html ; [W7d] https://support.ptc.com/help/windchill_rest_services/r2.7/en/windchill_rest_services/wccg_restapiaccessexamples_CADDocumentMgmt_getCADdocumentusingfilter.html ; [W7e] https://support.ptc.com/help/windchill_rest_services/r2.7/en/windchill_rest_services/wccg_restapiaccessexamples_CADDocumentMgmt_getCADstructure.html ; [W7f] https://support.ptc.com/help/windchill_rest_services/r2.7/en/windchill_rest_services/example_CADDocumentMgmt_retrieveAssociation.html ; [W7g] https://support.ptc.com/help/windchill_rest_services/r2.7/en/windchill_rest_services/example_CADDocumentMgmt_navigate_CADdocument_to_Drawings.html
- [W8a] OData query parameters: https://support.ptc.com/help/windchill_rest_services/r2.4/en/windchill_rest_services/WCCG_RESTAPIsSupportedQueryOptions.html ; [W8b] examples (13.1.0.0): https://support.ptc.com/help/windchill/r13.1.0.0/en/Windchill_Help_Center/WCRESTFramework/examples_WCCG_RESTAPIsSupportedQueryOptions.html
- [W9] Visualization domain: https://support.ptc.com/help/windchill_rest_services/r2.7/en/windchill_rest_services/visualizationdomain.html
- [W10] Retrieving a representation: https://support.ptc.com/help/windchill_rest_services/r2.7/en/windchill_rest_services/wccg_restapiaccessexamples_visualization_getrepresentation.html
- [W11] Versioning of the domain API: https://support.ptc.com/help/windchill_rest_services/r1.7/en/windchill_rest_services/WCCG_RESTAPIsVersioningofAPI.html
- [W12] Accessing domains: https://support.ptc.com/help/windchill_rest_services/r1.6/en/windchill_rest_services/WCCG_RESTAPIsAccess.html
- [W13] WRS OAuth: https://support.ptc.com/help/windchill_rest_services/r2.7/en/windchill_rest_services/oauth_for_wrs.html
- [W14] Summary of changes, WRS 2.7: https://support.ptc.com/help/windchill_rest_services/r2.7/en/windchill_rest_services/WCCG_REST_atechsum_2_7.html
- [W15] WRS changes 13.1.0.0: https://support.ptc.com/help/windchill/r13.1.0.0/en/Windchill_Help_Center/NewandChanged_WRS/wrs_generalcapabilities_13_1_00.html
- [W16] WRS changes 13.1.1.0: https://support.ptc.com/help/windchill/r13.1.2.0/en/Windchill_Help_Center/NewandChanged_WRS/wrs_generalcapabilities_13_1_10.html
- [W17] Retrieving the latest version: https://support.ptc.com/help/windchill_rest_services/r1.6/en/windchill_rest_services/wccg_restapis_latest_version_search.html
- [W18] ProdMgmt domain: https://support.ptc.com/help/windchill_rest_services/r2.7/en/windchill_rest_services/prodmgmtdomain.html
- [W19] Windchill subtypes in OData: https://support.ptc.com/help/windchill_rest_services/r2.5/en/windchill_rest_services/wccg_restapis_wcsubtypes_in_OData.html
- [W20] Creating a part: https://support.ptc.com/help/windchill_rest_services/r2.7/en/windchill_rest_services/WCCG_RESTAccessExamplesCreatePart.html
- [W21] Windchill REST Services User's Guide 1.2 (PDF): https://www.ptc.com/-/media/372A9A2D67424933B356F94BB8ABCF2F.ashx?sc_lang=
- [W22] PTC community, where-used latest: https://community.ptc.com/windchill-10/how-can-i-get-part-where-used-latest-view-from-rest-api-143090
- [W23] PTC community, CSRF plus Basic: https://community.ptc.com/t5/Windchill/POST-ODATA-API-with-CSRF-NONCE-in-header-got-401-Unauthorized/td-p/899465
- [W24] PTC community, nonce HTTP 400 / Accept header: https://community.ptc.com/t5/Windchill/Problem-getting-CSRF-NONCE-value-HTTP-400/td-p/863661
- [W25] PTC community, AllPrimaryContents and native Creo: https://community.ptc.com/windchill-customization-438/getting-cad-documents-using-the-odata-rest-api-155778
- [W26] PTC community, CADDocument Uses fields: https://community.ptc.com/windchill-10/how-to-find-more-information-on-caddocument-memberlinks-via-windchill-rest-services-api-165942
- [W27] PTC community, Representations URL: https://community.ptc.com/t5/Windchill/RESTFul-get-representation-URL/td-p/619915
- [W28] Reading a part with expanded navigation: https://support.ptc.com/help/windchill_rest_services/r1.6/en/windchill_rest_services/WCCG_RESTAccessExamplesReadPartbyID.html
- [W29] Configuring structural properties: https://support.ptc.com/help/windchill_rest_services/r2.0/en/windchill_rest_services/WCCG_RESTAPIsConfiguringStructuralProperties.html

Siemens Teamcenter:
- [T1] Krusty84 Teamcenter REST API Postman collection (community, TC 13.3 saved responses): https://github.com/Krusty84/Teamcenter_REST_API ; raw: https://raw.githubusercontent.com/Krusty84/Teamcenter_REST_API/main/Teamcenter_REST_API.postman_collection.json
- [T2] Mendix docs (Siemens), "Using Teamcenter Services Not Included with the Teamcenter Connector": https://docs.mendix.com/appstore/industry/teamcenter-connector/services-not-included/
- [T3] Mendix docs, connection configuration 2512: https://docs.mendix.com/appstore/industry/teamcenter-connector/configuring-connection-2512/
- [T4] Teamcenter Connector for Mendix guide (operation names; via WebFetch): https://anyflip.com/bezer/plmr/basic/51-79
- [T5] TcLoadTester FMSDownload.java (community): https://github.com/mjonsson/TcLoadTester/blob/master/TcLoadTester/src/com/siemens/tcloadtester/modules/FMSDownload.java
- [T6] TcLoadTester ExpandStructure.java (community): https://github.com/mjonsson/TcLoadTester/blob/master/TcLoadTester/src/com/siemens/tcloadtester/modules/ExpandStructure.java
- [T7] Teamcenter Open Gate blog, executeSavedQueries Java (community): https://teamcenter-open-gate.blogspot.com/2016/12/soa-serive-client-assign-project-to.html
- [T8] Teamcenter Open Gate blog, dataset download (community): https://teamcenter-open-gate.blogspot.com/2016/12/soa-service-client-download-dataset.html
- [T9] TCPLM blog, C# query and LoadObjects (community): http://tcplm.blogspot.com/2018/12/teamcenter-soa-c-how-to-get-model.html
- [T10] Siemens Teamcenter SLM 2412 install guide (AW gateway cookies, tc/micro routes): https://appexchange.salesforce.com/image_host/521e2572-7155-4441-b40e-1ae03b6bc637.pdf
- [T11] Violet docs, Teamcenter connect via API (community): https://docs.violetlabs.com/apps/t/teamcenter/connect-via-api
- [T12] Siemens developer portal API catalogue: https://developer.siemens.com/apis.html
- [T13] eng-tips, STEP dataset preference (community): https://www.eng-tips.com/threads/export-step-file-to-teamcenter.494248/
- [T14] Teamcenter Services Reference (requires Siemens login; NOT accessed): https://support.industrysoftware.automation.siemens.com/docs/teamcenter/10.1/help/en_US/custom/services_reference/Help.html
- [T15] tc-mcp README (mentions X-XSRF-Token handling; community): https://github.com/goenninger-b-t/tc-mcp
- [T16] anwinnova/teamcenter-automation (LOW confidence: uses a non-standard `/rest/v1/...` path and wraps responses in `body`, which contradicts [T1]): https://github.com/anwinnova/teamcenter-automation
- [T17] Medium, Teamcenter DB design (UGMASTER mention; community): https://medium.com/@mjvibhute/plm-teamcenter-database-design-relations-dataset-3dfcae9eadf7
