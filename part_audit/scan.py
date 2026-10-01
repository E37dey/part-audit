"""Folder scanner: finds CAD files, reads STEP headers/product names, computes L1 hashes.

Also loads the ERP export (CSV) with tolerant encoding and column detection.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .hashes import normalized_step_hash, sha256_bytes
from .stepfile import bytes_to_text, parse_step_text

STEP_EXTS = {".step", ".stp", ".p21"}
# Formats we recognise but cannot read in this demo (listed in Errors_Skipped).
OTHER_CAD_EXTS = {
    ".sldprt": "SOLIDWORKS part - export to STEP first",
    ".sldasm": "SOLIDWORKS assembly - export to STEP first",
    ".slddrw": "SOLIDWORKS drawing - not a 3D model",
    ".catpart": "CATIA part - export to STEP first",
    ".catproduct": "CATIA product - export to STEP first",
    ".prt": "NX/Creo part - export to STEP first",
    ".asm": "Creo assembly - export to STEP first",
    ".ipt": "Inventor part - export to STEP first",
    ".iam": "Inventor assembly - export to STEP first",
    ".par": "Solid Edge part - export to STEP first",
    ".x_t": "Parasolid - export to STEP first",
    ".x_b": "Parasolid - export to STEP first",
    ".igs": "IGES - not supported in this demo, export to STEP",
    ".iges": "IGES - not supported in this demo, export to STEP",
    ".sat": "ACIS - export to STEP first",
    ".jt": "JT - export to STEP first",
    ".stl": "mesh only (STL) - not supported",
    ".obj": "mesh only (OBJ) - not supported",
    ".3mf": "mesh only (3MF) - not supported",
    ".dwg": "2D drawing - not a 3D model",
    ".dxf": "2D drawing - not a 3D model",
    ".stpz": "compressed STEP - unzip first",
}
SKIP_DIRS = {".git", ".svn", "__pycache__", ".part_audit_cache", "$RECYCLE.BIN"}


@dataclass
class FileRecord:
    file_id: str            # path relative to the scanned root, '/' separated
    path: str               # absolute path
    folder: str
    filename: str
    stem: str
    ext: str
    size: int
    mtime: float
    sha256: str = ""
    norm_sha256: str = ""
    schema: str = ""
    header_file_name: str = ""
    timestamp: str = ""
    originating_system: str = ""
    products: list = field(default_factory=list)   # [(id, name, description)]
    length_unit: str = ""
    n_entities: int = 0
    error: str = ""
    t_scan: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SkipRecord:
    file_id: str
    reason: str
    detail: str = ""
    size: int = 0
    stage: str = "scan"


def iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for fn in sorted(filenames):
            yield Path(dirpath) / fn


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def read_step_record(path: str, root: str) -> FileRecord:
    """Read one STEP file: raw hash, normalized hash, header and product names."""
    p = Path(path)
    t0 = time.perf_counter()
    st = p.stat()
    rec = FileRecord(
        file_id=_rel(p, Path(root)), path=str(p), folder=_rel(p.parent, Path(root)) if p.parent != Path(root) else "",
        filename=p.name, stem=p.stem, ext=p.suffix.lower(), size=st.st_size, mtime=st.st_mtime,
    )
    try:
        data = p.read_bytes()
        rec.sha256 = sha256_bytes(data)
        text = bytes_to_text(data)
        info = parse_step_text(text)
        if not info.is_step:
            rec.error = "not an ISO-10303-21 file (missing header)"
        else:
            rec.norm_sha256 = normalized_step_hash(text)
            rec.schema = info.schema
            rec.header_file_name = info.header_file_name
            rec.timestamp = info.timestamp
            rec.originating_system = info.originating_system
            rec.products = [list(p_) for p_ in info.products]
            rec.length_unit = info.length_unit
            rec.n_entities = info.n_entities
    except Exception as exc:  # unreadable file, permissions, ...
        rec.error = f"{type(exc).__name__}: {exc}"
    rec.t_scan = time.perf_counter() - t0
    return rec


def scan_folder(root: str | Path, workers: int = 1, progress=None) -> tuple[list[FileRecord], list[SkipRecord]]:
    """Walk ``root``; return STEP file records and records of skipped files."""
    root = Path(root).resolve()
    step_paths: list[Path] = []
    skipped: list[SkipRecord] = []
    for p in iter_files(root):
        ext = p.suffix.lower()
        if ext in STEP_EXTS:
            step_paths.append(p)
        elif ext in OTHER_CAD_EXTS:
            skipped.append(SkipRecord(_rel(p, root), "unsupported CAD format", OTHER_CAD_EXTS[ext], p.stat().st_size))
        # everything else (pdf, xlsx, images...) is silently ignored
    records: list[FileRecord] = []
    args = [(str(p), str(root)) for p in step_paths]
    if workers > 1 and len(args) > 20:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for i, rec in enumerate(ex.map(read_step_record, *zip(*args), chunksize=8)):
                records.append(rec)
                if progress:
                    progress(i + 1, len(args))
    else:
        for i, a in enumerate(args):
            records.append(read_step_record(*a))
            if progress:
                progress(i + 1, len(args))
    for rec in records:
        if rec.error:
            skipped.append(SkipRecord(rec.file_id, "unreadable STEP file", rec.error, rec.size))
    return records, skipped


# ---------------------------------------------------------------- ERP export

ERP_COLUMN_ALIASES = {
    "part_number": ["part_number", "part number", "partnumber", "pn", "p/n", "item", "item number", "item_no",
                    "item code", "catalog number", "part no", "part_no", "מקט", 'מק"ט', "מק''ט", "מספר פריט", "קוד פריט"],
    "description": ["description", "desc", "item description", "part name", "name", "תאור", "תיאור", "תאור פריט",
                    "תיאור פריט", "שם פריט"],
    "unit": ["unit", "uom", "unit of measure", "יחידה", "יחידת מידה", "יח"],
    "material": ["material", "mat", "חומר", "חומר גלם"],
    "supplier": ["supplier", "vendor", "manufacturer", "ספק", "יצרן"],
}


def _norm_header(h: str) -> str:
    return " ".join(str(h).strip().lower().replace("_", " ").replace("״", '"').split())


def load_erp(path: str | Path):
    """Load an ERP CSV export. Returns a pandas DataFrame with canonical column names.

    Tries UTF-8 (with/without BOM), UTF-16 and Windows-1255 (Hebrew); maps common
    English/Hebrew header names to part_number/description/unit/material/supplier.
    """
    import pandas as pd

    raw = Path(path).read_bytes()
    last_exc: Exception | None = None
    df = None
    for enc in ("utf-8-sig", "utf-16", "cp1255", "latin-1"):
        try:
            text = raw.decode(enc)
            if enc == "utf-16" and not raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                continue
            from io import StringIO
            df = pd.read_csv(StringIO(text), dtype=str, keep_default_na=False, sep=None, engine="python")
            break
        except Exception as exc:  # try next encoding
            last_exc = exc
    if df is None:
        raise ValueError(f"cannot read ERP file {path}: {last_exc}")
    rename = {}
    for col in df.columns:
        key = _norm_header(col)
        for canon, aliases in ERP_COLUMN_ALIASES.items():
            if key in {_norm_header(a) for a in aliases} and canon not in rename.values():
                rename[col] = canon
                break
    df = df.rename(columns=rename)
    if "part_number" not in df.columns:
        raise ValueError(f"ERP file {path}: no part-number column found (columns: {list(df.columns)})")
    for col in ERP_COLUMN_ALIASES:
        if col not in df.columns:
            df[col] = ""
    df["part_number"] = df["part_number"].astype(str).str.strip()
    df = df[df["part_number"] != ""].reset_index(drop=True)
    df.insert(0, "erp_row", range(2, len(df) + 2))  # spreadsheet-style row number (header = 1)
    return df
