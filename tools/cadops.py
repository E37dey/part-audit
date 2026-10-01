"""OpenCascade helpers used to build the synthetic test sets (and the tests).

Only needed for data generation; the audit itself never modifies CAD files.
"""
from __future__ import annotations

import math
import random
import re

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import BRepBuilderAPI_GTransform, BRepBuilderAPI_Transform
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer, BRepFilletAPI_MakeFillet
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakePrism
from OCP.GeomAbs import GeomAbs_Plane
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Ax1, gp_Ax2, gp_Dir, gp_GTrsf, gp_Mat, gp_Pnt, gp_Trsf, gp_Vec, gp_XYZ
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.TopTools import TopTools_IndexedMapOfShape

from part_audit.geometry import read_step_shape, silence_occ
from part_audit.stepfile import encode_step_string

silence_occ()

SCHEMAS = ["AP203", "AP214CD", "AP214IS", "AP242DIS"]


def write_step(shape, path: str, schema: str = "AP214CD", unit: str = "MM", product: str | None = None) -> None:
    """Write a shape to STEP; ``unit`` is the declared length unit (OCC converts coordinates)."""
    Interface_Static.SetCVal_s("write.step.schema", schema)
    Interface_Static.SetCVal_s("write.step.unit", unit)
    w = STEPControl_Writer()
    if w.Transfer(shape, STEPControl_AsIs) != IFSelect_RetDone:
        raise RuntimeError("STEP transfer failed")
    if w.Write(path) != IFSelect_RetDone:
        raise RuntimeError(f"cannot write {path}")
    if product is not None:
        set_product_name(path, product, product)


_PRODUCT_RE = re.compile(r"((?<![A-Z0-9_])PRODUCT\s*\(\s*)'(?:[^']|'')*'\s*,\s*'(?:[^']|'')*'")


def set_product_name(path: str, pid: str, name: str) -> None:
    """Replace id and name of the first PRODUCT entity (text edit, geometry untouched)."""
    with open(path, "rb") as fh:
        data = fh.read()
    text = data.decode("latin-1")
    rep = f"\\1'{encode_step_string(pid)}','{encode_step_string(name)}'"
    new, n = _PRODUCT_RE.subn(rep, text, count=1)
    if n:
        with open(path, "wb") as fh:
            fh.write(new.encode("latin-1"))


def volume(shape) -> float:
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, g)
    return g.Mass()


def n_solids(shape) -> int:
    m = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_SOLID, m)
    return m.Extent()


def is_valid(shape) -> bool:
    return BRepCheck_Analyzer(shape).IsValid()


def bbox(shape):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    b = Bnd_Box()
    BRepBndLib.Add_s(shape, b, False)
    return b.Get()


def transform(shape, trsf):
    return BRepBuilderAPI_Transform(shape, trsf, True).Shape()


def random_rigid(rng: random.Random):
    """Random rotation (axis/angle) followed by a translation of up to +-500 mm."""
    ax = gp_Dir(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1) + 1e-3)
    r = gp_Trsf()
    r.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), ax), rng.uniform(0.3, 2 * math.pi - 0.3))
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(rng.uniform(-500, 500), rng.uniform(-500, 500), rng.uniform(-500, 500)))
    return t.Multiplied(r)


def uniform_scale(shape, factor: float):
    t = gp_Trsf()
    t.SetScale(gp_Pnt(0, 0, 0), factor)
    return transform(shape, t)


def mirror(shape, normal=(1, 0, 0)):
    t = gp_Trsf()
    t.SetMirror(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*normal)))
    return transform(shape, t)


def axis_scale(shape, axis: int, factor: float):
    """Non-uniform scale along one global axis (converts analytic faces to B-splines)."""
    m = gp_Mat(1, 0, 0, 0, 1, 0, 0, 0, 1)
    m.SetValue(axis + 1, axis + 1, factor)
    g = gp_GTrsf()
    g.SetVectorialPart(m)
    g.SetTranslationPart(gp_XYZ(0, 0, 0))
    return BRepBuilderAPI_GTransform(shape, g, True).Shape()


def _faces(shape):
    m = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, m)
    return [TopoDS.Face_s(m.FindKey(i)) for i in range(1, m.Extent() + 1)]


def _edges(shape):
    m = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_EDGE, m)
    return [TopoDS.Edge_s(m.FindKey(i)) for i in range(1, m.Extent() + 1)]


def _face_area(f) -> float:
    g = GProp_GProps()
    BRepGProp.SurfaceProperties_s(f, g)
    return g.Mass()


def _clean(shape):
    u = ShapeUpgrade_UnifySameDomain(shape, True, True, False)
    u.Build()
    return u.Shape()


def _ok(new, old, max_rel_vol_change: float) -> bool:
    try:
        if new is None or new.IsNull() or n_solids(new) != 1 or not is_valid(new):
            return False
        v0, v1 = volume(old), volume(new)
        return v1 > 0 and abs(v1 - v0) / v0 <= max_rel_vol_change and abs(v1 - v0) > 1e-9 * v0
    except Exception:
        return False


def push_pull(shape, rng: random.Random, rel: float, max_rel_vol_change: float = 0.08):
    """Move one planar face outward by ``rel`` of the part size along its normal (a 'dimension change')."""
    from OCP.BRepLProp import BRepLProp_SLProps
    from OCP.BRepTools import BRepTools
    from OCP.TopAbs import TopAbs_REVERSED
    x0, y0, z0, x1, y1, z1 = bbox(shape)
    size = max(x1 - x0, y1 - y0, z1 - z0)
    faces = [f for f in _faces(shape) if BRepAdaptor_Surface(f).GetType() == GeomAbs_Plane]
    faces.sort(key=_face_area, reverse=True)
    cands = faces[:6]
    rng.shuffle(cands)
    for f in cands:
        umin, umax, vmin, vmax = BRepTools.UVBounds_s(f)
        props = BRepLProp_SLProps(BRepAdaptor_Surface(f), (umin + umax) / 2, (vmin + vmax) / 2, 1, 1e-6)
        if not props.IsNormalDefined():
            continue
        n = props.Normal()
        if f.Orientation() == TopAbs_REVERSED:
            n.Reverse()
        d = rel * size
        try:
            prism = BRepPrimAPI_MakePrism(f, gp_Vec(n.X() * d, n.Y() * d, n.Z() * d)).Shape()
            fused = _clean(BRepAlgoAPI_Fuse(shape, prism).Shape())
        except Exception:
            continue
        if _ok(fused, shape, max_rel_vol_change):
            return fused, f"push-pull {rel:.2%} of size on a planar face"
    return None, ""


def drill_hole(shape, rng: random.Random, rel_d: float, max_rel_vol_change: float = 0.08):
    """Drill a small through/blind hole normal to a large planar face."""
    from OCP.BRepLProp import BRepLProp_SLProps
    from OCP.BRepTools import BRepTools
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_IN, TopAbs_REVERSED
    from OCP.gp import gp_Pnt2d
    x0, y0, z0, x1, y1, z1 = bbox(shape)
    size = max(x1 - x0, y1 - y0, z1 - z0)
    faces = [f for f in _faces(shape) if BRepAdaptor_Surface(f).GetType() == GeomAbs_Plane]
    faces.sort(key=_face_area, reverse=True)
    for f in faces[:4]:
        umin, umax, vmin, vmax = BRepTools.UVBounds_s(f)
        for _ in range(12):
            u, v = rng.uniform(umin, umax), rng.uniform(vmin, vmax)
            if BRepClass_FaceClassifier(f, gp_Pnt2d(u, v), 1e-6).State() != TopAbs_IN:
                continue
            props = BRepLProp_SLProps(BRepAdaptor_Surface(f), u, v, 1, 1e-6)
            if not props.IsNormalDefined():
                continue
            p, n = props.Value(), props.Normal()
            if f.Orientation() != TopAbs_REVERSED:
                n.Reverse()  # point into the material
            r = 0.5 * rel_d * size
            depth = rng.uniform(0.2, 0.6) * size
            try:
                cyl = BRepPrimAPI_MakeCylinder(gp_Ax2(p.Translated(gp_Vec(-n.X() * r * 0.01, -n.Y() * r * 0.01,
                                                                            -n.Z() * r * 0.01)),
                                                      gp_Dir(n.X(), n.Y(), n.Z())), r, depth).Shape()
                cut = _clean(BRepAlgoAPI_Cut(shape, cyl).Shape())
            except Exception:
                continue
            if _ok(cut, shape, max_rel_vol_change):
                return cut, f"hole d={2 * r:.3g} mm ({rel_d:.1%} of size)"
    return None, ""


def fillet_edge(shape, rng: random.Random, rel_r: float, max_rel_vol_change: float = 0.08, chamfer: bool = False):
    """Fillet (or chamfer) one straight edge with radius rel_r * part size."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Line
    x0, y0, z0, x1, y1, z1 = bbox(shape)
    size = max(x1 - x0, y1 - y0, z1 - z0)
    edges = [e for e in _edges(shape) if BRepAdaptor_Curve(e).GetType() == GeomAbs_Line]
    rng.shuffle(edges)
    r = rel_r * size
    for e in edges[:15]:
        try:
            mk = BRepFilletAPI_MakeChamfer(shape) if chamfer else BRepFilletAPI_MakeFillet(shape)
            mk.Add(r, e)
            mk.Build()
            if not mk.IsDone():
                continue
            new = mk.Shape()
        except Exception:
            continue
        if _ok(new, shape, max_rel_vol_change):
            return new, f"{'chamfer' if chamfer else 'fillet'} {r:.3g} mm on one edge"
    return None, ""


def chiral_test_part(arms=(30.0, 20.0, 10.0), t: float = 5.0):
    """Three arms of different length from a corner: has no mirror symmetry (used in tests)."""
    a = BRepPrimAPI_MakeBox(arms[0], t, t).Shape()
    b = BRepPrimAPI_MakeBox(t, arms[1], t).Shape()
    c = BRepPrimAPI_MakeBox(t, t, arms[2]).Shape()
    return _clean(BRepAlgoAPI_Fuse(BRepAlgoAPI_Fuse(a, b).Shape(), c).Shape())


def plate_with_hole(w=80.0, h=50.0, t=6.0, d=10.0):
    p = BRepPrimAPI_MakeBox(w, h, t).Shape()
    cyl = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(w * 0.3, h * 0.5, -1), gp_Dir(0, 0, 1)), d / 2, t + 2).Shape()
    return _clean(BRepAlgoAPI_Cut(p, cyl).Shape())


def read(path: str):
    return read_step_shape(path)
