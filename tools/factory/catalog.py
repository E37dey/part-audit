"""Design catalog of the demo factory: unique physical designs with names in Hebrew/English/PLM style.

A *design* is one physical part. The factory build (build.py) places designs into the
systems of the four sites (and a legacy folder) as *records*, with site-specific part
numbers, names and CAD-library details - which is how real duplicates come about.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import parts as P

# key -> (Hebrew, English, density g/cm3)
MATERIALS = {
    "AL6061": ("אלומיניום 6061-T6", "AL 6061-T6", 2.70),
    "AL5083": ("אלומיניום 5083", "AL 5083", 2.66),
    "S235": ("פלדה S235JR", "STEEL S235JR", 7.85),
    "C45": ("פלדה C45", "STEEL C45", 7.85),
    "42CRMO4": ("פלדה 42CrMo4", "STEEL 42CrMo4", 7.85),
    "SS304": ("נירוסטה 304", "STAINLESS 304", 7.93),
    "SS316": ("נירוסטה 316", "STAINLESS 316", 7.98),
    "BRASS": ("פליז CuZn39Pb3", "BRASS CuZn39Pb3", 8.47),
    "BRONZE": ("ברונזה CuSn12", "BRONZE CuSn12", 8.75),
    "POM": ("POM-C (דלרין)", "POM-C", 1.41),
    "PA6": ("ניילון PA6", "NYLON PA6", 1.14),
    "GALV": ("פח מגולוון DX51D", "GALV. STEEL DX51D", 7.85),
    "STEEL129": ("פלדה 12.9", "STEEL 12.9", 7.85),
    "STEEL88": ("פלדה 8.8", "STEEL 8.8", 7.85),
    "A2": ("נירוסטה A2-70", "STAINLESS A2-70", 7.93),
    "100CR6": ("פלדת מסבים 100Cr6", "BEARING STEEL 100Cr6", 7.81),
    "STEEL": ("פלדה", "STEEL", 7.85),
    "ZINC_STEEL": ("פלדה מגולוונת", "ZINC PLATED STEEL", 7.85),
}

FINISHES = {
    "": ("", ""),
    "black": ("השחרה", "BLACK OXIDE"),
    "zinc": ("גלוון", "ZINC PLATED"),
    "anod_nat": ("אנודייז טבעי", "CLEAR ANODIZE"),
    "anod_black": ("אנודייז שחור", "BLACK ANODIZE"),
    "paint": ("צביעה RAL 7035", "PAINT RAL 7035"),
    "nickel": ("ניקל כימי", "ELECTROLESS NICKEL"),
}


@dataclass
class Design:
    did: str
    family: str
    he: str                       # Hebrew name
    en: str                       # English name
    plm: str                      # PLM noun-first style
    make_buy: str                 # make | buy
    material: str                 # MATERIALS key
    fn: object                    # generator in parts.py
    kwargs: dict = field(default_factory=dict)
    std: str = ""                 # standard (ISO 4762 ...) for standard parts
    spec: str = ""                # canonical spec (M6x20, 6204-2RS ...)
    finish: str = ""
    cost: float = 0.0             # synthetic unit cost (ILS)
    styled: bool = False          # generator takes a CAD-library style argument
    chiral: bool = False          # has a distinct mirror image
    tags: tuple = ()

    def build(self, style: str = "A", **over):
        kw = {**self.kwargs, **over}
        if self.styled:
            kw["style"] = style
        return self.fn(**kw)


def _f(x: float) -> str:
    return f"{x:g}"


def catalog() -> list[Design]:
    out: list[Design] = []

    def add(**kw):
        d = Design(did=f"D{len(out) + 1:03d}", **kw)
        out.append(d)
        return d

    # ---------------------------------------------------------------- fasteners (buy)
    shcs = [(3, 8), (3, 12), (4, 10), (4, 16), (5, 12), (5, 16), (5, 20), (6, 12), (6, 16), (6, 20), (6, 25),
            (6, 30), (8, 16), (8, 20), (8, 25), (8, 30), (8, 40), (10, 25), (10, 30), (10, 40), (12, 40)]
    for d, L in shcs:
        add(family="shcs", he=f"בורג אלן ראש גלילי M{d}x{L} DIN 912", en=f"SOCKET HEAD CAP SCREW M{d}x{L} ISO 4762",
            plm=f"SCREW,SOCKET HEAD CAP,M{d}X{L}", make_buy="buy", material="STEEL129", finish="black",
            fn=P.socket_head_cap_screw, kwargs={"d": d, "L": L}, std="ISO 4762", spec=f"M{d}x{L}",
            cost=round(0.04 * d * d * (1 + L / 40) / 3 + 0.08, 2), styled=True)
    for d, L in [(5, 12), (6, 20)]:  # stainless twins of two sizes (same geometry, different item)
        add(family="shcs", he=f"בורג אלן ראש גלילי M{d}x{L} DIN 912 נירוסטה A2",
            en=f"SOCKET HEAD CAP SCREW M{d}x{L} ISO 4762 A2", plm=f"SCREW,SOCKET HEAD CAP,M{d}X{L},A2",
            make_buy="buy", material="A2", fn=P.socket_head_cap_screw, kwargs={"d": d, "L": L}, std="ISO 4762",
            spec=f"M{d}x{L} A2", cost=round(0.12 * d * d * (1 + L / 40) / 3 + 0.2, 2), styled=True,
            tags=("hn_spec",))
    for d, L in [(6, 20), (8, 25), (8, 30), (10, 30), (10, 40), (12, 50)]:
        add(family="hexscrew", he=f"בורג ראש משושה M{d}x{L} DIN 933", en=f"HEX HEAD SCREW M{d}x{L} ISO 4017",
            plm=f"SCREW,HEX HEAD,M{d}X{L}", make_buy="buy", material="STEEL88", finish="zinc",
            fn=P.hex_head_screw, kwargs={"d": d, "L": L}, std="ISO 4017", spec=f"M{d}x{L}",
            cost=round(0.03 * d * d * (1 + L / 50) / 3 + 0.06, 2), styled=True)
    for d in (4, 5, 6, 8, 10, 12):
        add(family="nut", he=f"אום משושה M{d} DIN 934", en=f"HEX NUT M{d} ISO 4032", plm=f"NUT,HEX,M{d}",
            make_buy="buy", material="STEEL88", finish="zinc", fn=P.hex_nut, kwargs={"d": d}, std="ISO 4032",
            spec=f"M{d}", cost=round(0.01 * d * d / 2 + 0.03, 2), styled=True)
    for d in (4, 5, 6, 8, 10, 12):
        add(family="washer", he=f"דיסקית שטוחה M{d} DIN 125", en=f"FLAT WASHER M{d} ISO 7089", plm=f"WASHER,FLAT,M{d}",
            make_buy="buy", material="STEEL", finish="zinc", fn=P.washer, kwargs={"d": d}, std="ISO 7089",
            spec=f"M{d}", cost=round(0.004 * d * d / 2 + 0.02, 2), styled=True)
    for d, L in [(4, 10), (5, 12), (6, 16), (8, 20)]:
        add(family="csk", he=f"בורג שקוע אלן M{d}x{L} DIN 7991", en=f"COUNTERSUNK SOCKET SCREW M{d}x{L} ISO 10642",
            plm=f"SCREW,COUNTERSUNK,M{d}X{L}", make_buy="buy", material="STEEL129", finish="black",
            fn=P.countersunk_screw, kwargs={"d": d, "L": L}, std="ISO 10642", spec=f"M{d}x{L}",
            cost=round(0.05 * d * d / 3 + 0.1, 2), styled=True)
    for d, L in [(4, 6), (5, 8), (6, 8), (8, 10)]:
        add(family="setscrew", he=f"בורג אל-ראש M{d}x{L} DIN 913", en=f"SET SCREW FLAT POINT M{d}x{L} ISO 4026",
            plm=f"SCREW,SET,FLAT PT,M{d}X{L}", make_buy="buy", material="STEEL", finish="black",
            fn=P.set_screw, kwargs={"d": d, "L": L}, std="ISO 4026", spec=f"M{d}x{L}",
            cost=round(0.03 * d * d / 3 + 0.08, 2), styled=True)
    for d, L in [(4, 12), (5, 16), (6, 20), (6, 24), (8, 24), (8, 30), (10, 40)]:
        add(family="pin", he=f"פין מכוון {d}x{L} h6 DIN 6325", en=f"DOWEL PIN {d}x{L} ISO 8734",
            plm=f"PIN,DOWEL,{d}X{L}", make_buy="buy", material="STEEL", fn=P.dowel_pin, kwargs={"d": d, "L": L},
            std="ISO 8734", spec=f"{d}x{L}", cost=round(0.05 * d * L / 20 + 0.1, 2), styled=True)
    for b, h, L in [(5, 5, 20), (6, 6, 25), (8, 7, 32), (10, 8, 40)]:
        add(family="key", he=f"שגם {b}x{h}x{L} DIN 6885", en=f"PARALLEL KEY {b}x{h}x{L} DIN 6885",
            plm=f"KEY,PARALLEL,{b}X{h}X{L}", make_buy="buy", material="C45", fn=P.parallel_key,
            kwargs={"b": b, "h": h, "L": L}, std="DIN 6885", spec=f"{b}x{h}x{L}", cost=round(0.4 + 0.02 * L, 2))

    # ---------------------------------------------------------------- bearings (buy)
    for code in ("6001", "6002", "6004", "6005", "6201", "6202", "6203", "6204", "6205", "6206", "6304"):
        dd, DD, BB, _ = P.BEARINGS[code]
        add(family="bearing", he=f"מסב כדורי {code}-2RS", en=f"BALL BEARING {code}-2RS", plm=f"BEARING,BALL,{code}-2RS",
            make_buy="buy", material="100CR6", fn=P.ball_bearing, kwargs={"code": code}, std="ISO 15",
            spec=f"{code}-2RS", cost=round(6 + 0.35 * DD * BB / 20, 1), styled=True)
    for code in ("6202", "6204", "6205"):  # ZZ (metal shields) twins: same envelope geometry, different item
        dd, DD, BB, _ = P.BEARINGS[code]
        add(family="bearing", he=f"מסב כדורי {code}-ZZ", en=f"BALL BEARING {code}-ZZ", plm=f"BEARING,BALL,{code}-ZZ",
            make_buy="buy", material="100CR6", fn=P.ball_bearing, kwargs={"code": code}, std="ISO 15",
            spec=f"{code}-ZZ", cost=round(5 + 0.33 * DD * BB / 20, 1), styled=True, tags=("hn_spec",))

    # ---------------------------------------------------------------- purchased components
    for bd, th, sl in [(50, 10, 50), (60, 12, 60), (80, 16, 80)]:
        add(family="foot", he=f"רגלית מתכווננת M{th}x{sl} בסיס {bd}", en=f"LEVELING FOOT M{th}x{sl} BASE {bd}",
            plm=f"FOOT,LEVELING,M{th}X{sl}", make_buy="buy", material="ZINC_STEEL",
            fn=P.leveling_foot, kwargs={"base_d": bd, "base_h": 10 + bd / 20, "thread": th, "stud_len": sl,
                                        "hex_s": {10: 17, 12: 19, 16: 24}[th]},
            spec=f"M{th}x{sl}", cost=round(9 + bd / 6, 1))
    for span, dia in [(120, 10), (180, 12)]:
        add(family="handle", he=f"ידית U {span} מ\"מ", en=f"U-HANDLE {span}MM", plm=f"HANDLE,U,{span}MM",
            make_buy="buy", material="AL6061", finish="anod_black", fn=P.u_handle,
            kwargs={"span": span, "height": 40 if span < 150 else 48, "d": dia, "thread_hole": 5.0 if dia < 12 else 6.8},
            spec=f"{span}", cost=round(14 + span / 20, 1))
    add(family="corner", he="זוויתן לפרופיל 40", en="CORNER BRACKET 40 SERIES", plm="BRACKET,CORNER,40",
        make_buy="buy", material="AL6061", fn=P.profile_corner_bracket, kwargs={}, spec="40", cost=4.2)
    for dd in (12, 16, 20):
        add(family="shaftsupport", he=f"תושבת ציר ליניארי SK{dd}", en=f"SHAFT SUPPORT SK{dd}", plm=f"SUPPORT,SHAFT,SK{dd}",
            make_buy="buy", material="AL6061", fn=P.shaft_support,
            kwargs={"d": dd, "H": 2.6 * dd + 6, "W": 3 * dd + 6, "T": 14 if dd < 20 else 18},
            spec=f"SK{dd}", cost=round(18 + dd, 1))
    for dd, LL in [(12, 400), (16, 500), (20, 600)]:
        add(family="linshaft", he=f"ציר ליניארי מוקשה Ø{dd}x{LL} h6", en=f"LINEAR SHAFT D{dd}x{LL} h6",
            plm=f"SHAFT,LINEAR,D{dd}X{LL}", make_buy="buy", material="C45", fn=P.linear_shaft,
            kwargs={"d": dd, "L": LL}, spec=f"{dd}x{LL}", cost=round(dd * LL / 200 + 20, 1))
    for bore, D_, w in [(12, 25, 10), (20, 36, 12), (25, 40, 14)]:
        add(family="collar", he=f"טבעת נעילה לציר Ø{bore}", en=f"SHAFT COLLAR D{bore}", plm=f"COLLAR,SHAFT,D{bore}",
            make_buy="buy", material="S235", finish="black", fn=P.shaft_collar,
            kwargs={"bore": bore, "D": D_, "w": w}, spec=f"{bore}", cost=round(6 + bore / 3, 1))
    for LL in (300, 400, 500, 600, 800, 1000, 1200, 1500, 2000):
        add(family="profile", he=f"פרופיל אלומיניום 40x40 L={LL}", en=f"AL PROFILE 40x40 L={LL}",
            plm=f"PROFILE,AL,40X40,L{LL}", make_buy="buy", material="AL6061", finish="anod_nat",
            fn=P.profile_4040, kwargs={"L": LL}, spec=f"40x40x{LL}", cost=round(LL * 0.055 + 6, 1))

    # ---------------------------------------------------------------- machined plates
    plates = [
        ("בסיס", "BASE", 300, 200, 15, "AL6061", "grid4", 10),
        ("בסיס", "BASE", 400, 250, 20, "S235", "grid6", 12),
        ("בסיס מנוע", "MOTOR BASE", 220, 160, 12, "S235", "grid4slots", 8),
        ("הרכבה", "MOUNTING", 200, 150, 10, "AL6061", "grid4", 9),
        ("הרכבה", "MOUNTING", 160, 120, 8, "AL6061", "grid4", 6.6),
        ("הרכבה", "MOUNTING", 250, 180, 10, "AL6061", "grid6", 9),
        ("עליונה", "TOP", 350, 220, 12, "AL6061", "pocket", 9),
        ("צד", "SIDE", 280, 140, 10, "AL6061", "row3", 9),
        ("צד", "SIDE", 320, 160, 12, "S235", "row4", 11),
        ("חיבור", "CONNECTION", 120, 80, 10, "S235", "grid4", 9),
        ("חיבור", "CONNECTION", 100, 60, 8, "AL6061", "grid4", 6.6),
        ("כיוון", "ADJUSTING", 140, 60, 10, "C45", "slots", 9),
        ("כיסוי", "COVER", 260, 200, 5, "AL5083", "grid4cs", 5.5),
        ("כיסוי", "COVER", 180, 140, 4, "AL5083", "grid4cs", 4.5),
        ("מתאם", "ADAPTER", 150, 150, 15, "AL6061", "pcd", 9),
        ("חיזוק", "STIFFENER", 200, 50, 8, "S235", "row2", 9),
        ("תחתונה", "BOTTOM", 300, 180, 10, "S235", "grid6", 11),
        ("חיישן", "SENSOR", 80, 50, 5, "AL6061", "row2", 4.5),
        ("פיקס", "FIXTURE", 250, 200, 20, "C45", "dowels", 11),
        ("פיקס", "FIXTURE", 180, 150, 16, "C45", "dowels", 9),
        ("שילוט", "LABEL", 120, 70, 3, "AL5083", "row2", 4.5),
        ("הגנה", "GUARD", 300, 250, 3, "AL5083", "grid6", 5.5),
    ]
    for i, (role_he, role_en, W, H, T, mat, pattern, hd) in enumerate(plates):
        kw = _plate_kwargs(W, H, T, pattern, hd)
        add(family="plate", he=f"פלטת {role_he} {W}x{H}x{T}", en=f"{role_en} PLATE {W}x{H}x{T}",
            plm=f"PLATE,{role_en},{W}X{H}X{T}", make_buy="make", material=mat,
            finish="anod_nat" if mat.startswith("AL") else "paint", fn=P.plate, kwargs=kw,
            spec=f"{W}x{H}x{T}", cost=_machined_cost(W * H * T, kw), tags=(pattern,))

    # ---------------------------------------------------------------- angle brackets
    brackets = [
        (60, 80, 40, 8, False, False), (80, 80, 60, 10, True, False), (50, 50, 30, 6, False, False),
        (100, 120, 80, 12, True, False), (70, 60, 50, 8, False, True), (90, 70, 60, 10, True, True),
        (40, 60, 30, 5, False, False), (130, 90, 80, 12, True, False), (60, 60, 40, 6, False, True),
        (80, 100, 50, 8, True, False), (45, 70, 35, 6, False, False), (110, 90, 70, 10, True, True),
    ]
    for (a, b, w, t, rib, chiral) in brackets:
        ha = [(a * 0.62, w * 0.3), (a * 0.62, w * 0.7)] if not chiral else [(a * 0.62, w * 0.25), (a * 0.8, w * 0.72)]
        hb = [(w * 0.5, b * 0.7)] if not chiral else [(w * 0.3, b * 0.7), (w * 0.75, b * 0.5)]
        mat = "AL6061" if t <= 8 else "S235"
        side_he, side_en = ("", "")
        d = add(family="angle", he=f"תושבת זוויתית {a}x{b}x{w}{side_he}", en=f"ANGLE BRACKET {a}x{b}x{w}{side_en}",
                plm=f"BRACKET,ANGLE,{a}X{b}X{w}", make_buy="make", material=mat,
                finish="anod_nat" if mat == "AL6061" else "paint", fn=P.angle_bracket,
                kwargs={"a": a, "b": b, "w": w, "t": t, "holes_a": ha, "holes_b": hb, "hole_d": 6.6 if t < 10 else 9.0,
                        "rib": rib}, spec=f"{a}x{b}x{w}", cost=_machined_cost(a * w * t + b * w * t, {}), chiral=chiral)
        if chiral:  # left/right hand pair: names carry the side
            d.he += " ימני"
            d.en += " RH"
            d.plm += ",RH"
            d.tags = ("rh",)
    # ---------------------------------------------------------------- motor mounts
    for frame, base, height, w, t in [("17", 60, 55, 50, 6), ("23", 80, 75, 70, 8), ("23", 90, 80, 75, 10),
                                      ("34", 110, 105, 100, 12), ("17", 50, 50, 46, 5)]:
        add(family="motormount", he=f"תושבת מנוע NEMA{frame} {base}x{height}",
            en=f"MOTOR BRACKET NEMA{frame} {base}x{height}", plm=f"BRACKET,MOTOR,NEMA{frame},{base}X{height}",
            make_buy="make", material="AL6061" if frame != "34" else "S235",
            finish="anod_black" if frame != "34" else "paint", fn=P.motor_mount,
            kwargs={"frame": frame, "base": base, "height": height, "w": w, "t": t},
            spec=f"NEMA{frame}", cost=_machined_cost((base + height) * w * t, {}), tags=("nema",))
    # ---------------------------------------------------------------- bearing housings
    for code, H, W, L, bt in [("6204", 60, 30, 70, 12), ("6205", 66, 32, 76, 12), ("6206", 76, 36, 88, 14),
                              ("6004", 56, 28, 64, 10)]:
        add(family="housing", he=f"בית מסב ל-{code}", en=f"BEARING HOUSING {code}", plm=f"HOUSING,BEARING,{code}",
            make_buy="make", material="S235", finish="paint", fn=P.bearing_housing,
            kwargs={"code": code, "H": H, "W": W, "L": L, "base_t": bt}, spec=code, cost=_machined_cost(H * W * L, {}))
    # ---------------------------------------------------------------- shafts
    shafts = [
        ("הנעה", "DRIVE", [(20, 22), (25, 18), (30, 160), (25, 18), (20, 40)], (4, 30, 5), "42CRMO4"),
        ("הנעה", "DRIVE", [(25, 24), (30, 20), (35, 210), (30, 20), (25, 50)], (4, 40, 5), "42CRMO4"),
        ("גלגלת זנב", "TAIL PULLEY", [(20, 22), (25, 230), (20, 22)], None, "C45"),
        ("גלגלת זנב", "TAIL PULLEY", [(25, 24), (30, 280), (25, 24)], None, "C45"),
        ("מנוע", "MOTOR", [(14, 30), (17, 12), (20, 60)], (0, 20, 4), "C45"),
        ("ציר סרק", "IDLER", [(12, 15), (15, 90), (12, 15)], None, "C45"),
        ("ציר סרק", "IDLER", [(15, 18), (20, 120), (15, 18)], None, "C45"),
        ("מתיחה", "TENSIONER", [(16, 20), (20, 60), (16, 20)], None, "C45"),
        ("גל העברה", "TRANSMISSION", [(20, 30), (25, 25), (30, 300), (25, 25), (20, 30)], (0, 25, 3), "42CRMO4"),
        ("ציר זרוע", "ARM PIVOT", [(10, 12), (12, 50), (10, 12)], None, "SS304"),
        ("ציר זרוע", "ARM PIVOT", [(12, 14), (16, 70), (12, 14)], None, "SS304"),
        ("פין ציר", "PIVOT PIN", [(8, 40)], None, "C45"),
    ]
    for role_he, role_en, segs, key, mat in shafts:
        L = sum(s[1] for s in segs)
        dmax = max(s[0] for s in segs)
        add(family="shaft", he=f"ציר {role_he} Ø{dmax}x{L}", en=f"{role_en} SHAFT D{dmax}x{L}",
            plm=f"SHAFT,{role_en},D{dmax}X{L}", make_buy="make", material=mat, finish="black" if mat != "SS304" else "",
            fn=P.stepped_shaft, kwargs={"segments": segs, "key": key}, spec=f"D{dmax}x{L}",
            cost=_machined_cost(math.pi * (dmax / 2) ** 2 * L, {"steps": len(segs)}))
    # ---------------------------------------------------------------- bushings & spacers
    for d_, D_, L_, fl, mat in [(20, 26, 20, (32, 3), "BRONZE"), (25, 32, 25, (38, 4), "BRONZE"),
                                (16, 22, 16, None, "BRONZE"), (12, 18, 15, None, "POM"), (20, 28, 30, None, "POM"),
                                (30, 38, 30, (46, 5), "BRONZE"), (10, 14, 12, (18, 2), "POM"), (8, 12, 10, None, "PA6"),
                                (35, 45, 35, None, "BRONZE"), (14, 20, 20, None, "POM")]:
        nm = "תותב אוגן" if fl else "תותב"
        en = "FLANGED BUSHING" if fl else "PLAIN BUSHING"
        add(family="bushing", he=f"{nm} {d_}/{D_}x{L_} {MATERIALS[mat][0].split()[0]}",
            en=f"{en} {d_}/{D_}x{L_} {MATERIALS[mat][1].split()[0]}", plm=f"BUSHING,{'FLANGED' if fl else 'PLAIN'},{d_}X{D_}X{L_}",
            make_buy="make", material=mat, fn=P.bushing, kwargs={"d": d_, "D": D_, "L": L_, "flange": fl},
            spec=f"{d_}/{D_}x{L_}", cost=round(8 + D_ * L_ / 40, 1))
    for d_, D_, L_, mat in [(6.4, 12, 10, "AL6061"), (6.4, 12, 15, "AL6061"), (6.4, 12, 20, "AL6061"),
                            (8.4, 14, 20, "AL6061"), (8.4, 14, 25, "AL6061"), (10.5, 16, 30, "S235"),
                            (6.4, 10, 8, "SS304"), (13, 20, 40, "S235"), (8.4, 16, 12, "POM"), (10.5, 18, 50, "AL6061")]:
        add(family="spacer", he=f"מרווח {_f(d_)}/{D_}x{L_}", en=f"SPACER {_f(d_)}/{D_}x{L_}", plm=f"SPACER,{_f(d_)}X{D_}X{L_}",
            make_buy="make", material=mat, fn=P.bushing, kwargs={"d": d_, "D": D_, "L": L_, "flange": None, "c": 0.3},
            spec=f"{_f(d_)}/{D_}x{L_}", cost=round(3 + D_ * L_ / 60, 1))
    # ---------------------------------------------------------------- flanges
    for D_, t_, bore, pcd, n, hd, sp, mat in [(90, 12, 30, 70, 4, 9, (50, 4), "S235"), (120, 15, 40, 95, 6, 11, (70, 5), "S235"),
                                              (75, 10, 20, 58, 4, 6.6, None, "AL6061"), (140, 16, 50, 115, 6, 13.5, (80, 5), "C45"),
                                              (100, 12, 35, 80, 4, 9, None, "AL6061"), (60, 8, 16, 46, 3, 5.5, None, "AL6061")]:
        add(family="flange", he=f"אוגן Ø{D_} {n} חורים", en=f"FLANGE D{D_} {n}-HOLE", plm=f"FLANGE,D{D_},{n}H",
            make_buy="make", material=mat, finish="paint" if mat != "AL6061" else "anod_nat", fn=P.flange,
            kwargs={"D": D_, "t": t_, "bore": bore, "pcd": pcd, "n_holes": n, "hole_d": hd, "spigot": sp},
            spec=f"D{D_}", cost=_machined_cost(math.pi * (D_ / 2) ** 2 * t_, {}))
    # ---------------------------------------------------------------- pulleys & rollers
    for D_, w, bore, hub_d, hub_len, fh, crown, role_he, role_en in [
            (160, 220, 30, 60, 230, 0, True, "תוף הנעה", "DRIVE DRUM"), (140, 220, 25, 50, 230, 0, True, "תוף זנב", "TAIL DRUM"),
            (100, 40, 20, 40, 50, 3, False, "גלגלת", "PULLEY"), (80, 30, 17, 35, 40, 3, False, "גלגלת", "PULLEY"),
            (120, 50, 25, 45, 60, 4, False, "גלגלת", "PULLEY")]:
        add(family="pulley", he=f"{role_he} Ø{D_}x{w}", en=f"{role_en} D{D_}x{w}", plm=f"PULLEY,{role_en},D{D_}X{w}",
            make_buy="make", material="S235", finish="paint", fn=P.pulley,
            kwargs={"D": D_, "width": w, "bore": bore, "hub_d": hub_d, "hub_len": hub_len, "flange_h": fh, "crown": crown},
            spec=f"D{D_}x{w}", cost=_machined_cost(math.pi * (D_ / 2) ** 2 * w * 0.3, {}))
    for L_ in (350, 450, 550, 650):
        add(family="roller", he=f"גלגלת מסוע Ø50x{L_}", en=f"CONVEYOR ROLLER D50x{L_}", plm=f"ROLLER,CONVEYOR,D50X{L_}",
            make_buy="buy", material="ZINC_STEEL", fn=P.conveyor_roller,
            kwargs={"D": 50, "L": L_, "wall": 1.5, "axle_d": 15, "axle_len": 12}, spec=f"50x{L_}", cost=round(38 + L_ / 25, 1))
    # ---------------------------------------------------------------- gears
    for m, z, b, bore, hub in [(1.5, 20, 12, 10, (22, 10)), (2, 30, 20, 20, (40, 15)), (2, 45, 20, 25, (45, 15)),
                               (2.5, 24, 25, 25, (45, 20)), (2.5, 60, 25, 35, None), (1.5, 40, 12, 15, (30, 10))]:
        add(family="gear", he=f"גלגל שיניים m{_f(m)} z{z}", en=f"SPUR GEAR m{_f(m)} z{z}", plm=f"GEAR,SPUR,M{_f(m)},Z{z}",
            make_buy="make", material="C45", finish="black", fn=P.spur_gear,
            kwargs={"m": m, "z": z, "b": b, "bore": bore, "hub": hub}, spec=f"m{_f(m)} z{z}",
            cost=round(40 + m * z * b / 12, 1))
    # ---------------------------------------------------------------- clamp blocks, tubes
    for L_, W_, H_, st, n in [(80, 40, 30, 10, 2), (120, 50, 35, 12, 3), (60, 30, 25, 8, 2), (100, 40, 30, 10, 2),
                              (150, 60, 40, 15, 3)]:
        add(family="clamp", he=f"בלוק הידוק {L_}x{W_}x{H_}", en=f"CLAMP BLOCK {L_}x{W_}x{H_}", plm=f"BLOCK,CLAMP,{L_}X{W_}X{H_}",
            make_buy="make", material="C45", finish="black", fn=P.clamp_block,
            kwargs={"L": L_, "W": W_, "H": H_, "step": st, "holes": n}, spec=f"{L_}x{W_}x{H_}",
            cost=_machined_cost(L_ * W_ * H_, {}))
    for D_, w_, L_ in [(40, 2, 300), (30, 2, 250), (60, 3, 400)]:
        add(family="tube", he=f"צינור Ø{D_}x{w_} L={L_}", en=f"TUBE D{D_}x{w_} L={L_}", plm=f"TUBE,D{D_}X{w_},L{L_}",
            make_buy="make", material="SS304", fn=P.tube, kwargs={"D": D_, "wall": w_, "L": L_}, spec=f"D{D_}x{w_}x{L_}",
            cost=round(12 + L_ * D_ / 800, 1))
    # ---------------------------------------------------------------- sheet metal
    for a, b, w, t in [(60, 50, 40, 2), (80, 60, 50, 2), (100, 80, 60, 3), (50, 40, 30, 1.5), (120, 100, 80, 3),
                       (70, 70, 40, 2), (40, 60, 25, 1.5), (90, 50, 60, 2.5)]:
        hd = 5.5 if t < 2.5 else 6.6
        add(family="sheetL", he=f"זוויתן פח {a}x{b}x{w} עובי {_f(t)}", en=f"SHEET BRACKET L {a}x{b}x{w} T{_f(t)}",
            plm=f"BRACKET,SHEET,L,{a}X{b}X{w},T{_f(t)}", make_buy="make", material="GALV",
            fn=P.sheet_l_bracket, kwargs={"a": a, "b": b, "w": w, "t": t, "holes_a": [(a * 0.6, w * 0.5)],
                                          "holes_b": [(w * 0.5, b * 0.65)], "hole_d": hd},
            spec=f"{a}x{b}x{w}x{_f(t)}", cost=round(6 + (a + b) * w * t / 900, 1))
    for web, fh, L_, t in [(80, 30, 300, 1.5), (120, 40, 400, 2), (60, 25, 250, 1.5), (150, 50, 600, 2),
                           (100, 35, 350, 1.5), (200, 60, 800, 2)]:
        add(family="sheetU", he=f"מכסה פח U {web}x{fh}x{L_}", en=f"SHEET COVER U {web}x{fh}x{L_}",
            plm=f"COVER,SHEET,U,{web}X{fh}X{L_}", make_buy="make", material="GALV", finish="paint",
            fn=P.sheet_u_channel, kwargs={"web": web, "flange_h": fh, "L": L_, "t": t,
                                          "holes_web": [(web / 2, L_ * 0.15), (web / 2, L_ * 0.85)],
                                          "flange_holes": [(L_ / 2, fh * 0.6)], "hole_d": 5.5},
            spec=f"{web}x{fh}x{L_}", cost=round(10 + (web + 2 * fh) * L_ * t / 4000, 1))
    for a, h, c, w, t in [(30, 40, 30, 40, 2), (40, 60, 40, 50, 2), (25, 30, 25, 30, 1.5), (50, 80, 50, 60, 3)]:
        add(family="sheetZ", he=f"זוויתן Z {a}x{h}x{c}", en=f"Z BRACKET {a}x{h}x{c}", plm=f"BRACKET,Z,{a}X{h}X{c}",
            make_buy="make", material="GALV", fn=P.sheet_z_bracket, kwargs={"a": a, "h": h, "c": c, "w": w, "t": t},
            spec=f"{a}x{h}x{c}", cost=round(7 + (a + h + c) * w * t / 900, 1))
    return out


def _plate_kwargs(W, H, T, pattern, hd) -> dict:
    m = max(12.0, hd * 1.6)
    holes, slots, pockets, cbores = [], [], [], []
    if pattern.startswith("grid4"):
        holes = [(m, m, hd), (W - m, m, hd), (m, H - m, hd), (W - m, H - m, hd)]
        if pattern == "grid4slots":
            slots = [(W / 2, H * 0.3, 30, hd, 0), (W / 2, H * 0.7, 30, hd, 0)]
        if pattern == "grid4cs":
            holes = [(m, m, hd), (W - m, m, hd), (m, H - m, hd), (W - m, H - m, hd), (W / 2, m, hd), (W / 2, H - m, hd)]
    elif pattern == "grid6":
        holes = [(x, y, hd) for x in (m, W / 2, W - m) for y in (m, H - m)]
    elif pattern == "pocket":
        holes = [(m, m, hd), (W - m, m, hd), (m, H - m, hd), (W - m, H - m, hd)]
        pockets = [(W / 2, H / 2, W * 0.45, H * 0.4, T * 0.4)]
    elif pattern.startswith("row"):
        n = int(pattern[3:])
        holes = [(m + i * (W - 2 * m) / (n - 1), H / 2, hd) for i in range(n)]
    elif pattern == "slots":
        slots = [(W * 0.25, H / 2, 30, hd, 0), (W * 0.75, H / 2, 30, hd, 0)]
    elif pattern == "pcd":
        holes = [(W / 2 + 50 * math.cos(a), H / 2 + 50 * math.sin(a), hd) for a in
                 [i * math.pi / 2 + math.pi / 4 for i in range(4)]]
        holes.append((W / 2, H / 2, 40))
    elif pattern == "dowels":
        holes = [(m, m, hd), (W - m, m, hd), (m, H - m, hd), (W - m, H - m, hd), (W * 0.3, H / 2, 8), (W * 0.7, H / 2, 8)]
        cbores = [(W / 2, H * 0.3, hd, hd * 1.7, hd * 0.9), (W / 2, H * 0.7, hd, hd * 1.7, hd * 0.9)]
    return {"W": W, "H": H, "T": T, "holes": holes, "slots": slots, "pockets": pockets, "cbores": cbores,
            "corner_r": 5.0 if T <= 12 else 8.0, "chamfer": 0.5}


def _machined_cost(vol_mm3: float, kw: dict) -> float:
    """Synthetic manufacturing cost (ILS): base setup + material volume + features. Demo data only."""
    n_feat = len(kw.get("holes", [])) + 2 * len(kw.get("slots", [])) + 3 * len(kw.get("pockets", [])) + kw.get("steps", 0)
    return round(45 + vol_mm3 / 4000 + 4 * n_feat, 0)


def mass_kg(volume_mm3: float, material: str) -> float:
    return volume_mm3 * MATERIALS[material][2] / 1e6
