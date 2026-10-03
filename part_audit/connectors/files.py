"""Connectors without a server: a network/local folder of CAD files, and an ERP export file (Excel/CSV)."""
from __future__ import annotations

import re
from pathlib import Path

from ..model import BomLine, ErpItem, PartRecord
from ..names import extract_part_numbers
from ..scan import ERP_COLUMN_ALIASES, OTHER_CAD_EXTS, STEP_EXTS, iter_files
from .base import Collected, Connector, Field, to_float
from .http import ConnectorError


class FolderSource(Connector):
    kind = "folder"
    role = "pdm"
    title = "תיקיית רשת / תיקייה מקומית"
    vendor = "—"
    interface = "קריאת קבצים מתיקייה (כולל תתי-תיקיות)"
    description = ("לחברות בלי PDM: סורק תיקייה משותפת (למשל \\\\server\\engineering) ומזהה קבצי STEP. "
                   "מק\"ט נלקח משם הקובץ. קבצים מקוריים (SLDPRT, IPT...) נרשמים כ\"לא נבדקו\".")
    fields = [
        Field("path", "נתיב התיקייה", type="path", required=True, help="נתיב מקומי או UNC, למשל \\\\server\\cad"),
        Field("pn_regex", "תבנית מק\"ט בשם הקובץ (Regex)", default="", group="mapping",
              help="ריק = זיהוי אוטומטי. למשל (\\d{3}-\\d{4})"),
    ]
    verification = "קורא קבצים ישירות מהדיסק; לא נדרש שרת."

    def test(self) -> dict:
        root = Path(self.cfg["path"])
        if not root.exists():
            return {"ok": False, "message": f"התיקייה לא נמצאה: {root}", "details": {}}
        n_step = n_other = 0
        for i, p in enumerate(iter_files(root)):
            ext = p.suffix.lower()
            n_step += ext in STEP_EXTS
            n_other += ext in OTHER_CAD_EXTS
            if i > 20000:
                break
        return {"ok": True, "message": "התיקייה נגישה", "details": {"קבצי STEP": n_step, "קבצי CAD אחרים": n_other}}

    def collect(self) -> Collected:
        out = Collected()
        root = Path(self.cfg["path"]).resolve()
        if not root.exists():
            raise ConnectorError(f"התיקייה לא נמצאה: {root}")
        rx = re.compile(self.cfg["pn_regex"]) if self.cfg.get("pn_regex") else None
        files = list(iter_files(root))
        for i, p in enumerate(files):
            if i % 50 == 0:
                self.progress("סורק את התיקייה", i, len(files))
            ext = p.suffix.lower()
            rel = p.relative_to(root).as_posix()
            if ext in STEP_EXTS:
                stem = p.stem
                pn = ""
                if rx:
                    m = rx.search(stem)
                    pn = m.group(1) if m and m.groups() else (m.group(0) if m else "")
                else:
                    cands = extract_part_numbers(stem)
                    pn = cands[0] if cands else ""
                st = p.stat()
                out.records.append(PartRecord(
                    uid=self.uid(rel), source_id=self.source_id, source_kind=self.kind, native_id=rel, kind="part",
                    pn=pn, name=stem, native_file=p.name, folder=str(Path(rel).parent) if "/" in rel else "",
                    step_path=str(p), step_name=p.name, modified=_date(st.st_mtime)))
            elif ext in OTHER_CAD_EXTS:
                out.skipped.append({"source": self.source_id, "file": rel, "reason": OTHER_CAD_EXTS[ext]})
        out.stats = {"files": len(files), "step": len(out.records), "skipped": len(out.skipped)}
        return out


def _date(ts: float) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(ts).date().isoformat()


ERP_FIELDS = {
    **ERP_COLUMN_ALIASES,
    "description_en": ["description en", "english description", "foreign name", "תיאור באנגלית", "תאור אנגלית", "epartdes"],
    "family": ["family", "group", "item group", "category", "משפחה", "קבוצה", "קבוצת פריטים"],
    "status": ["status", "סטטוס", "מצב"],
    "stock": ["stock", "on hand", "quantity", "qty", "balance", "מלאי", "יתרה", "כמות במלאי"],
    "unit_cost": ["cost", "unit cost", "price", "standard cost", "last price", "עלות", "מחיר", "עלות יחידה", "מחיר אחרון"],
    "currency": ["currency", "מטבע"],
    "supplier_pn": ["supplier part number", "vendor part", "מקט ספק", 'מק"ט ספק'],
    "lead_time": ["lead time", "זמן אספקה", "ימי אספקה"],
    "make_buy": ["make/buy", "type", "סוג", "ייצור/קנייה"],
    "warehouse": ["warehouse", "מחסן"],
}
BOM_FIELDS = {"parent": ["parent", "assembly", "אב", "מכלול", "מק\"ט אב"], "child": ["child", "component", "בן", "רכיב",
                                                                                       "מק\"ט בן"],
              "qty": ["qty", "quantity", "כמות"]}
INACTIVE = re.compile(r"inactive|obsolete|לא\s*פעיל|מבוטל|מוקפא|frozen|blocked", re.I)


def _norm(h: str) -> str:
    return " ".join(str(h).strip().lower().replace("_", " ").replace("״", '"').split())


def _map_columns(cols, spec: dict) -> dict:
    out = {}
    for col in cols:
        key = _norm(col)
        for canon, aliases in spec.items():
            if canon in out.values():
                continue
            if key in {_norm(a) for a in aliases} or key == canon:
                out[col] = canon
                break
    return out


def read_table(path: Path, sheet: str | None = None):
    import pandas as pd
    if path.suffix.lower() == ".xls":
        raise ValueError("קובץ Excel בפורמט הישן (.xls) – שמרו אותו מחדש כ-.xlsx או כ-CSV")
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        xl = pd.read_excel(path, sheet_name=None, dtype=str)
        return {k: v.fillna("") for k, v in xl.items()}
    from ..scan import load_erp  # CSV with encoding detection (Hebrew code pages)
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1255", "latin-1"):
        try:
            from io import StringIO
            df = pd.read_csv(StringIO(raw.decode(enc)), dtype=str, keep_default_na=False, sep=None, engine="python")
            return {"Sheet1": df}
        except Exception:
            continue
    load_erp(path)  # raises a readable error
    return {}


class ErpFile(Connector):
    kind = "erp_file"
    role = "erp"
    title = "קובץ יצוא ERP (Excel / CSV)"
    vendor = "—"
    interface = "קריאת קובץ"
    description = ("כשאין חיבור ישיר ל-ERP: מעלים קובץ יצוא של מק\"טים (Excel או CSV, עברית או אנגלית). "
                   "עמודות מזוהות אוטומטית: מק\"ט, תיאור, יחידה, מלאי, עלות, ספק, סטטוס. גיליון נוסף בשם BOM – עץ מוצר.")
    fields = [Field("path", "קובץ (xlsx / csv)", type="path", required=True),
              Field("currency", "מטבע ברירת מחדל", default="ILS", group="mapping")]
    verification = "קורא קבצים מקומיים; לא נדרש שרת."

    def test(self) -> dict:
        p = Path(self.cfg["path"])
        if not p.exists():
            return {"ok": False, "message": f"הקובץ לא נמצא: {p}", "details": {}}
        try:
            sheets = read_table(p)
        except Exception as exc:
            return {"ok": False, "message": f"לא ניתן לקרוא את הקובץ: {exc}", "details": {}}
        first = next(iter(sheets.values()))
        cols = _map_columns(first.columns, ERP_FIELDS)
        ok = "part_number" in cols.values()
        return {"ok": ok, "message": "הקובץ נקרא" if ok else "לא נמצאה עמודת מק\"ט",
                "details": {"שורות": len(first), "עמודות שזוהו": ", ".join(sorted(set(cols.values())))}}

    def collect(self) -> Collected:
        out = Collected()
        p = Path(self.cfg["path"])
        sheets = read_table(p)
        items_df = None
        bom_df = None
        for name, df in sheets.items():
            cols = _map_columns(df.columns, BOM_FIELDS)
            if {"parent", "child"} <= set(cols.values()) and ("bom" in name.lower() or "עץ" in name):
                bom_df = df.rename(columns=cols)
            elif items_df is None and "part_number" in _map_columns(df.columns, ERP_FIELDS).values():
                items_df = df.rename(columns=_map_columns(df.columns, ERP_FIELDS))
        if items_df is None:
            raise ConnectorError("לא נמצא גיליון עם עמודת מק\"ט")
        by_pn: dict[str, ErpItem] = {}
        for _, row in items_df.iterrows():
            pn = str(row.get("part_number", "")).strip()
            if not pn:
                continue
            status = str(row.get("status", "")).strip()
            it = by_pn.get(pn) or ErpItem(source_id=self.source_id, pn=pn,
                                          description=str(row.get("description", "")).strip(),
                                          description_en=str(row.get("description_en", "")).strip(),
                                          uom=str(row.get("unit", "")).strip(), family=str(row.get("family", "")).strip(),
                                          status=status, active=not bool(INACTIVE.search(status)),
                                          unit_cost=to_float(row.get("unit_cost")),
                                          currency=str(row.get("currency", "") or self.cfg.get("currency", "ILS")),
                                          supplier=str(row.get("supplier", "")).strip(),
                                          supplier_pn=str(row.get("supplier_pn", "")).strip(),
                                          lead_time_days=to_float(row.get("lead_time")),
                                          material=str(row.get("material", "")).strip(),
                                          make_buy=_mb(row.get("make_buy")))
            q = to_float(row.get("stock"))
            if q is not None:
                wh = str(row.get("warehouse", "") or "—")
                it.stock[wh] = it.stock.get(wh, 0.0) + q
                it.stock_total += q
            by_pn[pn] = it
        out.erp_items = list(by_pn.values())
        if bom_df is not None:
            for _, row in bom_df.iterrows():
                if str(row.get("parent", "")).strip() and str(row.get("child", "")).strip():
                    out.bom.append(BomLine(self.source_id, str(row["parent"]).strip(), str(row["child"]).strip(),
                                           to_float(row.get("qty")) or 1.0))
        out.stats = {"items": len(out.erp_items), "bom_lines": len(out.bom)}
        return out


def _mb(v) -> str:
    s = str(v or "").strip().lower()
    if s in ("p", "make", "ייצור", "יצור", "m"):
        return "make"
    if s in ("r", "buy", "קנייה", "קניה", "b", "purchased"):
        return "buy"
    return ""
