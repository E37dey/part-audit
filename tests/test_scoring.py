"""L5 scoring helpers."""
import importlib.util
from pathlib import Path

from part_audit.scoring import material_key, materials_conflict


def test_material_key_equivalences_and_differences():
    spec = importlib.util.spec_from_file_location("bd", Path(__file__).resolve().parents[1] / "tools" / "build_dataset.py")
    bd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bd)
    keys = []
    for styles in bd.MATERIALS:          # every spelling of one material maps to one key
        ks = {material_key(x) for x in styles}
        assert len(ks) == 1, styles
        keys.append(ks.pop())
    assert len(set(keys)) == len(keys)   # different materials stay different
    assert material_key("SS-316") == material_key("נירוסטה 316") == "stainless 316"
    assert material_key("ST37") == material_key("Steel ST37") == "steel 37"


def test_materials_conflict_rules():
    assert not materials_conflict(material_key("Aluminium"), material_key("AL 6061"))   # grade unspecified
    assert materials_conflict(material_key("AL 6061"), material_key("AL 7075"))
    assert materials_conflict(material_key("AL 6061"), material_key("SS 304"))
    assert not materials_conflict(material_key("Delrin"), material_key("POM"))
    assert materials_conflict(material_key("POM"), material_key("PEEK"))
    assert not materials_conflict("", material_key("POM"))
