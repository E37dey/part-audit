"""3D display data: meshes from STEP, point-to-mesh distances, alignment and deviation maps."""
import math
import random

import numpy as np
import pytest

pytest.importorskip("OCP")

import cadops  # noqa: E402  (tools/cadops.py)
from part_audit.viewer import (MeshDistance, align_meshes, build_mesh, compare_bytes, compare_meshes,  # noqa: E402
                               mesh_bytes, parse_compare, parse_mesh, point_triangle_distance, subdivide)


def _brute_distance(p, v, t):
    best = math.inf
    for tri in t:
        a, b, c = v[tri[0]], v[tri[1]], v[tri[2]]
        # dense barycentric sampling is an upper bound; the closed form must not exceed it
        for i in range(0, 21):
            for j in range(0, 21 - i):
                q = a + (b - a) * (i / 20) + (c - a) * (j / 20)
                best = min(best, float(np.linalg.norm(p - q)))
    return best


def test_point_triangle_distance_matches_sampling():
    rng = np.random.default_rng(3)
    v = rng.normal(size=(3, 3))
    pts = rng.normal(size=(40, 3)) * 2
    d = point_triangle_distance(pts, np.repeat(v[None, 0], 40, 0), np.repeat(v[None, 1], 40, 0), np.repeat(v[None, 2], 40, 0))
    for p, x in zip(pts, d):
        ref = _brute_distance(p, v, [(0, 1, 2)])
        assert x <= ref + 1e-9            # exact distance is never above a sampled one
        assert ref - x < 0.15             # and close to it (sampling resolution)


@pytest.fixture(scope="module")
def meshes(tmp_path_factory):
    d = tmp_path_factory.mktemp("viewer")
    base = cadops.chiral_test_part()
    out = {}
    for name, shape in (("base", base), ("moved", cadops.transform(base, cadops.random_rigid(random.Random(5)))),
                        ("plate", cadops.plate_with_hole())):
        p = str(d / f"{name}.step")
        cadops.write_step(shape, p)
        out[name] = build_mesh(p)
    hole, _ = cadops.drill_hole(base, random.Random(2), 0.08)
    p = str(d / "hole.step")
    cadops.write_step(hole, p)
    out["hole"] = build_mesh(p)
    return out


def test_mesh_roundtrip(meshes):
    m = meshes["base"]
    back = parse_mesh(mesh_bytes(m))
    assert np.array_equal(back["v"], m["v"]) and np.array_equal(back["t"], m["t"])
    assert len(back["e"]) > 0 and back["bbox"] == pytest.approx(m["bbox"])


def test_subdivide_keeps_area_and_limits_edges(meshes):
    m = meshes["plate"]
    v, t = m["v"].astype(float), m["t"].astype(int)

    def area(v, t):
        return 0.5 * np.linalg.norm(np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]]), axis=1).sum()
    sv, st = subdivide(v, t, max_edge=5.0)
    assert area(sv, st) == pytest.approx(area(v, t), rel=1e-9)
    e = np.linalg.norm(sv[st[:, 1]] - sv[st[:, 0]], axis=1)
    assert e.max() <= 5.0 + 1e-9


def test_mesh_distance_on_flat_face_with_long_triangles(meshes):
    """Points in the middle of a large flat face lie on the mesh (distance ~0), even though the face is made of
    a few long triangles whose centroids are far away. The shortlist of nearest triangles is an approximation:
    the error must stay far below what the display can show (0.05% of the part size)."""
    m = meshes["plate"]
    v, t = m["v"].astype(float), m["t"].astype(int)
    dist = MeshDistance(v, t)
    rng = np.random.default_rng(0)
    tri = rng.integers(0, len(t), 400)
    w = rng.dirichlet([1, 1, 1], 400)
    pts = (v[t[tri]] * w[:, :, None]).sum(1)
    diag = float(np.linalg.norm(v.max(0) - v.min(0)))
    d = dist(pts)
    assert np.median(d) < 1e-9
    assert d.max() < 2e-4 * diag


def test_alignment_recovers_a_moved_copy(meshes):
    c = compare_meshes(meshes["base"], meshes["moved"])
    diag = c["diag_mm"]
    assert not c["mirror"]
    assert c["max_mm"] < 0.01 * diag          # same part: only display-mesh faceting remains
    M = np.array(c["matrix"]).reshape(4, 4).T  # column-major -> row-major
    vb = np.c_[meshes["moved"]["v"], np.ones(len(meshes["moved"]["v"]))] @ M.T
    assert np.abs(vb[:, :3].min(0) - meshes["base"]["v"].min(0)).max() < 0.01 * diag


def test_deviation_map_shows_the_hole_locally(meshes):
    c = compare_meshes(meshes["base"], meshes["hole"])
    back = parse_compare(compare_bytes(c))
    dev_b = back["dev_b"]
    assert back["max_mm"] > 0.5                               # the hole wall is far from the other surface
    assert back["median_mm"] < 0.05 * back["max_mm"]          # most of the surface (by area) still matches
    v, t = back["mesh_b"]["v"].astype(float), back["mesh_b"]["t"].astype(int)
    area = 0.5 * np.linalg.norm(np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]]), axis=1)
    tri_dev = dev_b[t].mean(1)
    order = np.argsort(tri_dev)
    w_median = tri_dev[order][np.searchsorted(np.cumsum(area[order]), area.sum() / 2)]
    assert w_median < 0.05 * back["max_mm"]                  # the colour map is local, not smeared
    assert len(back["mesh_b"]["v"]) == len(dev_b) and back["mesh_b"]["t"].max() < len(dev_b)
    # B's refined mesh is returned in B's own coordinates
    assert back["mesh_b"]["v"].min(0) == pytest.approx(meshes["hole"]["v"].min(0), abs=1e-3)


def test_display_alignment_never_mirrors(meshes):
    al = align_meshes(meshes["base"], meshes["moved"], proper_only=True)
    assert np.linalg.det(al["R"]) > 0
