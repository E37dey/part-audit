"""Parametric engineering parts for the demo factory (CadQuery, dev-time only).

Standard parts use the nominal dimensions of the published standards (ISO 4762, ISO 4017,
ISO 4032, ISO 7089, ISO 8734, ISO 4026, ISO 10642, ISO 15 / DIN 625 bearing boundary
dimensions, DIN 6885 keys, NEMA ICS-16 motor flanges). Threads are cosmetic (nominal
diameter), as in most CAD libraries. Machined and sheet-metal parts are typical shop
designs with realistic proportions.

Every generator returns a CadQuery Workplane holding one solid, in millimetres.
"""
from __future__ import annotations

import math

import cadquery as cq

# --------------------------------------------------------------------------- standard tables

# ISO 4762 / DIN 912 socket head cap screw: d -> (dk head dia, k head height, s hex key, t socket depth)
ISO4762 = {3: (5.5, 3, 2.5, 1.3), 4: (7, 4, 3, 2), 5: (8.5, 5, 4, 2.5), 6: (10, 6, 5, 3), 8: (13, 8, 6, 4),
           10: (16, 10, 8, 5), 12: (18, 12, 10, 6), 16: (24, 16, 14, 8)}
# ISO 4017 / DIN 933 hex head screw: d -> (s across flats, k head height)
ISO4017 = {4: (7, 2.8), 5: (8, 3.5), 6: (10, 4), 8: (13, 5.3), 10: (16, 6.4), 12: (18, 7.5), 16: (24, 10)}
# ISO 4032 / DIN 934 hex nut: d -> (s, m height)
ISO4032 = {3: (5.5, 2.4), 4: (7, 3.2), 5: (8, 4.7), 6: (10, 5.2), 8: (13, 6.8), 10: (16, 8.4), 12: (18, 10.8),
           16: (24, 14.8)}
# ISO 7089 / DIN 125-A plain washer: d -> (d1 inner, d2 outer, h)
ISO7089 = {3: (3.2, 7, 0.5), 4: (4.3, 9, 0.8), 5: (5.3, 10, 1.0), 6: (6.4, 12, 1.6), 8: (8.4, 16, 1.6),
           10: (10.5, 20, 2.0), 12: (13, 24, 2.5), 16: (17, 30, 3.0)}
# ISO 10642 / DIN 7991 countersunk socket screw: d -> (dk, k, s)
ISO10642 = {4: (8.96, 2.48, 2.5), 5: (11.2, 3.1, 3), 6: (13.44, 3.72, 4), 8: (17.92, 4.96, 5), 10: (22.4, 6.2, 6)}
# ISO 4026 / DIN 913 set screw, flat point: d -> (s, t)
ISO4026 = {3: (1.5, 1.2), 4: (2, 1.5), 5: (2.5, 2), 6: (3, 2), 8: (4, 3), 10: (5, 4)}
# Deep groove ball bearings (ISO 15 boundary dimensions): designation -> (d, D, B, r chamfer)
BEARINGS = {
    "6000": (10, 26, 8, 0.3), "6001": (12, 28, 8, 0.3), "6002": (15, 32, 9, 0.3), "6003": (17, 35, 10, 0.3),
    "6004": (20, 42, 12, 0.6), "6005": (25, 47, 12, 0.6), "6006": (30, 55, 13, 1.0),
    "6200": (10, 30, 9, 0.6), "6201": (12, 32, 10, 0.6), "6202": (15, 35, 11, 0.6), "6203": (17, 40, 12, 0.6),
    "6204": (20, 47, 14, 1.0), "6205": (25, 52, 15, 1.0), "6206": (30, 62, 16, 1.0), "6207": (35, 72, 17, 1.1),
    "6304": (20, 52, 15, 1.1), "6305": (25, 62, 17, 1.1),
}
# DIN 6885-A parallel key for shaft diameter ranges: (d_min, d_max) -> (b, h, t1 shaft groove depth)
DIN6885 = [((10, 12), (4, 4, 2.5)), ((12, 17), (5, 5, 3.0)), ((17, 22), (6, 6, 3.5)), ((22, 30), (8, 7, 4.0)),
           ((30, 38), (10, 8, 5.0)), ((38, 44), (12, 8, 5.0)), ((44, 50), (14, 9, 5.5))]
# NEMA ICS-16 stepper flange: frame -> (bolt square spacing, pilot dia, hole dia, flange size)
NEMA = {"17": (31.0, 22.0, 3.4, 42.3), "23": (47.14, 38.1, 5.2, 56.4), "34": (69.6, 73.0, 6.6, 86.0)}
# Metric clearance holes (ISO 273 medium)
CLEARANCE = {3: 3.4, 4: 4.5, 5: 5.5, 6: 6.6, 8: 9.0, 10: 11.0, 12: 13.5, 16: 17.5}


def key_for_shaft(d: float) -> tuple[float, float, float]:
    for (lo, hi), v in DIN6885:
        if lo < d <= hi:
            return v
    return DIN6885[-1][1]


# --------------------------------------------------------------------------- helpers


def revolve(points: list[tuple[float, float]]) -> cq.Workplane:
    """Solid of revolution around global Z from a closed (r, z) profile."""
    return cq.Workplane("XZ").polyline(points).close().revolve(360, (0, 0, 0), (0, 1, 0))


def ring(r_in: float, r_out: float, z0: float, z1: float, c_out: float = 0.0, c_in: float = 0.0) -> cq.Workplane:
    """Annulus between z0 and z1 with optional 45-degree chamfers on the outer / inner corners."""
    pts = [(r_in + c_in, z0), (r_out - c_out, z0), (r_out, z0 + c_out), (r_out, z1 - c_out), (r_out - c_out, z1),
           (r_in + c_in, z1), (r_in, z1 - c_in), (r_in, z0 + c_in)]
    out = []
    for p in pts:  # drop duplicate points when a chamfer is zero
        if not out or (abs(out[-1][0] - p[0]) > 1e-9 or abs(out[-1][1] - p[1]) > 1e-9):
            out.append(p)
    if abs(out[0][0] - out[-1][0]) < 1e-9 and abs(out[0][1] - out[-1][1]) < 1e-9:
        out.pop()
    return revolve(out)


def cyl_cut(solid: cq.Workplane, origin, direction, d: float, length: float) -> cq.Workplane:
    """Cut a cylinder of diameter d starting at origin along direction (both ways if length<0 -> through)."""
    ox, oy, oz = origin
    dx, dy, dz = direction
    n = math.sqrt(dx * dx + dy * dy + dz * dz)
    dx, dy, dz = dx / n, dy / n, dz / n
    if length < 0:  # through: start far behind
        L = -length
        ox, oy, oz = ox - dx * L / 2, oy - dy * L / 2, oz - dz * L / 2
        length = L
    c = cq.Solid.makeCylinder(d / 2, length, cq.Vector(ox, oy, oz), cq.Vector(dx, dy, dz))
    return solid.cut(cq.Workplane().add(c))


def chamfer_profile_shaft(segments: list[tuple[float, float]], c: float = 0.5) -> list[tuple[float, float]]:
    """(r, z) profile for a stepped shaft from (diameter, length) segments, chamfering every step."""
    pts = [(0.0, 0.0)]
    z = 0.0
    prev_r = 0.0
    for i, (dia, L) in enumerate(segments):
        r = dia / 2
        cc = min(c, r * 0.15, L * 0.25)
        if r > prev_r:  # step up: chamfer outer corner at the start
            pts += [(r - cc, z), (r, z + cc)]
        else:
            pts += [(r, z)]
        z += L
        nxt = segments[i + 1][0] / 2 if i + 1 < len(segments) else 0.0
        if nxt < r:  # step down next: chamfer at the end
            pts += [(r, z - cc), (r - cc, z)]
        else:
            pts += [(r, z)]
        prev_r = r
    pts.append((0.0, z))
    clean = []
    for p in pts:
        if not clean or (abs(clean[-1][0] - p[0]) > 1e-9 or abs(clean[-1][1] - p[1]) > 1e-9):
            clean.append(p)
    return clean


# --------------------------------------------------------------------------- fasteners


# Library "styles": the same standard part drawn by different CAD libraries differs in small details
# (edge rounding, socket depth, end chamfers). Values are fractions used by the generators below.
STYLES = {
    "A": {"edge": 0.08, "socket": 1.00, "tip": 0.10},
    "B": {"edge": 0.05, "socket": 1.15, "tip": 0.12},
    "C": {"edge": 0.06, "socket": 0.90, "tip": 0.08},
    "D": {"edge": 0.07, "socket": 1.05, "tip": 0.15},
}


def socket_head_cap_screw(d: int, L: float, style: str = "A") -> cq.Workplane:
    st = STYLES[style]
    dk, k, s, t = ISO4762[d]
    head = cq.Workplane("XY").circle(dk / 2).extrude(k)
    head = head.faces(">Z").edges().fillet(min(st["edge"] * dk, 0.6 if style == "A" else 0.5))
    head = head.faces(">Z").workplane().polygon(6, s, circumscribed=True).cutBlind(-t * st["socket"])
    c = st["tip"] * d
    shank = revolve([(0, -L), (d / 2 - c, -L), (d / 2, -L + c), (d / 2, 0), (0, 0)])
    return head.union(shank)


def hex_head_screw(d: int, L: float, style: str = "A") -> cq.Workplane:
    st = STYLES[style]
    s, k = ISO4017[d]
    e = s * 2 / math.sqrt(3)
    hexp = cq.Workplane("XY").polygon(6, s, circumscribed=True).extrude(k)
    cham = revolve([(0, 0), (e / 2 + 1, 0), (e / 2 + 1, k - (e / 2 + 1 - 0.95 * s / 2) * math.tan(math.radians(30))),
                    (0.95 * s / 2, k), (0, k)])
    head = hexp.intersect(cham)
    c = st["tip"] * d
    shank = revolve([(0, -L), (d / 2 - c, -L), (d / 2, -L + c), (d / 2, 0), (0, 0)])
    return head.union(shank)


def hex_nut(d: int, style: str = "A") -> cq.Workplane:
    st = STYLES[style]
    s, m = ISO4032[d]
    e = s * 2 / math.sqrt(3)
    hexp = cq.Workplane("XY").polygon(6, s, circumscribed=True).extrude(m)
    h = (e / 2 + 1 - 0.95 * s / 2) * math.tan(math.radians(30))
    cham = revolve([(0, 0), (0.95 * s / 2, 0), (e / 2 + 1, h), (e / 2 + 1, m - h), (0.95 * s / 2, m), (0, m)])
    nut = hexp.intersect(cham)
    c = st["tip"] * d
    bore = revolve([(0, -1), (d / 2 + c + 1, -1), (d / 2, c), (d / 2, m - c), (d / 2 + c + 1, m + 1), (0, m + 1)])
    return nut.cut(bore)


def washer(d: int, style: str = "A") -> cq.Workplane:
    d1, d2, h = ISO7089[d]
    return ring(d1 / 2, d2 / 2, 0, h)


def dowel_pin(d: float, L: float, style: str = "A") -> cq.Workplane:
    c = round(STYLES[style]["tip"] * d, 2)
    return revolve([(0, 0), (d / 2 - c, 0), (d / 2, c), (d / 2, L - c), (d / 2 - c, L), (0, L)])


def set_screw(d: int, L: float, style: str = "A") -> cq.Workplane:
    s, t = ISO4026[d]
    t = t * STYLES[style]["socket"]
    c = STYLES[style]["tip"] * d
    body = revolve([(0, 0), (d / 2 - 1.5 * c, 0), (d / 2, 1.5 * c), (d / 2, L - c), (d / 2 - c, L), (0, L)])
    return body.faces(">Z").workplane().polygon(6, s, circumscribed=True).cutBlind(-t)


def countersunk_screw(d: int, L: float, style: str = "A") -> cq.Workplane:
    st = STYLES[style]
    dk, k, s = ISO10642[d]
    head = revolve([(0, 0), (d / 2, 0), (dk / 2, k), (0, k)])
    head = head.faces(">Z").workplane().polygon(6, s, circumscribed=True).cutBlind(-0.6 * k * st["socket"])
    c = st["tip"] * d
    shank = revolve([(0, -L + k), (d / 2 - c, -L + k), (d / 2, -L + k + c), (d / 2, 0), (0, 0)])
    return head.union(shank)


def ball_bearing(code: str, style: str = "A") -> cq.Workplane:
    """Simplified shielded deep groove ball bearing: rings + shields (balls are not modelled)."""
    d, D, B, r = BEARINGS[code]
    wall = (D - d) / 2 * (0.28 if style in ("A", "C") else 0.26)
    outer = ring(D / 2 - wall, D / 2, 0, B, c_out=r, c_in=0)
    inner = ring(d / 2, d / 2 + wall, 0, B, c_out=0, c_in=r)
    sh = (0.4 if style in ("A", "B") else 0.3) + 0.02 * B  # shield recess
    shield1 = ring(d / 2 + wall - 0.01, D / 2 - wall + 0.01, sh, sh + 0.6)
    shield2 = ring(d / 2 + wall - 0.01, D / 2 - wall + 0.01, B - sh - 0.6, B - sh)
    return outer.union(inner).union(shield1).union(shield2)


def parallel_key(b: float, h: float, L: float) -> cq.Workplane:
    """DIN 6885-A key (round ends)."""
    return cq.Workplane("XY").slot2D(L, b).extrude(h)


# --------------------------------------------------------------------------- machined parts


def stepped_shaft(segments: list[tuple[float, float]], key: tuple[int, float, float] | None = None,
                  c: float = 0.5) -> cq.Workplane:
    """segments: [(diameter, length)]; key: (segment index, key length, offset from segment start)."""
    sh = revolve(chamfer_profile_shaft(segments, c))
    if key:
        i, kl, off = key
        z0 = sum(L for _, L in segments[:i])
        dia = segments[i][0]
        b, h, t1 = key_for_shaft(dia)
        slot = (cq.Workplane("YZ").workplane(offset=dia / 2 - t1)
                .center(0, z0 + off + kl / 2).slot2D(kl, b, angle=90).extrude(t1 + 1))
        sh = sh.cut(slot)
    return sh


def bushing(d: float, D: float, L: float, flange: tuple[float, float] | None = None, c: float = 0.5) -> cq.Workplane:
    b = ring(d / 2, D / 2, 0, L, c_out=c, c_in=c)
    if flange:
        Df, tf = flange
        b = b.union(ring(d / 2, Df / 2, 0, tf, c_out=c, c_in=c))
    return b


def flange(D: float, t: float, bore: float, pcd: float, n_holes: int, hole_d: float,
           spigot: tuple[float, float] | None = None, c: float = 1.0) -> cq.Workplane:
    f = ring(bore / 2, D / 2, 0, t, c_out=c, c_in=0.5)
    if spigot:
        ds, hs = spigot
        f = f.union(ring(bore / 2, ds / 2, t, t + hs, c_out=0.5, c_in=0.5))
    f = (f.faces("<Z").workplane(centerOption="CenterOfBoundBox")
         .polarArray(pcd / 2, 0, 360, n_holes).hole(hole_d))
    return f


def plate(W: float, H: float, T: float, holes: list[tuple[float, float, float]] = (),
          corner_r: float = 0.0, slots: list[tuple[float, float, float, float, float]] = (),
          pockets: list[tuple[float, float, float, float, float]] = (), chamfer: float = 0.0,
          cbores: list[tuple[float, float, float, float, float]] = ()) -> cq.Workplane:
    """Rectangular plate, origin at a corner. holes: (x, y, d); slots: (x, y, length, width, angle);
    pockets: (x, y, w, h, depth); cbores: (x, y, d, cbore_d, cbore_depth)."""
    p = cq.Workplane("XY").box(W, H, T, centered=False)
    if corner_r > 0:
        p = p.edges("|Z").fillet(corner_r)
    if chamfer > 0:
        p = p.faces(">Z").edges().chamfer(chamfer)
    for (x, y, w, h, dep) in pockets:
        p = p.cut(cq.Workplane("XY").box(w, h, dep + 0.01, centered=False).translate((x - w / 2, y - h / 2, T - dep))
                  .edges("|Z").fillet(min(w, h) * 0.12))
    for (x, y, d) in holes:
        p = cyl_cut(p, (x, y, T / 2), (0, 0, 1), d, -(T * 3))
    for (x, y, d, cd, cdep) in cbores:
        p = cyl_cut(p, (x, y, T / 2), (0, 0, 1), d, -(T * 3))
        p = p.cut(cq.Workplane().add(cq.Solid.makeCylinder(cd / 2, cdep + 0.01, cq.Vector(x, y, T - cdep))))
    for (x, y, L, w, ang) in slots:
        p = p.cut(cq.Workplane("XY").center(x, y).slot2D(L, w, ang).extrude(T * 3).translate((0, 0, -T)))
    return p


def angle_bracket(a: float, b: float, w: float, t: float, holes_a: list[tuple[float, float]] = (),
                  holes_b: list[tuple[float, float]] = (), hole_d: float = 6.6, rib: bool = False,
                  r_in: float = 0.0) -> cq.Workplane:
    """Machined L-bracket: base leg a (along X) x vertical leg b (along Z), width w (along Y), thickness t.
    holes_a: (x, y) on the base; holes_b: (y, z) on the vertical leg."""
    prof = (cq.Workplane("XZ").polyline([(0, 0), (a, 0), (a, t), (t, t), (t, b), (0, b)]).close().extrude(-w))
    if r_in > 0:
        prof = prof.edges("|Y").edges(cq.selectors.NearestToPointSelector((t, w / 2, t))).fillet(r_in)
    if rib:
        rib_w = max(t, 4.0)
        tri = (cq.Workplane("XZ").polyline([(t, t), (a * 0.75, t), (t, b * 0.75)]).close().extrude(-rib_w)
               .translate((0, w / 2 - rib_w / 2, 0)))
        prof = prof.union(tri)
    for (x, y) in holes_a:
        prof = cyl_cut(prof, (x, y, t / 2), (0, 0, 1), hole_d, -(t * 3))
    for (y, z) in holes_b:
        prof = cyl_cut(prof, (t / 2, y, z), (1, 0, 0), hole_d, -(t * 3))
    return prof


def motor_mount(frame: str, base: float, height: float, w: float, t: float, slot_len: float = 12.0) -> cq.Workplane:
    """L-shaped NEMA motor bracket: motor face (vertical) with pilot + 4 holes, base with 2 slots."""
    sq, pilot, hd, fl = NEMA[frame]
    br = angle_bracket(base, height, w, t, rib=False)
    zc = t + (height - t) / 2 + 2
    br = cyl_cut(br, (t / 2, w / 2, zc), (1, 0, 0), pilot + 0.5, -(t * 3))
    for dy in (-sq / 2, sq / 2):
        for dz in (-sq / 2, sq / 2):
            br = cyl_cut(br, (t / 2, w / 2 + dy, zc + dz), (1, 0, 0), hd, -(t * 3))
    hole = CLEARANCE[6] if frame != "34" else CLEARANCE[8]
    for y in (w * 0.2, w * 0.8):
        x = t + (base - t) * 0.6
        br = br.cut(cq.Workplane("XY").center(x, y).slot2D(slot_len, hole, 0).extrude(t * 3).translate((0, 0, -t)))
    return br


def bearing_housing(code: str, H: float, W: float, L: float, base_t: float, bolt: int = 8) -> cq.Workplane:
    """Pillow-block style housing for a bearing: block with stepped bore, two base bolt holes."""
    d, D, B, _ = BEARINGS[code]
    blk = cq.Workplane("XY").box(L, W, H, centered=(True, True, False))
    blk = blk.edges("|Y and >Z").fillet(min(H, L) * 0.18)
    axis_z = H * 0.58
    blk = cyl_cut(blk, (0, -W, axis_z), (0, 1, 0), d + 6, 3 * W)          # clearance bore
    blk = blk.cut(cq.Workplane().add(cq.Solid.makeCylinder(D / 2, B + 0.5, cq.Vector(0, -W / 2 - 0.01, axis_z),
                                                           cq.Vector(0, 1, 0))))  # bearing seat
    feet = cq.Workplane("XY").box(L + 2 * (CLEARANCE[bolt] + 8), W, base_t, centered=(True, True, False))
    blk = blk.union(feet)
    for x in (-(L / 2 + CLEARANCE[bolt] / 2 + 4), L / 2 + CLEARANCE[bolt] / 2 + 4):
        blk = cyl_cut(blk, (x, 0, base_t / 2), (0, 0, 1), CLEARANCE[bolt], -(base_t * 3))
    return blk


def pulley(D: float, width: float, bore: float, hub_d: float, hub_len: float, flange_h: float = 0.0,
           crown: bool = False) -> cq.Workplane:
    """Flat-belt / drum pulley with hub; bore with DIN 6885 keyway."""
    pts = [(bore / 2, 0), (hub_d / 2, 0), (hub_d / 2, (hub_len - width) / 2 if hub_len > width else 0)]
    z0 = max((hub_len - width) / 2, 0)
    rim_in = D / 2 - max(4.0, D * 0.06)
    web = max(6.0, width * 0.25)
    zc = z0 + width / 2
    pts += [(rim_in, zc - web / 2), (rim_in, z0)]
    if flange_h:
        pts += [(D / 2 + flange_h, z0), (D / 2 + flange_h, z0 + 2.0), (D / 2, z0 + 2.0)]
    else:
        pts += [(D / 2, z0)]
    if crown:
        pts += [(D / 2 + 0.6, zc)]
    if flange_h:
        pts += [(D / 2, z0 + width - 2.0), (D / 2 + flange_h, z0 + width - 2.0), (D / 2 + flange_h, z0 + width)]
    else:
        pts += [(D / 2, z0 + width)]
    pts += [(rim_in, z0 + width), (rim_in, zc + web / 2), (hub_d / 2, zc + web / 2) if hub_len <= width else
            (hub_d / 2, z0 + width), (hub_d / 2, max(hub_len, width)), (bore / 2, max(hub_len, width))]
    clean = []
    for p in pts:
        if not clean or (abs(clean[-1][0] - p[0]) > 1e-9 or abs(clean[-1][1] - p[1]) > 1e-9):
            clean.append(p)
    pl = revolve(clean)
    b, h, t1 = key_for_shaft(bore)
    t2 = h - t1 + 0.3
    kw = cq.Workplane("XY").box(b, t2 + 0.01 + bore / 2, max(hub_len, width) + 2, centered=(True, False, False)) \
        .translate((0, 0, -1))
    return pl.cut(kw)


def conveyor_roller(D: float, L: float, wall: float, axle_d: float, axle_len: float) -> cq.Workplane:
    tube = ring(D / 2 - wall, D / 2, 0, L, c_out=0.8)
    caps = ring(axle_d / 2, D / 2 - wall + 0.01, 0, 8).union(ring(axle_d / 2, D / 2 - wall + 0.01, L - 8, L))
    axle = revolve([(0, -axle_len), (axle_d / 2 - 0.5, -axle_len), (axle_d / 2, -axle_len + 0.5),
                    (axle_d / 2, L + axle_len - 0.5), (axle_d / 2 - 0.5, L + axle_len), (0, L + axle_len)])
    r = tube.union(caps).union(axle)
    # flats on the axle ends (hex seat in the conveyor side frame)
    fl = axle_d * 0.8
    for z in (-axle_len, L):
        cut = cq.Workplane("XY").box(axle_d * 2, axle_d * 2, axle_len - 1, centered=(True, True, False)) \
            .cut(cq.Workplane("XY").box(axle_d * 2, fl, axle_len - 1, centered=(True, True, False)))
        r = r.cut(cut.translate((0, 0, z if z < 0 else L + 1)))
    return r


def spur_gear(m: float, z: int, b: float, bore: float, hub: tuple[float, float] | None = None,
              alpha_deg: float = 20.0) -> cq.Workplane:
    """Involute spur gear (standard addendum 1m, dedendum 1.25m), spline flanks, bore with keyway."""
    alpha = math.radians(alpha_deg)
    r = m * z / 2
    rb = r * math.cos(alpha)
    ra = r + m
    rf = r - 1.25 * m
    inv = math.tan(alpha) - alpha
    half = math.pi / (2 * z) + inv  # angular half-thickness at the base circle
    t0 = math.sqrt(max(rf / rb, 1.0) ** 2 - 1)
    tmax = math.sqrt((ra / rb) ** 2 - 1)
    n = 7
    flank = []  # (radius, polar angle of the involute point)
    for i in range(n + 1):
        t = t0 + (tmax - t0) * i / n
        x = rb * (math.cos(t) + t * math.sin(t))
        y = rb * (math.sin(t) - t * math.cos(t))
        flank.append((math.hypot(x, y), math.atan2(y, x)))
    pitch = 2 * math.pi / z

    def P(rr, ang):
        return (rr * math.cos(ang), rr * math.sin(ang))

    wp = cq.Workplane("XY").moveTo(*P(rf, -half))
    for k in range(z):
        c = k * pitch
        if rf < rb:
            wp = wp.lineTo(*P(rb, c - half))
        wp = wp.spline([P(rr, c - half + a) for rr, a in flank[1:]], includeCurrent=True)
        a_tip = flank[-1][1]
        wp = wp.threePointArc(P(ra, c), P(ra, c + half - a_tip))
        wp = wp.spline([P(rr, c + half - a) for rr, a in reversed(flank[:-1])], includeCurrent=True)
        if rf < rb:
            wp = wp.lineTo(*P(rf, c + half))
        nxt = P(rf, c + pitch - half) if k < z - 1 else P(rf, -half)
        wp = wp.threePointArc(P(rf, c + pitch / 2), nxt)
    g = wp.close().extrude(b)
    if hub:
        hd, hl = hub
        g = g.union(ring(0, hd / 2, b, b + hl, c_out=0.5))
    total = b + (hub[1] if hub else 0)
    g = g.cut(ring(0, bore / 2, -1, total + 1))
    kb, kh, t1 = key_for_shaft(bore)
    t2 = kh - t1 + 0.3
    g = g.cut(cq.Workplane("XY").box(kb, bore / 2 + t2, total + 2, centered=(True, False, False)).translate((0, 0, -1)))
    return g


def profile_4040(L: float, size: float = 40.0, slot: float = 8.2) -> cq.Workplane:
    """Generic slot-8 aluminium extrusion section (four T-slots, centre bore), cut to length L."""
    s = size / 2
    sec = cq.Workplane("XY").rect(size, size).extrude(L)
    sec = sec.edges("|Z").fillet(1.5)
    lip = 4.3
    cav_w, cav_d = 16.0, 6.2
    for ang in (0, 90, 180, 270):
        t = (cq.Workplane("XY").center(s - lip / 2, 0).rect(lip + 0.02, slot).extrude(L + 2).translate((0, 0, -1))
             .union(cq.Workplane("XY").center(s - lip - cav_d / 2, 0).rect(cav_d, cav_w).extrude(L + 2)
                    .translate((0, 0, -1))))
        sec = sec.cut(t.rotate((0, 0, 0), (0, 0, 1), ang))
    sec = sec.cut(ring(0, 3.4, -1, L + 1))
    return sec


def profile_corner_bracket(size: float = 40.0, t: float = 4.5, hole: float = 8.5) -> cq.Workplane:
    br = angle_bracket(size, size, size * 0.85, t, holes_a=[(size * 0.6, size * 0.425)],
                       holes_b=[(size * 0.425, size * 0.6)], hole_d=hole, rib=True)
    return br


def leveling_foot(base_d: float, base_h: float, thread: int, stud_len: float, hex_s: float) -> cq.Workplane:
    base = revolve([(0, 0), (base_d / 2 - 2, 0), (base_d / 2, 2), (base_d / 2, base_h * 0.6),
                    (base_d * 0.3, base_h), (0, base_h)])
    hx = cq.Workplane("XY").polygon(6, hex_s, circumscribed=True).extrude(hex_s * 0.5).translate((0, 0, base_h))
    stud = revolve([(0, base_h), (thread / 2, base_h), (thread / 2, base_h + stud_len - 1),
                    (thread / 2 - 1, base_h + stud_len), (0, base_h + stud_len)])
    return base.union(hx).union(stud)


def u_handle(span: float, height: float, d: float, thread_hole: float) -> cq.Workplane:
    path = cq.Workplane("XZ").polyline([(0, 0), (0, height), (span, height), (span, 0)])
    h = cq.Workplane("XY").circle(d / 2).sweep(path, transition="round")
    for x in (0, span):
        h = h.cut(cq.Workplane().add(cq.Solid.makeCylinder(thread_hole / 2, d * 1.6, cq.Vector(x, 0, -0.01))))
    return h


def shaft_collar(bore: float, D: float, w: float, screw: int = 5) -> cq.Workplane:
    c = ring(bore / 2, D / 2, 0, w, c_out=0.5, c_in=0.3)
    return cyl_cut(c, (0, D / 2 + 1, w / 2), (0, -1, 0), screw * 0.85, D / 2 - bore / 2 + 2)


def shaft_support(d: float, H: float, W: float, T: float) -> cq.Workplane:
    """SK-style linear shaft support: block with bore, clamp slit, two base holes."""
    blk = cq.Workplane("XY").box(W, T, H, centered=(True, True, False))
    blk = blk.edges("|Y and >Z").fillet(T * 0.35)
    hz = H * 0.62
    blk = cyl_cut(blk, (0, -T, hz), (0, 1, 0), d, 3 * T)
    blk = blk.cut(cq.Workplane("XY").box(1.2, T + 2, H - hz + 1, centered=(True, True, False)).translate((0, 0, hz)))
    blk = cyl_cut(blk, (-W / 2 - 1, 0, hz + d * 0.85), (1, 0, 0), 4.5, W * 0.6)
    for x in (-W * 0.36, W * 0.36):
        blk = cyl_cut(blk, (x, 0, H * 0.2), (0, 0, 1), 5.5, -(H * 0.6))
    return blk


def linear_shaft(d: float, L: float) -> cq.Workplane:
    c = 0.5 if d < 12 else 1.0
    return revolve([(0, 0), (d / 2 - c, 0), (d / 2, c), (d / 2, L - c), (d / 2 - c, L), (0, L)])


# --------------------------------------------------------------------------- sheet metal


def _bent_l_profile(a: float, b: float, t: float, r: float):
    R = r + t
    q = 1 / math.sqrt(2)
    return (cq.Workplane("XZ").moveTo(a, 0).lineTo(R, 0).threePointArc((R - R * q, R - R * q), (0, R))
            .lineTo(0, b).lineTo(t, b).lineTo(t, R).threePointArc((R - r * q, R - r * q), (R, t)).lineTo(a, t)
            .close())


def sheet_l_bracket(a: float, b: float, w: float, t: float, holes_a=(), holes_b=(), hole_d: float = 6.6,
                    slots_a=()) -> cq.Workplane:
    """Bent sheet-metal L bracket (inner bend radius = t)."""
    br = _bent_l_profile(a, b, t, t).extrude(-w)
    for (x, y) in holes_a:
        br = cyl_cut(br, (x, y, t / 2), (0, 0, 1), hole_d, -(t * 4))
    for (y, z) in holes_b:
        br = cyl_cut(br, (t / 2, y, z), (1, 0, 0), hole_d, -(t * 4))
    for (x, y, L) in slots_a:
        br = br.cut(cq.Workplane("XY").center(x, y).slot2D(L, hole_d, 0).extrude(t * 4).translate((0, 0, -t * 2)))
    return br


def sheet_u_channel(web: float, flange_h: float, L: float, t: float, holes_web=(), hole_d: float = 6.6,
                    flange_holes=()) -> cq.Workplane:
    """U channel / cover: web along X (width web), flanges up along Z, length L along Y."""
    r = t
    R = r + t
    q = 1 / math.sqrt(2)
    xw = web
    prof = (cq.Workplane("XZ").moveTo(R, 0).lineTo(xw - R, 0)
            .threePointArc((xw - R + R * q, R - R * q), (xw, R)).lineTo(xw, flange_h).lineTo(xw - t, flange_h)
            .lineTo(xw - t, R).threePointArc((xw - R + r * q, R - r * q), (xw - R, t)).lineTo(R, t)
            .threePointArc((R - r * q, R - r * q), (t, R)).lineTo(t, flange_h).lineTo(0, flange_h).lineTo(0, R)
            .threePointArc((R - R * q, R - R * q), (R, 0)).close())
    u = prof.extrude(-L)
    for (x, y) in holes_web:
        u = cyl_cut(u, (x, y, t / 2), (0, 0, 1), hole_d, -(t * 4))
    for (y, z) in flange_holes:
        u = cyl_cut(u, (t / 2, y, z), (1, 0, 0), hole_d, -(t * 4))
        u = cyl_cut(u, (xw - t / 2, y, z), (1, 0, 0), hole_d, -(t * 4))
    return u


def sheet_z_bracket(a: float, h: float, c: float, w: float, t: float, hole_d: float = 6.6) -> cq.Workplane:
    """Z bracket: lower flange a, rise h, upper flange c (inner radius t)."""
    r = t
    R = r + t
    q = 1 / math.sqrt(2)
    prof = (cq.Workplane("XZ").moveTo(0, 0).lineTo(a - R, 0)
            .threePointArc((a - R + R * q, R - R * q), (a, R)).lineTo(a, h - r)
            .threePointArc((a + r - r * q, h - r + r * q), (a + r, h)).lineTo(a + c, h).lineTo(a + c, h + t)
            .lineTo(a + r, h + t).threePointArc((a + r - R * q, h - r + R * q), (a - t, h - r))
            .lineTo(a - t, R).threePointArc((a - R + r * q, R - r * q), (a - R, t)).lineTo(0, t).close())
    z = prof.extrude(-w)
    z = cyl_cut(z, ((a - t) / 2, w / 2, t / 2), (0, 0, 1), hole_d, -(t * 4))
    z = cyl_cut(z, (a + r + (c - r) / 2, w / 2, h + t / 2), (0, 0, 1), hole_d, -(t * 4))
    return z


# --------------------------------------------------------------------------- misc


def clamp_block(L: float, W: float, H: float, step: float, holes: int = 2, screw: int = 6) -> cq.Workplane:
    b = cq.Workplane("XY").box(L, W, H, centered=(True, True, False))
    b = b.cut(cq.Workplane("XY").box(L + 1, W / 2, step, centered=(True, False, False)).translate((0, 0, H - step)))
    xs = [(-L / 2 + L * (i + 1) / (holes + 1)) for i in range(holes)]
    dk, k, _, _ = ISO4762[screw]
    for x in xs:
        b = cyl_cut(b, (x, -W / 4, H / 2), (0, 0, 1), CLEARANCE[screw], -(H * 3))
        b = b.cut(cq.Workplane().add(cq.Solid.makeCylinder((dk + 1) / 2, k + 0.5, cq.Vector(x, -W / 4, H - k - 0.5))))
    return b.edges("|X and >Z").chamfer(0.8)


def tube(D: float, wall: float, L: float) -> cq.Workplane:
    return ring(D / 2 - wall, D / 2, 0, L, c_out=0.3, c_in=0.3)
