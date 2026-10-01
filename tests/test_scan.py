"""Scanner and ERP loader."""
from pathlib import Path

from part_audit.scan import load_erp, scan_folder
from tests.conftest import make_step


def test_scan_folder_finds_step_and_skips_native(tmp_path: Path):
    (tmp_path / "a" / "_old").mkdir(parents=True)
    (tmp_path / "a" / "PA-1 bracket.step").write_text(make_step())
    (tmp_path / "a" / "_old" / "copy.STP").write_text(make_step())
    (tmp_path / "a" / "x.sldprt").write_bytes(b"\x00\x01")
    (tmp_path / "a" / "notes.txt").write_text("ignore me")
    (tmp_path / "a" / "broken.step").write_text("not a step file")
    recs, skipped = scan_folder(tmp_path)
    ids = sorted(r.file_id for r in recs)
    assert ids == ["a/PA-1 bracket.step", "a/_old/copy.STP", "a/broken.step"]
    good = [r for r in recs if not r.error]
    assert len({r.sha256 for r in good}) == 1 and len({r.norm_sha256 for r in good}) == 1
    reasons = {s.file_id: s.reason for s in skipped}
    assert reasons["a/x.sldprt"] == "unsupported CAD format"
    assert reasons["a/broken.step"] == "unreadable STEP file"
    rec = next(r for r in recs if r.file_id == "a/PA-1 bracket.step")
    assert rec.folder == "a" and rec.products[0][0] == "PA-1" and rec.length_unit == "mm"


def test_load_erp_hebrew_headers_cp1255(tmp_path: Path):
    text = 'מק"ט;תיאור;יחידה;חומר;ספק\nPA-1;תושבת הרכבה;יח\';אלומיניום;ספק א\nPA-2;בורג M6;יח\';פלדה;ספק ב\n'
    p = tmp_path / "erp.csv"
    p.write_bytes(text.encode("cp1255"))
    df = load_erp(p)
    assert list(df["part_number"]) == ["PA-1", "PA-2"]
    assert df.loc[0, "description"] == "תושבת הרכבה"
    assert df.loc[1, "material"] == "פלדה"
    assert list(df["erp_row"]) == [2, 3]


def test_load_erp_english_utf8_bom(tmp_path: Path):
    p = tmp_path / "erp.csv"
    p.write_text("Part Number,Description,UOM,Material,Vendor\nPA-1,BRACKET,EA,AL6061,Acme\n,empty,,,\n",
                 encoding="utf-8-sig")
    df = load_erp(p)
    assert len(df) == 1 and df.loc[0, "unit"] == "EA" and df.loc[0, "supplier"] == "Acme"
