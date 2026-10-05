import io
import sqlite3
import zipfile

import pytest

from part_audit import backup
from part_audit.cli import main
from part_audit.server.store import Store


def _ws(tmp_path):
    ws = tmp_path / "ws"
    st = Store(ws)
    (ws / "runs").mkdir(exist_ok=True)
    (ws / "runs" / "r1.json").write_text("{}", encoding="utf-8")
    (ws / "cache").mkdir(exist_ok=True)
    (ws / "cache" / "big.step").write_text("x", encoding="utf-8")
    return ws, st


def test_backup_has_db_and_results_not_cache(tmp_path):
    ws, _ = _ws(tmp_path)
    out = tmp_path / "b.zip"
    backup.make_backup(ws, out)
    names = zipfile.ZipFile(out).namelist()
    assert "app.db" in names and "runs/r1.json" in names and backup.MARK in names
    assert not any(n.startswith("cache/") for n in names)


def test_restore_round_trip_and_refuses_overwrite(tmp_path):
    ws, _ = _ws(tmp_path)
    out = tmp_path / "b.zip"
    backup.make_backup(ws, out)
    new = tmp_path / "new"
    backup.restore_backup(out, new)
    assert (new / "runs" / "r1.json").exists()
    sqlite3.connect(new / "app.db").execute("select count(*) from sqlite_master").fetchone()
    with pytest.raises(FileExistsError):
        backup.restore_backup(out, new)
    backup.restore_backup(out, new, force=True)
    assert (new / "app.db.before-restore").exists()


def test_restore_rejects_foreign_zip_and_path_escape(tmp_path):
    bad = tmp_path / "x.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(ValueError):
        backup.restore_backup(bad, tmp_path / "w1")
    evil = tmp_path / "e.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr(backup.MARK, "x")
        z.writestr("app.db", "x")
        z.writestr("../escape.txt", "x")
    with pytest.raises(ValueError):
        backup.restore_backup(evil, tmp_path / "w2")
    assert not (tmp_path / "escape.txt").exists()


def test_cli_and_missing_workspace(tmp_path, capsys):
    ws, _ = _ws(tmp_path)
    assert main(["backup", str(tmp_path / "c.zip"), "--workspace", str(ws)]) == 0
    assert main(["backup", str(tmp_path / "d.zip"), "--workspace", str(tmp_path / "nothing")]) == 2
    assert main(["restore", str(tmp_path / "c.zip"), "--workspace", str(tmp_path / "r")]) == 0


def test_api_backup_is_admin_only_in_team_mode():
    from part_audit.server.auth import required_role
    assert required_role("GET", "/api/backup") == "admin"
