"""L1: STEP text parsing and exact/normalized hashing."""
from part_audit.hashes import group_by, normalized_step_hash, sha256_bytes
from part_audit.stepfile import decode_step_string, encode_step_string, parse_step_text, strip_comments
from tests.conftest import make_step


def test_decode_step_string_escapes():
    assert decode_step_string("it''s") == "it's"
    assert decode_step_string("a\\\\b") == "a\\b"
    # Hebrew via \X2\ (UCS-2)
    assert decode_step_string("\\X2\\05EA05D505E905D105EA\\X0\\ 12") == "תושבת 12"
    # \X\HH latin-1 and \S\ upper half
    assert decode_step_string("caf\\X\\E9") == "café"
    assert decode_step_string("\\S\\i") == "é"
    # ISO 8859-8 (Hebrew) code page selected with \PH\
    assert decode_step_string("\\PH\\\\S\\`") == "א"


def test_encode_roundtrip():
    for s in ["Bracket 40x25", "תושבת הרכבה", "it's a \\ test", "mixed עברית and English"]:
        assert decode_step_string(encode_step_string(s)) == s


def test_strip_comments_keeps_strings():
    text = "FILE_NAME(/* name */ 'a /* not a comment */ b');"
    assert strip_comments(text) == "FILE_NAME(  'a /* not a comment */ b');"


def test_parse_header_products_units():
    info = parse_step_text(make_step(fname="x.step", system="NX", pid="PA-10234", pname="Mounting bracket"))
    assert info.is_step
    assert info.header_file_name == "x.step"
    assert info.originating_system == "NX"
    assert "AUTOMOTIVE_DESIGN" in info.schema
    assert info.products == [("PA-10234", "Mounting bracket", "")]
    assert info.length_unit == "mm"


def test_inch_unit_detected():
    text = make_step().replace("( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) )",
                               "( CONVERSION_BASED_UNIT('INCH',#99) LENGTH_UNIT() NAMED_UNIT(#98) )")
    assert parse_step_text(text).length_unit == "inch"


def test_not_step():
    assert not parse_step_text("hello world").is_step


def test_normalized_hash_ignores_header_names_whitespace_numbering():
    base = normalized_step_hash(make_step())
    assert base
    assert normalized_step_hash(make_step(fname="other.stp", ts="2025-05-05T10:00:00", system="SysB")) == base
    assert normalized_step_hash(make_step(pid="XX-9", pname="Other name", pdesc="desc")) == base
    assert normalized_step_hash(make_step().replace("\n", "\r\n").replace(" = ", "=")) == base
    assert normalized_step_hash(make_step(base=101)) == base           # entity ids shifted
    assert normalized_step_hash(make_step(x="1.50000000000")) == base  # same real, other spelling
    assert normalized_step_hash(make_step(x="1.6")) != base            # geometry differs


def test_raw_hash_and_grouping():
    a, b = make_step().encode(), make_step(ts="2030-01-01T00:00:00").encode()
    assert sha256_bytes(a) == sha256_bytes(make_step().encode())
    assert sha256_bytes(a) != sha256_bytes(b)
    groups = group_by({"f1": "h1", "f2": "h1", "f3": "h2", "f4": ""})
    assert groups == {"h1": ["f1", "f2"]}


def test_normalized_hash_ignores_colour():
    a = make_step() .replace("ENDSEC;\nEND", "#50=COLOUR_RGB('Steel',0.59,0.66,0.68);\nENDSEC;\nEND")
    b = make_step().replace("ENDSEC;\nEND", "#50=COLOUR_RGB('Blue',0.1,0.2,0.9);\nENDSEC;\nEND")
    assert normalized_step_hash(a) == normalized_step_hash(b)
