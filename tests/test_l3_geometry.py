"""L3: geometry fingerprints, invariances, unit handling, pool timeouts; L3b shape check."""
import math
import random

import pytest

pytest.importorskip("OCP")

import cadops  # noqa: E402  (tools/cadops.py)
from part_audit.geometry import TimeoutPool, fingerprint_files, fingerprint_path  # noqa: E402
from part_audit.scoring import Item, Thresholds, compare_geometry  # noqa: E402
from part_audit.shape import compare_point_sets  # noqa: E402


@pytest.fixture(scope="module")
def parts(tmp_path_factory):
    d = tmp_path_factory.mktemp("parts")
    rng = random.Random(1)
    base = cadops.chiral_test_part()
    paths = {}

    def w(name, shape, **kw):
        p = str(d / f"{name}.step")
        cadops.write_step(shape, p, **kw)
        paths[name] = p

    w("base", base)
    w("reexport_ap203", base, schema="AP203")
    w("rotated", cadops.transform(base, cadops.random_rigid(rng)))
    w("inch_file", base, unit="INCH")                          # same part, file in inches
    w("unit_error", cadops.uniform_scale(base, 1 / 25.4))      # numbers /25.4 but declared mm
    w("mirror", cadops.mirror(base))
    hole, _ = cadops.drill_hole(base, rng, 0.08)
    w("hole", hole)
    w("other", cadops.plate_with_hole())
    fps, errs, stats, cache = fingerprint_files([(k, v, k) for k, v in paths.items()], workers=2, timeout_s=60)
    assert not errs
    return fps, cache


def _geo(fps, a, b, scale=1.0):
    return compare_geometry(fps[a], fps[b], Thresholds(), scale)


def test_fingerprint_basic(parts):
    fps, _ = parts
    fp = fps["base"]
    assert fp["ok"] and fp["closed"] and fp["n_solids"] == 1
    assert fp["volume"] == pytest.approx(30 * 5 * 5 + 15 * 5 * 5 + 5 * 5 * 5, rel=1e-9)
    assert sorted(fp["bbox_pca"], reverse=True) == fp["bbox_pca"] and len(fp["bbox_pca"]) == 3
    assert set(fp["surf_counts"]) == {"plane"}


@pytest.mark.parametrize("other", ["reexport_ap203", "rotated", "inch_file"])
def test_invariant_copies_are_identical(parts, other):
    g = _geo(parts[0], "base", other)
    assert g.relation == "identical", g
    assert g.max_rel < 1e-6


def test_unit_error_detected_as_scale(parts):
    fps, _ = parts
    assert _geo(fps, "base", "unit_error").relation == "different"
    g = _geo(fps, "base", "unit_error", scale=25.4)
    assert g.relation == "unit_scaled" and "inch" in g.unit_note


def test_hole_is_near_not_identical(parts):
    g = _geo(parts[0], "base", "hole")
    assert g.relation == "near" and 1e-4 < g.max_rel < 0.05


def test_other_part_is_different(parts):
    assert _geo(parts[0], "base", "other").relation == "different"


def test_mirror_has_identical_properties_but_l3b_detects_it(parts):
    fps, cache = parts
    assert _geo(fps, "base", "mirror").relation == "identical"  # properties cannot see handedness
    pa, pm, pr = (cache.get_samples(fps[k]["sha"]) for k in ("base", "mirror", "rotated"))
    res = compare_point_sets(pa, pm, fps["base"]["surf_eig"], fps["mirror"]["surf_eig"])
    assert res["mirror"] and res["improper_p50"] < 0.01
    res2 = compare_point_sets(pa, pr, fps["base"]["surf_eig"], fps["rotated"]["surf_eig"])
    assert not res2["mirror"] and res2["p50_rel"] < 0.01


def test_pool_timeout_crash_and_errors():
    got = {}
    tasks = [("a", 0.0), ("slow", 30.0), ("b", 0.0)]
    TimeoutPool("tests._pool_tasks:sleepy", 2, timeout_s=2).run(tasks, lambda t, st, p, s: got.setdefault(t, st))
    assert got == {"a": "ok", "b": "ok", "slow": "timeout"}
    got.clear()
    TimeoutPool("tests._pool_tasks:crash", 1, timeout_s=10).run([("c", 0)], lambda t, st, p, s: got.setdefault(t, (st, p)))
    assert got["c"][0] == "crash"
    got.clear()
    TimeoutPool("tests._pool_tasks:boom", 1, timeout_s=10).run([("d", 0)], lambda t, st, p, s: got.setdefault(t, (st, p)))
    assert got["d"] == ("err", "ValueError: bad file")


def test_unreadable_step_reported(tmp_path):
    bad = tmp_path / "bad.step"
    bad.write_text("ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\n#1=FOO(;\nENDSEC;\nEND-ISO-10303-21;\n")
    fps, errs, _, _ = fingerprint_files([("bad", str(bad), "x")], workers=1, timeout_s=30)
    assert "bad" in errs and errs["bad"][0] in ("geometry read error", "no usable geometry")


def test_cache_roundtrip(tmp_path, parts):
    p = tmp_path / "p.step"
    cadops.write_step(cadops.plate_with_hole(), str(p))
    a = fingerprint_files([("p", str(p), "sha-p")], workers=1, timeout_s=30, cache_dir=str(tmp_path / "c"))
    b = fingerprint_files([("p", str(p), "sha-p")], workers=1, timeout_s=30, cache_dir=str(tmp_path / "c"))
    assert a[2]["computed"] == 1 and b[2]["cached"] == 1
    assert math.isclose(a[0]["p"]["volume"], b[0]["p"]["volume"])
    assert b[3].get_samples("sha-p").shape == (4096, 3)
