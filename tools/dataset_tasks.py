"""Worker-side tasks for tools/build_dataset.py (run inside TimeoutPool processes)."""
from __future__ import annotations

import random
import shutil

import cadops
from part_audit.geometry import read_step_shape, shape_fingerprint


def screen(path: str) -> dict:
    """Fingerprint + validity flags used to pick clean single-body base parts."""
    shape = read_step_shape(path)
    fp = shape_fingerprint(shape)
    fp.pop("_samples", None)
    fp["ok"] = fp["n_faces"] > 0 and fp["area"] > 0
    fp["valid"] = bool(cadops.is_valid(shape))
    return fp


def _exact_distances(points, shape):
    """Exact distance from each point to the B-rep of ``shape``."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.gp import gp_Pnt
    out = []
    for x, y, z in points:
        v = BRepBuilderAPI_MakeVertex(gp_Pnt(float(x), float(y), float(z))).Vertex()
        d = BRepExtrema_DistShapeShape(v, shape)
        out.append(d.Value() if d.IsDone() else float("inf"))
    return out


def chirality(path: str, n_points: int = 300) -> dict:
    """Is the part chiral (no rotation maps its mirror image onto itself)?

    The mirror image is aligned to the part with each of the 4 proper sign choices of the
    principal axes of inertia; points sampled on the aligned mirror surface are measured
    with exact point-to-B-rep distances (BRepExtrema). Achiral if some alignment brings
    the points onto the original surface (p99 < 0.3% of the size, i.e. within mesh
    deflection); chiral if even the best alignment leaves p95 >= 1% of the size;
    anything in between is ambiguous and not used. Independent of the audit's L3b.
    """
    import numpy as np
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.gp import gp_Trsf
    from part_audit.geometry import mesh_arrays

    def frame(s):
        g = GProp_GProps()
        BRepGProp.VolumeProperties_s(s, g)
        m = g.MatrixOfInertia()
        mat = np.array([[m.Value(r, c) for c in (1, 2, 3)] for r in (1, 2, 3)])
        w, v = np.linalg.eigh(mat)
        if np.linalg.det(v) < 0:
            v[:, 2] = -v[:, 2]
        c = g.CentreOfMass()
        return np.array([c.X(), c.Y(), c.Z()]), w, v

    s = read_step_shape(path)
    m = cadops.mirror(s)
    cs, ws, es = frame(s)
    cm, _, em = frame(m)
    gaps = [(ws[1] - ws[0]) / ws[1], (ws[2] - ws[1]) / ws[2]]
    if min(gaps) < 0.02:
        return {"chiral": None, "reason": "near-degenerate inertia, alignment ambiguous"}
    x0, y0, z0, x1, y1, z1 = cadops.bbox(s)
    size = float(np.linalg.norm([x1 - x0, y1 - y0, z1 - z0]))
    best = None
    for sg in [(1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)]:
        r = es @ np.diag(sg) @ em.T
        t = cs - r @ cm
        tr = gp_Trsf()
        tr.SetValues(*r[0], t[0], *r[1], t[1], *r[2], t[2])
        mm = cadops.transform(m, tr)
        v, tri = mesh_arrays(mm, rel_deflection=0.002)
        a, b, c = v[tri[:, 0]], v[tri[:, 1]], v[tri[:, 2]]
        w = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
        rng = np.random.default_rng(3)
        idx = rng.choice(len(tri), size=n_points, p=w / w.sum())
        r1, r2 = rng.random(n_points), rng.random(n_points)
        flip = r1 + r2 > 1
        r1[flip], r2[flip] = 1 - r1[flip], 1 - r2[flip]
        pts = a[idx] + r1[:, None] * (b[idx] - a[idx]) + r2[:, None] * (c[idx] - a[idx])
        d = np.array(_exact_distances(pts, s))
        q = {"p50": float(np.median(d)) / size, "p95": float(np.quantile(d, 0.95)) / size,
             "p99": float(np.quantile(d, 0.99)) / size, "signs": sg}
        if best is None or q["p99"] < best["p99"]:
            best = q
    if best["p99"] < 0.003:
        verdict = False          # mirror image coincides with a rotated copy: same part
    elif best["p95"] >= 0.01:
        verdict = True           # clear handedness difference
    else:
        verdict = None           # only a tiny region differs: ambiguous, not used as a label
    return {"chiral": verdict, "best_alignment": best, "size": size}


def make_variant(spec: dict) -> dict:
    """Create one planted variant file. spec: kind, src, dst, seed, schema, product, params."""
    rng = random.Random(spec["seed"])
    kind = spec["kind"]
    if kind == "copy":
        shutil.copyfile(spec["src"], spec["dst"])
        if spec.get("product"):
            cadops.set_product_name(spec["dst"], *spec["product"])
        return {"ok": True, "detail": "byte copy" + (" + product renamed" if spec.get("product") else "")}
    shape = read_step_shape(spec["src"])
    schema = spec.get("schema", "AP214CD")
    unit = "MM"
    detail = ""
    if kind == "reexport":
        new, detail = shape, f"re-exported by OpenCascade as {schema}"
    elif kind == "rigid":
        new, detail = cadops.transform(shape, cadops.random_rigid(rng)), "random rotation + translation"
    elif kind == "inch":
        new, unit, detail = shape, "INCH", "file written in inches (declared INCH)"
    elif kind == "unit_error":
        new, detail = cadops.uniform_scale(shape, 1 / 25.4), "coordinates divided by 25.4 but declared mm (unit error)"
    elif kind == "mirror":
        new, detail = cadops.mirror(shape, normal=spec.get("normal", (1, 0, 0))), "mirror image"
    elif kind == "edit":  # E: tiny design change
        new = None
        ops = list(spec["ops"])
        for op in ops:
            if op == "pushpull":
                new, detail = cadops.push_pull(shape, rng, rng.uniform(0.001, 0.02))
            elif op == "hole":
                new, detail = cadops.drill_hole(shape, rng, rng.uniform(0.02, 0.08))
            elif op == "fillet":
                new, detail = cadops.fillet_edge(shape, rng, rng.uniform(0.005, 0.03))
            elif op == "chamfer":
                new, detail = cadops.fillet_edge(shape, rng, rng.uniform(0.005, 0.03), chamfer=True)
            if new is not None:
                detail = f"{op}: {detail}"
                break
        if new is None:
            return {"ok": False, "detail": "no edit succeeded: " + ",".join(ops)}
    elif kind == "thickness":  # hard negative: same profile, clearly different thickness
        new, detail = cadops.push_pull(shape, rng, rng.uniform(0.25, 0.8), max_rel_vol_change=2.0, n_faces=2)
        if new is None:
            return {"ok": False, "detail": "thickness change failed"}
        detail = "thickness/size change: " + detail
    else:
        raise ValueError(kind)
    cadops.write_step(new, spec["dst"], schema=schema, unit=unit)
    if spec.get("product"):
        cadops.set_product_name(spec["dst"], *spec["product"])
    return {"ok": True, "detail": detail}
