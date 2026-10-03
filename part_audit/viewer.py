"""3D data for the app: triangle meshes with CAD edges, and alignment + deviation maps between two parts.

Mesh binary format (little-endian):
    b"PAM1", uint32 n_vertices, uint32 n_triangles, uint32 n_edge_points, float32[6] bbox,
    float32[n_vertices*3] positions, uint32[n_triangles*3] indices, float32[n_edge_points*3] edge segment points
"""
from __future__ import annotations

import hashlib

import struct
from pathlib import Path

import numpy as np

from .geometry import mesh_arrays, read_step_shape, surface_moments


def _edges(shape, deflection: float) -> np.ndarray:
    """B-rep edges discretized as line-segment point pairs."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape
    from OCP.BRep import BRep_Tool

    m = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_EDGE, m)
    segs = []
    for i in range(1, m.Extent() + 1):
        e = TopoDS.Edge_s(m.FindKey(i))
        if BRep_Tool.Degenerated_s(e):
            continue
        try:
            c = BRepAdaptor_Curve(e)
            d = GCPnts_QuasiUniformDeflection(c, deflection)
            if not d.IsDone() or d.NbPoints() < 2:
                continue
            pts = [d.Value(k) for k in range(1, d.NbPoints() + 1)]
        except Exception:
            continue
        for a, b in zip(pts[:-1], pts[1:]):
            segs.append((a.X(), a.Y(), a.Z()))
            segs.append((b.X(), b.Y(), b.Z()))
    return np.asarray(segs, dtype=np.float32).reshape(-1, 3)


def build_mesh(step_path: str) -> dict:
    shape = read_step_shape(step_path)
    v, t = mesh_arrays(shape, rel_deflection=0.002, ang_deflection=0.35)
    lo, hi = v.min(0), v.max(0)
    diag = float(np.linalg.norm(hi - lo)) or 1.0
    edges = _edges(shape, 0.002 * diag)
    return {"v": v.astype(np.float32), "t": t.astype(np.uint32), "e": edges,
            "bbox": [float(x) for x in (*lo, *hi)]}


def mesh_bytes(m: dict) -> bytes:
    head = b"PAM1" + struct.pack("<III", len(m["v"]), len(m["t"]), len(m["e"])) + struct.pack("<6f", *m["bbox"])
    return head + m["v"].astype("<f4").tobytes() + m["t"].astype("<u4").tobytes() + m["e"].astype("<f4").tobytes()


def parse_mesh(data: bytes) -> dict:
    nv, nt, ne = struct.unpack_from("<III", data, 4)
    bbox = list(struct.unpack_from("<6f", data, 16))
    off = 40
    v = np.frombuffer(data, "<f4", nv * 3, off).reshape(-1, 3)
    off += nv * 12
    t = np.frombuffer(data, "<u4", nt * 3, off).reshape(-1, 3)
    off += nt * 12
    e = np.frombuffer(data, "<f4", ne * 3, off).reshape(-1, 3)
    return {"v": v, "t": t, "e": e, "bbox": bbox}


class MeshCache:
    def __init__(self, folder: str | Path):
        self.dir = Path(folder)
        self.dir.mkdir(parents=True, exist_ok=True)

    def key(self, step_path: str) -> str:
        p = Path(step_path)
        st = p.stat()
        return hashlib.sha1(f"{p.resolve()}|{st.st_size}|{st.st_mtime_ns}|v2".encode()).hexdigest()[:20]

    def get_bytes(self, step_path: str) -> bytes:
        f = self.dir / f"{self.key(step_path)}.pam"
        if f.exists():
            return f.read_bytes()
        data = mesh_bytes(build_mesh(step_path))
        tmp = f.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(f)
        return data

    def get(self, step_path: str) -> dict:
        return parse_mesh(self.get_bytes(step_path))


# --------------------------------------------------------------------------- alignment + deviation


def _frame(v: np.ndarray, t: np.ndarray):
    area, cen, cov, w = surface_moments(v.astype(np.float64), t.astype(np.int64))
    lam, vec = np.linalg.eigh(cov)
    order = np.argsort(lam)[::-1]
    lam, vec = lam[order], vec[:, order]
    if np.linalg.det(vec) < 0:
        vec[:, 2] = -vec[:, 2]
    return area, cen, vec, lam, w


def _samples(v, t, w, n=4096, seed=7):
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(t), size=n, p=w / w.sum())
    r1, r2 = rng.random(n), rng.random(n)
    flip = r1 + r2 > 1
    r1[flip], r2[flip] = 1 - r1[flip], 1 - r2[flip]
    a, b, c = v[t[idx, 0]], v[t[idx, 1]], v[t[idx, 2]]
    return a + r1[:, None] * (b - a) + r2[:, None] * (c - a)


def point_triangle_distance(p: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Exact distance from points p[i] to triangles (a[i], b[i], c[i]) (vectorized, Ericson's method)."""
    return point_triangle_closest(p, a, b, c)[0]


def point_triangle_closest(p: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(distance, closest point) from points p[i] to triangles (a[i], b[i], c[i])."""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = (ab * ap).sum(1), (ac * ap).sum(1)
    bp = p - b
    d3, d4 = (ab * bp).sum(1), (ac * bp).sum(1)
    cp = p - c
    d5, d6 = (ab * cp).sum(1), (ac * cp).sum(1)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    out = np.empty(len(p))
    qs = np.empty_like(p, dtype=np.float64)
    done = np.zeros(len(p), bool)

    def take(mask, q):
        m = mask & ~done
        out[m] = np.linalg.norm(p[m] - q[m], axis=1)
        qs[m] = q[m]
        done[m] = True
    take((d1 <= 0) & (d2 <= 0), a)
    take((d3 >= 0) & (d4 <= d3), b)
    vcm = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        take(vcm, a + (d1 / np.where(d1 - d3 == 0, 1, d1 - d3))[:, None] * ab)
        take((d6 >= 0) & (d5 <= d6), c)
        vbm = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
        take(vbm, a + (d2 / np.where(d2 - d6 == 0, 1, d2 - d6))[:, None] * ac)
        vam = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
        wv = (d4 - d3) / np.where((d4 - d3) + (d5 - d6) == 0, 1, (d4 - d3) + (d5 - d6))
        take(vam, b + wv[:, None] * (c - b))
        denom = 1.0 / np.where(va + vb + vc == 0, 1, va + vb + vc)
        v_ = vb * denom
        w_ = vc * denom
        take(np.ones(len(p), bool), a + ab * v_[:, None] + ac * w_[:, None])
    return out, qs


def subdivide(v: np.ndarray, t: np.ndarray, max_edge: float, max_tris: int = 400_000) -> tuple[np.ndarray, np.ndarray]:
    """Split triangles (longest edge at its midpoint) until no edge is longer than max_edge. The surface is
    unchanged; it only makes 'nearest triangle centroids' a reliable shortlist for point-to-mesh distances
    (a large flat face is often just two long triangles)."""
    v = np.asarray(v, np.float64)
    t = np.asarray(t, np.int64)
    for _ in range(16):
        a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
        lens = np.stack([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1), np.linalg.norm(a - c, axis=1)], 1)
        big = lens.max(1) > max_edge
        if not big.any() or len(t) + big.sum() > max_tris:
            break
        tb, e = t[big], lens[big].argmax(1)
        r = np.arange(len(tb))
        i0, i1, i2 = tb[r, e], tb[r, (e + 1) % 3], tb[r, (e + 2) % 3]
        mi = np.arange(len(v), len(v) + len(tb))
        v = np.vstack([v, (v[i0] + v[i1]) / 2])
        t = np.vstack([t[~big], np.stack([i0, mi, i2], 1), np.stack([mi, i1, i2], 1)])
    return v, t


class MeshDistance:
    """Distance from points to a triangle mesh: exact point-triangle distance to the triangles whose centroids
    are nearest (after subdividing long triangles, so the true nearest triangle is in the shortlist)."""

    def __init__(self, v: np.ndarray, t: np.ndarray, k: int = 16):
        from scipy.spatial import cKDTree
        diag = float(np.linalg.norm(v.max(0) - v.min(0))) or 1.0
        self.v, self.t = subdivide(v, t, diag / 60)
        self.tri = self.v[self.t]
        self.tree = cKDTree(self.tri.mean(1))
        self.k = min(k, len(self.t))

    def __call__(self, points: np.ndarray) -> np.ndarray:
        return self.closest(points)[0]

    def closest(self, points: np.ndarray, chunk: int = 16_000) -> tuple[np.ndarray, np.ndarray]:
        points = np.asarray(points, np.float64)
        n = len(points)
        best = np.empty(n)
        q = np.empty((n, 3))
        for s in range(0, n, chunk):
            pts = points[s:s + chunk]
            m = len(pts)
            _, idx = self.tree.query(pts, k=self.k)
            tri = self.tri[np.asarray(idx).reshape(-1)]
            d, qq = point_triangle_closest(np.repeat(pts, self.k, axis=0), tri[:, 0], tri[:, 1], tri[:, 2])
            d, qq = d.reshape(m, self.k), qq.reshape(m, self.k, 3)
            j = d.argmin(1)
            r = np.arange(m)
            best[s:s + m], q[s:s + m] = d[r, j], qq[r, j]
        return best, q


def refine_by_deviation(v: np.ndarray, t: np.ndarray, dist, diag: float, max_tris: int = 60_000,
                        rounds: int = 10) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Deviation per vertex, with triangles split (longest edge) only where the deviation varies inside them, so
    a heat map shows a local difference locally. A triangle is split when its corners disagree, or when its centre
    disagrees with its corners (e.g. a hole wall whose rims touch the other part but whose middle does not).
    The surface itself is unchanged."""
    v = np.asarray(v, np.float64)
    t = np.asarray(t, np.int64)
    dev = dist(v)
    min_edge = diag / 300

    def centre_dev(tt):
        out = np.full(len(tt), np.nan)
        a, b, c = v[tt[:, 0]], v[tt[:, 1]], v[tt[:, 2]]
        lens = np.stack([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1), np.linalg.norm(a - c, axis=1)], 1)
        long_ = lens.max(1) > min_edge
        if long_.any():
            out[long_] = dist((a[long_] + b[long_] + c[long_]) / 3)
        return out, lens

    dc, lens = centre_dev(t)                    # NaN = triangle already small enough
    for _ in range(rounds):
        td = dev[t]
        top = max(float(dev.max()), float(np.nanmax(dc)) if np.isfinite(dc).any() else 0.0)
        thr = max(0.15 * top, 5e-4 * diag)
        long_ = np.isfinite(dc)
        need = long_ & ((td.max(1) - td.min(1) > thr) | (np.abs(np.nan_to_num(dc) - td.mean(1)) > thr))
        if not need.any() or len(t) + need.sum() > max_tris:
            break
        tb, e = t[need], lens[need].argmax(1)
        r = np.arange(len(tb))
        i0, i1, i2 = tb[r, e], tb[r, (e + 1) % 3], tb[r, (e + 2) % 3]
        mid = (v[i0] + v[i1]) / 2
        mi = np.arange(len(v), len(v) + len(tb))
        v = np.vstack([v, mid])
        dev = np.concatenate([dev, dist(mid)])
        new_t = np.vstack([np.stack([i0, mi, i2], 1), np.stack([mi, i1, i2], 1)])
        new_dc, new_lens = centre_dev(new_t)   # only the new triangles need new centre distances
        t = np.vstack([t[~need], new_t])
        dc = np.concatenate([dc[~need], new_dc])
        lens = np.vstack([lens[~need], new_lens])
    return v, t, dev


def distances_to_mesh(points: np.ndarray, v: np.ndarray, t: np.ndarray, k: int = 16) -> np.ndarray:
    return MeshDistance(v, t, k)(points)


def _icp_refine(R: np.ndarray, T: np.ndarray, src: np.ndarray, target: "MeshDistance", diag: float, iters: int = 25,
                keep: float = 0.8) -> tuple[np.ndarray, np.ndarray]:
    """Trimmed ICP against the exact surface of the other mesh: refine (R, T) using the best-matching share of
    the points, so a local change (a hole, a longer flange) does not pull the alignment of everything else.
    The result is kept only if it fits better than the starting pose."""
    def fit(R, T):
        d, q = target.closest(src @ R.T + T)
        return float(np.sort(d)[: max(1, int(keep * len(d)))].mean()), d, q
    best_score, d, q = fit(R, T)
    best = (R, T)
    for _ in range(iters):
        moved = src @ R.T + T
        m = d <= np.quantile(d, keep)
        P, Q = moved[m], q[m]
        pc, qc = P.mean(0), Q.mean(0)
        U, _, Vt = np.linalg.svd((P - pc).T @ (Q - qc))
        D = np.diag([1.0, 1.0, np.sign(np.linalg.det(Vt.T @ U.T))])
        Ri = Vt.T @ D @ U.T                       # proper increment: a mirror alignment stays a mirror
        Ti = qc - Ri @ pc
        R, T = Ri @ R, Ri @ T + Ti
        score, d, q = fit(R, T)
        if score < best_score - 1e-12:
            best_score, best = score, (R, T)
        if np.linalg.norm(Ti) < 1e-6 * diag:
            break
    return best


def align_meshes(ma: dict, mb: dict, scale_b: float = 1.0, mirror: bool = False, proper_only: bool = False) -> dict:
    """Best rigid alignment of B onto A: principal frames + the shape check's choice among the axis flips
    (an improper one only for mirror pairs), refined by trimmed ICP. Returns R, T (applied to B already scaled
    by scale_b)."""
    from .shape import compare_point_sets
    va, ta = ma["v"].astype(np.float64), ma["t"].astype(np.int64)
    vb, tb = mb["v"].astype(np.float64) * scale_b, mb["t"].astype(np.int64)
    area_a, cen_a, vec_a, lam_a, wa = _frame(va, ta)
    area_b, cen_b, vec_b, lam_b, wb = _frame(vb, tb)
    pa = (_samples(va, ta, wa) - cen_a) @ vec_a
    pb = (_samples(vb, tb, wb) - cen_b) @ vec_b
    res = compare_point_sets(pa, pb, lam_a, lam_b, area_a)
    use_improper = (mirror or bool(res.get("mirror"))) and not proper_only
    tt = np.array(res["improper_t" if use_improper else "proper_t"])
    R = vec_a @ tt @ vec_b.T
    T = cen_a - R @ cen_b
    diag = float(np.linalg.norm(va.max(0) - va.min(0))) or 1.0
    R, T = _icp_refine(R, T, _samples(vb, tb, wb, n=1500, seed=21), MeshDistance(va, ta), diag)
    M = np.eye(4)
    M[:3, :3] = R * scale_b
    M[:3, 3] = T
    return {"R": R, "T": T, "va": va, "ta": ta, "vb": vb, "tb": tb, "wa": wa, "wb": wb, "mirror": use_improper,
            "mode": res.get("mode"), "matrix": M.T.reshape(-1).tolist()}


def compare_meshes(ma: dict, mb: dict, scale_b: float = 1.0, mirror: bool = False) -> dict:
    """Best rigid alignment of B onto A (optionally improper for mirror pairs) + deviation maps.

    The deviation maps are given on refined copies of both display meshes (triangles split where the deviation
    changes across them), so a heat map shows a difference where it is instead of smearing it across a face."""
    al = align_meshes(ma, mb, scale_b, mirror)
    R, T, use_improper = al["R"], al["T"], al["mirror"]
    va, ta, vb, tb, wa, wb = al["va"], al["ta"], al["vb"], al["tb"], al["wa"], al["wb"]
    vb_al = vb @ R.T + T
    to_b, to_a = MeshDistance(vb_al, tb), MeshDistance(va, ta)
    diag = float(np.linalg.norm(va.max(0) - va.min(0))) or 1.0
    sva, sta, dev_a = refine_by_deviation(va, ta, to_b, diag)
    svb_al, stb, dev_b = refine_by_deviation(vb_al, tb, to_a, diag)
    # B's subdivided mesh is returned in B's own coordinates (the viewer shows B as it is in its file)
    Rinv = R.T
    svb = (svb_al - T) @ Rinv.T / (scale_b or 1.0)
    # summary statistics over area-weighted surface samples (vertices crowd on curved faces)
    sa = to_b(_samples(va, ta, wa, n=3000, seed=11))
    sb = to_a(_samples(vb_al, tb, wb, n=3000, seed=12))
    return {"matrix": al["matrix"],                      # column-major (three.js Matrix4.fromArray)
            "mesh_a": {"v": sva.astype(np.float32), "t": sta.astype(np.uint32)},
            "mesh_b": {"v": svb.astype(np.float32), "t": stb.astype(np.uint32)},
            "dev_a": dev_a.astype(np.float32), "dev_b": dev_b.astype(np.float32),
            "max_mm": float(max(dev_a.max(), dev_b.max(), sa.max(), sb.max())),
            "p95_mm": float(max(np.quantile(sa, 0.95), np.quantile(sb, 0.95))),
            "median_mm": float(max(np.median(sa), np.median(sb))),
            "share_over_01mm": float(((sa > 0.1).mean() + (sb > 0.1).mean()) / 2),
            "diag_mm": diag, "mirror": use_improper, "mode": al.get("mode")}


def compare_bytes(c: dict) -> bytes:
    """b'PAC2', uint32 na, nta, nb, ntb, float32[16] matrix, float32 max, p95, median, flags, then for A and for B:
    float32 positions (n x 3), uint32 triangles (nt x 3), float32 deviation per vertex (n)."""
    a, b = c["mesh_a"], c["mesh_b"]
    head = b"PAC2" + struct.pack("<IIII", len(a["v"]), len(a["t"]), len(b["v"]), len(b["t"])) + \
        struct.pack("<16f", *c["matrix"]) + \
        struct.pack("<4f", c["max_mm"], c["p95_mm"], c["median_mm"], 1.0 if c["mirror"] else 0.0)
    body = b""
    for m, d in ((a, c["dev_a"]), (b, c["dev_b"])):
        body += m["v"].astype("<f4").tobytes() + m["t"].astype("<u4").tobytes() + d.astype("<f4").tobytes()
    return head + body


def parse_compare(data: bytes) -> dict:
    na, nta, nb, ntb = struct.unpack_from("<IIII", data, 4)
    matrix = list(struct.unpack_from("<16f", data, 20))
    mx, p95, med, flags = struct.unpack_from("<4f", data, 84)
    off = 100
    out = {"matrix": matrix, "max_mm": mx, "p95_mm": p95, "median_mm": med, "mirror": flags > 0.5}
    for key, n, nt in (("a", na, nta), ("b", nb, ntb)):
        v = np.frombuffer(data, "<f4", n * 3, off).reshape(-1, 3); off += n * 12
        t = np.frombuffer(data, "<u4", nt * 3, off).reshape(-1, 3); off += nt * 12
        d = np.frombuffer(data, "<f4", n, off); off += n * 4
        out["mesh_" + key], out["dev_" + key] = {"v": v, "t": t}, d
    return out
