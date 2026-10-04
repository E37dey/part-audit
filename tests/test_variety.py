"""Variety: standard parts by specification, designed parts by family; counted, never estimated."""
from part_audit.variety import analyze, family_of


def _p(uid, pn, name, spec_key="", spec="", group=None, used=0, erp=None, bbox=(10, 20, 30), material="", mk=""):
    return {"uid": uid, "pn": pn, "name": name, "kind": "part", "source": "PDM", "source_kind": "folder",
            "state_class": "released", "spec_key": spec_key, "spec": spec, "group_id": group, "used_in": used,
            "erp": erp, "bbox": list(bbox), "volume_mm3": 1.0, "material": material, "material_key": mk, "has_step": True}


def test_families_follow_the_name_in_both_languages():
    assert family_of("תושבת זוויתית 80x80x60") == "bracket" == family_of("BRACKET,ANGLE,90X70X60")
    assert family_of("Motor base plate 220x160x12") == "plate" == family_of("פלטת צד 280x140x10")
    assert family_of("טבעת נעילה לציר Ø25") == "collar"          # a shaft collar is a collar, not a shaft
    assert family_of("CLAMP BLOCK 120x50x35") == family_of("בלוק הידוק 80x40x30") == "block"


def test_counts_specifications_part_numbers_designs_and_use():
    erp = lambda pn, stock, cost: {"pn": pn, "stock": stock, "unit_cost": cost, "currency": "ILS"}  # noqa: E731
    parts = [
        _p("a", "900-1", "בורג אלן M6x20", "shcs|M6|20|12.9|", "M6x20 DIN 912 12.9", group="G1", used=2, erp=erp("900-1", 100, 0.5)),
        _p("b", "N-1", "SCREW M6X20", "shcs|M6|20|12.9|", "M6x20 ISO 4762 12.9", group="G1", used=1, erp=erp("N-1", 50, 0.4)),
        _p("c", "900-2", "בורג אלן M6x25", "shcs|M6|25|12.9|", "M6x25 DIN 912 12.9", used=0),
        _p("d", "200-1", "מרווח 6.4/12x10", group="G2", used=1, bbox=(12, 12, 10), material="אלומיניום 6061", mk="aluminum 6061"),
        _p("e", "200-2", "SPACER 6.4/12x10", group="G2", used=0, bbox=(12, 12, 10), material="AL 6061", mk="aluminum 6061"),
        _p("f", "200-3", "מרווח 6.4/12x20", used=0, bbox=(20, 12, 12), material="POM", mk="pom"),
    ]
    res = {"parts": parts, "groups": [{"id": "G1", "members": ["a", "b"], "master_uid": "a"},
                                      {"id": "G2", "members": ["d", "e"], "master_uid": "d"}],
           "erp_bom": [{"parent": "X", "child": "900-1", "qty": 4}], "summary": {"currency": "ILS"}}
    v = analyze(res)
    k = v["standard"][0]
    assert (k["kind"], k["specs"], k["pns"], k["extra_pns"], k["unused_specs"]) == ("shcs", 2, 3, 1, 1)
    m6x20 = k["rows"][0]
    assert m6x20["pns"] == ["900-1", "N-1"] and m6x20["used"] == 2 + 1 + 1        # PDM lines + one ERP BOM line
    assert m6x20["stock"] == 150 and m6x20["value"] == 70.0
    f = next(x for x in v["families"] if x["family"] == "spacer")
    assert (f["records"], f["designs"], f["sizes"], f["materials"], f["unused"], f["duplicated"]) == (3, 2, 2, 2, 1, 1)
    d = f["rows"][0]
    assert d["group_id"] == "G2" and d["pns"] == ["200-1", "200-2"] and d["used"] == 1
    assert v["summary"]["standard_extra_pns"] == 1 and v["summary"]["designs"] == 2
