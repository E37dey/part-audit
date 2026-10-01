"""L2: part-number / description normalization and fuzzy matching."""
import pytest

from part_audit.names import (blocking_pairs, compare_names, extract_part_numbers, is_generic_product_name,
                              parse_name, phonetic_key, pn_core, pn_key)


@pytest.mark.parametrize("raw,key", [
    ("PA-10234", "PA10234"), ("pa10234", "PA10234"), ("PA_010234", "PA10234"), ("pa.10234", "PA10234"),
    ("100-2345-01", "10023451"), ("100-02345-1", "10023451"),
])
def test_pn_key(raw, key):
    assert pn_key(raw) == key


def test_pn_core():
    assert pn_core("PA-010234") == "10234"
    assert pn_core("XB-10234") == pn_core("10234")


def test_extract_part_numbers():
    assert extract_part_numbers("PA-10234_MOUNTING-BRACKET") == ["PA-10234"]
    assert extract_part_numbers("bracket10234_v2") == ["10234"]
    assert extract_part_numbers("BRACKET 40X25") == []          # dimensions are not part numbers
    assert extract_part_numbers("bracket_20190529") == []       # dates are not part numbers
    assert extract_part_numbers("100-2345-01 spacer") == ["100-2345-01"]


def test_noise_words_removed():
    n = parse_name("Copy of PA_010234 Mounting Bracket rev B FINAL (2) old")
    assert n.pn_keys == ["PA10234"]
    assert sorted(n.words) == ["bracket", "mount"]
    assert n.numbers == []


def test_hebrew_translation_and_prefixes():
    assert sorted(parse_name("תושבת הרכבה").words) == ["bracket", "mount"]
    assert parse_name("והתושבת").words == ["bracket"]                   # prefix letters stripped
    assert parse_name("בורג M6x20 ישן").words == ["screw"]              # ישן (old) is noise
    assert parse_name("גלגל שיניים").words == ["gear"]                  # phrase


def test_transliterated_hebrew():
    assert phonetic_key("תושבת") == phonetic_key("tushevet")
    assert sorted(parse_name("tushevet harkava").words) == ["bracket", "mount"]


def test_abbreviations_and_word_order():
    a, b = parse_name("MTG BRKT"), parse_name("bracket, mounting")
    assert a.canon == b.canon == "bracket mount"


def test_numbers_normalized():
    assert parse_name("PLATE 2,50MM").numbers == ["2.5"]
    assert parse_name("plate 2.5 mm").numbers == ["2.5"]
    assert parse_name("SPACER 040X025").numbers == ["40x25"]


def test_compare_same_pn_different_format():
    m = compare_names(parse_name("PA-10234 bracket"), parse_name("pa010234_brkt_final"))
    assert m.pn_relation == "same" and m.score == 1.0


def test_compare_translation_variant():
    m = compare_names(parse_name("PA-10234 MOUNTING BRACKET"), parse_name("תושבת הרכבה"))
    assert m.score >= 0.95


def test_dimension_conflict_lowers_score():
    same = compare_names(parse_name("MOUNTING BRACKET 40X25"), parse_name("bracket mounting 40x25"))
    diff = compare_names(parse_name("MOUNTING BRACKET 40X25"), parse_name("MOUNTING BRACKET 40X30"))
    assert same.score >= 0.95
    assert diff.number_relation == "conflict" and diff.score <= 0.5


def test_one_digit_pn_difference_is_weak_evidence():
    m = compare_names(parse_name("PA-10234 BRACKET 40X25"), parse_name("PA-10235 BRACKET 40X30"))
    assert m.pn_relation == "typo"
    assert m.score < 0.7


def test_generic_product_names():
    for g in ["Part1", "Body", "", "NONE", "Blob3", "Open CASCADE STEP translator 7.8 1", "5ae2de131ced560fc658f4d5"]:
        assert is_generic_product_name(g), g
    assert not is_generic_product_name("PA-10234 Mounting bracket")


def test_blocking_finds_variants_not_everything():
    items = {
        "a": [parse_name("PA-10234 mounting bracket")],
        "b": [parse_name("pa10234 brkt")],                 # same PN
        "c": [parse_name("PA-10243 support arm")],          # transposed digits
        "d": [parse_name("hinge pin 8x40")],
        "e": [parse_name("pin hinge 8x40 old")],           # word order
        "f": [parse_name("gear")],
    }
    pairs = blocking_pairs(items)
    assert ("a", "b") in pairs and ("a", "c") in pairs and ("d", "e") in pairs
    assert not any("f" in p for p in pairs)
