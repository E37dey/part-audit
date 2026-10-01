"""End-to-end without geometry (L1 + L2 + report)."""
from pathlib import Path

from openpyxl import load_workbook

from part_audit.audit import AuditConfig, run_audit
from part_audit.report import write_report
from tests.conftest import make_step


def _folder(tmp_path: Path) -> Path:
    root = tmp_path / "cad"
    (root / "_old").mkdir(parents=True)
    (root / "copy").mkdir()
    (root / "PA-10234_MOUNTING-BRACKET.step").write_text(make_step(pid="PA-10234", pname="MOUNTING BRACKET"))
    # byte-identical copy under another name/folder (A)
    (root / "_old" / "pa10234 brkt final.step").write_text(make_step(pid="PA-10234", pname="MOUNTING BRACKET"))
    # same DATA, other header + other product name, new PN (B-like, normalized hash)
    (root / "copy" / "PA-20871 תושבת הרכבה.step").write_text(
        make_step(fname="z.stp", ts="2030-01-01T00:00:00", pid="PA-20871", pname="tushevet"))
    # same PN, different content -> conflict (unverified without geometry)
    (root / "PA-10234 bracket rev B.step").write_text(make_step(x="9.9", pid="PA-10234", pname="bracket"))
    # unrelated part with similar words but conflicting dimensions
    (root / "PA-30000 hinge pin 8x40.step").write_text(make_step(x="2.0", pid="PA-30000", pname="hinge pin 8x40"))
    (root / "PA-30001 hinge pin 8x45.step").write_text(make_step(x="3.0", pid="PA-30001", pname="hinge pin 8x45"))
    (root / "legacy.sldprt").write_bytes(b"x")
    erp = tmp_path / "erp.csv"
    erp.write_text("part_number,description,unit,material,supplier\n"
                   "PA-10234,MOUNTING BRACKET,EA,AL 6061,Acme\n"
                   "PA-20871,תושבת הרכבה,EA,Aluminium 6061,Acme\n"
                   "PA-30000,HINGE PIN 8X40,EA,SS304,Gamma\n"
                   "PA-30001,HINGE PIN 8X45,EA,SS304,Gamma\n"
                   "PA-40000,HINGE PIN 8X40,EA,SS304,Delta\n", encoding="utf-8")
    return root, erp


def test_end_to_end_no_geometry(tmp_path: Path):
    root, erp = _folder(tmp_path)
    cfg = AuditConfig(root=str(root), erp_csv=str(erp), use_geometry=False, verbose=False)
    res = run_audit(cfg)
    cats = {(p.a, p.b): p.category for p in res.pairs}
    assert cats[("PA-10234_MOUNTING-BRACKET.step", "_old/pa10234 brkt final.step")] == "identical"
    assert cats[("PA-10234_MOUNTING-BRACKET.step", "copy/PA-20871 תושבת הרכבה.step")] == "identical"
    assert cats[("PA-10234 bracket rev B.step", "PA-10234_MOUNTING-BRACKET.step")] == "conflict_unverified"
    assert ("PA-30000 hinge pin 8x40.step", "PA-30001 hinge pin 8x45.step") not in cats
    assert len(res.groups) == 1 and len(res.groups[0]) == 3
    assert [(m["old_pn"], m["proposed_pn"]) for m in res.mapping] == [("PA-20871", "PA-10234")]
    assert all(m["status"] == "pending approval" for m in res.mapping)
    # ERP rows with the same description (also across Hebrew/English)
    assert {(d["pn_a"], d["pn_b"]) for d in res.erp_duplicates} == {("PA-30000", "PA-40000"), ("PA-10234", "PA-20871")}

    out = write_report(res, tmp_path / "r.xlsx")
    wb = load_workbook(out)
    assert wb.sheetnames == ["Summary", "Duplicate_Groups", "Near_Duplicates", "Name_Inconsistencies",
                             "PartNumber_Mapping", "ERP_vs_CAD", "Errors_Skipped"]
    ws = wb["PartNumber_Mapping"]
    headers = [c.value for c in ws[3]]
    assert "Approved (Y/N)" in headers and "Reviewer notes" in headers
    row = [c.value for c in ws[4]]
    assert row[headers.index("Old PN")] == "PA-20871" and row[headers.index("Approved (Y/N)")] is None
    skipped = [c.value for c in wb["Errors_Skipped"]["A"]][1:]
    assert "legacy.sldprt" in skipped
