# ERP API research: Priority, SAP S/4HANA, SAP Business One (read-only part data)

Researched 2026-10-03 for the part-data audit tool. Scope: **read-only** access to the part/item master, stock per warehouse, cost/price and currency, main supplier and supplier part number, and BOMs, plus enough detail on wire formats to build local simulators.

Method: public sources only (vendor developer portals and PDFs, SAP-published artifacts on npm/GitHub, public GitHub code, odata.org). I did not sign up for anything, did not log in to any system (including the Priority demo sandbox whose credentials are published), did not submit forms and did not upload data.

---

## 0. How to read this document

Every fact has one of these labels:

| Label | Meaning |
|---|---|
| **CONFIRMED** [id] | Stated in vendor documentation or a vendor-published artifact. The `[id]` points to the "Sources" list for that system, which has the URL. Vendor artifacts include the Priority dev portal and PDFs, SAP Cloud SDK schema files published by SAP on npm, SAP's OpenAPI spec, and SAP B1 guides. |
| **CONFIRMED-3P** [id] | Seen only in public third-party code, samples or payloads that talk to real systems. Probably right, but verify it against `$metadata` or a live system. |
| **UNCONFIRMED** | My inference, a common convention, or a name I could not find in any reachable source. Do not hard-code it without verifying. |

**Sources I could not use:** `help.sap.com` and `api.sap.com` disallow all non-search-engine bots in robots.txt. Most `community.sap.com` pages refused the fetch tool. `biuan.com` (a mirror of the SAP B1 DI-API help) explicitly disallows Claude agents. I did not fetch any of these. Where an official SAP document had a public copy elsewhere (npm, GitHub), I used that copy. See §5.

**Advice that applies to all three systems:**
- Drive the connectors from configuration: form/entity names and field names belong in a mapping file, not in code.
- Always send an explicit `$select`.
- Check every name against the customer system's metadata. All three ERPs are customised per customer, Priority most of all.

---

## 1. Priority Software ERP: REST API (OData v4)

### 1.1 Service root, protocol, discovery

| Fact | Status |
|---|---|
| The REST API is OData. `GET {root}/GetODataVersion()` returns `{"@odata.context":"serviceroot/$metadata#Edm.String","value":"4.0"}` | CONFIRMED [P3] |
| Service root: `https://www.server.com/odata/Priority/tabula.ini/environment`. Here `www.server.com` is the application-server URL, `tabula.ini` is the system's tabula.ini file name, and `environment` is "the company's internal name in Priority". Metadata is at `{root}/$metadata` | CONFIRMED [P8][P9] |
| The ini file name varies by installation. The demo uses `tabbtd38.ini`, i.e. `https://t.eu.priority-connect.online/odata/Priority/tabbtd38.ini/usdemo` (sandbox, v25.0) | CONFIRMED [P1] |
| Some installations add a path prefix before `/odata`, e.g. `https://www.eshbelsaas.com/ui/odata/Priority/tabmob.ini/usdemo/` (seen in `@odata.context` examples) | CONFIRMED [P3][P5] |
| An admin can output the exact root with the "Send Program Activation Link" program. Ask the customer for it rather than building it yourself | CONFIRMED [P1][P8] |
| Language: append `,<code>` after the ini name, e.g. `https://www.example.com/odata/Priority/tabula.ini,3/test/CUSTOMERS('1234')` (3 = American English). This mainly affects the language of error and warning messages. Hebrew's code is not documented publicly (UNCONFIRMED) | CONFIRMED [P3] |
| Mapping: an EntityType is a Priority **form**, a Property is a **form column**, and a NavigationProperty is a **sub-level form** ("subform") | CONFIRMED [P3] |
| Requests are case-sensitive. Form and field names are usually UPPERCASE (rare exceptions such as `DOCUMENTS_p`) | CONFIRMED [P1] |
| `GET {root}/` returns `{"@odata.context":"serviceRoot/$metadata","value":[{"name":"ABILITIES","kind":"EntitySet","url":"ABILITIES"}, ...]}` | CONFIRMED [P3] |
| `GET {root}/GetPriorityVersion()` returns e.g. `"22.0-20.0.0.119"`. `GET {root}/GetLoginName` returns the API user name | CONFIRMED [P3] |
| `GET {root}/GetMetadataFor(entity='LOGPART')` returns metadata for one top-level form (v25.0+). On-prem it needs a BIN released on or after 2025-06-29. It works only for top-level entities. Make a `$top=1` request first if the metadata has not been prepared yet | CONFIRMED [P3] |
| From v25.1, metadata marks mandatory columns with `Priority.OData.Mandatory`. Descriptions arrive in the system language as `Priority.OData.Description` annotations, which are Hebrew in Hebrew systems (e.g. `String="&#x5DC;&#x5E7;&#x5D5;&#x5D7;&#x5D5;&#x5EA;"`) | CONFIRMED [P3] |
| Priority **Zoom** does not offer the API; only the regular Priority edition does | CONFIRMED-3P [P24] |

### 1.2 Authentication and headers

| Method | Details | Status |
|---|---|---|
| Basic (user/password) | `Authorization: Basic …` on every request. Requests without it are denied. The user name is the **"API User Name"** field in the Personnel File, not the normal login. You cannot use Basic while External ID is enabled. The Aug-2026 KB says on-prem customers can use API User Name plus the Priority password | CONFIRMED [P2][P8] |
| Personal Access Token (PAT) (v19.1+) | Still HTTP Basic: **username = the token, password = the literal `PAT`** (uppercase only). Tokens are created in "REST Interface Access Tokens" (System Management > System Maintenance > Users), a user can have several, and each token is shown only once. Customers on Priority Accounts, AD or SSO **must** use tokens. This is the recommended method for server-to-server use | CONFIRMED [P2][P8][P9] |
| OAuth2 (External ID module) | `Authorization: Bearer …`, Authorization Code + PKCE, scope `openid rest_api`, discovery at `https://(PRIORITY_DOMAIN)/accounts/.well-known/openid-configuration`. Intended for browser/mobile apps; Priority itself says to use PAT for server-to-server. The guide is "relevant only for on-prem (non-SaaS) installations" | CONFIRMED [P2] |
| `X-App-Id` / `X-App-Key` | Needed only when the customer licenses your application under the per-application license (v18.3+). Without them, requests count under generic API licensing. Example: `X-App-Id: APP001`, `X-App-Key: 15nXqSDX…` | CONFIRMED [P1] |
| `X-App-Trace: 1` | Debug tracing. It also needs `[Internet] Sqldebug=1` in tabula.ini. Do not use it in production | CONFIRMED [P1] |

Customer-side setup to request (CONFIRMED [P1][P8]):
1. Personnel File: set **API User Name**.
2. User Permissions: tick the **API License** checkbox.
3. **Limited Access/API Forms** form: tick **Available for API** for every *upper-level* form you read. Sub-levels are included automatically.
4. To make the API user read-only, set it up through the user's privileges in the **Privilege Explorer**. CONFIRMED [P8]

If a form is not enabled, a 400 response reading "API cannot be run for this form." has been reported in a Power BI thread. The message text is CONFIRMED-3P [P23]; the cause is UNCONFIRMED.

### 1.3 Response format

| Fact | Status |
|---|---|
| The default format is JSON. Successful reads return 200 | CONFIRMED [P1] |
| A collection looks like `{"@odata.context":"serviceRoot/$metadata#LOGPART","value":[{...},{...}]}` | CONFIRMED [P4] |
| With `$select`, the context lists the fields: `"@odata.context":"serviceRoot/$metadata#ACCOUNTS(ACCNAME,ACCDES,USERLOGIN,UDATE)"` | CONFIRMED [P4] |
| A single entity by key (`GET {root}/LOGPART('111-012')`) returns `{"@odata.context":"serviceRoot/$metadata#LOGPART/$entity","PARTNAME":"111-012",...}` | CONFIRMED [P3] |
| An expanded subform arrives as property `<NAME>_SUBFORM` (an array for collection subforms; an object or `null` for single-row ones such as `SHIPTO2_SUBFORM`) plus `<NAME>_SUBFORM@odata.context` | CONFIRMED [P3][P4] |
| Dates are DateTimeOffset `YYYY-MM-DDTHH:MM:SS+HH:MM`, e.g. `"2021-01-31T15:10:00+02:00"`. Since v21.0 the offset follows the company timezone when `TZSERVER=1` | CONFIRMED [P1][P3] |
| Resource IDs are strings. Blank fields come back as `null` or `""` rather than being omitted | CONFIRMED [P1] |
| Property types are only `Edm.String`, `Edm.Decimal`, `Edm.Int64` and `Edm.DateTimeOffset`. In JSON, decimals and integers are **numbers** (`"LASTPRICE": 233.48`, `"PRICE":50.00`, `"FAMILY": -1`). From v22.0 the decimal separator is always `.` | CONFIRMED [P3][P4][P17] |
| Full metadata: `$format=application/json;odata.metadata=full` adds `@odata.type`, `@odata.id`, `@odata.editLink` and navigation links | CONFIRMED [P3] |
| Text subforms (e.g. `ORDERSTEXT_SUBFORM`) return `{"TEXT":"<style>…</style><p dir=rtl>…","APPEND":null,"SIGNATURE":null}`, i.e. HTML with RTL markup | CONFIRMED [P3] |
| Responses are capped at 350 MB | CONFIRMED [P1] |

### 1.4 Query options, paging and limits

| Fact | Status |
|---|---|
| `$filter` supports `eq ne gt ge lt le`, `and`/`or`, parentheses, and `contains()`, `startswith()`, `endswith()` (with `tolower()` nested). **`substringof` is not supported and returns 400** | CONFIRMED [P4] |
| `$orderby x asc/desc`, `$top`, `$skip` (v19.1+), `$select`, and `$expand` (v18.1+). `$expand` can nest and takes options separated by `;`, e.g. `$expand=ORDERITEMS_SUBFORM($filter=PRICE gt 3;$select=PARTNAME,TQUANT,PRICE;$expand=ORDISTATUSLOG_SUBFORM)` | CONFIRMED [P4] |
| **Row cap:** from v25.1, `MAXAPILINES` (default **2,000**) limits rows per response; before v25.1, `MAXFORMLINES` did. This applies "even if you do not use `$top`", and Priority "strongly recommend[s] you implement pagination" | CONFIRMED [P1][P4] |
| Paging is client-driven with `$top` + `$skip`, e.g. `GET {root}/FAMILY_LOG?$top=3&$skip=1` | CONFIRMED [P4] |
| `@odata.nextLink` appears **nowhere** in the official REST docs or examples. Whether it is ever emitted is UNCONFIRMED. Priority's own MCP server doc says of its `form_fetch` tool: "There is no indicator in the response when results are truncated". That is a different interface, but consistent | UNCONFIRMED (CONFIRMED for the MCP tool [P19]) |
| A third-party MCP reports that "Priority silently truncates responses at MAXFORMLINES regardless of `$top`", that `GET /ENTITY/$count` returns 500, and that `$apply` is unsupported | CONFIRMED-3P [P20] |
| `$since=2020-01-01T07:25:00Z` returns only changed records, and only on forms with BPM. Use UTC `Z` | CONFIRMED [P4] |
| Change detection on lookup forms without BPM: `UDATE`/`USERLOGIN` columns were added (v25.0 with latest CU+BIN, and v26.1) to **SUPPLIERPARTS, WAREHOUSES, FNCPART, ICOSTCENTERS, PROFITCENTERS, ACCOUNTS, ACCOUNTS_GENERAL, BUDGETS, FNCWARHS, FNCTRANS**. Use them like `$filter=UDATE ge 2025-06-01T00:00:00Z`. LOGPART is not in that list | CONFIRMED [P4] |
| Date literals in `$filter` are unquoted. Encode spaces as `%20` and `+` as `%2B` (the docs show `ge%2018-02-23` as a broken example) | CONFIRMED [P4] |
| IIS or a WAF may sanitise `;` inside `$expand` options, giving a 400. Send it as `%3B` | CONFIRMED [P4] |
| When you `$expand` a subform with composite keys, the outer `$select` must include all key fields of the upper-level form | CONFIRMED [P4] |
| Composite key syntax: `DOCUMENTS_D(DOCNO='SH17000001',TYPE='D')` | CONFIRMED [P17] |
| Subforms are reached through their parent (`FAMILY_LOG('001')/FAMILY_LOGPART_SUBFORM`) or with `$expand` | CONFIRMED [P3] |
| Querying a subform as if it were top-level (e.g. `PORDERITEMS_SUBFORM`) returns 404 | CONFIRMED-3P [P20] |
| Without `$select`, all fields are returned ("By default, the OData service returns all available fields"). Selecting is recommended | CONFIRMED [P4] |

Recommended connector paging loop (UNCONFIRMED but defensive):
- Set `$top=N` with N ≤ MAXAPILINES (e.g. 500).
- Add a stable `$orderby=PARTNAME`.
- Increase `$skip` by N until a page returns fewer than N rows.
- If an `@odata.nextLink` ever appears, follow it.

### 1.5 Rate limits, licensing, permissions

| Fact | Status |
|---|---|
| Priority Cloud fair use: max **100 API calls/min per user**; up to 15 queued (10 concurrent + 5 queue); requests over **3 min** are dropped; **5,000 requests per 300 s** sliding window; throttled requests get **HTTP 429** | CONFIRMED [P1] |
| **Reads are licensed transactions too.** The Aug-2026 KB says "Write and read API transactions are counted and limited together". The "API Transaction Count" report shows read and write transactions by month, user and entity. Since v25.1 all API users share one transaction pool. The older dev-portal text talks only about updates, so the newer KB is the one to trust. Budget the audit's calls: large pages, `$select`, `$expand` instead of N+1 calls | CONFIRMED [P8][P9][P1] |
| Row-level data privileges are **not** applied to REST ("user requests via REST API are not subject to data privilege restrictions") | CONFIRMED [P3] |
| Field-level permissions **are** applied from v22.1: fields the user cannot see are absent, so field sets can differ per API user | CONFIRMED [P7] |
| Status codes: 200 OK; 201 for DELETE; 400 bad request; 404 "requested form or record do not exist"; 409 conflict; 500 server error; 429 throttled (cloud) | CONFIRMED [P1] |
| Since v19.1 errors are JSON rather than XML, but the only documented example is still XML (`<FORM TYPE="FAMILY_LOG">…<InterfaceErrors><text>…</text></InterfaceErrors></FORM>`). The JSON error shape is UNCONFIRMED, so treat error bodies as opaque text | CONFIRMED [P1][P5] / shape UNCONFIRMED |

### 1.6 Part master: forms `LOGPART` and `PART`

- `LOGPART` is titled "Part Catalogue" and `PART` is titled "Parts". Both are built on the base table `PART`. CONFIRMED [P6][P10]
- The Hebrew SOP describes two screens. The part card ("כרטיס פריט") holds logistic data. The "מוצרים" (Parts) screen is its "direct continuation" for engineering data: product revision, process, issue method, whether BOM revisions are managed, serial numbers, and sub-levels for child parts, revisions and manufacturers. The content is CONFIRMED [P16]. That "כרטיס פריט" = `LOGPART` and "מוצרים" = `PART` is UNCONFIRMED (inferred from the English titles "Part Catalogue"/"Parts").
- The key is `PARTNAME`, as in `GET {root}/LOGPART('111-012')`. CONFIRMED [P3]

| Audit field | Priority field | Status / evidence |
|---|---|---|
| Part number | `PARTNAME` | CONFIRMED [P3][P4] |
| Barcode | `BARCODE` | CONFIRMED [P3][P4] |
| Description (system language; Hebrew in Israeli installs) | `PARTDES` | CONFIRMED [P3][P4] |
| English description | `EPARTDES` (appears in the LOGPART payload, often `null`) | Field CONFIRMED [P4]. The meaning follows Priority's documented "E" convention: `ESTATDES` "adds a description in English" and SEARCH-EDES-FIELD searches "the name/description in English" in non-English systems. CONFIRMED [P15] by analogy |
| Status | `STATDES` (e.g. `"In Use"`) | CONFIRMED [P3][P4]. The list of statuses and which mean "inactive" vary by installation (UNCONFIRMED). New parts default to "active" in the UI [P16] |
| Make/buy type | `TYPE`, one of **`P`/`R`/`O`**. The built-in check says "Specify P (part), R (raw material) or O (other)". The Choose list defines P as a **"Make" item**, and new parts default to **R = raw material** | CONFIRMED [P11][P10][P16]. Mapping R→buy and O→other/non-stock is UNCONFIRMED (an inference) |
| Family code | `FAMILYNAME` (filterable: `LOGPART?$filter=FAMILYNAME eq '001'`). Default family `'0'` | CONFIRMED [P4][P3][P16] |
| Family description on LOGPART | `FAMILYDES`? | UNCONFIRMED. `FAMILY_LOG` uses `FAMILYDESC` [P3]; a third party selects `FAMILYDES` on PART [P20] |
| Internal ids | `PART` (in `FAMILY_LOGPART_SUBFORM`), `EXTPART` (in the LOGPART payload) | Fields CONFIRMED [P3][P4]; meaning UNCONFIRMED |
| Last price | `LASTPRICE` (decimal; e.g. `$filter=TYPE eq 'P' and LASTPRICE gt 200`) | Field CONFIRMED [P4]; meaning (last purchase price?) and currency UNCONFIRMED |
| Buy/sell unit | `UNITNAME`? | UNCONFIRMED. The UI has "Buy/Sell Unit" and "Factory Unit" plus a conversion ratio [P16][P18]. ORDERITEMS uses `UNITNAME`/`TUNITNAME` [P17]. A third party reads `UNITNAME` from LOGPART [P21] |
| Factory (stock) unit | `PUNITNAME`? | UNCONFIRMED. Table `PART` has `PUNIT` and `UNIT`, both joined to `UNIT.UNITNAME` [P14] |
| Preferred (main) vendor | `SUPNAME`? | UNCONFIRMED. The UI has a "Preferred Vendor" (ספק מועדף) column on the General Details tab [P16]. Priority's vendor-code column is `SUPNAME` elsewhere (ORDERITEMS [P17]) |
| Base price | `BASEPLPRICE`? | UNCONFIRMED. The UI has a "base price list price" on the Prices tab [P16] |
| Inventory-managed flag | ? | UNCONFIRMED. The UI has an "inventory managed" checkbox [P16] |
| Revision | `REVNAME`? on PART | UNCONFIRMED. The UI has a part revision on PART [P16]; ORDERITEMS has `REVNAME` [P17] |
| Creation date | ? | UNCONFIRMED |
| Purchase lead time | Probably in form **`PRDPART`** ("Purchase/MRP Parameters for Part") | Form name CONFIRMED [P6]; field UNCONFIRMED |
| Standard cost | Possibly in **`FNCPART`** ("Financial Parameters for Parts"), which has `UDATE` from 25.0 | Form name CONFIRMED [P6][P4]; field UNCONFIRMED |

Stock unit: "inventory is always managed in the factory unit"; the buy/sell setting affects prices only. CONFIRMED [P16] (Hebrew SOP: "ואינה משפיעה על המלאי המנוהל תמיד ביחידת מפעל").

### 1.7 Part families: `FAMILY_LOG`

`FAMILY_LOG` is the Part Families form, keyed by `FAMILYNAME`. A `$batch` example returned these fields: `FAMILYNAME, FAMILYDESC, EFAMILYDES, TECHFLAG, DEBITFLAG, PROJPROCESS, TECHNICIANLOGIN, FTCODE, FTNAME, DISTRFLAG, DUTYPERCENT, DUTYPERCENT1, DUTYPERCENT2, DUTYPERCENTTYPE, SELLFLAG, NEGBALFLAG, FORECAST, PARTNAME, PARTDES, STORAGETYPECODE, STORAGETYPEDES, SERIALMONTHEXPIRY, ISMFAMILY, MFAMILYNAME, MFAMILYDES, INACTIVE, METERFLAG, FAMILY`. CONFIRMED [P5]

The subform `FAMILY_LOGPART_SUBFORM` returns rows of `{"PARTNAME","TYPE","PARTDES","STATDES","PART"}`. CONFIRMED [P3]

### 1.8 Stock per warehouse

| Fact | Status |
|---|---|
| **`WARHSBAL`** ("Warehouse Balances") is a *query form*: read-only, "displays balances per part for the warehouse in question, calculated automatically on the basis of recorded warehouse transactions" | CONFIRMED [P12][P10] |
| It is a sub-level of the warehouse form, linked by `=:WAREHOUSES.WARHS`. The SDK's example condition uses its column **`TBALANCE`** (`>0` to hide zero balances) | CONFIRMED [P12][P10] |
| Form `WAREHOUSES` exists. In the tables, `WARHS` is the internal id and `WARHSNAME` the warehouse code | CONFIRMED [P4][P10] |
| REST path is probably `GET {root}/WAREHOUSES('<WARHSNAME>')/WARHSBAL_SUBFORM` or `WAREHOUSES?$expand=WARHSBAL_SUBFORM`, following the documented `<FORM>_SUBFORM` naming | UNCONFIRMED |
| Two third-party connectors query `WARHSBAL` as a **top-level** entity with fields `PARTNAME`, `WARHSNAME`, `BALANCE` (and `ONORDER`). This conflicts with the SDK's `TBALANCE`, so verify | CONFIRMED-3P [P20][P21] |
| No public source confirms a per-part balance subform under `LOGPART` (names such as `PARTBAL`, `LOGCOUNTERS`) | UNCONFIRMED |

### 1.9 Supplier and supplier part number

| Fact | Status |
|---|---|
| Form **`SUPPLIERPARTS`** exists (a lookup form that gained `UDATE`/`USERLOGIN` in 25.0) | CONFIRMED [P4] |
| Its field names (vendor `SUPNAME`? part `PARTNAME`? vendor's part number?) | UNCONFIRMED |
| Underlying table `SUPPART` links vendor and part (`SUPPART.SUP`, `SUPPART.PART`, `VALIDFLAG = 'Y'`) | CONFIRMED [P15][P10] |
| Vendors form `SUPPLIERS` keyed by `SUPNAME` | CONFIRMED-3P [P20] (the `SUPNAME` naming itself is CONFIRMED on ORDERITEMS [P17]) |

### 1.10 BOM (part tree)

| Fact | Status |
|---|---|
| "the PARTARC form (which stores child parts)" is linked to the `PART` form | CONFIRMED [P13] |
| REST: `GET {root}/PART('<PARTNAME>')?$select=PARTNAME,PARTDES&$expand=PARTARC_SUBFORM` | Subform name CONFIRMED-3P [P20] (and consistent with the `_SUBFORM` convention) |
| Child fields `SONNAME` (child part number, "NOT PARTNAME"), `SONQUANT` (quantity), `SONDES`, `UNITNAME`, `COEF`, `OP`, `TYPE` | CONFIRMED-3P [P20] only |
| Whether `PARTARC` is also under `LOGPART`, and how BOM revisions appear | UNCONFIRMED |

### 1.11 Example requests and responses

```http
GET {root}/LOGPART?$select=PARTNAME,PARTDES,EPARTDES,STATDES,TYPE,FAMILYNAME,LASTPRICE&$orderby=PARTNAME&$top=500&$skip=0
Authorization: Basic base64("<PAT-token>:PAT")
Accept: application/json
```
The shape is CONFIRMED [P4]; the values are illustrative:
```json
{
  "@odata.context": "{root}/$metadata#LOGPART(PARTNAME,PARTDES,EPARTDES,STATDES,TYPE,FAMILYNAME,LASTPRICE)",
  "value": [
    {"PARTNAME": "111-001", "PARTDES": "Sony HT7100DH Home Theater", "EPARTDES": null,
     "STATDES": "In Use", "TYPE": "P", "FAMILYNAME": "001", "LASTPRICE": 233.48}
  ]
}
```
Family to parts by navigation (CONFIRMED [P3]):
```http
GET {root}/FAMILY_LOG('001')/FAMILY_LOGPART_SUBFORM
```
```json
{"@odata.context":"serviceRoot/$metadata#FAMILY_LOG('001')/FAMILY_LOGPART_SUBFORM",
 "value":[{"PARTNAME":"111-001","TYPE":"P","PARTDES":"Sony HT7100DH Home Theater","STATDES":"In Use","PART":18}]}
```
Inline expand. The shape is CONFIRMED [P3][P4]; the subform name below is UNCONFIRMED:
```json
{"@odata.context":"…$metadata#PART/$entity","PARTNAME":"A-100","PARTDES":"…",
 "PARTARC_SUBFORM@odata.context":"…$metadata#PART('A-100')/PARTARC_SUBFORM",
 "PARTARC_SUBFORM":[{"SONNAME":"C-1","SONQUANT":2.0}]}
```

### 1.12 Verification recipe (to turn UNCONFIRMED into CONFIRMED per customer)
1. `GET {root}/LOGPART?$top=1` with no `$select` returns every field the API user may see [P4]. Record them.
2. `GET {root}/GetMetadataFor(entity='LOGPART')` (25.0+). NavigationProperty names are the real subform names; you also get property types and Hebrew descriptions [P3]. If that call is not available, use `$metadata` (large).
3. Repeat for `PART`, `WAREHOUSES`, `SUPPLIERPARTS`, `FNCPART`, `PRDPART`, `FAMILY_LOG`.
4. Priority publishes a public sandbox (root plus demo user and password) in [P1] and a Postman collection [P17]. You could use them for step 1–3. I did not log in.

### 1.13 Simulator notes (Priority)
- **Routes:**
  - Collection: `/odata/Priority/{ini}[,{lang}]/{company}/{FORM}`
  - Single entity: `{FORM}('{key}')` or `{FORM}(K1='a',K2='b')`
  - Subform: `{FORM}('{key}')/{SUB}_SUBFORM`
  - Functions: `GetODataVersion()`, `GetPriorityVersion()`, `GetMetadataFor(entity='X')`, `$metadata`
- **Auth:** Basic. Accept `token:PAT` and `apiuser:password`; anything else gets 401. The 401 status for bad credentials is UNCONFIRMED (standard Basic).
- **Payload:**
  - Return `@odata.context` and `value`.
  - Never omit null fields.
  - Decimals are JSON numbers; dates are `…+02:00`.
- **Paging and query:**
  - Do not emit `@odata.nextLink`.
  - Silently cap rows at `MAXAPILINES` (configurable, default 2000).
  - Support `$top`, `$skip`, `$select`, `$orderby`, and `$filter` with eq/ne/gt/ge/lt/le/and/or/contains/startswith/endswith.
  - Return 400 for `substringof`.
  - Support `$expand` with `;`-separated options.
- **Errors and failure modes:** 404 for unknown forms or keys; optionally 429 above 100 calls/min and 400 "API cannot be run for this form." for forms not enabled.
- Include Hebrew strings in `PARTDES` and English in `EPARTDES` to test RTL handling.

### Sources (Priority)
- [P1] Priority REST API, Introduction: https://prioritysoftware.github.io/restapi/ (service root, MAXAPILINES/MAXFORMLINES, 350 MB cap, X-App-Id/X-App-Key, fair-use limits, transaction counting, HTTP codes)
- [P2] Authenticating: https://prioritysoftware.github.io/restapi/authenticate/
- [P3] Requesting Data: https://prioritysoftware.github.io/restapi/request/
- [P4] Querying Data: https://prioritysoftware.github.io/restapi/query/
- [P5] Modifying Data (error example, `$batch` FAMILY_LOG payload): https://prioritysoftware.github.io/restapi/modify/
- [P6] Removed Forms (form titles: LOGPART "Part Catalogue", PART "Parts", PRDPART, FNCPART): https://prioritysoftware.github.io/restapi/removed-forms/
- [P7] Release notes (22.1 field-level permissions; batch limits): https://prioritysoftware.github.io/restapi/releasenotes/
- [P8] "Working with the Priority REST API" KB LB150473 (Aug 2, 2026): https://cdn.priority-software.com/docs/Priority_OData_API.pdf
- [P9] Hebrew version KB LB150474: https://cdn.priority-software.com/docs/Priority_OData_API_H.pdf
- [P10] Priority SDK PDF: https://cdn.priority-software.com/docs/PrioritySDK.pdf. Covers TYPE CHECK-FIELD `NOT IN ('O','R','P')`; WARHSBAL query form; PARTARC; PUNIT/UNIT; SUPPART; PART/LOGPART on the same base table
- [P11] SDK "Errors and Warnings" and "Creating your Own Triggers" (message "Specify P (part), R (raw material) or O (other)", and `P, "Make" item`): https://prioritysoftware.github.io/sdk/Errors-and-Warnings and https://prioritysoftware.github.io/sdk/Creating-your-Triggers
- [P12] SDK "Forms", "Sub-level Forms" and "Conditions of Record Display" (WARHSBAL, TBALANCE, `=:WAREHOUSES.WARHS`): https://prioritysoftware.github.io/sdk/Forms , https://prioritysoftware.github.io/sdk/Sub-level-Forms , https://prioritysoftware.github.io/sdk/Conditions-Record-Display
- [P13] SDK "Built-in Triggers" (PARTARC stores child parts): https://prioritysoftware.github.io/sdk/Built-in-Triggers
- [P14] SDK "Report Columns" (PART.PUNIT / PART.UNIT joined to UNIT.UNITNAME): https://prioritysoftware.github.io/sdk/Report-Columns
- [P15] SDK "Creating your Own Triggers" (SUPPART query; SEARCH-EDES-FIELD = English) and "BPM Statuses Form" (ESTATDES = English description): https://prioritysoftware.github.io/sdk/Creating-your-Triggers , https://prioritysoftware.github.io/sdk/BPM-Statuses-Form
- [P16] Priority SOP (Hebrew) "פתיחת מק"ט" Cat. LB19000119: https://www.eshbelsaas.co.il/eshbel/primail/library/SOP_Defining%20a%20Part13_H.pdf
- [P17] Official Postman collection: https://documenter.getpostman.com/view/30274649/2sB3QRmRt4 . Raw JSON via https://documenter.gw.postman.com/api/collections/30274649/2sB3QRmRt4 . Contains the ORDERITEMS payload with UNITNAME, SUPNAME, REVNAME, ICODE; composite-key URL `DOCUMENTS_D(DOCNO=…,TYPE=…)`
- [P18] Web SDK example (LOGPART, CHUNIT "Factory Unit" / "Buy/Sell Unit"): https://prioritysoftware.github.io/api/form_examples/
- [P19] Priority MCP server, Tools Reference (no truncation indicator): https://prioritysoftware.github.io/mcp/tools/
- [P20] 3rd-party: priority-mcp/priority-odata-mcp (README "Known Limitations"; `src/resources/subform-reference-resource.js`, `common-queries-resource.js`, `src/priority/client.js`): https://github.com/priority-mcp/priority-odata-mcp
- [P21] 3rd-party: justinholtweb/craft-erpy-priority `src/connectors/PriorityConnector.php`: https://github.com/justinholtweb/craft-erpy-priority
- [P22] 3rd-party: HirezRa/n8n-nodes-priority (docs mention LOGPART `ONHAND`/`MINBAL`; unreliable, not used for any claim): https://github.com/HirezRa/n8n-nodes-priority
- [P23] 3rd-party: Power BI forum, "API cannot be run for this form": https://community.fabric.microsoft.com/t5/Desktop/OData-Error-in-Power-BI-API-Cannot-Be-Run-for-This-Form-400-Bad/m-p/4323037
- [P24] 3rd-party: Procee wiki, Priority API (Zoom has no API): https://he.procee.com/wiki/priority-api/

---

## 2. SAP S/4HANA (Cloud and on-premise): OData APIs

### 2.1 Services and entity sets

| Need | Service | Service root (path) | Main entity sets | Status |
|---|---|---|---|---|
| Product master | `API_PRODUCT_SRV` (OData v2) | `/sap/opu/odata/sap/API_PRODUCT_SRV` | `A_Product`, `A_ProductDescription`, `A_ProductPlant`, `A_ProductSupplyPlanning`, `A_ProductValuation`, `A_ProductUnitsOfMeasure`, `A_ProductStorageLocation`, `A_ProductBasicText`, … | CONFIRMED [S1][S6] |
| Stock | `API_MATERIAL_STOCK_SRV` (v2) | `/sap/opu/odata/sap/API_MATERIAL_STOCK_SRV` | `A_MaterialStock`, `A_MatlStkInAcctMod` | CONFIRMED [S2] |
| BOM | `API_BILL_OF_MATERIAL_SRV;v=0002` (v2) | `/sap/opu/odata/sap/API_BILL_OF_MATERIAL_SRV;v=0002` | `MaterialBOM`, `MaterialBOMItem`, `MaterialBOMSubItem`, `MBOMItmObjDpnAssignment`, `A_BillOfMaterialUsage`, `A_BOMItemCategory` | CONFIRMED [S3][S14] |
| Purchasing info records | `API_INFORECORD_PROCESS_SRV` (v2) | `/sap/opu/odata/sap/API_INFORECORD_PROCESS_SRV` | `A_PurchasingInfoRecord`, `A_PurgInfoRecdOrgPlantData`, `A_PurInfoRecdPrcgCndnValidity`, `A_PurInfoRecdPrcgCndn`, `A_PurInfoRecdSuplmntPrcgCndn` | CONFIRMED [S4] |
| Product (new) | `api_product` (OData v4) | `/sap/opu/odata4/sap/api_product/srvd_a2x/sap/product/0002/` | `Product`, `ProductDescription` (navigation `_ProductDescription`) | CONFIRMED [S12][S13] |

All `API_PRODUCT_SRV` entity sets: `A_Product, A_ProductBasicText, A_ProductDescription, A_ProductInspectionText, A_ProductMLAccount, A_ProductMLPrices, A_ProductPlant, A_ProductPlantCosting, A_ProductPlantForecasting, A_ProductPlantIntlTrd, A_ProductPlantMRPArea, A_ProductPlantProcurement, A_ProductPlantQualityMgmt, A_ProductPlantSales, A_ProductPlantStorage, A_ProductPlantText, A_ProductProcurement, A_ProductPurchaseText, A_ProductQualityMgmt, A_ProductSales, A_ProductSalesDelivery, A_ProductSalesTax, A_ProductSalesText, A_ProductStorage, A_ProductStorageLocation, A_ProductSupplyPlanning, A_ProductUnitsOfMeasure, A_ProductUnitsOfMeasureEAN, A_ProductValuation, A_ProductValuationAccount, A_ProductValuationCosting, A_ProductWorkScheduling`. CONFIRMED [S1]

Note on [S1]–[S5]: these are SAP-published SAP Cloud SDK "VDM" npm packages (v2.1.0, now deprecated). Each contains a `*-csn.json` schema generated from the service EDMX, which is the source of every property name, type and length below. Newer S/4HANA releases may *add* properties. The on-prem package differs from the cloud one for `A_Product` only by the cloud-only `DocumentIsCreatedByCAD`. CONFIRMED [S1][S5]

### 2.2 URL, authentication, headers

| Fact | Status |
|---|---|
| On-prem server URL template `https://{host}:{port}/sap/opu/odata/sap/API_PRODUCT_SRV`. Authentication methods "Basic, x509" | CONFIRMED [S6] |
| S/4HANA Cloud inbound authentication for communication arrangements: `BasicAuthentication`, `OAuth2SAMLBearerAssertion`, `ClientCertificateAuthentication`. For a server-side tool, use a **communication user** with Basic (or a client certificate) | CONFIRMED [S10] |
| Cloud API access goes through a **communication arrangement** for the API's **communication scenario**. Without it, calls fail with "You do not have start authorization for R3TR IWSV API_PRODUCT_SRV". The product API's scenario is **SAP_COM_0009** | CONFIRMED-3P [S11] (SAP help page "Product Integration (SAP_COM_0009)" exists but was not fetchable) |
| Scenario for `API_MATERIAL_STOCK_SRV`: **SAP_COM_0164** "Material Stock Integration" | UNCONFIRMED (only a help.sap.com page title seen in search results) |
| Scenario IDs for BOM and info-record APIs | UNCONFIRMED. Look them up on api.sap.com under the API's "Communication Scenario" |
| Cloud host: use the URL shown in the communication arrangement. The usual pattern is `https://my<NNNNNN>-api.s4hana.cloud.sap` | UNCONFIRMED |
| **CSRF is only for modifying requests.** The SAP Cloud SDK fetches a CSRF token "To create, update, and delete requests". The flow is: send `X-CSRF-Token: Fetch` on a GET, then echo the token on POST/PUT/PATCH/MERGE/DELETE; otherwise the server returns 403 with `X-CSRF-Token: Required`. A read-only connector never needs it | CONFIRMED [S9][S12] |
| `sap-client`: the SAP Cloud SDK sends it as an HTTP **header** `sap-client: NNN` when configured. The `?sap-client=NNN` URL parameter is UNCONFIRMED (widely used). It matters only for multi-client on-prem systems | CONFIRMED [S9] |
| `sap-language` header controls the language of messages and texts | CONFIRMED [S9] |
| JSON: add `$format=json`. In OData v2, `$format` overrides `Accept`. Gateway's default (Atom/XML) when neither is sent is UNCONFIRMED, so always send `$format=json` and `Accept: application/json` | CONFIRMED [S15][S8] |

### 2.3 OData v2 JSON wire format (for connectors and simulators)

| Fact | Status |
|---|---|
| Everything is wrapped in `{"d": …}` | CONFIRMED [S7] |
| A collection is `{"d": {"results": [ … ], "__count": "1234", "__next": "…$skiptoken=…"}}` | CONFIRMED [S6][S7] |
| `__count` is a **string**, present only with `$inlinecount=allpages` (`allpages`\|`none`) | CONFIRMED [S6][S7] |
| `__next` (a URI) appears only under server-driven paging. The SAP Cloud SDK follows `$skiptoken` next links automatically, and a third-party guide says v2 returns `__next` while v4 returns `@odata.nextLink`. Whether each of these A2X services enforces a server page size is UNCONFIRMED | CONFIRMED [S7][S9][S12] |
| A single entity is `{"d": { …entity… }}` | CONFIRMED [S7] |
| Each entry carries `"__metadata": {"id": "…", "uri": "https://host/sap/opu/odata/sap/API_PRODUCT_SRV/A_Product('66')", "type": "API_PRODUCT_SRV.A_ProductType"}`. `uri` and `type` are required by the spec [S7]; `id` is seen in a real-system client [S14]; the type naming `<SERVICE>.<Entity>Type` matches the spec's schema names [S6] | CONFIRMED [S7] / CONFIRMED-3P [S14] |
| A navigation property that is not expanded comes back as `"to_Description": {"__deferred": {"uri": ".../A_Product('66')/to_Description"}}`. An expanded collection comes back as `"to_Description": {"results": [ … ]}` | CONFIRMED [S7][S6] / CONFIRMED-3P [S14] |
| Date (`Edm.DateTime`) is `"/Date(1492041600000)/"` (ms since 1970). SAP uses the same form for timestamps, e.g. `LastChangeDateTime: "/Date(1492098664000)/"`; the spec also allows `+offset`. Nullable values come back as `null` | CONFIRMED [S6][S7] |
| `Edm.Decimal` is a **JSON string** (`"GrossWeight": "0.000"`, `"StandardPrice": "12.340"`). Booleans are `true`/`false`. Int16/Int32 are JSON numbers. Int64 and Double are strings | CONFIRMED [S6][S7] |
| Error body: `{"error":{"code":"…","message":{"lang":"en","value":"…"},"innererror":{…}}}` | CONFIRMED [S6] |

Paging approach:
- Client-driven paging with `$top` (integer ≥ 0) and `$skip`, plus `$inlinecount`, `$orderby`, `$filter`, `$select` and `$expand`, is in the spec. CONFIRMED [S6]
- Recommended loop (UNCONFIRMED, defensive): send `$top=N&$skip=k*N&$orderby=<key>`; if `d.__next` exists, follow it instead. No documented maximum `$top` was found (UNCONFIRMED), so 1,000–5,000 is a reasonable range.
- Combining `$select` with `$expand`: list the navigation property inside `$select`, e.g. `$select=Product,ProductType,to_Description&$expand=to_Description`. CONFIRMED (OData v2 rule [S8])

### 2.4 `A_Product` (key `Product`)

| Audit field | Property (type) | Status |
|---|---|---|
| Part number | `Product` String(40) | CONFIRMED [S1][S6] |
| Type | `ProductType` String(4). Sample value `"NLAG"` [S14]. Meanings such as FERT/HALB/ROH are UNCONFIRMED | CONFIRMED [S1] |
| Group / family | `ProductGroup` String(9) ("Product Group"), `ProductHierarchy` String(18) | CONFIRMED [S1][S6] |
| Base unit | `BaseUnit` String(3). Sample values `"KG"`, `"PC"` (external code style) [S14] | CONFIRMED [S1] |
| Status | `CrossPlantStatus` String(2) ("Cross-Plant Product Status", customer-defined codes), `CrossPlantStatusValidityDate`, `IsMarkedForDeletion` Boolean | CONFIRMED [S1][S6] |
| Old part number | `ProductOldID` String(40) | CONFIRMED [S1][S6] |
| Revision | `MaterialRevisionLevel` String(2) ("Revision Level"), `ChangeNumber` String(12) | CONFIRMED [S1][S6] |
| Created / changed | `CreationDate`, `CreatedByUser`, `LastChangeDate`, `LastChangedByUser`, `LastChangeDateTime` | CONFIRMED [S1] |
| Weights | `GrossWeight`, `NetWeight` Decimal(13,3), `WeightUnit` | CONFIRMED [S1] |
| Manufacturer part | `ProductManufacturerNumber` String(40), `ManufacturerNumber` String(10) | CONFIRMED [S1] |
| Purchasing unit | `PurchaseOrderQuantityUnit` String(3) | CONFIRMED [S1] |

Full `A_Product` property list (CONFIRMED [S1]): `Product:String(40)`, `ProductType:String(4)`, `CrossPlantStatus:String(2)`, `CrossPlantStatusValidityDate:Date`, `CreationDate:Date`, `CreatedByUser:String(12)`, `LastChangeDate:Date`, `LastChangedByUser:String(12)`, `LastChangeDateTime:Timestamp`, `IsMarkedForDeletion:Boolean`, `ProductOldID:String(40)`, `GrossWeight:Decimal(13,3)`, `PurchaseOrderQuantityUnit:String(3)`, `SourceOfSupply:String(1)`, `WeightUnit:String(3)`, `NetWeight:Decimal(13,3)`, `CountryOfOrigin:String(3)`, `CompetitorID:String(10)`, `ProductGroup:String(9)`, `BaseUnit:String(3)`, `ItemCategoryGroup:String(4)`, `ProductHierarchy:String(18)`, `Division:String(2)`, `VarblPurOrdUnitIsActive:String(1)`, `VolumeUnit:String(3)`, `MaterialVolume:Decimal(13,3)`, `ANPCode:String(9)`, `Brand:String(4)`, `ProcurementRule:String(1)`, `ValidityStartDate:Date`, `LowLevelCode:String(3)`, `ProdNoInGenProdInPrepackProd:String(40)`, `SerialIdentifierAssgmtProfile:String(4)`, `SizeOrDimensionText:String(32)`, `IndustryStandardName:String(18)`, `ProductStandardID:String(18)`, `InternationalArticleNumberCat:String(2)`, `ProductIsConfigurable:Boolean`, `IsBatchManagementRequired:Boolean`, `ExternalProductGroup:String(18)`, `CrossPlantConfigurableProduct:String(40)`, `SerialNoExplicitnessLevel:String(1)`, `ProductManufacturerNumber:String(40)`, `ManufacturerNumber:String(10)`, `ManufacturerPartProfile:String(4)`, `QltyMgmtInProcmtIsActive:Boolean`, `IndustrySector:String(1)`, `ChangeNumber:String(12)`, `MaterialRevisionLevel:String(2)`, `HandlingIndicator:String(4)`, `WarehouseProductGroup:String(4)`, `WarehouseStorageCondition:String(2)`, `StandardHandlingUnitType:String(4)`, `SerialNumberProfile:String(4)`, `AdjustmentProfile:String(3)`, `PreferredUnitOfMeasure:String(3)`, `IsPilferable:Boolean`, `IsRelevantForHzdsSubstances:Boolean`, `QuarantinePeriod:Decimal(3,0)`, `TimeUnitForQuarantinePeriod:String(3)`, `QualityInspectionGroup:String(4)`, `AuthorizationGroup:String(4)`, `DocumentIsCreatedByCAD:Boolean` (cloud only), `HandlingUnitType:String(4)`, `HasVariableTareWeight:Boolean`, `MaximumPackagingLength:Decimal(15,3)`, `MaximumPackagingWidth:Decimal(15,3)`, `MaximumPackagingHeight:Decimal(15,3)`, `UnitForMaxPackagingDimensions:String(3)`.

Navigation properties: `to_Description` (many), `to_Plant` (many), `to_ProductBasicText` (many), `to_ProductInspectionText` (many), `to_ProductProcurement` (one), `to_ProductPurchaseText` (many), `to_ProductQualityMgmt` (one), `to_ProductSales` (one), `to_ProductSalesTax` (many), `to_ProductStorage` (one), `to_ProductUnitsOfMeasure` (many), `to_SalesDelivery` (many), `to_Valuation` (many). CONFIRMED [S1][S6]

Documented GET paths (CONFIRMED [S6]):
- `/A_Product`
- `/A_Product('{Product}')`
- `/A_Product('{Product}')/to_Description`, `/to_Plant`, `/to_Valuation`, `/to_ProductUnitsOfMeasure`, …
- `/A_ProductDescription`
- `/A_ProductDescription(Product='{Product}',Language='{Language}')`
- `/A_ProductPlant(Product='{Product}',Plant='{Plant}')`
- `/A_ProductPlant(...)/to_ProductSupplyPlanning`
- `/A_ProductValuation`
- `/A_ProductValuation(Product='{Product}',ValuationArea='{ValuationArea}',ValuationType='{ValuationType}')`

### 2.5 Descriptions (Hebrew and English)

| Fact | Status |
|---|---|
| `A_ProductDescription` has keys `Product` String(40) and `Language` String(2) ("Language Key"), and property `ProductDescription` String(40). It is reachable as the top-level set or via `to_Description` | CONFIRMED [S1][S6] |
| Language values are 2-character codes. A real integration filters with `Language eq 'JA'`, so Hebrew is probably `'HE'` and English `'EN'` | CONFIRMED-3P [S14] / `'HE'` UNCONFIRMED |
| Bulk read: `GET …/A_ProductDescription?$filter=Language eq 'HE' or Language eq 'EN'&$top=5000&$skip=0&$format=json` | Syntax standard; behaviour UNCONFIRMED |
| Long text: `A_ProductBasicText` (keys `Product`, `Language`; `LongText`) | CONFIRMED [S1] |

### 2.6 Plant data: make/buy, lead time

| Fact | Status |
|---|---|
| `A_ProductPlant` (keys `Product`, `Plant`) includes `ProcurementType` String(1), `MRPType`, `PurchasingGroup`, `ProfitCenter`, `MaintenanceStatusName`, `IsMarkedForDeletion`, `BaseUnit`, … | CONFIRMED [S1] |
| `A_ProductSupplyPlanning` (via `to_ProductSupplyPlanning`; keys `Product`, `Plant`) includes `PlannedDeliveryDurationInDays` Decimal(3,0) (purchase lead time), `InHouseProductionTime`, `TotalReplenishmentLeadTime`, `ProcurementType`, `ProcurementSubType`, `SafetyStockQuantity`, `MinimumLotSizeQuantity`, … | CONFIRMED [S1] |
| `ProcurementType` values `E` (in-house = make), `F` (external = buy), `X` (both) | UNCONFIRMED (standard SAP values, not in any reachable doc) |

`A_ProductPlant` properties (CONFIRMED [S1]): `Product, Plant, PurchasingGroup, CountryOfOrigin, RegionOfOrigin, ProductionInvtryManagedLoc, ProfileCode, ProfileValidityStartDate, AvailabilityCheckType, FiscalYearVariant, PeriodType, ProfitCenter, Commodity, GoodsReceiptDuration, MaintenanceStatusName, IsMarkedForDeletion, MRPType, MRPResponsible, ABCIndicator, MinimumLotSizeQuantity, MaximumLotSizeQuantity, FixedLotSizeQuantity, ConsumptionTaxCtrlCode, IsCoProduct, ProductIsConfigurable, StockDeterminationGroup, StockInTransferQuantity, StockInTransitQuantity, HasPostToInspectionStock, IsBatchManagementRequired, SerialNumberProfile, IsNegativeStockAllowed, GoodsReceiptBlockedStockQty, HasConsignmentCtrl, FiscalYearCurrentPeriod, FiscalMonthCurrentPeriod, ProcurementType, IsInternalBatchManaged, ProductCFOPCategory, ProductIsExciseTaxRelevant, BaseUnit, ConfigurableProduct, GoodsIssueUnit, MaterialFreightGroup, OriginalBatchReferenceMaterial, OriglBatchManagementIsRequired, ProductIsCriticalPrt, ProductLogisticsHandlingGroup`. Its navigation properties are `to_PlantMRPArea, to_PlantQualityMgmt, to_PlantSales, to_PlantStorage, to_PlantText, to_ProdPlantInternationalTrade, to_ProductPlantCosting, to_ProductPlantForecast, to_ProductPlantProcurement, to_ProductSupplyPlanning, to_ProductWorkScheduling, to_StorageLocation`.

### 2.7 Cost: `A_ProductValuation`

| Fact | Status |
|---|---|
| Keys: `Product`, `ValuationArea` String(4), `ValuationType` String(10) | CONFIRMED [S1][S6] |
| `StandardPrice` and `MovingAveragePrice` Decimal(12,3) (`MovingAveragePrice` = "Moving Average Price/Periodic Unit Price"); `PriceUnitQty` Decimal(5,0) ("Price unit"); `Currency` String(5); `InventoryValuationProcedure` String(1) ("Price Control"); `PriceDeterminationControl`; `PriceLastChangeDate`; `PlannedPrice`; `ValuationClass`; `BaseUnit`; `IsMarkedForDeletion` | CONFIRMED [S1][S6] |
| Unit cost = `StandardPrice / PriceUnitQty` (the price applies per `PriceUnitQty` base units) | UNCONFIRMED (follows from the "Price unit" label) |
| Price-control values `S` (standard) and `V` (moving average) | UNCONFIRMED |
| `ValuationArea` usually equals the plant. `ValuationType` is `''` for materials without split valuation, so the key is `(…,ValuationType='')` | UNCONFIRMED |

### 2.8 Stock: `API_MATERIAL_STOCK_SRV`

| Fact | Status |
|---|---|
| `A_MaterialStock` has key `Material`, property `MaterialBaseUnit`, and navigation `to_MatlStkInAcctMod` | CONFIRMED [S2] |
| `A_MatlStkInAcctMod` has an **11-part key**: `Material, Plant, StorageLocation, Batch, Supplier, Customer, WBSElementInternalID, SDDocument, SDDocumentItem, InventorySpecialStockType, InventoryStockType`. Properties: `MaterialBaseUnit` String(3) and `MatlWrhsStkQtyInMatlBaseUnit` Decimal(31,14) | CONFIRMED [S2] |
| Example query: `GET /sap/opu/odata/sap/API_MATERIAL_STOCK_SRV/A_MatlStkInAcctMod?$filter=Material eq '21' and Plant eq '0001' and StorageLocation eq '0001'` | CONFIRMED-3P [S14] |
| Sample row from a real system (reformatted by the sample tool): `Material "21"`, `Plant "0001"`, `StorageLocation "0001"`, `Batch ""`, `Supplier ""`, `Customer ""`, `WBSElementInternalID "000000000000000000000000"`, `SDDocument ""`, `SDDocumentItem "0"`, `InventorySpecialStockType ""`, `InventoryStockType "01"`, `MaterialBaseUnit "PC"`, `MatlWrhsStkQtyInMatlBaseUnit "10"` | CONFIRMED-3P [S14] |
| Rows are split by stock type and special stock. "On hand per warehouse" means summing by `Plant` (and `StorageLocation`) for the chosen `InventoryStockType` values. The code meanings (`01` unrestricted, `02` quality inspection, `07` blocked, …) are UNCONFIRMED; SAP's "Inventory Stock Type" help page was not fetchable | Aggregation rule UNCONFIRMED (business decision) |

### 2.9 BOM: `API_BILL_OF_MATERIAL_SRV;v=0002`

| Fact | Status |
|---|---|
| The `;v=0002` matrix parameter is part of the service path | CONFIRMED [S3][S14] |
| `MaterialBOM` has a **7-part key**: `BillOfMaterial` String(8), `BillOfMaterialCategory` String(1), `BillOfMaterialVariant` String(2), `BillOfMaterialVersion` String(4), `EngineeringChangeDocument` String(12), `Material` String(40), `Plant` String(4). Useful properties: `BillOfMaterialVariantUsage`, `BOMHeaderBaseUnit`, `BOMHeaderQuantityInBaseUnit`, `HeaderValidityStartDate`, `HeaderValidityEndDate`, `BillOfMaterialStatus`, `IsMarkedForDeletion`, `ProductDescription`, `PlantName`, `LastChangeDateTime`. Navigation: `to_BillOfMaterialItem` (many) | CONFIRMED [S3] |
| `MaterialBOMItem` has an **8-part key**: the header keys plus `BillOfMaterialItemNodeNumber` and `HeaderChangeDocument`. Main properties: **`BillOfMaterialComponent`** String(40) (child), **`BillOfMaterialItemQuantity`** Decimal(13,3), **`BillOfMaterialItemUnit`** String(3), `BillOfMaterialItemNumber` String(4), `BillOfMaterialItemCategory`, `ComponentDescription`, `ValidityStartDate`, `ValidityEndDate`, `IsDeleted`, `ComponentScrapInPercent`, `FixedQuantity`, `IsAssembly`, `SpecialProcurementType`, `LastChangeDateTime`. Navigation: `to_BillOfMaterial`, `to_BOMSubItems` | CONFIRMED [S3] |
| Queries used against a real system: `MaterialBOM?$filter=Material eq '21' and Plant eq '0001'`, `MaterialBOMItem?$filter=Material eq '21' and Plant eq '0001'`, and where-used `MaterialBOMItem?$filter=Plant eq '0001' and BillOfMaterialComponent eq '72'` | CONFIRMED-3P [S14] |
| Sample values: `BillOfMaterial "00000001"`, `BillOfMaterialVariant "1"`, `BillOfMaterialCategory "M"`, `ValidityEndDate` 9999-12-31, `BillOfMaterialItemQuantity "3"`, `ComponentScrapInPercent "0.00"` | CONFIRMED-3P [S14] |
| The schema includes boolean control properties ending `_ac`, `_mc`, `_oc` (e.g. `Delete_mc`, `Update_mc`, `to_BillOfMaterialItem_oc`) | CONFIRMED [S3] (whether they appear in payloads is UNCONFIRMED) |
| Component quantity is per `BOMHeaderQuantityInBaseUnit` of the parent. Filter by usage (production is commonly `'1'`) and the current validity window; several alternatives (`BillOfMaterialVariant`) may exist | UNCONFIRMED |

### 2.10 Supplier and supplier part number: `API_INFORECORD_PROCESS_SRV`

| Fact | Status |
|---|---|
| `A_PurchasingInfoRecord` (key `PurchasingInfoRecord` String(10)) has `Supplier`, `Material`, `MaterialGroup`, **`SupplierMaterialNumber`** String(35), `IsRegularSupplier` Boolean, `IsDeleted`, `PurgDocOrderQuantityUnit`, `BaseUnit`, `Manufacturer`, `CreationDate`, `LastChangeDateTime`, `PurchasingInfoRecordDesc`, `AvailabilityStartDate`, `AvailabilityEndDate`. Navigation: `to_PurgInfoRecdOrgPlantData` (many) | CONFIRMED [S4] |
| `A_PurgInfoRecdOrgPlantData` (keys `PurchasingInfoRecord`, `PurchasingInfoRecordCategory`, `PurchasingOrganization`, `Plant`) has **`NetPriceAmount`** Decimal(12,3), `MaterialPriceUnitQty`, **`Currency`**, `PurchaseOrderPriceUnit`, `NetPriceQuantityUnit`, **`MaterialPlannedDeliveryDurn`** (lead time in days), `MinimumPurchaseOrderQuantity`, `StandardPurchaseOrderQuantity`, `PriceValidityEndDate`, `IsMarkedForDeletion`, `Supplier`, `Material` | CONFIRMED [S4] |
| Example: `GET …/A_PurchasingInfoRecord?$filter=Material eq '21'&$expand=to_PurgInfoRecdOrgPlantData&$format=json`. Sample: `PurchasingInfoRecord "5300000000"`, `Supplier "100000"`, `SupplierMaterialNumber "TEST SUPPLIER MATERIAL NO"` | Nav name CONFIRMED [S4]; filter pattern and sample CONFIRMED-3P [S14] |
| "Main supplier" has no single field in these APIs. Candidates: an info record with `IsRegularSupplier = true` (the field is CONFIRMED [S4]; the semantics are UNCONFIRMED), a source-list API (not researched), or the most recent info record. This is a business rule to decide | UNCONFIRMED |

### 2.11 OData v4 Product API (brief)

| Fact | Status |
|---|---|
| Root: `/sap/opu/odata4/sap/api_product/srvd_a2x/sap/product/0002/`. Entity sets `Product` and `ProductDescription`; navigation `_ProductDescription`. Example: `Product(Product='X')?$expand=_ProductDescription($filter=Language eq 'EN')` | CONFIRMED [S13][S12] |
| Paging uses `@odata.nextLink` | CONFIRMED [S12] |
| The response root is `{"@odata.context": …, "value": [ … ]}` | UNCONFIRMED for this service (OData v4 standard) |
| Other entity names (plant, valuation), and whether `API_PRODUCT_SRV` is deprecated | UNCONFIRMED. Check `$metadata` and api.sap.com |

### 2.12 Example request and response (SAP v2)

```http
GET /sap/opu/odata/sap/API_PRODUCT_SRV/A_Product?$select=Product,ProductType,ProductGroup,BaseUnit,CrossPlantStatus,IsMarkedForDeletion,ProductOldID,MaterialRevisionLevel,CreationDate,LastChangeDateTime,to_Description&$expand=to_Description&$orderby=Product&$top=1000&$skip=0&$inlinecount=allpages&$format=json
Authorization: Basic base64("<comm_user>:<password>")
Accept: application/json
sap-client: 100            (on-prem multi-client only)
```
The shape is CONFIRMED [S6][S7]; the values are illustrative:
```json
{"d": {
  "__count": "2",
  "results": [
    {"__metadata": {"id": "https://host/sap/opu/odata/sap/API_PRODUCT_SRV/A_Product('TG11')",
                    "uri": "https://host/sap/opu/odata/sap/API_PRODUCT_SRV/A_Product('TG11')",
                    "type": "API_PRODUCT_SRV.A_ProductType"},
     "Product": "TG11", "ProductType": "FERT", "ProductGroup": "L001", "BaseUnit": "PC",
     "CrossPlantStatus": "", "IsMarkedForDeletion": false, "ProductOldID": "", "MaterialRevisionLevel": "",
     "CreationDate": "/Date(1492041600000)/", "LastChangeDateTime": "/Date(1492098664000)/",
     "to_Description": {"results": [
        {"__metadata": {"type": "API_PRODUCT_SRV.A_ProductDescriptionType", "uri": "…/A_ProductDescription(Product='TG11',Language='EN')"},
         "Product": "TG11", "Language": "EN", "ProductDescription": "Trading good 11"}]}}
  ]
}}
```
Valuation for one product: `GET …/A_Product('TG11')/to_Valuation?$select=ValuationArea,ValuationType,StandardPrice,MovingAveragePrice,PriceUnitQty,Currency,InventoryValuationProcedure&$format=json`. Here `StandardPrice` comes back as a string, e.g. `"10.000"`.

### 2.13 Gotchas (SAP S/4HANA)
- **Material number format.** Numeric material numbers appear without leading zeros in a sample (`"21"`) [S14] (CONFIRMED-3P). Filter values must use the same external form (UNCONFIRMED).
- **Unit codes.** Units appear in commercial/external form (`"PC"`, `"KG"`) [S14] (CONFIRMED-3P). The internal code may differ (UNCONFIRMED).
- **Select explicitly.** `A_Product` has about 70 properties and `MaterialBOMItem` about 100.
- **Value encodings.** Decimals are strings and dates are `/Date(ms)/` [S6][S7]. Parse `/Date(ms[+-mmmm])/` robustly, and do not use floats for money.
- **Authorization.** On-prem services must be activated in Gateway and the user authorised for the IWSV service (UNCONFIRMED procedure). The authorization error text is CONFIRMED-3P [S11]. In the cloud, access is only through a communication arrangement with a communication user [S10][S11].
- **Rate limits.** None publicly documented (UNCONFIRMED).

### 2.14 Simulator notes (SAP)
- **Routes:**
  - Collections: `/sap/opu/odata/sap/{SERVICE}[;v=0002]/{EntitySet}`
  - Keys: `('{k}')` and `(K1='a',K2='b')`
  - Navigation: `/{nav}`
  - Metadata: `$metadata` (an EDMX stub is enough)
- **Query options:** support `$select`, `$filter` (eq/ne/gt/lt/ge/le/and/or, `substringof`), `$top`, `$skip`, `$orderby`, `$inlinecount=allpages`, `$expand`, and `$format=json`.
- **Wire format:**
  - Collections are `{"d":{"results":[…]}}` with `__metadata` on every entry; `__count` is a string.
  - Navigation that is not expanded is `__deferred`.
  - Decimals are strings; dates are `/Date(ms)/`.
  - Errors are `{"error":{"code","message":{"lang","value"}}}`.
- **Server-driven paging:** optionally enable it by returning `__next` with `$skiptoken`, so connectors are tested both ways.
- **CSRF:** reply to `X-CSRF-Token: Fetch` with a token header; reject non-GET requests without a token with 403 `X-CSRF-Token: Required`.
- **Prior art:** `rseufert/mock-sap` (MIT, stdlib Python) already emits SAP v2 wire shapes (`{"d":{"results"…}}`, `__metadata`, `__deferred`, `/Date()/`, decimal strings, CSRF) and includes a partial `API_PRODUCT_SRV`. Not vendor-verified. [S16]

### Sources (SAP S/4HANA)
- [S1] SAP Cloud SDK VDM `@sap/cloud-sdk-vdm-product-service` 2.1.0 (SAP-published; files `product-service-csn.json`, `*Api.js` with `_defaultServicePath`/`_entityName`): https://registry.npmjs.org/@sap/cloud-sdk-vdm-product-service/-/cloud-sdk-vdm-product-service-2.1.0.tgz
- [S2] `@sap/cloud-sdk-vdm-material-stock-service` 2.1.0: https://registry.npmjs.org/@sap/cloud-sdk-vdm-material-stock-service/-/cloud-sdk-vdm-material-stock-service-2.1.0.tgz
- [S3] `@sap/cloud-sdk-vdm-bill-of-material-v2-service` 2.1.0: https://registry.npmjs.org/@sap/cloud-sdk-vdm-bill-of-material-v2-service/-/cloud-sdk-vdm-bill-of-material-v2-service-2.1.0.tgz
- [S4] `@sap/cloud-sdk-vdm-purchasing-info-record-service` 2.1.0: https://registry.npmjs.org/@sap/cloud-sdk-vdm-purchasing-info-record-service/-/cloud-sdk-vdm-purchasing-info-record-service-2.1.0.tgz
- [S5] `@sap/cloud-sdk-op-vdm-product-service` 2.1.0 (on-prem): https://registry.npmjs.org/@sap/cloud-sdk-op-vdm-product-service/-/cloud-sdk-op-vdm-product-service-2.1.0.tgz
- [S6] SAP OpenAPI spec "Product Master (A2X)" `OP_API_PRODUCT_SRV_0001`, S/4HANA on-prem 2021 (SAP artifact re-hosted in a public repo): https://github.com/latonaio/sap-api-integrations-product-master-reads/blob/main/OP_API_PRODUCT_SRV_0001_format.json (original page https://api.sap.com/api/OP_API_PRODUCT_SRV_0001/overview, not fetched)
- [S7] OData v2 JSON format: https://www.odata.org/documentation/odata-version-2-0/json-format/
- [S8] OData v2 URI conventions (`$select`/`$expand`, `$format` precedence, `$inlinecount`): https://www.odata.org/documentation/odata-version-2-0/uri-conventions/
- [S9] SAP Cloud SDK docs (GitHub source):
  - CSRF: https://github.com/SAP/cloud-sdk/blob/main/docs-js/features/common/csrf-token.mdx
  - `sap-client` header: https://github.com/SAP/cloud-sdk/blob/main/docs-js/features/connectivity/destination.mdx
  - `sap-client`/`sap-language` headers: https://github.com/SAP/cloud-sdk/blob/main/docs-java/features/connectivity/004-http-destinations.mdx
  - Server-driven paging: https://github.com/SAP/cloud-sdk/blob/main/docs-java/features/odata/v2-client.mdx
- [S10] SAP BTP docs (SAP-docs GitHub), inbound authentication types: https://github.com/SAP-docs/btp-cloud-platform/blob/main/docs/40-extensions/create-a-service-instance-to-consume-the-sap-s-4hana-cloud-apis-a735641.md and https://github.com/SAP-docs/btp-cloud-platform/blob/main/docs/40-extensions/communication-arrangement-json-yaml-file-properties-553a4c6.md
- [S11] 3rd-party: DevDiary, communication users and SAP_COM_0009: https://devdiary.ch/2024/12/02/how-to-authorize-communication-users-in-sap-s-4hana-cloud-public-edition/
- [S12] 3rd-party: Cleo, "API-related Information – SAP S4HANA" (v2 `__next` vs v4 `@odata.nextLink`, CSRF flow, v4 product path): https://support.cleo.com/hc/en-us/articles/19955468388759-API-related-Information-SAP-S4HANA
- [S13] SAP Community Q&A, v4 product API `Product`/`ProductDescription`/`_ProductDescription`: https://community.sap.com/t5/technology-q-a/accessing-product-description-in-value-help-using-sap-api-product-srvd-a2x/qaq-p/14070770
- [S14] 3rd-party real-system samples (latonaio, Go): https://github.com/latonaio/sap-api-integrations-product-master-reads , https://github.com/latonaio/sap-api-integrations-material-stock-reads , https://github.com/latonaio/sap-api-integrations-bill-of-material-reads , https://github.com/latonaio/sap-api-integrations-purchasing-info-record-reads
- [S15] SAP Learning, "Explaining Open Data Protocol" (`$format=json`): https://learning.sap.com/courses/building-odata-services-with-sap-gateway/explaining-open-data-protocol-odata-
- [S16] 3rd-party mock: https://github.com/rseufert/mock-sap

---

## 3. SAP Business One Service Layer

### 3.1 Endpoints and OData versions

| Fact | Status |
|---|---|
| Base URL `https://<server>:<port>/b1s/<version>/`, e.g. `https://databaseserver:50000/b1s/v1/Items`. "Service layer supports HTTPS by default" | CONFIRMED [B1] |
| `/b1s/v1` is **OData v3**; `/b1s/v2` is **OData v4**. Metadata is at `/b1s/v1/$metadata` and `/b1s/v2/$metadata` | CONFIRMED [B1] |
| OData v1/v2 are not supported. XML is not supported for entity CRUD, so the API is JSON only. `odata=fullmetadata` (v3) and `odata.metadata=full` (v4) are unsupported. Arithmetic operators and many query functions are unsupported | CONFIRMED [B1 §7.1] |
| The guide used is v1.22 (2021-06-10), covering SAP Business One 9.1–10.0. Newer feature packs may differ | CONFIRMED [B1] |

### 3.2 Login, session, logout

```http
POST https://<server>:50000/b1s/v1/Login
Content-Type: application/json

{"CompanyDB": "SBODEMOUS", "UserName": "manager", "Password": "1234"}
```
Response (CONFIRMED [B1][B2]):
```http
HTTP/1.1 200 OK
Set-Cookie: B1SESSION=PTRzIjYK-weN6-1Lx1-ZG0J-3ARxfjcU0Shy;HttpOnly;
Set-Cookie: ROUTEID=.node1; path=/b1s

{"odata.metadata": "https://databaseserver:50000/b1s/v1/$metadata#B1Sessions/@Element",
 "SessionId": "PTRzIjYK-weN6-1Lx1-ZG0J-3ARxfjcU0Shy", "Version": "1000110", "SessionTimeout": 30}
```

| Fact | Status |
|---|---|
| Every later request must send **both** cookies: `Cookie: B1SESSION=…; ROUTEID=.node1`. `ROUTEID` comes from the Apache load balancer for stickiness | CONFIRMED [B1] |
| An invalid or expired session returns `HTTP/1.1 401 Unauthorized` with `{"error":{"code":301,"message":{"lang":"en-us","value":"Invalid session or session already timeout."}}}` | CONFIRMED [B1] |
| Logout is `POST /Logout` with the cookies; it returns `204 No Content` | CONFIRMED [B1][B2] |
| The session expires after **30 min without a request** (default). Change it with `SessionTimeout` in `{install}/ServiceLayer/conf/b1s.conf` | CONFIRMED [B1][B2] |
| Login is "a heavy job". Reuse one session, refresh it on 401, and log out at the end | CONFIRMED [B1 §8] |
| The Login body also accepts an optional `"Language": <int>` | CONFIRMED-3P [B4] |
| v2 login is `POST /b1s/v2/Login` with the same body; the response then has OData v4 annotations | UNCONFIRMED |
| SSO via SAML2 exists (9.2+), but it is not needed here | CONFIRMED [B1] |

### 3.3 Response format, paging, query options

| Fact | Status |
|---|---|
| v1 collection: `{"value":[…], "odata.nextLink":"/b1s/v1/Orders?$skip=20"}`. v4 uses `"@odata.context"`, `"value"`, `"@odata.nextLink"` | CONFIRMED [B1] |
| **Default page size is 20.** Change it per request with `Prefer: odata.maxpagesize=50` (the response confirms with `Preference-Applied: odata.maxpagesize=50`) or globally with `PageSize` in b1s.conf. `0` disables paging, and the per-request value wins | CONFIRMED [B1] |
| Any b1s.conf option can be overridden per request with header `B1S-<option>: <value>`, e.g. `B1S-PageSize: 100` (9.1 PL01+) | CONFIRMED [B1] |
| `nextLink` comes in several forms: `"/b1s/v1/Orders?$skip=20"` (absolute path) and `"SQLQueries?$skip=5"` (relative). Resolve both against the service root | CONFIRMED [B1] |
| Count: `$inlinecount=allpages` gives `"odata.count": "5"` (a string) in v1. v2 uses `"@odata.count"` | CONFIRMED [B1] / v2 CONFIRMED-3P [B4] |
| `$filter` functions: `startswith`, `endswith`, `contains`, `substringof`. Operators: `and or not eq ne gt ge lt le`. Also `$select`, `$orderby`, `$top`, `$skip`, `$expand`, `$inlinecount`, and `$crossjoin(...)` (cross-joins were added in guide v1.8, 2016-07-28) | CONFIRMED [B1][B2] |
| Enums can be filtered by value or name (`CardType eq 'C'` or `'cCustomer'`) | CONFIRMED [B1] |
| Date filters accept several formats (`'2014-04-23'`, `'20140423'`, `datetime'2014-04-23'`, …) | CONFIRMED [B1] |
| Dates in payloads look like `"CreateDate": "2020-10-08"`. Some versions may send `…T00:00:00Z`; a third-party client parses both | CONFIRMED [B1] / variant UNCONFIRMED [B5] |
| Numbers are JSON numbers (`"Price": 1`, `"OpeningBalance": 1`). Yes/no values are enum strings **`"tYES"` / `"tNO"`** | CONFIRMED [B2][B1] |
| On SAP HANA, queries are **case-sensitive by default**. Case-insensitive queries are supported from 9.2 PL07 | CONFIRMED [B1] |
| The header `B1S-CaseInsensitive: true` requests case-insensitive matching | CONFIRMED-3P [B4] |
| v1 errors: `{"error":{"code":<int>,"message":{"lang":"en-us","value":"…"}}}`. v2 errors may have a string `code` and a plain-string `message` | CONFIRMED [B1] / v2 CONFIRMED-3P [B4] |
| SAP's own .NET sample disables TLS certificate validation, which suggests self-signed certificates on :50000 are common. Configure a CA bundle rather than disabling verification | CONFIRMED [B1] (sample) |

### 3.4 `Items` entity

Official URL examples (CONFIRMED [B2][B1]):
- `GET /b1s/v1/Items('i001')`
- `GET /b1s/v1/Items('i001')?$select=ItemCode,ItemName,ForeignName`
- `GET /b1s/v1/Items?$select=ItemCode,ItemName,ForeignName&$filter=startswith(ItemCode, 'a')&$orderby=ItemCode&$top=10&$skip=1`
- `GET /Items('i1')?$select=ItemCode,ItemName,ItemPrices`

| Audit field | Property | Status |
|---|---|---|
| Part number (key) | `ItemCode` | CONFIRMED [B2] |
| Description | `ItemName` | CONFIRMED [B2] |
| Foreign/English description | `ForeignName` | CONFIRMED [B2]. That it holds English in Israeli companies is UNCONFIRMED (a convention) |
| Item group | `ItemsGroupCode` (int). Look it up in `ItemGroups` (key `Number` int; `GroupName`) | Field CONFIRMED-3P [B5][B6]; ItemGroups CONFIRMED [B2] |
| Item type | `ItemType` (e.g. `"itItems"`) | CONFIRMED [B2] |
| Inventory/sales/purchase flags | `InventoryItem`, `SalesItem`, `PurchaseItem` (`tYES`/`tNO`) | CONFIRMED-3P [B5][B6] |
| Active/inactive | `Valid`, `Frozen` (`tYES`/`tNO`) plus `ValidFrom`, `ValidTo`, `ValidRemarks`, `FrozenFrom`, `FrozenTo`, `FrozenRemarks` | Fields CONFIRMED-3P [B5]; mapping (Valid=tYES and Frozen=tNO means active) UNCONFIRMED |
| Make/buy | `ProcurementMethod`. Values `bom_Buy` / `bom_Make` are UNCONFIRMED; check the EnumType in `$metadata` | Field CONFIRMED-3P [B5] |
| Has BOM | `TreeType`: `iNotATree`, `iAssemblyTree`, `iSalesTree`, `iProductionTree`, `iTemplateTree`, `iIngredient` | `iProductionTree` CONFIRMED [B2]; full list CONFIRMED-3P [B6] |
| Units | `InventoryUOM`, `PurchaseUnit`, `SalesUnit`, `UoMGroupEntry`, `InventoryUoMEntry` (plus `PurchaseItemsPerUnit`, `SalesItemsPerUnit`) | CONFIRMED-3P [B5] |
| Total stock | `QuantityOnStock`, `QuantityOrderedFromVendors`, `QuantityOrderedByCustomers` (numbers) | CONFIRMED-3P [B5][B6] |
| Main supplier | **`Mainsupplier`** (note the lowercase `s`; the value is the vendor CardCode, UNCONFIRMED) | CONFIRMED-3P [B5][B6] |
| Supplier part number | **`SupplierCatalogNo`** | CONFIRMED-3P [B5][B6] |
| Cost | `AvgStdPrice`, `MovingAveragePrice`, `CostAccountingMethod` (enum values such as `bis_MovingAverage`/`bis_Standard`/`bis_FIFO` are UNCONFIRMED) | CONFIRMED-3P [B5] |
| Prices | `ItemPrices` collection (DI name `Items_Prices`) | CONFIRMED [B1] |
| Stock per warehouse | `ItemWarehouseInfoCollection` (DI name `ItemWarehouseInfo`) | CONFIRMED [B1 App. II] |
| Preferred vendors list | `ItemPreferredVendors` (collection; structure UNCONFIRMED) | CONFIRMED-3P [B5] |
| Dates | `CreateDate`, `CreateTime`, `UpdateDate`, `UpdateTime` | CONFIRMED-3P [B5] (the names are CONFIRMED on other entities [B1]) |
| Lead time | `LeadTime` | CONFIRMED-3P [B5] |
| Barcode | `BarCode` | CONFIRMED-3P [B5][B6] |
| User-defined fields | `U_<Name>` properties on the entity; filterable (`$filter=startswith(U_BPSpecRemarks, 'First')`). A new UDF is visible only after a Service Layer restart | CONFIRMED [B1] |
| ETag | `"@odata.etag"` appears in the payload (ETag support from 10.0 FP2102) | CONFIRMED-3P [B5] / CONFIRMED [B1] |

### 3.5 Stock per warehouse

| Fact | Status |
|---|---|
| `ItemWarehouseInfoCollection[]` elements carry `WarehouseCode`, **`InStock`**, `Committed`, `Ordered`, `StandardAveragePrice`, `MinimalStock`, `MaximalStock`, `MinimalOrder`, `Locked` (`tYES`/`tNO`), `ItemCode`, `CountedQuantity`, `DefaultBin`, and roughly 45 G/L account fields | CONFIRMED-3P [B5] |
| `Available` and `WarehouseName` on this collection | UNCONFIRMED (only one TypeScript typing lists them [B6]) |
| Request: `GET /b1s/v1/Items?$select=ItemCode,QuantityOnStock,ItemWarehouseInfoCollection` with `Prefer: odata.maxpagesize=200` | UNCONFIRMED (composed from documented features) |
| Warehouse list: `GET /b1s/v1/Warehouses` returns `WarehouseCode` and `WarehouseName` | CONFIRMED [B2] |

### 3.6 Prices and cost

| Fact | Status |
|---|---|
| `ItemPrices[]` elements carry `PriceList` (int), `Price`, `Currency`, `AdditionalPrice1`, `AdditionalCurrency1`, `AdditionalPrice2`, `AdditionalCurrency2`, `BasePriceList`, `Factor`, `UoMPrices[]` | CONFIRMED-3P [B5] |
| Price lists: `PriceLists` (key `PriceListNo` int; `PriceListName`, `BasePriceList`, `RoundingMethod`, `GroupNum`) | CONFIRMED [B2] |
| Item-level cost is `AvgStdPrice` (and `MovingAveragePrice`); per-warehouse cost is `ItemWarehouseInfoCollection[].StandardAveragePrice`. Which applies depends on `CostAccountingMethod` and whether cost is managed per warehouse | UNCONFIRMED |

### 3.7 BOM: `ProductTrees`

Official examples (CONFIRMED [B2]):
- `GET /b1s/v1/ProductTrees('pt001')`
- `GET /b1s/v1/ProductTrees?$select=TreeCode,TreeType,Quantity&$filter=startswith(TreeCode, 'a')&$orderby=TreeCode&$top=10&$skip=1`
- Creation payload (shown only for its shape; never send it): `{"ProductTreeLines":[{"ItemCode":"i001","Quantity":5}],"TreeCode":"pt001","TreeType":"iProductionTree"}`

| Fact | Status |
|---|---|
| Header: `TreeCode` (the key, which equals the parent `ItemCode`; the equality is UNCONFIRMED), `TreeType`, `Quantity` (parent quantity) | CONFIRMED [B2] |
| Lines: `ProductTreeLines` (DI name `ProductTrees_Lines`) with `ItemCode` (component) and `Quantity` | CONFIRMED [B1][B2] |
| Other line fields (`Warehouse`, `Price`, `Currency`, `IssueMethod`, `ParentItem`, `ItemType`, `PriceList`, `Comment`, …) | UNCONFIRMED. Read `$metadata` (type `ProductTreeLine`) |

### 3.8 Simulator notes (B1)
- **Session:**
  - `POST /b1s/v1/Login` (and `/b1s/v2/Login`) sets the `B1SESSION` and `ROUTEID` cookies and returns `SessionId`, `Version` and `SessionTimeout`.
  - Without the cookies, or with an expired session, return 401 with code 301.
  - `POST /Logout` returns 204.
  - Expire sessions after N minutes idle.
- **Paging:**
  - Default page size 20; honour `Prefer: odata.maxpagesize=N`, echo `Preference-Applied`, and honour `B1S-PageSize`.
  - v1 emits `odata.nextLink: "Items?$skip=20"`; v2 emits `@odata.nextLink`.
  - `$inlinecount=allpages` returns `"odata.count": "123"`.
- **Payload:**
  - Items include the `ItemPrices` and `ItemWarehouseInfoCollection` arrays unless `$select` excludes them.
  - Booleans are `"tYES"`/`"tNO"`, dates are `"YYYY-MM-DD"`, and numbers are JSON numbers.
  - Include `U_*` fields.
- **HANA mode:** an optional flag that makes `$filter` case-sensitive unless `B1S-CaseInsensitive: true` is sent.

### Sources (SAP Business One)
- [B1] SAP, "Working with SAP Business One Service Layer" user manual v1.22 (2021-06-10), public copy: https://github.com/omniboost/go-sap-b1-service-layer/blob/master/docs/Working_with_SAP_Business_One_Service_Layer.pdf (official URL https://help.sap.com/doc/0d2533ad95ba4ad7a702e83570a21c32/9.3/en-US/Working_with_SAP_Business_One_Service_Layer.pdf, not fetched due to robots). Sections cited: 1.3 OData versions; 3.1 Login/Logout/Session; 3.7 query options; 3.7.6 paging; 3.7.7.7 inlinecount; 3.14 UDFs; 6.2–6.3 b1s.conf and `B1S-*` headers; 7 Limitations; 8 HA/LB; Appendix II naming
- [B2] SAP "Service Layer API Reference" (OData 3.0; Login, Logout, Items, ProductTrees, Warehouses, ItemGroups and PriceLists examples), published by SAP's B1 team on GitHub Pages and now archived: https://github.com/SAP-archive/smb-summit-hackathon/blob/gh-pages/b1sl.html (former URL https://b1sa.github.io/hackathon/b1sl.html, now 404)
- [B3] SAP-archive hackathon B1 backend Postman collection (Login body; GET Items): https://github.com/SAP-archive/smb-summit-hackathon/tree/main/B1Backend
- [B4] 3rd-party: B1SLayer (.NET), source of the `B1S-PageSize` and `B1S-CaseInsensitive` headers, `odata.nextLink`/`@odata.nextLink`, `odata.count`/`@odata.count`, error variants, and the `Language` login field: https://github.com/bgmulinari/B1SLayer
- [B5] 3rd-party: omniboost/go-sap-b1-service-layer `types.go` (Item, ItemPrices and ItemWarehouseInfoCollection structs mirroring real payloads) and `json_types.go` (date formats): https://github.com/omniboost/go-sap-b1-service-layer
- [B6] 3rd-party: npm `sap-b1-mcp-server` `dist/sap/types.d.ts` (Item and ItemWarehouseInfo typings, TreeType enum): https://www.npmjs.com/package/sap-b1-mcp-server

---

## 4. Cross-system mapping for the audit model

| Audit field | Priority (OData v4) | S/4HANA (OData v2) | SAP B1 Service Layer |
|---|---|---|---|
| Part number | `LOGPART.PARTNAME` (C) | `A_Product.Product` (C) | `Items.ItemCode` (C) |
| Description (Hebrew/primary) | `PARTDES` (C) | `A_ProductDescription.ProductDescription` where `Language='HE'`? (field C; code U) | `ItemName` (C) |
| Description (English) | `EPARTDES` (C) | same, `Language='EN'` (U) | `ForeignName` (C; meaning U) |
| Unit | `UNITNAME`/`PUNITNAME`? (U) | `BaseUnit` (C) | `InventoryUOM` (3P) |
| Group/family | `FAMILYNAME` (C) | `ProductGroup` (C) | `ItemsGroupCode` (3P) → `ItemGroups.GroupName` (C) |
| Status | `STATDES` (C; values U) | `CrossPlantStatus`, `IsMarkedForDeletion` (C) | `Valid`/`Frozen` (3P) |
| Make/buy | `TYPE` P=make (C), R=raw material (C) → buy (U) | `A_ProductPlant.ProcurementType` (C; values U) | `ProcurementMethod` (3P; values U) |
| Stock per warehouse | `WARHSBAL` (C, as a form; REST path U) with `TBALANCE` (C in SDK) or `BALANCE` (3P) | `A_MatlStkInAcctMod.MatlWrhsStkQtyInMatlBaseUnit` by Plant/StorageLocation (C) | `ItemWarehouseInfoCollection[].InStock` by `WarehouseCode` (3P) |
| Standard/avg cost + currency | `LASTPRICE` (C; meaning U); other cost fields U | `A_ProductValuation.StandardPrice`/`MovingAveragePrice`/`PriceUnitQty`/`Currency` (C) | `AvgStdPrice`, `ItemWarehouseInfoCollection[].StandardAveragePrice` (3P); `ItemPrices[].Price`/`Currency` (3P) |
| Main supplier | `SUPNAME` on LOGPART? (U) | Info record `IsRegularSupplier` (C field; semantics U) | `Mainsupplier` (3P) |
| Supplier part no. | `SUPPLIERPARTS` form (C); fields U | `A_PurchasingInfoRecord.SupplierMaterialNumber` (C) | `SupplierCatalogNo` (3P) |
| Lead time | `PRDPART` form (C); field U | `A_ProductSupplyPlanning.PlannedDeliveryDurationInDays` (C); info-record `MaterialPlannedDeliveryDurn` (C) | `LeadTime` (3P) |
| BOM | `PART`→`PARTARC_SUBFORM` (3P): `SONNAME`, `SONQUANT` (3P) | `MaterialBOM` + `MaterialBOMItem.BillOfMaterialComponent`/`BillOfMaterialItemQuantity`/`BillOfMaterialItemUnit` (C) | `ProductTrees.TreeCode`/`Quantity` + `ProductTreeLines[].ItemCode`/`Quantity` (C) |
| Revision | `REVNAME` on PART? (U) | `MaterialRevisionLevel` (C) | n/a |
| Created / changed | U | `CreationDate`, `LastChangeDateTime` (C) | `CreateDate`, `UpdateDate` (3P) |

C = CONFIRMED, 3P = CONFIRMED-3P, U = UNCONFIRMED (see the sections above for sources).

---

## 5. Sources that could not be read

| Source | Reason | What I used instead |
|---|---|---|
| help.sap.com: S/4HANA API docs (e.g. "Operations for Product Master (A2X) API", "Material Stock", "Inventory Stock Type", "Product Integration (SAP_COM_0009)", "Material Stock Integration (SAP_COM_0164)"), the B1 SDK help, and the B1 Service Layer guide/reference | robots.txt `Disallow: /` for non-search bots | SAP Cloud SDK schemas on npm [S1–S5], the SAP OpenAPI spec copy [S6], and B1 guide/reference copies on GitHub [B1][B2] |
| api.sap.com (Business Accelerator Hub) | robots.txt disallows | The same as above |
| community.sap.com (most blog and Q&A pages) | fetch tool refused (robots) | One Q&A page was fetchable [S13] |
| biuan.com (DI-API mirror) | robots.txt explicitly disallows Claude agents | Third-party code [B5][B6] |
| sap.highwaytwo.com (another API-reference mirror) | connection reset | [B2] |
| SAP support KBAs (userapps.support.sap.com) | login required | Titles only; content not used |
| Priority demo sandbox `$metadata` | requires logging in with the published demo credentials, which is outside the agreed rules | None. Listed in §1.12 as a step the user can run |
