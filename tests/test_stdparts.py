"""Standard-part designations: DIN/ISO equivalence, grades, bearing seals."""
from part_audit.stdparts import compare_specs, parse_spec


def test_din_and_iso_socket_screw_are_the_same_spec():
    a = parse_spec("בורג אלן ראש גלילי M8x20 DIN 912 12.9")
    b = parse_spec("SOCKET HEAD CAP SCREW M8x20 ISO 4762 12.9")
    assert a and b
    assert (a.kind, a.size, a.length, a.grade) == (b.kind, b.size, b.length, b.grade) == (a.kind, "M8", "20", "12.9")
    assert compare_specs(a, b)[0] == "same"


def test_grade_and_length_differences():
    base = parse_spec("SCREW SOCKET HEAD M8x20 DIN 912 12.9")
    assert compare_specs(base, parse_spec("SCREW SOCKET HEAD M8x20 DIN 912 8.8"))[0] == "spec_conflict"
    assert compare_specs(base, parse_spec("SCREW SOCKET HEAD M8x20 DIN 912 A2"))[0] == "spec_conflict"
    assert compare_specs(base, parse_spec("SCREW SOCKET HEAD M8x25 DIN 912 12.9"))[0] == "different_size"


def test_grade_stated_on_one_side_only_is_not_a_conflict():
    rel, note = compare_specs(parse_spec("M6x16 DIN 933 8.8"), parse_spec("בורג ראש משושה M6x16 DIN 933"))
    assert rel == "same" and "grade" in note


def test_bearing_seal_types():
    a = parse_spec("מסב כדורי 6205-2RS")
    b = parse_spec("BALL BEARING 6205 2RS1")
    c = parse_spec("BALL BEARING 6205-ZZ")
    assert a.size == b.size == c.size == "6205"
    assert a.seal == b.seal == "2RS" and c.seal == "ZZ"
    assert compare_specs(a, b)[0] == "same"
    assert compare_specs(a, c)[0] == "spec_conflict"


def test_not_a_standard_part():
    assert parse_spec("פלטת חיבור 100x60x8") is None
    assert parse_spec("") is None


def test_different_part_types_with_same_size():
    nut = parse_spec("אום משושה M8 DIN 934")
    screw = parse_spec("בורג ראש משושה M8x20 DIN 933")
    assert compare_specs(nut, screw)[0] == "different_type"
