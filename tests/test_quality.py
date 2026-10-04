"""Single-record data quality checks and the canonical material / finish keys."""
from part_audit.model import PartRecord
from part_audit.project import ProjectSettings
from part_audit.quality import record_checks
from part_audit.scoring import finish_key, material_key


def test_material_and_finish_keys_ignore_language():
    assert material_key("פלדה 12.9") == material_key("STEEL 12.9")
    assert material_key("AL 6061-T6") == material_key("אלומיניום 6061-T6") == "aluminum 6061"
    assert material_key("STEEL C45") != material_key("STAINLESS 304")
    assert finish_key("BLACK OXIDE") == finish_key("השחרה") == "black-oxide"
    assert finish_key("CLEAR ANODIZE") == finish_key("אנודייז טבעי") != finish_key("אנודייז שחור")
    assert finish_key("PAINT RAL 7035") == finish_key("צביעה RAL 7035") != finish_key("צביעה RAL 9005")
    assert finish_key("") == ""


def _rec(uid, pn, **kw):
    base = dict(uid=f"pdm:{uid}", source_id="pdm", source_kind="swpdm_web", native_id=str(uid), kind="part", pn=pn,
                name=f"פלטה {uid}", native_file=f"{pn}.SLDPRT", material="פלדה", make_buy="make")
    base.update(kw)
    return PartRecord(**base)


def test_record_checks():
    recs = [_rec(i, f"200-{1000 + i}") for i in range(25)]
    recs += [
        _rec(100, "2001234"),                                            # format differs from the source's habit
        _rec(101, "200-1101", material=""),                              # make part without material
        _rec(102, "200-1102", native_file="200-9999.SLDPRT"),           # file name carries another PN
        _rec(103, "200-1103", mass_kg=2.0, mass_text="2.0", step_path="/x.step"),   # 1000 cm3 of steel ~ 7.85 kg
        _rec(104, "200-1104", mass_kg=7.8, mass_text="7.8", step_path="/y.step"),   # within tolerance
        _rec(105, "", name="ללא מק\"ט"),
    ]
    fps = {"pdm:103": {"closed": True, "volume": 1_000_000.0}, "pdm:104": {"closed": True, "volume": 1_000_000.0}}
    out = record_checks(recs, fps, ProjectSettings(mass_tolerance=0.10))
    by = {}
    for q in out:
        by.setdefault(q["type"], set()).update(q["uids"])
    assert by["pn_format"] == {"pdm:100"}
    assert by["missing_material"] == {"pdm:101"}
    assert by["filename_pn_mismatch"] == {"pdm:102"}
    assert by["mass_mismatch"] == {"pdm:103"}
    assert by["missing_pn"] == {"pdm:105"}
    assert "pdm:104" not in by.get("mass_mismatch", set())


def test_folder_records_are_not_held_to_pdm_rules():
    recs = [_rec(i, "", source_kind="folder", source_id="dir", material="") for i in range(3)]
    out = record_checks(recs, {}, ProjectSettings())
    assert not [q for q in out if q["type"] in ("missing_pn", "missing_material", "pn_format", "no_step")]


def test_empty_description_where_the_source_always_has_one():
    recs = [_rec(i, f"200-{1000 + i}", description=f"פלטה {i} מלאה") for i in range(24)]
    recs.append(_rec(50, "200-1050", description=""))                # the one record left empty
    out = record_checks(recs, {}, ProjectSettings())
    assert {u for q in out if q["type"] == "missing_description" for u in q["uids"]} == {"pdm:50"}
    # a source that does not use the field at all is not flagged
    recs = [_rec(i, f"200-{1000 + i}", description="") for i in range(24)]
    assert not [q for q in record_checks(recs, {}, ProjectSettings()) if q["type"] == "missing_description"]


def test_static_export_never_overwrites_a_foreign_folder(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "keep.txt").write_text("my file")
    r = subprocess.run([sys.executable, str(root / "tools" / "export_static.py"), "--workspace", str(tmp_path / "ws"),
                        "--out", str(tmp_path)], capture_output=True, text=True, timeout=120)
    assert r.returncode != 0 and (tmp_path / "keep.txt").read_text() == "my file"


def test_erp_written_without_dashes_is_compared_through_the_link():
    """The ERP writes '3001000' where the PDM writes '300-1000': same item, and the BOM is compared through it."""
    from part_audit.model import BomLine, ErpItem
    from part_audit.quality import erp_checks
    asm = _rec(1, "300-1000", kind="assembly", name="מכלול הנעה", state_class="released")
    child = _rec(2, "300-2000", name="פלטה 2", state_class="released")
    erp = [ErpItem("erp", "3001000", "מכלול הנעה"), ErpItem("erp", "3002000", "פלטה 2")]
    bom = [BomLine("erp", "3001000", "3002000", 3.0)]
    out = erp_checks([child], [asm], erp, bom, {}, {asm.uid: [(child.uid, 2.0)]}, {r.uid: r for r in (asm, child)},
                     {child.uid: [(asm.uid, 2.0)]})
    types = [q["type"] for q in out]
    assert "released_not_in_erp" not in types and "erp_without_cad" not in types
    assert types.count("pn_format") == 2                             # the different writing is reported, low severity
    diffs = [q["details"]["diffs"] for q in out if q["type"] == "erp_bom_mismatch"]
    assert diffs == [[{"child": "3002000", "pdm_qty": 2.0, "erp_qty": 3.0}]]


def test_impact_counts_the_target_by_its_erp_item():
    from part_audit.decisions import group_impact, main_currency
    g = {"erp": [{"pn": "9005961", "value": 100.0, "currency": "ILS"},
                 {"pn": "900-5962", "value": 40.0, "currency": "ILS"}],
         "pns": ["900-5961", "900-5962"],
         "where_used": [{"via": "900-5961"}, {"via": "900-5962"}, {"via": "900-5962"}]}
    imp = group_impact(g, "900-5961", "9005961")
    assert imp["redundant_stock_value"] == 40.0 and imp["bom_lines_to_update"] == 2
    assert group_impact(g, "900-5961")["redundant_stock_value"] == 140.0   # without the link: the target's own stock
    # a tie between currencies does not depend on the order of the rows (or on the run)
    assert main_currency(["USD", "ILS"]) == main_currency(["ILS", "USD"]) == "ILS"
    assert main_currency(["USD", "ILS"], default="USD") == "USD"
    assert main_currency(["EUR", "USD", "USD"]) == "USD" and main_currency([]) is None
