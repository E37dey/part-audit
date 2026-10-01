"""L3b - aligned surface comparison for candidate pairs only.

Each file carries 4096 surface points sampled (area-weighted) from its mesh and
expressed in its own surface-principal frame (computed in geometry.py). Two
shapes are compared by trying the frame ambiguities (8 axis sign flips, plus
rotations around an axis when two principal values are nearly equal) and
measuring nearest-neighbour distances between the point sets:

* ``p50_rel`` / ``p95_rel`` - median / 95th percentile surface distance of the
  best proper (rotation-only) alignment, divided by the bounding-box diagonal.
* ``mirror``                - the best *improper* alignment (a reflection) fits
  much better than any rotation: mirror-image part (left/right hand).

Sampling noise is a few tenths of a percent of the part size, so this layer
separates "same overall shape" from "different shape" and detects mirror images;
small design changes are detected by the global properties in L3.
"""
from __future__ import annotations

import math
import time

import numpy as np

try:  # scipy is installed with cadquery; fall back to brute force without it
    from scipy.spatial import cKDTree as _KDTree
except Exception:  # pragma: no cover
    _KDTree = None

_SIGNS = [np.diag(s).astype(np.float64) for s in
          [(1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1), (-1, 1, 1), (1, -1, 1), (1, 1, -1), (-1, -1, -1)]]


def _rot(axis: int, theta: float) -> np.ndarray:
    c, s = math.cos(theta), math.sin(theta)
    i, j = [k for k in range(3) if k != axis]
    r = np.eye(3)
    r[i, i], r[i, j], r[j, i], r[j, j] = c, -s, s, c
    return r


def _random_rotations(n: int, seed: int = 7) -> list[np.ndarray]:
    rng = np.random.default_rng(seed)
    out = []
    for q in rng.normal(size=(n, 4)):
        q /= np.linalg.norm(q)
        w, x, y, z = q
        out.append(np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                             [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                             [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]))
    return out


_RANDOM_ROTS = _random_rotations(240)


class _NN:
    def __init__(self, pts: np.ndarray):
        self.pts = pts
        self.tree = _KDTree(pts) if _KDTree is not None else None

    def query(self, q: np.ndarray) -> np.ndarray:
        if self.tree is not None:
            return self.tree.query(q, k=1)[0]
        out = np.empty(len(q))
        for i in range(0, len(q), 512):  # brute force fallback
            d = ((q[i:i + 512, None, :] - self.pts[None, :, :]) ** 2).sum(-1)
            out[i:i + 512] = np.sqrt(d.min(1))
        return out


def _gaps(eig) -> tuple[float, float]:
    l1, l2, l3 = (max(float(x), 1e-30) for x in eig)
    return (l1 - l2) / l1, (l2 - l3) / l2


def candidate_transforms(eig_a, eig_b, tol: float = 0.03, step_deg: float = 10.0) -> tuple[list[np.ndarray], str]:
    """Transforms (applied to B in its canonical frame) that cover the frame ambiguity."""
    ga, gb = _gaps(eig_a), _gaps(eig_b)
    amb12 = min(ga[0], gb[0]) < tol
    amb23 = min(ga[1], gb[1]) < tol
    if amb12 and amb23:
        base = [np.eye(3)] + _RANDOM_ROTS
        mode = "isotropic"
    elif amb12 or amb23:
        axis = 2 if amb12 else 0
        base = [_rot(axis, math.radians(a)) for a in np.arange(0.0, 360.0, step_deg)]
        mode = "axis-12" if amb12 else "axis-23"
    else:
        base = [np.eye(3)]
        mode = "unique"
    out = []
    for r in base:
        for s in _SIGNS:
            out.append(r @ s)
    return out, mode


def compare_point_sets(pa: np.ndarray, pb: np.ndarray, eig_a, eig_b, mirror_ratio: float = 0.5) -> dict:
    """Best proper and improper alignment distances between two canonical point sets."""
    diag = float(np.linalg.norm(pa.max(0) - pa.min(0))) or 1.0
    nn_a = _NN(pa)
    transforms, mode = candidate_transforms(eig_a, eig_b)
    sub = pb[:: max(1, len(pb) // 1024)]  # coarse search on a subset
    best = {+1: (math.inf, None), -1: (math.inf, None)}
    for t in transforms:
        d = float(np.median(nn_a.query(sub @ t.T)))
        sgn = 1 if np.linalg.det(t) > 0 else -1
        if d < best[sgn][0]:
            best[sgn] = (d, t)
    res = {"mode": mode, "n_transforms": len(transforms), "diag": diag}
    for sgn, label in ((1, "proper"), (-1, "improper")):
        t = best[sgn][1]
        tb = pb @ t.T
        d_ba = nn_a.query(tb)
        d_ab = _NN(tb).query(pa)
        res[f"{label}_p50"] = max(float(np.median(d_ab)), float(np.median(d_ba))) / diag
        res[f"{label}_p95"] = max(float(np.quantile(d_ab, 0.95)), float(np.quantile(d_ba, 0.95))) / diag
    res["p50_rel"] = res["proper_p50"]
    res["p95_rel"] = res["proper_p95"]
    res["mirror"] = bool(res["improper_p50"] < mirror_ratio * res["proper_p50"] and res["proper_p50"] > 0.01)
    return res


class ShapeChecker:
    """Callable used by scoring.build_pairs for candidate pairs (lazy, memoised)."""

    def __init__(self, cache, thresholds, max_memo: int = 2000):
        self.cache = cache
        self.th = thresholds
        self.memo: dict[str, np.ndarray | None] = {}
        self.max_memo = max_memo
        self.n_checks = 0
        self.seconds = 0.0

    def _points(self, item):
        sha = (item.fp or {}).get("sha")
        if not sha or not (item.fp or {}).get("has_samples", True):
            return None
        if sha not in self.memo:
            if len(self.memo) >= self.max_memo:
                self.memo.pop(next(iter(self.memo)))
            self.memo[sha] = self.cache.get_samples(sha)
        return self.memo[sha]

    def __call__(self, ia, ib, geo) -> dict | None:
        pa, pb = self._points(ia), self._points(ib)
        if pa is None or pb is None:
            return None
        t0 = time.perf_counter()
        if geo is not None and geo.scale != 1.0:
            pb = pb * geo.scale
        res = compare_point_sets(pa, pb, ia.fp.get("surf_eig", [1, 1, 1]), ib.fp.get("surf_eig", [1, 1, 1]),
                                 self.th.mirror_ratio)
        self.n_checks += 1
        self.seconds += time.perf_counter() - t0
        return res
