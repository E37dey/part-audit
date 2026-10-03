"""Build the demo factory: an industrial group with four sites, four PDM/PLM systems, a legacy
network folder and one ERP. Output (default demo/factory/):

    factory.json        every CAD record per system + ERP data + ground truth (what is planted)
    files/<system>/...  STEP files served by the simulators (neutral files of the PDM records)
    archive/...         the legacy network folder (STEP + some native/other files)
    README.md           provenance and what is synthetic

All business data (part numbers, names, costs, stock, people) is synthetic. Geometry of the
standard parts follows the published standards (see parts.py); the NIST models are real CAD
models (NIST MBE PMI project, public domain) exported from different CAD systems.

    python tools/factory/build.py --out demo/factory --nist RAW/nist RAW/NIST-FTC-CTC-PMI-CAD-models
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import random
import shutil
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path[:0] = [str(HERE), str(ROOT), str(ROOT / "tools")]

import catalog as C  # noqa: E402
import cadops  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402

SEED = 20261003

SITES = {
    "center": {"he": "אתר מרכז", "en": "Center site", "system": "swpdm", "system_he": "SOLIDWORKS PDM",
               "cad": "SOLIDWORKS", "ext": ".SLDPRT", "asm_ext": ".SLDASM", "style": "A", "schema": "AP214CD",
               "step_rate": 0.93, "warehouse": "ראשי"},
    "north": {"he": "אתר צפון (חברה בת)", "en": "North site (subsidiary)", "system": "vault",
              "system_he": "Autodesk Vault", "cad": "Inventor", "ext": ".ipt", "asm_ext": ".iam", "style": "B",
              "schema": "AP214IS", "step_rate": 0.86, "warehouse": "צפון"},
    "hq": {"he": "מטה – הנדסת מוצר", "en": "HQ product engineering", "system": "windchill",
           "system_he": "PTC Windchill", "cad": "Creo", "ext": ".prt", "asm_ext": ".asm", "style": "C",
           "schema": "AP242DIS", "step_rate": 0.9, "warehouse": "ראשי"},
    "south": {"he": "אתר דרום", "en": "South site", "system": "teamcenter", "system_he": "Siemens Teamcenter",
              "cad": "NX", "ext": ".prt", "asm_ext": ".prt", "style": "D", "schema": "AP214CD", "step_rate": 0.82,
              "warehouse": "דרום"},
    "archive": {"he": "ארכיון קבצים ישן", "en": "Legacy archive (network folder)", "system": "folder",
                "system_he": "תיקיית רשת", "cad": "", "ext": ".stp", "asm_ext": "", "style": "A", "schema": "AP203",
                "step_rate": 1.0, "warehouse": ""},
}
PDM_SITES = ["center", "north", "hq", "south"]

AUTHORS = {
    "center": ["יוסי כ.", "מיכל ל.", "אבי מ.", "נועה פ.", "דני ב."],
    "north": ["רונית א.", "עומר ש.", "גיל ט."],
    "hq": ["שירה ג.", "איתי ר.", "ליאת ד.", "בועז ה."],
    "south": ["משה ז.", "הילה ו.", "סאמר ח."],
}
# lifecycle state names per system (normalized class -> system display value)
STATES = {
    "swpdm": {"released": "Released", "in_work": "In Work", "review": "Pending Approval", "obsolete": "Obsolete"},
    "vault": {"released": "Released", "in_work": "Work in Progress", "review": "For Review", "obsolete": "Obsolete"},
    "windchill": {"released": ("RELEASED", "Released"), "in_work": ("INWORK", "In Work"),
                  "review": ("UNDERREVIEW", "Under Review"), "obsolete": ("OBSOLETE", "Obsolete")},
    "teamcenter": {"released": "TCM Released", "in_work": "", "review": "Pending", "obsolete": "Obsolete"},
}
NORTH_CAT = {"plate": "PLT", "angle": "BRK", "motormount": "BRK", "housing": "HSG", "shaft": "SHF", "bushing": "BSH",
             "spacer": "SPC", "flange": "FLG", "pulley": "PUL", "gear": "GER", "clamp": "CLP", "tube": "TUB",
             "sheetL": "SHM", "sheetU": "SHM", "sheetZ": "SHM", "roller": "ROL"}
SUPPLIERS = {
    "fastener": "ספק ברגים א'", "bearing": "ספק מסבים ב'", "profile": "ספק פרופילים ג'", "component": "ספק רכיבים ד'",
    "machining": "עיבוד שבבי ה'", "sheet": "מסגריה ו'", "internal": "ייצור עצמי",
}
FASTENER_FAMS = {"shcs", "hexscrew", "nut", "washer", "csk", "setscrew", "pin", "key"}
SHEET_FAMS = {"sheetL", "sheetU", "sheetZ"}


# --------------------------------------------------------------------------- helpers


def volume_of(shape) -> float:
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, g)
    return g.Mass()


class PNs:
    """Per-site part-number factories (synthetic, site conventions)."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.used: set[str] = set()
        self.ctr = defaultdict(int)

    def _uniq(self, make):
        for _ in range(1000):
            pn = make()
            if pn not in self.used:
                self.used.add(pn)
                return pn
        raise RuntimeError("PN space exhausted")

    def center(self, kind: str, buy: bool) -> str:
        pre = "100" if kind == "assembly" else ("900" if buy else "200")
        return self._uniq(lambda: f"{pre}-{self.rng.randint(1001, 9899):04d}")

    def north(self, kind: str, family: str, buy: bool) -> str:
        cat = "ASM" if kind == "assembly" else ("STD" if buy else NORTH_CAT.get(family, "PRT"))
        return self._uniq(lambda: f"N-{cat}-{self.rng.randint(10, 999):04d}")

    def hq(self) -> str:
        return self._uniq(lambda: f"{self.rng.randint(10000, 99999):010d}")

    def south(self) -> str:
        return self._uniq(lambda: f"{self.rng.randint(1000, 99999):06d}")

    def old(self) -> str:
        return self._uniq(lambda: f"P-{self.rng.randint(100, 2999)}")

    def for_site(self, site: str, kind: str, family: str, buy: bool) -> str:
        if site == "center":
            return self.center(kind, buy)
        if site == "north":
            return self.north(kind, family, buy)
        if site == "hq":
            return self.hq()
        if site == "south":
            return self.south()
        return self.old()


def site_names(site: str, d: C.Design, rng: random.Random) -> tuple[str, str, str]:
    """(name, description, english name) as the site's engineers write them."""
    he, en, plm = d.he, d.en, d.plm
    if site == "center":
        name = he
        if d.family in FASTENER_FAMS and rng.random() < 0.3:
            name = he.replace("ראש גלילי ", "").replace("X", "x")
        desc = he + (f" {C.MATERIALS[d.material][0]}" if d.make_buy == "make" and rng.random() < 0.5 else "")
        return name, desc, en
    if site == "north":
        name = en if rng.random() < 0.8 else en.title()
        desc = he if rng.random() < 0.5 else en
        return name, desc, en
    if site == "hq":
        return plm, en, en
    if site == "south":
        if d.family in FASTENER_FAMS or d.family == "bearing":
            name = he.split(" DIN")[0].split(" h6")[0]
        else:
            name = en.capitalize() if rng.random() < 0.4 else he
        return name, he, en
    return he, he, en


def near_overrides(d: C.Design, rng: random.Random) -> tuple[dict, str] | None:
    """A small design change an engineer might make when re-drawing a similar part."""
    kw = d.kwargs
    f = d.family
    if f == "plate":
        if kw["holes"] and rng.random() < 0.6:
            holes = [list(h) for h in kw["holes"]]
            old = holes[0][2]
            new = {9: 8.5, 11: 10.5, 6.6: 7.0, 5.5: 6.0, 4.5: 5.0, 12: 13.0, 40: 42}.get(old, round(old + 0.5, 1))
            for h in holes:
                if h[2] == old:
                    h[2] = new
            return {"holes": [tuple(h) for h in holes]}, f"קוטר חורים {old:g}→{new:g} מ\"מ"
        return {"T": kw["T"] + 1}, f"עובי {kw['T']}→{kw['T'] + 1} מ\"מ"
    if f == "angle":
        if rng.random() < 0.5:
            return {"t": kw["t"] + 1}, f"עובי {kw['t']}→{kw['t'] + 1} מ\"מ"
        return {"hole_d": 9.0 if kw["hole_d"] < 9 else 11.0}, f"קוטר חורים {kw['hole_d']:g}→{9.0 if kw['hole_d'] < 9 else 11.0:g}"
    if f == "shaft":
        segs = [list(s) for s in kw["segments"]]
        i = max(range(len(segs)), key=lambda j: segs[j][1])
        dl = rng.choice([-5, -3, 2, 4, 6])
        segs[i][1] += dl
        return {"segments": [tuple(s) for s in segs]}, f"אורך מקטע {segs[i][1] - dl}→{segs[i][1]} מ\"מ"
    if f in ("bushing", "spacer"):
        dl = rng.choice([-1, 0.5, 1, 2])
        return {"L": kw["L"] + dl}, f"אורך {kw['L']:g}→{kw['L'] + dl:g} מ\"מ"
    if f == "flange":
        return {"hole_d": round(kw["hole_d"] + 0.5, 1)}, f"קוטר חורים {kw['hole_d']:g}→{kw['hole_d'] + 0.5:g}"
    if f == "motormount":
        return {"slot_len": 16.0}, "אורך חריצים 12→16 מ\"מ"
    if f == "housing":
        return {"base_t": kw["base_t"] + 2}, f"עובי בסיס {kw['base_t']}→{kw['base_t'] + 2} מ\"מ"
    if f == "pulley":
        return {"hub_len": kw["hub_len"] + 6}, f"אורך טבור {kw['hub_len']}→{kw['hub_len'] + 6} מ\"מ"
    if f == "gear":
        return {"b": kw["b"] + 2}, f"רוחב שן {kw['b']}→{kw['b'] + 2} מ\"מ"
    if f == "clamp":
        return {"step": kw["step"] + 2}, f"עומק מדרגה {kw['step']}→{kw['step'] + 2} מ\"מ"
    if f in SHEET_FAMS:
        if f == "sheetL":
            return {"b": kw["b"] + 3}, f"גובה כנף {kw['b']}→{kw['b'] + 3} מ\"מ"
        if f == "sheetU":
            return {"flange_h": kw["flange_h"] + 3}, f"גובה דופן {kw['flange_h']}→{kw['flange_h'] + 3} מ\"מ"
        return {"h": kw["h"] + 3}, f"גובה {kw['h']}→{kw['h'] + 3} מ\"מ"
    if f == "tube":
        return {"L": kw["L"] + 5}, f"אורך {kw['L']}→{kw['L'] + 5} מ\"מ"
    return None


def oldrev_overrides(d: C.Design, rng: random.Random) -> tuple[dict, str] | None:
    """An older revision: a clearly different geometry kept under the same part number."""
    kw = d.kwargs
    f = d.family
    if f == "plate":
        holes = [(x, y, dd) for (x, y, dd) in kw["holes"]][: max(2, len(kw["holes"]) - 2)]
        return {"holes": holes, "pockets": [], "T": kw["T"] + 2}, "גרסה ישנה: פחות חורים, עובי שונה"
    if f == "angle":
        return {"a": kw["a"] + 20, "rib": not kw["rib"]}, "גרסה ישנה: בסיס ארוך יותר"
    if f == "shaft":
        segs = [list(s) for s in kw["segments"]]
        segs[-1][1] += 25
        return {"segments": [tuple(s) for s in segs], "key": None}, "גרסה ישנה: ללא חריץ שגם, קצה ארוך"
    if f == "bracket" or f == "motormount":
        return {"height": kw["height"] + 15}, "גרסה ישנה: גבוהה יותר"
    if f == "flange":
        return {"n_holes": kw["n_holes"] + 2}, "גרסה ישנה: מספר חורים שונה"
    return None


def date_between(rng, y0, y1) -> dt.date:
    a = dt.date(y0, 1, 1).toordinal()
    b = dt.date(y1, 9, 30).toordinal()
    return dt.date.fromordinal(rng.randint(a, b))


# --------------------------------------------------------------------------- build


class Factory:
    def __init__(self, out: Path, nist_dirs: list[Path], seed: int = SEED):
        self.out = out
        self.rng = random.Random(seed)
        self.pns = PNs(random.Random(seed + 1))
        self.designs = {d.did: d for d in C.catalog()}
        self.records: list[dict] = []
        self.by_rid: dict[str, dict] = {}
        self.native_ids = defaultdict(lambda: 1000)
        self.nist_dirs = nist_dirs
        self.shape_cache: dict = {}
        self.truth: list[dict] = []   # planted scenarios
        self.step_paths: dict[str, str] = {}  # rid -> file path relative to out

    # ------------------------------------------------------------------ geometry
    def shape(self, did: str, style: str = "A", over: dict | None = None):
        key = (did, style, json.dumps(over or {}, sort_keys=True, default=str))
        if key not in self.shape_cache:
            self.shape_cache[key] = self.designs[did].build(style, **(over or {})).val().wrapped
        return self.shape_cache[key]

    def new_rid(self, site: str) -> tuple[str, int]:
        self.native_ids[site] += self.rng.randint(1, 7)
        nid = self.native_ids[site]
        return f"{SITES[site]['system']}:{site}:{nid}", nid

    # ------------------------------------------------------------------ records
    def add_record(self, site: str, d: C.Design | None, *, kind="part", pn=None, name=None, desc=None, name_en=None,
                   variant="base", gt=None, style=None, over=None, geom_note="", state=None, extra=None) -> dict:
        rng = self.rng
        rid, nid = self.new_rid(site)
        sys_ = SITES[site]["system"]
        buy = bool(d and d.make_buy == "buy")
        if pn is None:
            pn = self.pns.for_site(site, kind, d.family if d else "", buy)
        if name is None and d is not None:
            name, desc0, en0 = site_names(site, d, rng)
            desc = desc if desc is not None else desc0
            name_en = name_en if name_en is not None else en0
        if state is None:
            r = rng.random()
            state = "released" if r < 0.72 else ("in_work" if r < 0.86 else ("review" if r < 0.92 else "obsolete"))
            if buy and state == "in_work":
                state = "released"
        created = date_between(rng, 2009 if site != "north" else 2015, 2025)
        modified = min(created + dt.timedelta(days=rng.randint(0, 1600)), dt.date(2026, 9, 28))
        nver = rng.randint(1, 9)
        nrev = 0 if state == "in_work" and nver < 3 else min(rng.randint(0, 3), max(0, nver - 1))
        rev_letters = "ABCDEFG"
        revision = rev_letters[nrev] if not (state == "in_work" and nrev == 0 and rng.random() < 0.4) else "-"
        rec = {
            "rid": rid, "site": site, "system": sys_, "native_id": nid, "kind": kind,
            "did": d.did if d else None, "family": d.family if d else ("assembly" if kind == "assembly" else ""),
            "gt": gt or (d.did if d else rid), "variant": variant, "geom_note": geom_note,
            "pn": pn, "name": name or "", "description": desc or "", "name_en": name_en or "",
            "make_buy": (d.make_buy if d else "make"), "std": d.std if d else "", "spec": d.spec if d else "",
            "material": d.material if d else "", "finish": (d.finish if d else ""),
            "state_class": state, "revision": revision, "version": nver,
            "created": created.isoformat(), "modified": modified.isoformat(),
            "author": rng.choice(AUTHORS.get(site, ["—"])), "style": style or SITES[site]["style"],
            "over": over or {}, "bom": [], "plants": [],
        }
        if extra:
            rec.update(extra)
        self.records.append(rec)
        self.by_rid[rid] = rec
        return rec

    # ------------------------------------------------------------------ plan
    def plan(self) -> None:
        rng = self.rng
        designs = list(self.designs.values())
        buy = [d for d in designs if d.make_buy == "buy"]
        make = [d for d in designs if d.make_buy == "make"]
        core = {("shcs", "M4x10"), ("shcs", "M5x12"), ("shcs", "M6x16"), ("shcs", "M6x20"), ("shcs", "M8x20"),
                ("shcs", "M8x25"), ("nut", "M6"), ("nut", "M8"), ("washer", "M6"), ("washer", "M8"),
                ("pin", "6x20"), ("bearing", "6204-2RS"), ("bearing", "6205-2RS"), ("profile", "40x40x500")}
        # ---- purchased/standard parts: each site keeps its own library copy
        for d in buy:
            if (d.family, d.spec) in core:
                sites = list(PDM_SITES)
            elif "hn_spec" in d.tags:
                sites = rng.sample(PDM_SITES, 1)
            else:
                k = rng.choices([1, 2, 3, 4], weights=[35, 35, 20, 10])[0]
                sites = rng.sample(PDM_SITES, k)
            for s in sites:
                self.add_record(s, d, variant="library", style=SITES[s]["style"],
                                geom_note=f"ספריית {SITES[s]['cad'] or 'STEP'} (סגנון {SITES[s]['style']})")
        # hard negatives: the A2 / ZZ twin must share a site with its base item so both are in one system
        for d in buy:
            if "hn_spec" in d.tags:
                base = next(b for b in buy if b.family == d.family and b.kwargs == d.kwargs and "hn_spec" not in b.tags)
                twin_sites = [r["site"] for r in self.records if r["did"] == d.did]
                base_sites = [r["site"] for r in self.records if r["did"] == base.did]
                if not set(twin_sites) & set(base_sites):
                    self.add_record(base_sites[0], d, variant="library", style=SITES[base_sites[0]]["style"])
                self.truth.append({"type": "hard_negative", "what": f"{base.spec} vs {d.spec}", "dids": [base.did, d.did],
                                   "why": "same geometry, different specification (material / seal type)"})
        # ---- manufactured parts: one owner site, some copied to other sites
        weights = {"center": 40, "north": 22, "hq": 20, "south": 18}
        owner_of = {}
        for d in make:
            s = rng.choices(list(weights), weights=list(weights.values()))[0]
            owner_of[d.did] = s
            self.add_record(s, d, variant="base")
        # cross-site copies (same geometry, re-modelled / imported in another system)
        copy_designs = rng.sample(make, 30)
        for i, d in enumerate(copy_designs):
            src = owner_of[d.did]
            dst = rng.choice([s for s in PDM_SITES if s != src])
            kind = ["moved", "reexport", "moved", "split"][i % 4]
            note = {"moved": "יובא ומוקם מחדש (ראשית צירים שונה)", "reexport": "יוצא מחדש מאותו מודל",
                    "split": "שורטט מחדש במערכת אחרת (פאות מחולקות אחרת)"}[kind]
            self.add_record(dst, d, variant=kind, geom_note=note)
            self.truth.append({"type": "cross_site_copy", "did": d.did, "from": src, "to": dst, "how": kind})
        # within-site duplicates: someone did not search and created the same part again
        for d in rng.sample([x for x in make if x not in copy_designs], 12):
            s = owner_of[d.did]
            nm, ds, en = site_names(s, d, rng)
            if rng.random() < 0.5:
                ctx = rng.choice(["חדש", "מסוע", "לפרויקט", "NEW", "V2", "מתוקן"])
                nm = f"{nm} {ctx}" if rng.random() < 0.6 else " ".join(nm.split()[:2])
            self.add_record(s, d, variant="saveas", name=nm, desc=ds, name_en=en,
                            geom_note="נוצר שוב באותו אתר (מק\"ט חדש)")
            self.truth.append({"type": "same_site_duplicate", "did": d.did, "site": s})
        # near-identical variants: a similar part with a small design difference
        cands = [x for x in make if near_overrides(x, random.Random(1)) is not None]
        for d in rng.sample(cands, 22):
            ov, why = near_overrides(d, rng)
            s = owner_of[d.did] if rng.random() < 0.55 else rng.choice(PDM_SITES)
            gt = f"{d.did}~near"
            self.add_record(s, d, variant="near", over=ov, gt=gt, geom_note=why)
            self.truth.append({"type": "near", "did": d.did, "site": s, "change": why})
        # mirror (left-hand) versions of chiral brackets: legitimate distinct parts
        for d in make:
            if d.chiral:
                s = owner_of[d.did]
                name, desc, en = site_names(s, d, rng)
                lh = lambda t: t.replace("ימני", "שמאלי").replace(" RH", " LH").replace(",RH", ",LH")  # noqa: E731
                self.add_record(s, d, variant="mirror", gt=f"{d.did}~LH", name=lh(name), desc=lh(desc), name_en=lh(en),
                                geom_note="גרסת מראה (שמאלי)")
                self.truth.append({"type": "mirror", "did": d.did, "site": s})
        # ---- legacy archive (network folder)
        self.plan_archive(make, buy, owner_of)
        # ---- NIST real models
        self.plan_nist()
        # ---- assemblies and BOMs
        self.plan_assemblies()
        # ---- data quality plants and STEP availability
        self.plan_quality()

    def plan_archive(self, make, buy, owner_of) -> None:
        rng = self.rng
        center_make = [r for r in self.records if r["site"] == "center" and r["variant"] == "base"]
        north_make = [r for r in self.records if r["site"] == "north" and r["variant"] == "base"]
        oldrev_fams = {"plate", "angle", "shaft", "motormount", "flange"}
        pool_old = rng.sample([r for r in center_make if r["family"] in oldrev_fams], 4)
        rest = [r for r in center_make if r not in pool_old]
        pool = pool_old + rng.sample(rest, min(22, len(rest))) + rng.sample(north_make, min(8, len(north_make)))
        kinds = ["oldrev"] * 4
        others = (["copy"] * 9 + ["reexport"] * 6 + ["moved"] * 5 + ["unit_error"] * 5 + ["near"] * 5)
        rng.shuffle(others)
        kinds += others
        for src, kind in zip(pool, kinds):
            d = self.designs[src["did"]]
            stem_opts = [f"{src['pn']} {src['name']}", f"{src['pn']}", f"{src['name']} ישן", f"{d.en.lower().replace(' ', '_')}",
                         f"{src['name']} final", f"{src['pn']}_rev{src['revision']}"]
            stem = rng.choice(stem_opts)
            over, note, gt = None, "", src["gt"]
            if kind == "near":
                r = near_overrides(d, rng)
                if r is None:
                    kind = "reexport"
                else:
                    over, note = r
                    gt = f"{d.did}~arch_near"
            if kind == "oldrev":
                r = oldrev_overrides(d, rng)
                if r is None:
                    kind = "moved"
                else:
                    over, note = r
                    gt = f"{d.did}~oldrev"
                    stem = f"{src['pn']} {src['name']} rev A"
            rec = self.add_record("archive", d, pn="", name=stem, desc="", name_en="", variant=kind, gt=gt, over=over,
                                  geom_note=note or {"copy": "עותק של קובץ ה-STEP מה-PDM", "reexport": "יצוא ישן של אותו מודל",
                                                     "moved": "יצוא ישן, ראשית צירים שונה",
                                                     "unit_error": "יצוא ביחידות שגויות (אינץ' במקום מ\"מ)"}.get(kind, ""),
                                  state="released", extra={"src_rid": src["rid"], "folder": rng.choice(
                                      ["פרויקטים ישנים/2014", "פרויקטים ישנים/2016", "מחלקת הנדסה/ייצוא", "לקוחות/שונות",
                                       "גיבוי שרטוטים"])})
            if kind in ("copy", "reexport", "moved", "unit_error"):
                self.truth.append({"type": "archive_copy", "did": d.did, "of": src["rid"], "how": kind})
            elif kind == "oldrev":
                self.truth.append({"type": "conflict_oldrev", "did": d.did, "of": src["rid"], "pn": src["pn"]})
            else:
                self.truth.append({"type": "near", "did": d.did, "site": "archive", "change": note})
        # legacy-only designs (old parts that exist nowhere else): reuse make designs with distinct params
        for i in range(10):
            d = rng.choice(make)
            ov = near_overrides(d, rng)
            if ov is None:
                continue
            over = dict(ov[0])
            if d.family == "plate":
                over["W"] = d.kwargs["W"] + 37
            elif d.family in ("bushing", "spacer"):
                over["L"] = d.kwargs["L"] + 13
            elif d.family == "shaft":
                segs = [list(s) for s in d.kwargs["segments"]]
                segs[0][1] += 30
                over["segments"] = [tuple(s) for s in segs]
            else:
                continue
            self.add_record("archive", d, pn="", name=f"{d.he.split(' ')[0]} {self.pns.old()}", desc="", name_en="",
                            variant="legacy_only", gt=f"{d.did}~legacy{i}", over=over, state="released",
                            extra={"folder": "פרויקטים ישנים/2011"})
        # non-STEP files that a real share also holds (reported as skipped)
        self.archive_extras = [("גיבוי שרטוטים/תושבת ישנה.SLDPRT", "native"), ("גיבוי שרטוטים/מסגרת.dwg", "dwg"),
                               ("מחלקת הנדסה/ייצוא/רשימת חלקים.xlsx", "other"), ("לקוחות/שונות/מכסה.igs", "iges")]

    def plan_nist(self) -> None:
        """Real CAD models (NIST MBE PMI): the same test parts exported from different CAD systems."""
        nist_files = {}
        for base in self.nist_dirs:
            for p in base.rglob("*.stp"):
                nist_files.setdefault(p.name, p)
        picks = [
            ("hq", "nist_ctc_01_asme1_ap242-e1.stp", "ctc_01"), ("hq", "nist_ctc_02_asme1_ap242-e2.stp", "ctc_02"),
            ("hq", "nist_ctc_04_asme1_ap242-e1.stp", "ctc_04"), ("hq", "nist_ftc_06_asme1_ap242-e2.stp", "ftc_06"),
            ("south", "nist_ctc_01_asme1_rd.stp", "ctc_01"), ("south", "nist_ctc_02_asme1_rc.stp", "ctc_02"),
            ("south", "nist_ftc_06_asme1_rd.stp", "ftc_06"), ("archive", "nist_ctc_04_asme1_ap203.stp", "ctc_04"),
            ("center", "nist_ctc_03_asme1_rc.stp", "ctc_03"), ("north", "nist_ctc_03_asme1_ap203.stp", "ctc_03"),
        ]
        names = {"ctc_01": ("גוף בדיקה CTC-01", "TEST PART CTC-01"), "ctc_02": ("גוף בדיקה CTC-02", "TEST PART CTC-02"),
                 "ctc_03": ("גוף בדיקה CTC-03", "TEST PART CTC-03"), "ctc_04": ("גוף בדיקה CTC-04", "TEST PART CTC-04"),
                 "ftc_06": ("גוף בדיקה FTC-06", "TEST PART FTC-06")}
        self.nist_src = {}
        for site, fn, case in picks:
            src = nist_files.get(fn)
            if src is None:
                print(f"[nist] missing {fn}, skipped")
                continue
            he, en = names[case]
            pn = None if site != "archive" else ""
            rec = self.add_record(site, None, pn=pn, name=he if site in ("center", "south", "archive") else en,
                                  desc=f"{he} (מודל NIST MBE PMI, {fn})", name_en=en, variant="nist", gt=f"nist_{case}",
                                  state="released", extra={"family": "nist", "material": "AL6061", "make_buy": "make",
                                                           "nist_file": fn})
            if site == "archive":
                rec["name"] = fn[:-4]
            self.nist_src[rec["rid"]] = src
        self.truth.append({"type": "nist", "note": "same NIST test case exported from different CAD systems"})

    def plan_assemblies(self) -> None:
        rng = self.rng
        products = {
            "center": [("מסוע רצועה CV-2000", ["יחידת הנעה", "יחידת זנב", "מסגרת מסוע", "רגל מסוע", "מגן רצועה"]),
                       ("מסוע רצועה CV-1200", ["יחידת הנעה קטנה", "מסגרת מסוע קצרה", "רגל מסוע"]),
                       ("תחנת הרמה LT-300", ["בסיס תחנה", "מנגנון הרמה"])],
            "north": [("FIXTURE FX-12", ["BASE ASSY", "CLAMP ASSY"]), ("LIFT TABLE LT-500", ["GUIDE ASSY", "FRAME ASSY"])],
            "hq": [("PACKING MACHINE PK-500", ["FEEDER MODULE", "SEALING MODULE", "MACHINE FRAME"])],
            "south": [("תחנת הברגה SC-3", ["יחידת הזנה", "ראש הברגה"]), ("מודול שינוע TR-2", ["מסלול", "עגלה"])],
        }
        for site, prods in products.items():
            parts = [r for r in self.records if r["site"] == site and r["kind"] == "part" and r["variant"] != "mirror"]
            make = [r for r in parts if r["make_buy"] == "make"]
            buy = [r for r in parts if r["make_buy"] == "buy"]
            for top_name, subs in prods:
                top = self.add_record(site, None, kind="assembly", name=top_name, desc=top_name, name_en=top_name,
                                      variant="assembly", state="released",
                                      extra={"family": "assembly", "make_buy": "make", "material": ""})
                for sub_name in subs:
                    sub = self.add_record(site, None, kind="assembly", name=sub_name, desc=f"{sub_name} – {top_name}",
                                          name_en=sub_name, variant="assembly",
                                          state="released" if rng.random() < 0.8 else "in_work",
                                          extra={"family": "assembly", "make_buy": "make", "material": ""})
                    for r in rng.sample(make, min(len(make), rng.randint(3, 7))):
                        sub["bom"].append({"child": r["rid"], "qty": rng.choice([1, 1, 1, 2, 2, 4])})
                    for r in rng.sample(buy, min(len(buy), rng.randint(4, 9))):
                        q = rng.choice([2, 4, 4, 6, 8, 12]) if r["family"] in FASTENER_FAMS else rng.choice([1, 2, 2, 4])
                        sub["bom"].append({"child": r["rid"], "qty": q})
                    top["bom"].append({"child": sub["rid"], "qty": 4 if "רגל" in sub_name else 1})

    def plan_quality(self) -> None:
        """STEP availability, mass property, and planted data-quality issues."""
        rng = self.rng
        for r in self.records:
            if r["kind"] != "part":
                continue
            if r["site"] != "archive":
                r["has_step"] = rng.random() < SITES[r["site"]]["step_rate"] or r["variant"] in ("nist",)
            else:
                r["has_step"] = True
        pdm_parts = [r for r in self.records if r["kind"] == "part" and r["site"] != "archive" and r["variant"] != "nist"]
        # missing material / description
        for r in rng.sample(pdm_parts, 14):
            r["plants"].append("missing_material")
        for r in rng.sample(pdm_parts, 5):
            r["plants"].append("missing_description")
        # stale recorded mass (geometry changed, mass property not updated)
        for r in rng.sample([r for r in pdm_parts if r["make_buy"] == "make"], 12):
            r["plants"].append(rng.choice(["stale_mass_high", "stale_mass_low"]))
        # file name / data card part number mismatch (SOLIDWORKS PDM and Vault)
        for r in rng.sample([r for r in pdm_parts if r["site"] in ("center", "north")], 6):
            r["plants"].append("filename_pn_mismatch")
        # part number format violations
        for r in rng.sample([r for r in pdm_parts if r["site"] in ("center", "north")], 4):
            r["plants"].append("pn_format")
            r["pn_original"] = r["pn"]
            if r["site"] == "center":
                r["pn"] = r["pn"].replace("-", "") if rng.random() < 0.5 else r["pn"].replace("-", "_")
            else:
                r["pn"] = r["pn"].lower()
        # BOM state conflicts: released assembly using in-work / obsolete children
        rel_asm = [r for r in self.records if r["kind"] == "assembly" and r["state_class"] == "released" and r["bom"]]
        for a in rng.sample(rel_asm, 4):
            ch = self.by_rid[a["bom"][0]["child"]]
            if ch["kind"] == "part":
                ch["state_class"] = rng.choice(["in_work", "obsolete"])
                ch["plants"].append(f"bom_state_{ch['state_class']}")

    # ------------------------------------------------------------------ files
    def write_files(self) -> None:
        files_dir = self.out / "files"
        arch_dir = self.out / "archive"
        for d in (files_dir, arch_dir):
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True)
        rng = random.Random(SEED + 7)
        by_rid_path: dict[str, Path] = {}
        # PDM records first (archive copies need their source files)
        order = sorted(self.records, key=lambda r: (r["site"] == "archive", r["rid"]))
        n = 0
        for r in order:
            if r["kind"] != "part" or not r.get("has_step"):
                continue
            site = SITES[r["site"]]
            if r["site"] == "archive":
                safe_stem = "".join(ch for ch in r["name"].replace("/", "-") if ch not in '\\:*?"<>|').strip() \
                    or f"part_{r['native_id']}"
                rel = Path("archive") / r.get("folder", "") / f"{safe_stem}{rng.choice(['.stp', '.STEP', '.step'])}"
                k = 2
                while (self.out / rel).exists():
                    rel = rel.with_name(f"{safe_stem} ({k}){rel.suffix}")
                    k += 1
            else:
                rel = Path("files") / r["system"] / f"{r['site']}_{r['native_id']}.stp"
            path = self.out / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            product = r["pn"] or Path(rel).stem
            if r["variant"] == "nist":
                shutil.copyfile(self.nist_src[r["rid"]], path)
            elif r["variant"] == "copy":
                shutil.copyfile(by_rid_path[r["src_rid"]], path) if r["src_rid"] in by_rid_path else None
                if not path.exists():  # source had no STEP: fall back to a re-export
                    r["variant"] = "reexport"
            if not path.exists():
                d = self.designs[r["did"]]
                style = r["style"] if d.styled else "A"
                shp = self.shape(r["did"], style, r["over"])
                if r["variant"] == "mirror":
                    shp = cadops.mirror(shp, normal=(0, 1, 0))
                if r["variant"] in ("moved", "split") or (r["site"] in ("north", "south") and r["variant"] == "library"
                                                          and rng.random() < 0.5):
                    shp = cadops.transform(shp, cadops.random_rigid(rng))
                if r["variant"] == "split":
                    shp = split_closed_faces(shp)
                if r["variant"] == "unit_error":
                    shp = cadops.uniform_scale(shp, 1 / 25.4 if rng.random() < 0.6 else 25.4)
                schema = site["schema"] if r["site"] != "archive" else rng.choice(["AP203", "AP214CD"])
                cadops.write_step(shp, str(path), schema=schema, unit="MM", product=product)
            r["step_file"] = rel.as_posix()
            by_rid_path[r["rid"]] = path
            if r["variant"] != "nist" and r["did"]:
                shp_true = self.shape(r["did"], r["style"] if self.designs[r["did"]].styled else "A", r["over"])
                r["volume_mm3"] = round(volume_of(shp_true), 3)
            n += 1
            if n % 50 == 0:
                print(f"[files] {n} STEP files", flush=True)
        for rel, kind in self.archive_extras:
            p = arch_dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes({"native": b"\x00SLDPRT (placeholder - native SOLIDWORKS file)\x00",
                           "dwg": b"AC1032 placeholder", "other": b"PK placeholder",
                           "iges": b"placeholder IGES\n"}[kind])
        print(f"[files] {n} STEP files written", flush=True)

    # ------------------------------------------------------------------ properties per record
    def finalize_properties(self) -> None:
        rng = random.Random(SEED + 11)
        for r in self.records:
            sys_ = r["system"]
            r["state"] = "" if sys_ == "folder" else STATES[sys_][r["state_class"]]
            if r["kind"] == "part" and r.get("did"):
                vol = r.get("volume_mm3")
                if vol is None:
                    vol = volume_of(self.shape(r["did"], r["style"] if self.designs[r["did"]].styled else "A", r["over"]))
                    r["volume_mm3"] = round(vol, 3)
                mass = C.mass_kg(vol, r["material"])
                r["mass_true_kg"] = round(mass, 4)
                rec_mass = mass
                if "stale_mass_high" in r["plants"]:
                    rec_mass = mass * rng.uniform(1.25, 1.6)
                elif "stale_mass_low" in r["plants"]:
                    rec_mass = mass * rng.uniform(0.55, 0.8)
                r["mass_recorded_kg"] = round(rec_mass, 4 if rec_mass < 1 else 3)
            elif r.get("variant") == "nist":
                r["mass_recorded_kg"] = None
            mat_he, mat_en, _ = C.MATERIALS.get(r["material"], ("", "", 0)) if r["material"] else ("", "", 0)
            r["material_text"] = "" if "missing_material" in r["plants"] else (mat_he if r["site"] in ("center", "south")
                                                                               else mat_en)
            fin = C.FINISHES.get(r.get("finish", ""), ("", ""))
            r["finish_text"] = fin[0] if r["site"] in ("center", "south") else fin[1]
            if "missing_description" in r["plants"]:
                r["description"] = ""
            site = SITES[r["site"]]
            if r["site"] != "archive":
                ext = site["asm_ext"] if r["kind"] == "assembly" else site["ext"]
                if r["system"] == "swpdm":
                    stem = f"{r['pn']} - {r['name']}" if rng.random() < 0.75 else r["pn"]
                elif r["system"] == "vault":
                    stem = r["pn"]
                elif r["system"] == "windchill":
                    stem = r["pn"].lower()
                else:
                    stem = f"{r['pn']}_{r['revision']}" if r["revision"] != "-" else r["pn"]
                if "filename_pn_mismatch" in r["plants"]:
                    other = self.pns.for_site(r["site"], r["kind"], r["family"], r["make_buy"] == "buy")
                    stem = f"{other} - {r['name']}" if r["system"] == "swpdm" else other
                r["native_file"] = "".join(ch for ch in stem.replace("/", "-") if ch not in '\\:*?"<>|') + ext
            r["history"] = self.history(r, rng)

    @staticmethod
    def history(r, rng) -> list[dict]:
        out = []
        created = dt.date.fromisoformat(r["created"])
        modified = dt.date.fromisoformat(r["modified"])
        nver = r["version"]
        revs = "ABCDEFG"
        target = revs.index(r["revision"]) if r["revision"] in revs else -1
        for v in range(1, nver + 1):
            day = created + (modified - created) * (v - 1) / max(nver - 1, 1) if nver > 1 else created
            rev = revs[min(target, round((v - 1) / max(nver - 1, 1) * target))] if target >= 0 else "-"
            out.append({"version": v, "revision": rev, "date": day.isoformat(),
                        "comment": ["יצירה", "עדכון מידות", "תיקון שרטוט", "שינוי חומר", "שחרור לייצור", "ECO",
                                    "עדכון לפי הערות ייצור"][min(v - 1, 6)] if v > 1 else "יצירה"})
        return out

    # ------------------------------------------------------------------ ERP
    def build_erp(self) -> dict:
        rng = random.Random(SEED + 23)
        items: dict[str, dict] = {}
        warehouses = ["ראשי", "צפון", "דרום"]

        def supplier(r):
            f = r["family"]
            if r["make_buy"] == "make":
                return SUPPLIERS["sheet"] if f in SHEET_FAMS else SUPPLIERS["machining"]
            if f in FASTENER_FAMS:
                return SUPPLIERS["fastener"]
            if f == "bearing":
                return SUPPLIERS["bearing"]
            if f == "profile":
                return SUPPLIERS["profile"]
            return SUPPLIERS["component"]

        skip_missing = set(r["rid"] for r in rng.sample(
            [r for r in self.records if r["kind"] == "part" and r["make_buy"] == "make" and r["state_class"] == "released"
             and r["site"] != "archive" and r["variant"] not in ("nist",)], 8))
        for r in self.records:
            if r["site"] == "archive" or r["variant"] == "nist":
                continue
            in_erp = r["make_buy"] == "buy" or r["state_class"] in ("released", "obsolete")
            if r["kind"] == "assembly":
                in_erp = r["state_class"] == "released"
            if r["rid"] in skip_missing:
                r["plants"].append("missing_in_erp")
                in_erp = False
            if not in_erp:
                continue
            d = self.designs.get(r["did"]) if r["did"] else None
            pn = r["pn"]
            if "pn_format" in r["plants"]:
                pn = r.get("pn_original", pn)
            he_desc = (d.he if d else r["name"]) if (r["site"] in ("center", "south") or rng.random() < 0.5) else r["name"]
            cost = (d.cost if d else 0.0) * rng.uniform(0.9, 1.15)
            if r["kind"] == "assembly":
                cost = 0.0
            fam = r["family"]
            if r["make_buy"] == "buy":
                stock = int(math.exp(rng.uniform(math.log(40), math.log(3000)))) if fam in FASTENER_FAMS else \
                    rng.randint(2, 80)
            else:
                stock = rng.choice([0, 0, 1, 2, 3, 5, 8, 12, 20, 35])
            status = "פעיל"
            if r["state_class"] == "obsolete":
                status = "לא פעיל" if rng.random() < 0.75 else "פעיל"
                if status == "פעיל":
                    r["plants"].append("obsolete_but_active_in_erp")
            item = {"pn": pn, "rid": r["rid"], "description": he_desc, "description_en": r.get("name_en") or "",
                    "type": "P" if r["make_buy"] == "make" else "R", "family": fam or "", "unit": "יח'",
                    "status": status, "unit_cost": round(cost, 2), "currency": "ILS",
                    "supplier": supplier(r) if r["kind"] == "part" else SUPPLIERS["internal"],
                    "lead_time_days": rng.choice([3, 5, 7, 10, 14, 21, 30]) if r["kind"] == "part" else 0,
                    "stock": {SITES[r["site"]]["warehouse"]: stock}, "created": r["created"],
                    "site": r["site"]}
            if r["make_buy"] == "make" and d is not None and rng.random() < 0.45:
                item["description"] = f"{item['description']} {C.MATERIALS[r['material']][0]}"
            items[pn] = item
        # planted description and material mismatches between PDM and ERP
        cand = [i for i in items.values() if self.by_rid[i["rid"]]["kind"] == "part"
                and self.by_rid[i["rid"]]["make_buy"] == "make"]
        for i in rng.sample(cand, 9):
            r = self.by_rid[i["rid"]]
            swaps = [("פלטת", "לוחית"), ("תושבת", "מחזיק"), ("ציר", "גל"), ("מרווח", "ספייסר"), ("תותב", "שרוול"),
                     ("גלגלת", "פולי"), ("אוגן", "פלנג'"), ("מכסה", "כיסוי"), ("בית מסב", "תושבת מסב")]
            for a, b in swaps:
                if a in i["description"]:
                    i["description"] = i["description"].replace(a, b, 1)
                    break
            else:
                i["description"] = i["description"] + " (ישן)"
            r["plants"].append("erp_description_differs")
        for i in rng.sample([i for i in cand if C.MATERIALS[self.by_rid[i["rid"]]["material"]][0].split()[0]
                             in ("אלומיניום", "פלדה")], 5):
            r = self.by_rid[i["rid"]]
            mat_he = C.MATERIALS[r["material"]][0]
            other = "פלדה S235JR" if mat_he.startswith("אלומיניום") else "אלומיניום 6061-T6"
            base = i["description"].replace(mat_he, "").strip()
            i["description"] = f"{base} {other}"
            r["plants"].append("erp_material_differs")
        # ERP items with no CAD at all (consumables, obsolete spare parts)
        extras = [("גריז ליתיום 400 גרם", "R", 38.0), ("דבק הברגות בינוני 50 מ\"ל", "R", 52.0),
                  ("שרוול כיווץ 6 מ\"מ (מטר)", "R", 2.4), ("שמן מכונות 1 ליטר", "R", 41.0),
                  ("מדבקת אזהרה 50x50", "R", 1.8), ("פלטה ישנה 220x140 (ללא שרטוט)", "P", 160.0),
                  ("ציר הנעה ישן Ø25 (ללא שרטוט)", "P", 240.0), ("תושבת חיישן ישנה", "P", 85.0),
                  ("רצועת מסוע PVC 400 מ\"מ (מטר)", "R", 210.0), ("כבל חשמל 3x1.5 (מטר)", "R", 6.5)]
        for k, (desc, typ, cost) in enumerate(extras):
            pn = f"{'900' if typ == 'R' else '200'}-{9900 + k}"
            items[pn] = {"pn": pn, "rid": None, "description": desc, "description_en": "", "type": typ,
                         "family": "", "unit": "יח'" if "מטר" not in desc else "מטר",
                         "status": "פעיל" if k < 6 else "לא פעיל", "unit_cost": cost, "currency": "ILS",
                         "supplier": SUPPLIERS["component"] if typ == "R" else SUPPLIERS["machining"],
                         "lead_time_days": 7, "stock": {"ראשי": rng.randint(0, 40)}, "created": "2012-05-01",
                         "site": "center"}
        # BOMs of released assemblies (ERP copy of the engineering BOM), with a few differences
        boms = []
        diffs = 0
        for r in self.records:
            if r["kind"] != "assembly" or r["pn"] not in items:
                continue
            for line in r["bom"]:
                ch = self.by_rid[line["child"]]
                q = line["qty"]
                if diffs < 4 and ch["family"] in FASTENER_FAMS and rng.random() < 0.3:
                    q = q + 2
                    diffs += 1
                    r["plants"].append("erp_bom_qty_differs")
                boms.append({"parent": r["pn"], "child": ch["pn"], "qty": q})
        return {"company": "קבוצת הדגמה (נתונים סינתטיים)", "warehouses": warehouses,
                "items": sorted(items.values(), key=lambda i: i["pn"]), "bom": boms}

    # ------------------------------------------------------------------ output
    def write(self) -> None:
        erp = self.build_erp()
        out = {
            "about": {
                "name": "מפעל הדגמה – קבוצת תעשייה עם 4 אתרים (נתונים סינתטיים)",
                "built": dt.date.today().isoformat(), "seed": SEED,
                "note": "All business data is synthetic. Standard-part geometry follows ISO/DIN dimensions; "
                        "NIST models are real public-domain CAD models.",
            },
            "sites": SITES,
            "records": [{k: v for k, v in r.items() if k not in ("over",)} | {"over": _jsonable(r["over"])}
                        for r in self.records],
            "erp": erp,
            "truth": self.truth,
        }
        (self.out / "factory.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), "utf-8")
        counts = defaultdict(int)
        for r in self.records:
            counts[(r["site"], r["kind"])] += 1
        print(json.dumps({f"{k[0]}/{k[1]}": v for k, v in sorted(counts.items())}, ensure_ascii=False))
        print(f"ERP items: {len(erp['items'])}, BOM lines: {len(erp['bom'])}, truth entries: {len(self.truth)}")


def _jsonable(x):
    return json.loads(json.dumps(x, default=str))


def split_closed_faces(shape):
    """Split periodic (closed) faces in two, as some CAD systems export cylinders as two half-faces."""
    from OCP.ShapeUpgrade import ShapeUpgrade_ShapeDivideClosed
    try:
        sd = ShapeUpgrade_ShapeDivideClosed(shape)
        sd.SetNbSplitPoints(1)
        sd.Perform()
        return sd.Result()
    except Exception:
        return shape


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "demo" / "factory"))
    ap.add_argument("--nist", nargs="*", default=[])
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    f = Factory(out, [Path(p) for p in a.nist], seed=a.seed)
    f.plan()
    f.write_files()
    f.finalize_properties()
    f.write()


if __name__ == "__main__":
    main()
