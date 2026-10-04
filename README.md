# PartAudit – בקרת נתונים הנדסיים

<div dir="rtl">

**PartAudit** קוראת את רשומות החלקים ממערכות ה-PDM/PLM, מתיקיות קבצים ומה-ERP, ומוצאת:

- **כפילויות**: אותו חלק שקיים תחת כמה מק"טים, גם כשהרשומות במערכות שונות.
- **חלקים כמעט זהים** שאולי אפשר לתקנן לחלק אחד. מפת צבעים בתלת-ממד מראה איפה הם שונים.
- **שמות ומק"טים לא עקביים**, ו**בעיות בנתונים**: משקל שלא תואם למודל, חומר חסר, קובץ ביחידות שגויות.
- **פערים בין ההנדסה ל-ERP**: חלק משוחרר שחסר ב-ERP, ותיאור, חומר, סטטוס או עץ מוצר שונים.

כל הצעה מחכה לאישור של מהנדס, והתוצאה יוצאת לקובץ Excel בעברית. **התוכנה רק קוראת מהמערכות ולא כותבת אליהן.** היא רצה במחשב שלכם ולא שולחת נתונים החוצה.

## הפעלה

| מערכת | מה עושים |
|---|---|
| Windows | לחיצה כפולה על `PartAudit-Windows.bat` |
| Mac | בפעם הראשונה: קליק ימני על `PartAudit-Mac.command` ואז "פתח" (macOS חוסם קבצים שהורדו מהאינטרנט). בפעמים הבאות מספיקה לחיצה כפולה |
| Linux | `./PartAudit-Linux.sh` |

- **בפעם הראשונה** נדרש חיבור לאינטרנט. ההתקנה מורידה כ-150 MB ולוקחת כמה דקות.
- ההתקנה יוצרת סביבת Python פרטית: ב-Windows בתיקייה `%LOCALAPPDATA%\PartAudit`, ובמק בתיקייה `~/Library/Application Support/PartAudit`. שום דבר אחר במחשב לא משתנה.
- הדפדפן נפתח לבד בכתובת `http://127.0.0.1:8765`. החלון השחור צריך להישאר פתוח בזמן העבודה, וסגירה שלו עוצרת את התוכנה.
- התוצאות, המטמון וקבצי ה-Excel נשמרים בתיקייה `PartAudit` שבתיקיית הבית.
- **הסרה:** מוחקים את תיקיית התוכנה ואת שתי התיקיות שלמעלה.

## איך מתחילים

1. **סביבת ההדגמה**: לוחצים "טען סביבת הדגמה" ואחר כך "סריקה חדשה". זו קבוצת תעשייה בדויה עם 4 אתרים ו-4 מערכות PDM/PLM שונות, ארכיון קבצים ישן ו-Priority. הסריקה הראשונה לוקחת בערך דקה.
2. **המערכות שלכם**: במסך "מקורות נתונים" לוחצים "הוסף מקור", בוחרים מערכת, ממלאים כתובת ומשתמש (מומלץ משתמש עם הרשאת קריאה בלבד) ולוחצים "בדוק חיבור". בתוך האפליקציה יש מדריך עם מה שכל מערכת צריכה.

| מערכת | ממשק |
|---|---|
| SOLIDWORKS PDM | Web API (2022 ומעלה), או COM דרך לקוח PDM ב-Windows |
| Autodesk Vault | Vault Data API (2025.2 ומעלה) |
| PTC Windchill | Windchill REST Services (OData) |
| Siemens Teamcenter | JSON REST של שירותי ה-SOA |
| תיקיית רשת / ארכיון | קבצי STEP בתיקייה ובתתי-תיקיות |
| Priority | REST API (OData) |
| SAP S/4HANA, SAP Business One | OData v2 / Service Layer |
| כל ERP אחר | קובץ יצוא Excel או CSV |

> **חשוב:** החיבורים נכתבו לפי התיעוד הפומבי של כל יצרן, ונבדקו מול סימולטורים שמחקים את ה-API. הם עוד לא נבדקו מול שרת אמיתי של לקוח. רשימת הפרטים שעוד לא אומתו מופיעה בתוכנה, בכרטיס של כל מערכת.

## מה נמדד

הנתונים נמדדו על סביבת ההדגמה בלבד. את הנתונים האלה בנינו בעצמנו, ולכן התוצאה היא חסם עליון לנתונים אמיתיים של מפעל.

- **זוגות כפולים: 297 מתוך 318 נמצאו, בלי אף זוג שגוי** (precision 100%, recall 93.4%).
  - כשלשני החלקים יש קובץ STEP: 253 מתוך 256 (98.8%).
  - כשחסר קובץ STEP וההשוואה היא לפי שם, מק"ט ומפרט בלבד: 44 מתוך 62 (71%).
- **18 זוגות "מלכודת"** (אותה צורה עם מפרט שונה, למשל 8.8 מול 12.9 או 2RS מול ZZ): **אף אחד מהם לא אוחד.** 15 מהם סומנו "צורה זהה, מפרט שונה".
- **בעיות שנשתלו בנתונים**: נשתלו 81 בעיות מ-14 סוגים. בדיקות התוכנה מכסות 71 מהן, ומתוכן נמצאו 70. הבעיה שלא נמצאה היא משקל רשום ישן אחד. את 10 הבעיות האחרות התוכנה לא בודקת:
  - 7 מקרים של חומר חסר בפריטי קנייה. לפריטי קנייה לא דורשים חומר.
  - משקל של חלק שאין לו קובץ STEP, כך שאין ממה לחשב משקל.
  - 2 תיאורים ריקים שלא מגיעים לנתונים: הסימולטורים של SOLIDWORKS PDM ו-Vault ממלאים את שדה התיאור בשם החלק.

הפירוט המלא נמצא ב-[RESULTS.md](RESULTS.md).

</div>

---

## English: what is in this repository

PartAudit v2 is a local web app (FastAPI + a vanilla-JS Hebrew RTL UI) on top of the v1 audit engine.

```
part_audit/
  connectors/   read-only connectors: SOLIDWORKS PDM (Web API, COM), Autodesk Vault, PTC Windchill,
                Siemens Teamcenter, folder, Priority, SAP S/4HANA, SAP Business One, ERP Excel/CSV
  simulators/   local stand-ins for those APIs (FastAPI routers), used by the demo and the tests
  project.py    collect() from sources -> Snapshot; audit_snapshot() -> groups, pairs, mapping, findings
  scoring.py names.py geometry.py shape.py stdparts.py quality.py explain.py   engine (v1 layers + v2 rules)
  server/       app.py (REST API, jobs), store.py (SQLite: sources, runs, decision history; OS keyring)
  viewer.py     meshes for display, trimmed-ICP alignment, deviation maps
  decisions.py  applies approvals (including a target part number chosen by the engineer) to the mapping
  excel_he.py   Hebrew right-to-left Excel report
  ui/           index.html, css, js (three.js 0.170 and IBM Plex fonts vendored: works offline)
tools/factory/  builds the demo factory (CadQuery) and evaluates the pipeline against what was planted
docs/research/  public API documentation that the connectors follow (with sources and confidence)
```

### Run from source

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv -r requirements-dev.txt
.venv/bin/python -m part_audit app            # http://127.0.0.1:8765, opens the browser
.venv/bin/python -m pytest                    # 110 tests
```

`python -m part_audit app --port 8765 --workspace ~/PartAudit --no-demo --no-browser` are the options.
If the port is taken, the next free one is used. If PartAudit already runs there, the browser is pointed at it.

The demo factory (`demo/factory`, ~46 MB, not in git) ships with the release archive. To rebuild it, use a
separate environment with CadQuery (it needs the VTK build of OCP, which cannot share an environment with
`cadquery-ocp-novtk`): `python tools/factory/build.py --nist <NIST STEP files>`.
`python tools/factory/evaluate.py` re-measures `results/demo_factory_eval.json`.

### Read-only guarantee

Every HTTP connector goes through `ReadOnlyHttp`. GET and HEAD always pass. A connector lists the few non-GET
calls it needs (logins, POST searches, SOA read operations, logouts). Any other request raises `WriteBlocked`
before it leaves the machine. The check also runs on every redirect httpx follows, so a 307 cannot turn an allowed
login into another call (`tests/test_connectors.py`).

The app binds to a loopback address only (any other `--host` value is replaced with 127.0.0.1). It answers only
when the Host header is a loopback name, which blocks DNS rebinding. A request that changes something must be
addressed to the app's own port, and is refused when another site's page sent it (Origin, Sec-Fetch-Site) or when
it is not JSON (`tests/test_app.py`). Calls to a server on this computer bypass any configured proxy.

Credentials (password fields, the Priority token) are kept in the OS credential store when one exists (Windows
Credential Manager, macOS Keychain). Otherwise they stay in the local SQLite database. The API never returns them,
and a stored credential is dropped when the source's address changes, so it is never sent to a server it was not
entered for.

### Connector verification levels

| Connector | Built from | Tested against | Not confirmed yet (from the code) |
|---|---|---|---|
| SOLIDWORKS PDM Web API | public SOLIDWORKS PDM Web API docs | local simulator | computed BOM row layout; FileRef layout (read leniently) |
| SOLIDWORKS PDM COM | official API docs (IEdmVault5, IEdmFile5) | **nothing**: needs Windows and a PDM client | pywin32 ByRef returns; the ProgID |
| Autodesk Vault | Vault Data API (REST v2) docs | local simulator | `uses`/`parents` response layout (fallback only) |
| PTC Windchill | Windchill REST Services (OData v4) docs | local simulator | site-specific IBA names (material/mass); STEP representation settings (WVS) |
| Siemens Teamcenter | SOA JSON REST docs | local simulator | ticket map encoding; BOM quantity property; site-specific property names |
| Priority | Priority REST API docs | local simulator | UNITNAME/SUPNAME/WARHSBAL field names; API calls count as licensed transactions |
| SAP S/4HANA | API_PRODUCT_SRV etc. (OData v2) | local simulator | Hebrew language key; ProcurementType semantics |
| SAP Business One | Service Layer docs | local simulator | ProcurementMethod values; Valid/Frozen as status |
| Folder, ERP Excel/CSV | – | real files | – |

Sources and confidence notes: [docs/research/pdm_plm_apis.md](docs/research/pdm_plm_apis.md),
[docs/research/erp_apis.md](docs/research/erp_apis.md). Field names that differ between sites can be
changed in each source's mapping settings.

### What the engine adds in v2

* Standard parts: DIN↔ISO equivalence (912/4762, 933/4017, 934/4032…), size, length, strength class and
  bearing seal are read from names. Same shape with a different class or seal is never merged.
* Records without a STEP file are compared by part number, name and spec only (lower confidence).
* The part number that stays is chosen by evidence: in the ERP, released, used in BOMs, has stock, has a model.
  The engineer can pick another one, and that choice flows into the mapping and the Excel.
* Data quality checks: mass vs geometry × density, missing material, part-number format per source, file name
  vs part number, released assembly with unreleased or obsolete components, unit errors.
* ERP vs PDM checks: released but missing in the ERP, active ERP item without a model, description, material,
  status and BOM differences.

### Measured results

Demo factory (synthetic business data, ISO/DIN geometry, 5 NIST models), read through the real connectors
from the simulators, then audited. Numbers from `results/demo_factory_eval.json`:

| | |
|---|---|
| duplicate pairs, all | 297 of 318 found, 0 wrong (precision 100%, recall 93.4%) |
| … both records have a STEP file | 253 of 256 (98.8%) |
| … a STEP file is missing (names/spec only) | 44 of 62 (71.0%) |
| same shape, different spec (hard negatives) | 18 of 18 not merged (15 flagged as spec conflict) |
| near-identical, mirror and old-revision variants | none merged |
| planted data-quality and ERP issues | 81 planted in 14 kinds, 71 within what the checks look at: 70 found (one stale mass missed). Not checked: 7 missing materials on purchased parts (by design), 1 mass without a STEP file, 2 empty descriptions that the SOLIDWORKS PDM and Vault simulators fill with the name |
| time | 4.7 s reading 6 sources + 40.1 s audit (472 parts, 2 workers, cold cache) |

The v1 measurements (held-out ABC test set, NIST files, 5000-file benchmark) are in [RESULTS.md](RESULTS.md),
including a re-run of the v1 test set with the v2 engine. The v1 command-line tool is documented in
[docs/v1_cli.md](docs/v1_cli.md).

### Limitations

* All accuracy numbers come from synthetic data that this project generated. Real data will be worse.
* The connectors have not been run against a real customer server. Expect to adjust field mappings on the first
  connection. The COM connector has never run.
* Without STEP files, duplicates are found by names and specs only (71% recall on the demo).
* Different CAD exports of the same NIST part were reported as identical in 2 of 5 cases and as near-identical
  (for review) in 3.
* Assemblies are not checked for duplicates. They are used for where-used, release-state checks and the ERP BOM comparison.

### Data and licences

* Demo factory: synthetic business data; standard-part geometry generated with CadQuery from ISO/DIN dimensions.
* 5 NIST MBE PMI test models (CTC/FTC), U.S. government works from the National Institute of Standards and
  Technology, used with acknowledgement.
* three.js (MIT), IBM Plex Sans Hebrew and IBM Plex Mono (SIL Open Font License), vendored in `part_audit/ui/`.
* v1 sample data: ABC dataset parts (MIT for the dataset; model rights belong to their creators; internal use).
  GrabCAD and the Fusion 360 Gallery were not used.
