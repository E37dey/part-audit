"""Shape search: the parts whose shape is closest to a given one.

A shape is described by numbers that do not depend on where the part lies, how it is turned, or how big it is:

* the proportions of its tight bounding box (middle / longest side, shortest / longest side)
* how much of that box it fills (volume / box volume) and how much surface it has compared with the box
* what its surface is made of (share of the area: plane, cylinder, cone, sphere, torus, free-form)
* its D2 shape distribution: the histogram of the distances between random pairs of points on its surface,
  relative to its size (Osada, Funkhouser, Chazelle and Dobkin, "Shape distributions", 2002)

The distance of two shapes is the weighted L1 distance of these numbers plus a small term for a difference in size,
so that among equally close shapes those of a similar size come first. It ranks shapes; it is not a probability. The
engine's own verdicts (the same part, near-identical) come from the full comparison, not from this ranking.
"""
from __future__ import annotations

import math

import numpy as np

TYPES = ("plane", "cylinder", "cone", "sphere", "torus")
W_ASPECT, W_FILL, W_SURF, W_TYPES, W_D2, W_SIZE = 2.0, 1.5, 0.7, 1.0, 3.0, 0.5
D2_BINS = 16
_PAIRS = np.random.default_rng(20261004).integers(0, 4096, size=(20000, 2))   # enough pairs that sampling noise stays small


def shape_vector(fp: dict, pts: np.ndarray | None) -> np.ndarray | None:
    """The shape numbers of one part (fingerprint + its canonical surface samples), or None without geometry."""
    if not fp or not fp.get("ok") or not fp.get("bbox_pca") or pts is None or len(pts) < 64:
        return None
    b = sorted((float(x) for x in fp["bbox_pca"]), reverse=True)
    b1 = max(b[0], 1e-9)
    box = max(b[0] * b[1] * b[2], 1e-12)
    fill = min(abs(fp["volume"]) / box, 1.0) if fp.get("closed") else 0.5
    surf = min(fp["area"] / max(2 * (b[0] * b[1] + b[0] * b[2] + b[1] * b[2]), 1e-12), 3.0)
    fr = fp.get("surf_area_frac") or {}
    types = [float(fr.get(t, 0.0)) for t in TYPES]
    types.append(max(0.0, 1.0 - sum(types)))
    pairs = _PAIRS[(_PAIRS < len(pts)).all(1)]
    d = np.linalg.norm(pts[pairs[:, 0]] - pts[pairs[:, 1]], axis=1)
    h, _ = np.histogram(d / max(float(d.max()), 1e-9), bins=D2_BINS, range=(0.0, 1.0))
    h = h / max(h.sum(), 1)
    return np.concatenate([np.array([b[1] / b1, b[2] / b1]) * W_ASPECT, [fill * W_FILL, surf * W_SURF],
                           np.array(types) * W_TYPES, h * W_D2]).astype(np.float64)


def size_of(fp: dict) -> float:
    """Log of the bounding-box diagonal (mm)."""
    return math.log(max(float(np.linalg.norm(fp.get("bbox_pca") or [1.0])), 1e-9))


class ShapeIndex:
    """Shape numbers of every part of a scan that has a readable model."""

    def __init__(self, uids: list[str], vectors: np.ndarray, sizes: np.ndarray):
        self.uids = uids
        self.pos = {u: i for i, u in enumerate(uids)}
        self.V = vectors
        self.S = sizes

    def __contains__(self, uid: str) -> bool:
        return uid in self.pos

    def __len__(self) -> int:
        return len(self.uids)

    @staticmethod
    def build(items: dict, samples) -> "ShapeIndex":
        """items: uid -> engine Item (with its fingerprint, as in precheck.RunIndex); samples: get_samples(sha)."""
        uids, vecs, sizes = [], [], []
        for uid, it in sorted(items.items()):
            fp = it.fp or {}
            if not fp.get("has_samples") or not fp.get("sha"):
                continue
            v = shape_vector(fp, samples.get_samples(fp["sha"]))
            if v is not None:
                uids.append(uid)
                vecs.append(v)
                sizes.append(size_of(fp))
        return ShapeIndex(uids, np.array(vecs) if vecs else np.zeros((0, 2 + 2 + 6 + D2_BINS)), np.array(sizes))

    def nearest(self, vec: np.ndarray, size: float, k: int = 10, exclude: set[str] | frozenset = frozenset()) -> list[tuple[str, float]]:
        if not len(self.uids):
            return []
        d = np.abs(self.V - vec).sum(1) + W_SIZE * np.abs(self.S - size)
        out = []
        for i in np.argsort(d, kind="stable"):
            if self.uids[i] in exclude:
                continue
            out.append((self.uids[i], float(d[i])))
            if len(out) >= k:
                break
        return out

    def nearest_to(self, uid: str, k: int = 10) -> list[tuple[str, float]]:
        i = self.pos[uid]
        return self.nearest(self.V[i], float(self.S[i]), k, exclude={uid})


def relation_of(a: dict, b: dict, pair: dict | None) -> str:
    """What the engine says about two parts of the scan: the same duplicate group, its pair verdict, or nothing."""
    if a.get("group_id") and a.get("group_id") == b.get("group_id"):
        return "same_group"
    if pair and pair.get("category"):
        return pair["category"]
    return "similar"
