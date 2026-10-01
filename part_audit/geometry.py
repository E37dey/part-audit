"""L3 - geometry fingerprint of a STEP file via OpenCascade (OCP).

Fingerprint (all in millimetres; OCC converts the file's declared unit on read):
volume, surface area, principal moments of inertia (density 1), bounding box in
the principal frame (sorted), counts of solids/shells/faces/edges/vertices,
face count and area fraction per surface type, closed-shell flag, timings.

Volume, area and inertia are invariant to translation and rotation; scale-free
ratios are derived at comparison time (scoring.py) for unit mismatches.

Files are processed in worker processes with a per-file timeout: a file that
hangs or crashes OpenCascade is killed and reported in Errors_Skipped, and the
worker is restarted. Results are cached by SHA-256 of the file content.
"""
from __future__ import annotations

import json
import math
import multiprocessing as mp
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from collections import deque
from multiprocessing.connection import wait
from pathlib import Path

FP_VERSION = 7

SURFACE_NAMES = {
    "GeomAbs_Plane": "plane", "GeomAbs_Cylinder": "cylinder", "GeomAbs_Cone": "cone", "GeomAbs_Sphere": "sphere",
    "GeomAbs_Torus": "torus", "GeomAbs_BezierSurface": "bezier", "GeomAbs_BSplineSurface": "bspline",
    "GeomAbs_SurfaceOfRevolution": "revolution", "GeomAbs_SurfaceOfExtrusion": "extrusion",
    "GeomAbs_OffsetSurface": "offset", "GeomAbs_OtherSurface": "other",
}


class StepReadError(RuntimeError):
    pass


# temporary ASCII-path copies (Windows); left-overs from killed workers are removed after each run
TMP_DIR = Path(tempfile.gettempdir()) / "part_audit_tmp"


def _clean_tmp(since: float) -> None:
    if not TMP_DIR.exists():
        return
    for f in TMP_DIR.glob("*.step"):
        try:
            if f.stat().st_mtime >= since - 1:
                f.unlink()
        except OSError:
            pass


def silence_occ() -> None:
    """OpenCascade prints progress to stdout; keep only failures."""
    try:
        from OCP.Message import Message, Message_Gravity
        for p in Message.DefaultMessenger_s().Printers():
            p.SetTraceLevel(Message_Gravity.Message_Fail)
    except Exception:
        pass


def read_step_shape(path: str):
    """Read a STEP file into one TopoDS_Shape (lengths converted to mm)."""
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader

    tmp = None
    if sys.platform == "win32" and not path.isascii():  # OCC + non-ASCII paths on Windows
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".step", dir=TMP_DIR)
        os.close(fd)
        shutil.copyfile(path, tmp)
        path = tmp
    try:
        reader = STEPControl_Reader()
        status = reader.ReadFile(path)
        if status != IFSelect_RetDone:
            raise StepReadError(f"STEP reader failed (status {int(status)})")
        reader.TransferRoots()
        shape = reader.OneShape()
        if shape is None or shape.IsNull():
            raise StepReadError("no geometry transferred from STEP file")
        return shape
    finally:
        if tmp:
            os.unlink(tmp)


def _map(shape, kind):
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape
    m = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, m)
    return m


def _dir_key(d, tol: float = 1e-6):
    v = [d.X(), d.Y(), d.Z()]
    k = next(i for i in range(3) if abs(v[i]) > tol)
    if v[k] < 0:
        v = [-x for x in v]
    return tuple(round(x, 5) for x in v), v


def surface_key(ad, st: str, q: float, idx: int):
    """Hashable identity of the underlying analytic surface (lengths quantised by q)."""
    def r(x):
        return int(round(x / q))
    if st == "plane":
        ax = ad.Plane().Axis()
        dk, v = _dir_key(ax.Direction())
        p = ax.Location()
        return ("plane", dk, r(v[0] * p.X() + v[1] * p.Y() + v[2] * p.Z()))
    if st == "cylinder":
        c = ad.Cylinder()
        dk, v = _dir_key(c.Axis().Direction())
        p = c.Axis().Location()
        t = v[0] * p.X() + v[1] * p.Y() + v[2] * p.Z()
        p0 = (p.X() - t * v[0], p.Y() - t * v[1], p.Z() - t * v[2])  # axis point closest to the origin
        return ("cylinder", dk, tuple(r(x) for x in p0), r(c.Radius()))
    if st == "cone":
        c = ad.Cone()
        dk, _ = _dir_key(c.Axis().Direction())
        a = c.Apex()
        return ("cone", dk, r(a.X()), r(a.Y()), r(a.Z()), round(c.SemiAngle(), 6))
    if st == "sphere":
        c = ad.Sphere()
        p = c.Location()
        return ("sphere", r(p.X()), r(p.Y()), r(p.Z()), r(c.Radius()))
    if st == "torus":
        c = ad.Torus()
        dk, _ = _dir_key(c.Axis().Direction())
        p = c.Location()
        return ("torus", dk, r(p.X()), r(p.Y()), r(p.Z()), r(c.MajorRadius()), r(c.MinorRadius()))
    return ("face", idx)  # free-form faces are each counted


def drop_stray_sheets(shape, max_share: float = 0.05):
    """Remove small *open* shells (annotation planes, construction sheets that some AP242 exporters put
    inside a solid). They barely change area but break the closed flag, the volume integral and the
    bounding box. Returns (shape, number of shells removed). Closed shells (incl. voids) are kept."""
    from OCP.BRep import BRep_Builder, BRep_Tool
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_SHELL, TopAbs_SOLID
    from OCP.TopoDS import TopoDS, TopoDS_Compound, TopoDS_Solid

    shells = _map(shape, TopAbs_SHELL)
    if shells.Extent() < 2:
        return shape, 0
    info = []
    for i in range(1, shells.Extent() + 1):
        sh = TopoDS.Shell_s(shells.FindKey(i))
        g = GProp_GProps()
        BRepGProp.SurfaceProperties_s(sh, g)
        info.append((sh, abs(g.Mass()), BRep_Tool.IsClosed_s(sh)))
    total = sum(a for _, a, _ in info) or 1.0
    keep = [sh for sh, a, closed in info if closed or a / total >= max_share]
    n_drop = len(info) - len(keep)
    if n_drop == 0 or not keep:
        return shape, 0
    b = BRep_Builder()
    if _map(shape, TopAbs_SOLID).Extent() > 0 and all(BRep_Tool.IsClosed_s(k) for k in keep):
        solid = TopoDS_Solid()
        b.MakeSolid(solid)
        for sh in keep:
            b.Add(solid, sh)
        return solid, n_drop
    comp = TopoDS_Compound()
    b.MakeCompound(comp)
    for sh in keep:
        b.Add(comp, sh)
    return comp, n_drop


def shape_fingerprint(shape) -> dict:
    """Compute the fingerprint of an OCC shape."""
    import numpy as np
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID, TopAbs_VERTEX
    from OCP.TopoDS import TopoDS

    t0 = time.perf_counter()
    shape, n_stray = drop_stray_sheets(shape)
    solids, shells = _map(shape, TopAbs_SOLID), _map(shape, TopAbs_SHELL)
    faces, edges, verts = _map(shape, TopAbs_FACE), _map(shape, TopAbs_EDGE), _map(shape, TopAbs_VERTEX)
    fp: dict = {
        "n_solids": solids.Extent(), "n_shells": shells.Extent(), "n_faces": faces.Extent(),
        "n_edges": edges.Extent(), "n_vertices": verts.Extent(), "stray_sheets_ignored": n_stray,
    }
    closed = shells.Extent() > 0
    for i in range(1, shells.Extent() + 1):
        if not BRep_Tool.IsClosed_s(TopoDS.Shell_s(shells.FindKey(i))):
            closed = False
            break
    fp["closed"] = bool(closed and solids.Extent() > 0)

    counts: dict[str, int] = {}
    areas: dict[str, float] = {}
    total_area = 0.0
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, False)
    x0, y0, z0, x1, y1, z1 = box.Get() if not box.IsVoid() else (0, 0, 0, 1, 1, 1)
    q = 1e-5 * (math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2 + (z1 - z0) ** 2) or 1.0)
    unique: dict[str, set] = {}
    for i in range(1, faces.Extent() + 1):
        f = TopoDS.Face_s(faces.FindKey(i))
        try:
            ad = BRepAdaptor_Surface(f)
            st = SURFACE_NAMES.get(ad.GetType().name, "other")
            key = surface_key(ad, st, q, i)
        except Exception:
            st, key = "other", ("face", i)
        g = GProp_GProps()
        BRepGProp.SurfaceProperties_s(f, g)
        a = abs(g.Mass())
        counts[st] = counts.get(st, 0) + 1
        areas[st] = areas.get(st, 0.0) + a
        unique.setdefault(st, set()).add(key)
        total_area += a
    fp["area"] = total_area
    fp["surf_counts"] = dict(sorted(counts.items()))
    # faces lying on the same plane / cylinder / ... count once: unchanged when a CAD system splits faces
    fp["unique_surfaces"] = {k: len(v) for k, v in sorted(unique.items())}
    fp["surf_area_frac"] = {k: (v / total_area if total_area > 0 else 0.0) for k, v in sorted(areas.items())}

    vp = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, vp)
    vol = vp.Mass()
    fp["volume"] = vol
    com = vp.CentreOfMass()
    fp["center"] = [com.X(), com.Y(), com.Z()]
    m = vp.MatrixOfInertia()
    mat = np.array([[m.Value(r, c) for c in (1, 2, 3)] for r in (1, 2, 3)])
    if vol < 0:  # reversed orientation: make moments positive
        mat = -mat
    w, v = np.linalg.eigh(mat)
    order = np.argsort(w)
    w, v = w[order], v[:, order]
    if np.linalg.det(v) < 0:
        v[:, 2] = -v[:, 2]
    fp["inertia"] = [float(x) for x in w]
    fp["axes"] = v.T.tolist()
    t1 = time.perf_counter()
    # mesh-based features: tight bounding box in the surface principal frame + surface samples (L3b)
    try:
        mesh_features(shape, fp)
    except Exception as exc:  # geometry above is still usable
        fp["bbox_pca"], fp["mesh_error"] = [], f"{type(exc).__name__}: {exc}"[:200]
    fp["t_props"] = t1 - t0
    fp["t_mesh"] = time.perf_counter() - t1
    for k in ("volume", "area"):
        if not math.isfinite(fp[k]):
            raise StepReadError(f"non-finite {k}")
    return fp


N_SAMPLES = 4096


def mesh_arrays(shape, rel_deflection: float = 0.004, ang_deflection: float = 0.5):
    """Triangulate the shape; return (vertices Nx3, triangles Mx3) in global coordinates."""
    import numpy as np
    from OCP.Bnd import Bnd_Box
    from OCP.BRep import BRep_Tool
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, False)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    diag = math.sqrt((xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2) or 1.0
    BRepMesh_IncrementalMesh(shape, max(rel_deflection * diag, 1e-6), False, ang_deflection, False)
    verts, tris = [], []
    offset = 0
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face_s(exp.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is not None and tri.NbTriangles() > 0:
            trsf = loc.Transformation()
            n = tri.NbNodes()
            for i in range(1, n + 1):
                p = tri.Node(i).Transformed(trsf)
                verts.append((p.X(), p.Y(), p.Z()))
            for i in range(1, tri.NbTriangles() + 1):
                a, b, c = tri.Triangle(i).Get()
                tris.append((a - 1 + offset, b - 1 + offset, c - 1 + offset))
            offset += n
        exp.Next()
    if not tris:
        raise StepReadError("triangulation failed")
    return np.asarray(verts, dtype=np.float64), np.asarray(tris, dtype=np.int64)


def surface_moments(v, t):
    """Exact area, centroid and covariance of a triangle mesh surface."""
    import numpy as np
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    w = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    area = w.sum()
    if area <= 0:
        raise StepReadError("degenerate mesh")
    g = (a + b + c) / 3.0
    centroid = (w[:, None] * g).sum(0) / area
    s = a + b + c
    # E[x x^T] over a triangle = (a a^T + b b^T + c c^T + s s^T) / 12
    second = (np.einsum("n,ni,nj->ij", w, a, a) + np.einsum("n,ni,nj->ij", w, b, b)
              + np.einsum("n,ni,nj->ij", w, c, c) + np.einsum("n,ni,nj->ij", w, s, s)) / (12.0 * area)
    cov = second - np.outer(centroid, centroid)
    return area, centroid, cov, w


def mesh_features(shape, fp: dict, n_samples: int = N_SAMPLES) -> None:
    """Add bbox_pca, surface principal values and canonical-frame surface samples to fp."""
    import numpy as np
    v, t = mesh_arrays(shape)
    area, cen, cov, w = surface_moments(v, t)
    lam, vec = np.linalg.eigh(cov)
    order = np.argsort(lam)[::-1]
    lam, vec = lam[order], vec[:, order]
    if np.linalg.det(vec) < 0:
        vec[:, 2] = -vec[:, 2]
    local = (v - cen) @ vec
    ext = local.max(0) - local.min(0)
    # exact third moments of the triangulated surface along the principal axes; their product
    # is a pseudoscalar: unchanged by rotations, sign flipped by a mirror, ~0 for symmetric parts
    ta, tb, tc = local[t[:, 0]], local[t[:, 1]], local[t[:, 2]]
    m3 = (w[:, None] * (ta**3 + tb**3 + tc**3 + ta * ta * tb + ta * ta * tc + tb * tb * ta + tb * tb * tc
                        + tc * tc * ta + tc * tc * tb + ta * tb * tc) / 10.0).sum(0) / area
    fp["surf_skew"] = [float(x) for x in m3 / np.maximum(lam, 1e-30) ** 1.5]
    fp["bbox_pca"] = sorted((float(x) for x in ext), reverse=True)
    fp["surf_eig"] = [float(x) for x in lam]
    fp["mesh_triangles"] = int(len(t))
    rng = np.random.default_rng(20241001)
    idx = rng.choice(len(t), size=n_samples, p=w / w.sum())
    r1, r2 = rng.random(n_samples), rng.random(n_samples)
    flip = r1 + r2 > 1
    r1[flip], r2[flip] = 1 - r1[flip], 1 - r2[flip]
    a, b, c = local[t[idx, 0]], local[t[idx, 1]], local[t[idx, 2]]
    pts = a + r1[:, None] * (b - a) + r2[:, None] * (c - a)
    scale = float(np.linalg.norm(ext)) or 1.0
    fp["sample_scale"] = scale  # samples are stored divided by the bbox diagonal (float16-safe)
    fp["sample_area"] = float(area)
    fp["_samples"] = (pts / scale).astype(np.float32)  # canonical (surface principal) frame


def fingerprint_path(path: str) -> dict:
    """Read a STEP file and fingerprint it (raises on failure)."""
    silence_occ()
    t0 = time.perf_counter()
    shape = read_step_shape(str(path))
    t_read = time.perf_counter() - t0
    fp = shape_fingerprint(shape)
    fp["t_read"] = t_read
    fp["t_total"] = time.perf_counter() - t0
    fp["ok"] = fp["n_faces"] > 0 and fp["area"] > 0
    if not fp["ok"]:
        fp["error"] = "no faces / zero area"
    fp["version"] = FP_VERSION
    return fp


# --------------------------------------------------------------------------- worker pool


def _worker_main(conn, task_fn_name: str) -> None:
    silence_occ()
    import importlib
    mod_name, fn_name = task_fn_name.rsplit(":", 1)
    fn = getattr(importlib.import_module(mod_name), fn_name)
    while True:
        try:
            task = conn.recv()
        except (EOFError, OSError):
            return
        if task is None:
            return
        tid, arg = task
        try:
            res = ("ok", tid, fn(arg))
        except BaseException as exc:  # report and continue with the next file
            res = ("err", tid, f"{type(exc).__name__}: {exc}"[:500])
        try:
            conn.send(res)
        except (EOFError, OSError, BrokenPipeError):
            return


class TimeoutPool:
    """Process pool where every task has its own wall-clock timeout.

    A task that exceeds ``timeout_s`` (hang) or kills its worker (segfault) is
    reported as an error; the worker is replaced. Workers are also recycled
    every ``max_tasks`` tasks to bound OpenCascade memory growth.
    """

    def __init__(self, task_fn: str, workers: int, timeout_s: float, max_tasks: int = 250):
        self.task_fn = task_fn
        self.n = max(1, workers)
        self.timeout_s = timeout_s
        self.max_tasks = max_tasks
        self.ctx = mp.get_context("fork" if sys.platform.startswith("linux") else "spawn")
        self.workers: dict[int, dict] = {}

    def _start(self, wid: int) -> None:
        parent, child = self.ctx.Pipe(duplex=True)
        proc = self.ctx.Process(target=_worker_main, args=(child, self.task_fn), daemon=True)
        proc.start()
        child.close()
        self.workers[wid] = {"proc": proc, "conn": parent, "task": None, "t0": 0.0, "done": 0}

    def _stop(self, wid: int, kill: bool) -> None:
        w = self.workers.pop(wid)
        try:
            if kill:
                w["proc"].kill()
            else:
                w["conn"].send(None)
        except Exception:
            pass
        w["proc"].join(timeout=5)
        if w["proc"].is_alive():
            w["proc"].kill()
            w["proc"].join(timeout=5)
        w["conn"].close()

    def run(self, tasks: list[tuple[str, object]], on_result) -> None:
        """tasks: [(task_id, arg)]; on_result(task_id, status, payload, seconds)."""
        pending = deque(tasks)
        for wid in range(min(self.n, len(tasks))):
            self._start(wid)
        try:
            while pending or any(w["task"] is not None for w in self.workers.values()):
                for wid, w in list(self.workers.items()):
                    if w["task"] is None and pending:
                        if w["done"] >= self.max_tasks:
                            self._stop(wid, kill=False)
                            self._start(wid)
                            w = self.workers[wid]
                        tid, arg = pending.popleft()
                        w["task"], w["t0"] = tid, time.perf_counter()
                        w["conn"].send((tid, arg))
                busy = {w["conn"]: wid for wid, w in self.workers.items() if w["task"] is not None}
                if not busy:
                    continue
                ready = wait(list(busy), timeout=0.2)
                for conn in ready:
                    wid = busy[conn]
                    w = self.workers[wid]
                    try:
                        status, tid, payload = conn.recv()
                    except (EOFError, OSError):
                        continue  # worker died; handled below
                    if tid == w["task"]:
                        on_result(tid, status, payload, time.perf_counter() - w["t0"])
                        w["task"] = None
                        w["done"] += 1
                now = time.perf_counter()
                for wid, w in list(self.workers.items()):
                    if w["task"] is None:
                        continue
                    if now - w["t0"] > self.timeout_s:
                        tid = w["task"]
                        self._stop(wid, kill=True)
                        on_result(tid, "timeout", f"no result after {self.timeout_s:g} s", now - w["t0"])
                        self._start(wid)
                    elif not w["proc"].is_alive():
                        tid, code = w["task"], w["proc"].exitcode
                        self._stop(wid, kill=True)
                        on_result(tid, "crash", f"worker process died (exit code {code})", now - w["t0"])
                        self._start(wid)
        finally:
            for wid in list(self.workers):
                self._stop(wid, kill=False)


# --------------------------------------------------------------------------- cache


class FingerprintCache:
    """SQLite cache keyed by file SHA-256: fingerprints (JSON) and surface samples (float16 blobs).

    Without a cache folder everything is kept in memory for the current run only.
    """

    def __init__(self, cache_dir: str | None, version: int = FP_VERSION):
        self.db = None
        self.version = version
        self._mem_samples: dict[str, bytes] = {}
        if cache_dir:
            Path(cache_dir).mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(str(Path(cache_dir) / "fingerprints.sqlite"))
            self.db.execute("CREATE TABLE IF NOT EXISTS fp (sha TEXT PRIMARY KEY, version INT, data TEXT)")
            self.db.execute("CREATE TABLE IF NOT EXISTS samples (sha TEXT PRIMARY KEY, version INT, data BLOB)")

    def get_many(self, shas: list[str]) -> dict[str, dict]:
        if not self.db or not shas:
            return {}
        out = {}
        for i in range(0, len(shas), 500):
            chunk = shas[i:i + 500]
            q = f"SELECT sha, data FROM fp WHERE version=? AND sha IN ({','.join('?' * len(chunk))})"
            for sha, data in self.db.execute(q, [self.version, *chunk]):
                out[sha] = json.loads(data)
        return out

    def put(self, sha: str, data: dict) -> None:
        if self.db:
            self.db.execute("INSERT OR REPLACE INTO fp VALUES (?,?,?)", (sha, self.version, json.dumps(data)))

    def put_samples(self, sha: str, pts) -> None:
        import numpy as np
        blob = np.asarray(pts, dtype=np.float16).tobytes()
        if self.db:
            self.db.execute("INSERT OR REPLACE INTO samples VALUES (?,?,?)", (sha, self.version, blob))
        else:
            self._mem_samples[sha] = blob

    def get_samples(self, sha: str):
        import numpy as np
        blob = self._mem_samples.get(sha)
        if blob is None and self.db:
            row = self.db.execute("SELECT data FROM samples WHERE sha=? AND version=?", (sha, self.version)).fetchone()
            blob = row[0] if row else None
        if blob is None:
            return None
        return np.frombuffer(blob, dtype=np.float16).astype(np.float32).reshape(-1, 3)

    def commit(self) -> None:
        if self.db:
            self.db.commit()


def fingerprint_files(files: list[tuple[str, str, str]], workers: int = 1, timeout_s: float = 60.0,
                      cache_dir: str | None = None, progress=None):
    """Fingerprint many files. files = [(file_id, path, sha256)].

    Returns (fingerprints {file_id: fp}, errors {file_id: (reason, detail)}, stats, cache).
    Identical files (same SHA-256) are computed once; ``cache`` serves surface samples (L3b).
    """
    cache = FingerprintCache(cache_dir)
    by_sha: dict[str, list[tuple[str, str]]] = {}
    for fid, path, sha in files:
        by_sha.setdefault(sha or fid, []).append((fid, path))
    cached = cache.get_many(list(by_sha))
    fps: dict[str, dict] = {}
    errors: dict[str, tuple[str, str]] = {}
    for sha, fp in cached.items():
        fp["sha"] = sha
        for fid, _ in by_sha[sha]:
            fps[fid] = fp
    todo = [(sha, members[0][1]) for sha, members in by_sha.items() if sha not in cached]
    times: list[float] = []
    done = [0]

    def on_result(sha, status, payload, secs):
        done[0] += 1
        members = by_sha[sha]
        if status == "ok":
            times.append(secs)
            payload["t_wall"] = secs
            payload["sha"] = sha
            samples = payload.pop("_samples", None)
            if samples is not None:
                cache.put_samples(sha, samples)
                payload["has_samples"] = True
            if payload.get("ok"):
                cache.put(sha, payload)
            for fid, _ in members:
                fps[fid] = payload
                if not payload.get("ok"):
                    errors[fid] = ("no usable geometry", payload.get("error", ""))
        else:
            reason = {"timeout": "geometry timeout", "crash": "geometry reader crashed"}.get(status, "geometry read error")
            for fid, _ in members:
                errors[fid] = (reason, str(payload))
        if progress and (done[0] % 100 == 0 or done[0] == len(todo)):
            progress(done[0], len(todo))

    t0 = time.perf_counter()
    if todo:
        if workers <= 1 and timeout_s <= 0:
            for sha, path in todo:
                t = time.perf_counter()
                try:
                    on_result(sha, "ok", fingerprint_path(path), time.perf_counter() - t)
                except Exception as exc:
                    on_result(sha, "err", f"{type(exc).__name__}: {exc}", time.perf_counter() - t)
        else:
            TimeoutPool("part_audit.geometry:fingerprint_path", workers, timeout_s).run(todo, on_result)
        _clean_tmp(t0)
    cache.commit()
    stats = {"files": len(files), "unique": len(by_sha), "cached": len(cached), "computed": len(todo),
             "wall_s": time.perf_counter() - t0}
    if times:
        st = sorted(times)
        stats.update({"per_file_mean_s": sum(st) / len(st), "per_file_median_s": st[len(st) // 2],
                      "per_file_p90_s": st[int(0.9 * (len(st) - 1))], "per_file_max_s": st[-1]})
    return fps, errors, stats, cache
