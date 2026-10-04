"""Pilot kit: field discovery suggests the property for each mapping field from names and values."""
import pytest

from part_audit.connectors.base import Connector, Field
from part_audit.connectors.files import suggest_pn_regex
from part_audit.discovery import analyze, name_score, profile, target_of
from part_audit.demo import DEMO_DIR


class _Fake(Connector):
    kind = "fake"
    fields = [Field("var_material", "חומר", group="mapping", default="Materiel"),
              Field("var_mass", "משקל", group="mapping", default="Weight"),
              Field("var_number", "מק\"ט", group="mapping", default="Number"),
              Field("config", "תצורה", group="mapping", default="@")]


ROWS = [{"Number": f"200-{1000 + i}", "Material": "פלדה S235JR" if i % 2 else "AL 6061-T6", "Weight": f"{0.1 * (i + 1):.2f} kg",
         "Finish": "השחרה", "Comment": "x"} for i in range(20)]


def test_target_and_name_scores():
    assert target_of("var_material") == "material" and target_of("prop_designer") == "author"
    assert target_of("f_desc_en") == "description_en" and target_of("config") is None
    assert name_score("PTC_MATERIAL_NAME", ["material"]) >= 0.8
    assert name_score("Comment", ["material"]) < 0.5
    p = profile(ROWS)
    assert p["Material"]["fill"] == 1.0 and p["Material"]["distinct"] == 2


def test_a_wrong_name_gets_a_suggestion_and_a_right_one_does_not():
    a = analyze(_Fake, {"var_material": "Materiel", "var_mass": "Weight", "var_number": "Number"}, {"rows": ROWS})
    by = {m["field"]: m for m in a["mapping"]}
    assert set(by) == {"var_material", "var_mass", "var_number"}            # 'config' is not a property name
    assert by["var_material"]["suggested"] == "Material" and not by["var_material"]["current_found"]
    assert by["var_mass"]["suggested"] == "" and by["var_mass"]["current_fill"] == 1.0
    assert by["var_number"]["suggested"] == ""
    assert not a["warnings"]


def test_file_name_pattern_suggestion():
    stems = [f"PA-{10000 + i} bracket" for i in range(8)] + ["drawing", "old copy"]
    s = suggest_pn_regex(stems)
    assert s and s["matched"] == 8 and s["of"] == 10
    assert suggest_pn_regex(["a", "b", "c"]) is None


needs_factory = pytest.mark.skipif(not (DEMO_DIR / "factory.json").exists(), reason="demo factory not built")


@needs_factory
@pytest.mark.parametrize("kind,wrong,expect", [
    ("swpdm_web", {"var_material": "Materiel"}, ("var_material", "Material")),
    ("windchill", {"attr_mass": "MASS"}, ("attr_mass", "PRO_MP_MASS")),
    ("teamcenter", {"prop_material": "u9_mat"}, ("prop_material", "u4_material")),
    ("priority", {"f_price": "PRICE"}, ("f_price", "LASTPRICE")),
])
def test_discovery_against_the_simulators(kind, wrong, expect, tmp_path):
    from part_audit import connectors
    from part_audit.demo import demo_sources
    from part_audit.simulators import ServerThread, create_sim_app
    with ServerThread(create_sim_app(DEMO_DIR)) as srv:
        src = next(s for s in demo_sources(srv.url, DEMO_DIR) if s["kind"] == kind)
        C = connectors.get(kind)
        conn = C(src["id"], src["name"], {**src["config"], **wrong}, tmp_path)
        smp = conn.sample(20)
        a = analyze(C, conn.cfg, smp)
    by = {m["field"]: m for m in a["mapping"]}
    assert a["records"] >= 15 and by[expect[0]]["suggested"] == expect[1]
    if smp.get("step"):
        assert 0 < smp["step"]["found"] <= smp["step"]["checked"]
