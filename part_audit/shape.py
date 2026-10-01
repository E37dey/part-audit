"""L3b - aligned surface comparison for candidate pairs only.

Each file carries 4096 surface points sampled (area-weighted) from its mesh and
expressed in its own surface-principal frame (computed in geometry.py). Two
shapes are compared by trying the frame ambiguities (8 axis sign flips, plus
rotations around an axis when two principal values are nearly equal) and
measuring nearest-neighbour (NN) distances between the two point sets.

Random sampling alone produces NN distances even between identical surfaces:
for n uniform points on area A the NN distance follows P(d > r) = exp(-n*pi*r^2/A),
so the median is 0.47*sqrt(A/n) and the 95th percentile 0.98*sqrt(A/n). Distances
are therefore reported as *excess* over that noise (1.0 = indistinguishable from
the same surface) and, for people, as a share of the bounding-box diagonal.

* ``excess50`` / ``excess95`` - best rotation-only alignment, median / p95 NN
  distance divided by the sampling-noise level.
* ``mirror`` - a reflection fits at noise level while no rotation does:
  mirror-image (left/right-hand) part.
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
NOISE50 = math.sqrt(math.log(2) / math.pi)    # 0.470 * sqrt(A/n)
NOISE95 = math.sqrt(math.log(20) / math.pi)   # 0.977 * sqrt(A/n)


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
            # thread pool only pays off for the full 4096-point queries
            return self.tree.query(q, k=1, workers=-1 if len(q) >= 2048 else 1)[0]
        out = np.empty(len(q))
        for i in range(0, len(q), 512):  # brute force fallback
            d = ((q[i:i + 512, None, :] - self.pts[None, :, :]) ** 2).sum(-1)
            out[i:i + 512] = np.sqrt(d.min(1))
        return out


def _gaps(eig) -> tuple[float, float]:
    l1, l2, l3 = (max(float(x), 1e-30) for x in eig)
    return (l1 - l2) / l1, (l2 - l3) / l2


def candidate_transforms(eig_a, eig_b, tol: float = 0.03, step_deg: float = 5.0):
    """Transforms (applied to B in its canonical frame) that cover the frame ambiguity.

    Returns (list of (transform, axis, angle_deg, sign_matrix)), mode). ``axis`` is None when no
    rotation search is needed."""
    ga, gb = _gaps(eig_a), _gaps(eig_b)
    amb12 = min(ga[0], gb[0]) < tol
    amb23 = min(ga[1], gb[1]) < tol
    out = []
    if amb12 and amb23:
        mode = "isotropic"
        for r in [np.eye(3)] + _RANDOM_ROTS:
            out += [(r @ s, None, 0.0, s) for s in _SIGNS]
    elif amb12 or amb23:
        axis = 2 if amb12 else 0
        mode = "axis-12" if amb12 else "axis-23"
        for a in np.arange(0.0, 360.0, step_deg):
            r = _rot(axis, math.radians(a))
            out += [(r @ s, axis, float(a), s) for s in _SIGNS]
    else:
        mode = "unique"
        out = [(s.copy(), None, 0.0, s) for s in _SIGNS]
    return out, mode


def compare_point_sets(pa: np.ndarray, pb: np.ndarray, eig_a, eig_b, area: float, mirror_ratio: float = 0.6) -> dict:
    """Best proper and improper alignment of two canonical point sets (same length unit).

    ``area`` is the surface area (same unit squared) used for the sampling-noise level.
    """
    diag = float(np.linalg.norm(pa.max(0) - pa.min(0))) or 1.0
    n = min(len(pa), len(pb))
    spacing = math.sqrt(max(area, 1e-30) / n)
    n50, n95 = NOISE50 * spacing, NOISE95 * spacing
    nn_a = _NN(pa)
    transforms, mode = candidate_transforms(eig_a, eig_b)
    sub = pb[:: max(1, len(pb) // 1024)]     # refinement subset
    coarse = pb[:: max(1, len(pb) // 256)]   # coarse-grid subset

    def score(t, pts=sub) -> float:  # mean NN distance: more sensitive to small features than the median
        return float(nn_a.query(pts @ t.T).mean())

    cands: dict[int, list] = {1: [], -1: []}
    for t, axis, ang, sg in transforms:
        sgn = 1 if np.linalg.det(t) > 0 else -1
        cands[sgn].append((score(t, coarse if len(transforms) > 8 else sub), t, axis, ang, sg))
    n_eval = len(transforms)
    best = {}
    for sgn in (1, -1):
        ranked = sorted(cands[sgn], key=lambda c: c[0])
        best[sgn] = ranked[0]
        if len(transforms) > 8:  # rescore the coarse winners on the larger subset
            ranked = sorted(((score(c[1]),) + c[1:] for c in ranked[:6]), key=lambda c: c[0])
            best[sgn] = ranked[0]
        if ranked[0][2] is None:
            continue
        # rotation search: refine the 3 best coarse angles (5 deg grid) in 0.5 deg steps, otherwise a
        # rotated copy can look worse than a reflection that happens to fall on the grid
        for d0, t0, axis, ang, sg in ranked[:3]:
            for da in np.arange(-4.0, 4.01, 0.5):
                t = _rot(axis, math.radians(ang + da)) @ sg
                d = score(t)
                n_eval += 1
                if d < best[sgn][0]:
                    best[sgn] = (d, t, axis, ang + da, sg)
    res = {"mode": mode, "n_transforms": n_eval, "diag": diag, "noise95_rel": n95 / diag}
    for sgn, label in ((1, "proper"), (-1, "improper")):
        t = best[sgn][1]
        tb = pb @ t.T
        d_ba = nn_a.query(tb)
        d_ab = _NN(tb).query(pa)
        p50 = max(float(np.median(d_ab)), float(np.median(d_ba)))
        p95 = max(float(np.quantile(d_ab, 0.95)), float(np.quantile(d_ba, 0.95)))
        res[f"{label}_excess50"] = p50 / n50
        res[f"{label}_excess95"] = p95 / n95
        res[f"{label}_p95_rel"] = p95 / diag
    res["excess50"] = res["proper_excess50"]
    res["excess95"] = res["proper_excess95"]
    res["p95_rel"] = res["proper_p95_rel"]
    strong = (res["improper_excess95"] < 1.5 and res["proper_excess95"] > 2.0
              and res["improper_excess95"] < mirror_ratio * res["proper_excess95"])
    # subtle handedness: the reflection fits at noise level and clearly better than any rotation; only
    # trusted when the principal frame is unique (no rotation search that could miss the best angle)
    subtle = (mode == "unique" and res["improper_excess50"] < 1.2
              and res["proper_excess50"] - res["improper_excess50"] > 0.4)
    res["mirror"] = bool(strong or subtle)
    return res


def _job_args(ia, ib, geo, mirror_ratio):
    fa, fb = ia.fp or {}, ib.fp or {}
    if not (fa.get("has_samples") and fb.get("has_samples") and fa.get("sha") and fb.get("sha")):
        return None
    return (fa["sha"], fa["sample_scale"], fb["sha"], fb["sample_scale"], 1.0 if geo is None else geo.scale,
            fa.get("surf_eig", [1, 1, 1]), fb.get("surf_eig", [1, 1, 1]),
            fa.get("sample_area") or fa.get("area", 0.0), mirror_ratio)


_WORKER_CACHE = None


def _init_worker(cache_dir):
    global _WORKER_CACHE
    from .geometry import FingerprintCache
    _WORKER_CACHE = FingerprintCache(cache_dir)


def _run_job(args):
    sha_a, sc_a, sha_b, sc_b, scale, eig_a, eig_b, area, ratio = args
    pa, pb = _WORKER_CACHE.get_samples(sha_a), _WORKER_CACHE.get_samples(sha_b)
    if pa is None or pb is None:
        return None
    return compare_point_sets(pa * sc_a, pb * sc_b * scale, eig_a, eig_b, area, ratio)


class ShapeChecker:
    """Callable used by scoring.build_pairs for candidate pairs (lazy, memoised).

    ``prefetch`` runs many checks in worker processes (they read the samples from the SQLite cache)."""

    def __init__(self, cache, thresholds, max_memo: int = 2000, workers: int = 1, cache_dir: str | None = None):
        self.cache = cache
        self.th = thresholds
        self.memo: dict[str, np.ndarray | None] = {}
        self.max_memo = max_memo
        self.n_checks = 0
        self.seconds = 0.0
        self.workers = workers
        self.cache_dir = cache_dir
        self.done: dict[tuple, dict | None] = {}

    def prefetch(self, jobs) -> None:
        if self.workers <= 1 or not self.cache_dir or len(jobs) < 20:
            return
        import multiprocessing as mp
        import sys as _sys
        keyed = []
        for ia, ib, geo in jobs:
            args = _job_args(ia, ib, geo, self.th.mirror_ratio)
            if args is not None:
                keyed.append(((ia.file_id, ib.file_id, args[4]), args))
        if not keyed:
            return
        t0 = time.perf_counter()
        ctx = mp.get_context("fork" if _sys.platform.startswith("linux") else "spawn")
        with ctx.Pool(self.workers, initializer=_init_worker, initargs=(self.cache_dir,)) as pool:
            for (key, _), res in zip(keyed, pool.imap(_run_job, [a for _, a in keyed], chunksize=8)):
                self.done[key] = res
        self.n_checks += len(keyed)
        self.seconds += time.perf_counter() - t0

    def _points(self, item):
        fp = item.fp or {}
        sha = fp.get("sha")
        if not sha or not fp.get("has_samples") or not fp.get("sample_scale"):
            return None
        if sha not in self.memo:
            if len(self.memo) >= self.max_memo:
                self.memo.pop(next(iter(self.memo)))
            pts = self.cache.get_samples(sha)
            self.memo[sha] = None if pts is None else pts * fp["sample_scale"]
        return self.memo[sha]

    def __call__(self, ia, ib, geo) -> dict | None:
        key = (ia.file_id, ib.file_id, 1.0 if geo is None else geo.scale)
        if key in self.done:
            return self.done[key]
        pa, pb = self._points(ia), self._points(ib)
        if pa is None or pb is None:
            return None
        t0 = time.perf_counter()
        area = ia.fp.get("sample_area") or ia.fp.get("area", 0.0)
        if geo is not None and geo.scale != 1.0:
            pb = pb * geo.scale
        res = compare_point_sets(pa, pb, ia.fp.get("surf_eig", [1, 1, 1]), ib.fp.get("surf_eig", [1, 1, 1]),
                                 area, self.th.mirror_ratio)
        self.n_checks += 1
        self.seconds += time.perf_counter() - t0
        return res
