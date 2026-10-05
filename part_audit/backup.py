"""Backup and restore of a workspace: the database (decisions, sources, users, settings), scan results and exports.

The STEP cache and uploads are not included: they are re-created by the next scan. The backup holds the connection
settings of the sources, which may include passwords: keep the file as private as the workspace itself.
"""
from __future__ import annotations

import io
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path

SKIP_DIRS = {"cache", "uploads"}
MARK = "partaudit-backup.txt"


def _db_copy(db: Path) -> bytes:
    """A consistent copy of a database that may be in use (SQLite online backup)."""
    with tempfile.TemporaryDirectory() as t:
        dst = Path(t) / "copy.db"
        src = sqlite3.connect(db, timeout=30)
        out = sqlite3.connect(dst)
        try:
            src.backup(out)
        finally:
            out.close()
            src.close()
        return dst.read_bytes()


def make_backup(workspace: str | Path, out: str | Path | io.IOBase) -> int:
    """Write the zip to a path or file object; returns the number of files."""
    ws = Path(workspace)
    db = ws / "app.db"
    if not db.exists():
        raise FileNotFoundError(f"no PartAudit workspace in {ws}")
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(MARK, f"PartAudit backup {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        z.writestr("app.db", _db_copy(db))
        n += 1
        for p in sorted(ws.rglob("*")):
            rel = p.relative_to(ws)
            if not p.is_file() or rel.parts[0] in SKIP_DIRS or rel.parts[0].startswith("app.db"):
                continue
            z.write(p, rel.as_posix())
            n += 1
    return n


def restore_backup(zip_path: str | Path, workspace: str | Path, force: bool = False) -> int:
    """Unpack into a workspace. Refuses to overwrite an existing one unless force (its old database is kept as app.db.before-restore)."""
    ws = Path(workspace)
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if MARK not in names or "app.db" not in names:
            raise ValueError("this is not a PartAudit backup file")
        root = ws.resolve()
        for n in names:                                            # no path may leave the workspace
            if not (root / n).resolve().is_relative_to(root):
                raise ValueError(f"unsafe path in backup: {n}")
        db = ws / "app.db"
        if db.exists():
            if not force:
                raise FileExistsError(f"{ws} already has a workspace; use force to replace it")
            db.replace(ws / "app.db.before-restore")
        ws.mkdir(parents=True, exist_ok=True)
        for n in names:
            if n == MARK:
                continue
            z.extract(n, ws)
        return len([n for n in names if n != MARK and not n.endswith("/")])
