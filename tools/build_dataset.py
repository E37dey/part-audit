"""Build a labeled synthetic test set from ABC Dataset STEP files.

    python tools/build_dataset.py --abc RAW/abc0 --n-base 250 --seed 11 --out data/dev

Steps
1. screen random ABC files: single solid, closed, BRepCheck-valid, readable;
2. remove natural duplicates/near-duplicates among them (relaxed tolerance);
3. give every base part a synthetic identity (PN, English/Hebrew description,
   material, supplier) and write it into a messy folder tree;
4. plant variants (~25-30% of all files): A identical copy, B re-export,
   C rotated/translated, D units (inch file or /25.4 unit error), E tiny change
   (push-pull 0.1-2%, small hole, fillet/chamfer), F name variants;
5. add hard negatives: near-identical names on different parts, identical
   geometry with a different ERP material, a clearly different thickness,
   mirror images of chiral parts;
6. write the mock ERP CSV, ground_truth.csv, hard_negative_pairs.csv and a
   manifest with every random choice.

Everything is deterministic for a given --seed and input folder. Synthetic data:
accuracy measured on it is an upper bound for real factory data.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import shutil
import string
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

from part_audit.geometry import TimeoutPool  # noqa: E402
from part_audit.hashes import normalized_step_hash  # noqa: E402
from part_audit.names import ABBREVIATIONS  # noqa: E402
from part_audit.scoring import UNIT_FACTORS, Thresholds, compare_geometry  # noqa: E402
from part_audit.stepfile import bytes_to_text  # noqa: E402

# --------------------------------------------------------------------------- vocabulary

NOUNS = [  # (english, hebrew, latin transliteration as a person might type it)
    ("BRACKET", "תושבת", "tushevet"), ("PLATE", "פלטה", "plata"), ("COVER", "מכסה", "mikse"),
    ("HOUSING", "בית", "bait"), ("SPACER", "מרווח", "mirvach"), ("BUSHING", "תותב", "totav"),
    ("SHAFT", "גל", "gal"), ("PIN", "פין", "pin"), ("FLANGE", "אוגן", "ogen"), ("HOLDER", "מחזיק", "machzik"),
    ("CLAMP", "מהדק", "mahadek"), ("SUPPORT", "תומך", "tomech"), ("ARM", "זרוע", "zroa"), ("LEVER", "מנוף", "manof"),
    ("GUIDE", "מוביל", "movil"), ("RAIL", "מסילה", "mesila"), ("BASE", "בסיס", "basis"), ("FRAME", "מסגרת", "misgeret"),
    ("BLOCK", "בלוק", "blok"), ("ADAPTER", "מתאם", "mataem"), ("COUPLING", "מצמד", "matsmed"), ("HINGE", "ציר", "tsir"),
    ("HANDLE", "ידית", "yadit"), ("KNOB", "כפתור", "kaftor"), ("RING", "טבעת", "taba'at"), ("WASHER", "דסקית", "diskit"),
    ("CAP", "כובע", "kova"), ("STOP", "עוצר", "otser"), ("RIB", "צלע", "tsela"), ("WHEEL", "גלגל", "galgal"),
    ("PULLEY", "גלגלת", "galgelet"), ("PROFILE", "פרופיל", "profil"), ("BEAM", "קורה", "kora"), ("POST", "עמוד", "amud"),
    ("LEG", "רגל", "regel"), ("TRAY", "מגש", "magash"), ("ENCLOSURE", "מארז", "maraz"), ("PANEL", "לוח", "luach"),
    ("SLEEVE", "שרוול", "sharvul"), ("STIFFENER", "חיזוק", "chizuk"), ("CHANNEL", "תעלה", "teala"),
    ("FIXTURE", "מקבע", "mekabea"), ("DAMPER", "בולם", "bolem"), ("NOZZLE", "פיה", "piya"),
]
MODS = [  # (english, hebrew, transliteration)
    ("MOUNT", "הרכבה", "harkava"), ("MOTOR", "מנוע", "manoa"), ("UPPER", "עליון", "elyon"),
    ("LOWER", "תחתון", "tachton"), ("FRONT", "קדמי", "kidmi"), ("REAR", "אחורי", "achori"), ("SIDE", "צדדי", "tsdadi"),
    ("INNER", "פנימי", "pnimi"), ("OUTER", "חיצוני", "chitsoni"), ("SMALL", "קטן", "katan"), ("LARGE", "גדול", "gadol"),
    ("LONG", "ארוך", "aroch"), ("SHORT", "קצר", "katsar"), ("ROUND", "עגול", "agol"), ("SQUARE", "מרובע", "meruba"),
    ("FLAT", "שטוח", "shatuach"), ("BENT", "כפוף", "kafuf"), ("SENSOR", "חיישן", "chayshan"), ("FAN", "מאוורר", "meavrer"),
    ("CABLE", "כבל", "kevel"), ("DOOR", "דלת", "delet"), ("VALVE", "שסתום", "shastom"), ("CYLINDER", "צילינדר", "tsilinder"),
    ("GUARD", "מגן", "magen"),
]
MATERIALS = [("AL 6061", "Aluminium 6061", "אלומיניום 6061"), ("AL 7075", "Aluminium 7075", "אלומיניום 7075"),
             ("SS 304", "Stainless 304", "נירוסטה 304"), ("SS 316", "Stainless 316", "נירוסטה 316"),
             ("ST37", "Steel ST37", "פלדה ST37"), ("ST52", "Steel ST52", "פלדה ST52"), ("POM", "Delrin", "דלרין"),
             ("PA6", "Nylon PA6", "ניילון"), ("BRASS", "Brass", "פליז"), ("PEEK", "PEEK", "PEEK")]
SUPPLIERS = ["Galil Metal Works", "Negev CNC", "Tefen Plastics", "In-house", "Acme Machining Ltd",
             "מתכת הגליל", "Haifa Precision", "Sharon Sheet Metal"]
UNITS = ["EA"] * 8 + ["PCS", "יח'"]
NOISE_SUFFIX = ["_final", "_old", " (1)", "_rev{r}", "_v{n}", " - Copy", "_FINAL2", "_backup", "_ישן", "_סופי", "_new"]
FOLDERS_BASE = ["PRJ-2201_Conveyor/parts", "PRJ-2307_Packaging_Line/parts", "PRJ-2410_Robot_Cell/mech",
                "Library/standard", "PRJ-2201_Conveyor/assy", "PRJ-2307_Packaging_Line/purchased"]
FOLDERS_DUP = ["PRJ-2201_Conveyor/_old", "PRJ-2201_Conveyor/_final", "PRJ-2307_Packaging_Line/_old",
               "PRJ-2410_Robot_Cell/mech/_old", "PRJ-2410_Robot_Cell/copy", "Archive/2019", "Archive/2021",
               "Archive/old versions", "Users/dana/Desktop", "Users/yossi/Desktop/backup", "שונות", "גרסאות ישנות",
               "Library/standard", "PRJ-2307_Packaging_Line/parts", "PRJ-2410_Robot_Cell/mech"]
ABBREV_OF: dict[str, list[str]] = {}
for _ab, _full in ABBREVIATIONS.items():
    ABBREV_OF.setdefault(_full.upper(), []).append(_ab.upper())
ABBREV_OF["MOUNT"] = ["MTG", "MNT"]


# --------------------------------------------------------------------------- helpers


def pn_number(pn: str) -> int:
    return int("".join(ch for ch in pn if ch.isdigit()) or 0)


class PNFactory:
    def __init__(self, rng: random.Random):
        self.rng = rng
        self.used: set[str] = set()

    def new(self, scheme: str | None = None) -> str:
        while True:
            scheme_ = scheme or self.rng.choices(["PA", "legacy", "MP"], [0.6, 0.25, 0.15])[0]
            if scheme_ == "PA":
                pn = f"PA-{self.rng.randint(10000, 19999)}"
            elif scheme_ == "MP":
                pn = f"MP-{self.rng.randint(2000, 4999):05d}"
            else:
                pn = f"{self.rng.choice([100, 200, 300])}-{self.rng.randint(1000, 9999)}"
            if pn not in self.used:
                self.used.add(pn)
                return pn

    def next_after(self, pn: str) -> str | None:
        head, num = pn.rsplit("-", 1)
        for k in range(1, 6):
            cand = f"{head}-{int(num) + k:0{len(num)}d}"
            if cand not in self.used:
                self.used.add(cand)
                return cand
        return None


def bump_last_number(text: str) -> str:
    import re
    m = list(re.finditer(r"\d+", text))
    if not m:
        return text + "-2"
    last = m[-1]
    return text[:last.start()] + str(int(last.group()) + 5) + text[last.end():]


def typo(word: str, rng: random.Random) -> str:
    if len(word) < 5:
        return word
    i = rng.randrange(1, len(word) - 2)
    op = rng.choice(["swap", "drop", "double", "replace"])
    if op == "swap":
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]
    if op == "drop":
        return word[:i] + word[i + 1:]
    if op == "double":
        return word[:i] + word[i] + word[i:]
    return word[:i] + rng.choice("AEIOU") + word[i + 1:]


def pn_format_variant(pn: str, rng: random.Random) -> str:
    head, num = pn.rsplit("-", 1)
    return rng.choice([f"{head}{num}", f"{head}_{num}", f"{head}-0{num}", f"{head.lower()}-{num}",
                       f"{head} {num}", f"{head.lower()}{num}", f"{head}.{num}"])


def noise(name: str, rng: random.Random, p: float) -> str:
    if rng.random() > p:
        return name
    suf = rng.choice(NOISE_SUFFIX).format(r=rng.choice("BCD"), n=rng.randint(2, 4))
    return ("Copy of " + name) if rng.random() < 0.1 else name + suf


def safe(name: str) -> str:
    bad = '<>:"/\\|?*'
    return "".join("_" if c in bad else c for c in name).strip()


# --------------------------------------------------------------------------- identity & names


def make_identity(rng: random.Random, pnf: PNFactory) -> dict:
    noun = rng.randrange(len(NOUNS))
    mods = rng.sample(range(len(MODS)), rng.choice([0, 1, 1, 2]))
    dims = ""
    r = rng.random()
    if r < 0.2:
        dims = f"{rng.choice([20, 25, 30, 40, 50, 60, 80, 100, 120])}X{rng.choice([10, 15, 20, 25, 30, 40])}"
    elif r < 0.3:
        dims = f"D{rng.choice([6, 8, 10, 12, 16, 20, 25])}"
    elif r < 0.38:
        dims = f"T{rng.choice([2, 3, 4, 5, 6, 8, 10])}"
    mat = rng.randrange(len(MATERIALS))
    return {"pn": pnf.new(), "noun": noun, "mods": mods, "dims": dims, "material": mat,
            "material_style": rng.randrange(3), "supplier": rng.choice(SUPPLIERS), "unit": rng.choice(UNITS),
            "erp_lang": "he" if rng.random() < 0.25 else "en", "suffix": ""}


def desc_en(idt: dict, mods_first: bool = False) -> str:
    words = [NOUNS[idt["noun"]][0]] + [MODS[m][0] for m in idt["mods"]]
    if mods_first:
        words = words[1:] + words[:1]
    out = " ".join(words)
    if idt["dims"]:
        out += " " + idt["dims"]
    if idt.get("suffix"):
        out += " " + idt["suffix"]
    return out


def desc_he(idt: dict) -> str:
    words = [NOUNS[idt["noun"]][1]] + [MODS[m][1] for m in idt["mods"]]
    out = " ".join(words)
    if idt["dims"]:
        out += " " + idt["dims"].lower()
    if idt.get("suffix"):
        out += " " + {"RH": "ימני", "LH": "שמאלי"}.get(idt["suffix"], idt["suffix"])
    return out


def base_filename(idt: dict, rng: random.Random) -> str:
    pn, en = idt["pn"], desc_en(idt)
    style = rng.choices(["s1", "s2", "s3", "s4", "s5"], [0.35, 0.25, 0.15, 0.15, 0.10])[0]
    if style == "s1":
        return f"{pn}_{en.replace(' ', '-')}"
    if style == "s2":
        return f"{pn} {en.lower()}"
    if style == "s3":
        return pn
    if style == "s4":
        return f"{desc_he(idt)} {pn}"
    return f"{pn}_{desc_he(idt)}"


def name_variant(idt: dict, rng: random.Random, pnf: PNFactory) -> tuple[str, str, str, str]:
    """F: a name variant of the same item. Returns (file stem, pn used or '', applied ops, description text)."""
    ops = rng.sample(["hebrew", "translit", "abbrev", "pn_format", "word_order", "typo"], rng.choice([1, 2, 2, 3]))
    words = [NOUNS[idt["noun"]][0]] + [MODS[m][0] for m in idt["mods"]]
    lang = "en"
    if "hebrew" in ops:
        words = [NOUNS[idt["noun"]][1]] + [MODS[m][1] for m in idt["mods"]]
        lang = "he"
    elif "translit" in ops:
        words = [NOUNS[idt["noun"]][2]] + [MODS[m][2] for m in idt["mods"]]
    if "abbrev" in ops and lang == "en":
        words = [rng.choice(ABBREV_OF.get(w.upper(), [w])) if w.upper() in ABBREV_OF else w for w in words]
    if "word_order" in ops and len(words) > 1:
        words = words[1:] + words[:1]
    if "typo" in ops and lang == "en":
        k = max(range(len(words)), key=lambda i: len(words[i]))
        words[k] = typo(words[k], rng)
    text = " ".join(words)
    if idt["dims"]:
        text += " " + (idt["dims"].lower() if rng.random() < 0.5 else idt["dims"])
    r = rng.random()
    if r < 0.5:
        pn = pn_format_variant(idt["pn"], rng) if "pn_format" in ops or rng.random() < 0.5 else idt["pn"]
        pn_used = idt["pn"]
    elif r < 0.7:
        pn, pn_used = "", ""
    else:
        pn = pn_used = pnf.new()
    sep = rng.choice([" ", "_", "-"])
    stem = f"{pn}{sep}{text}" if pn and rng.random() < 0.7 else (f"{text} {pn}" if pn else text)
    if sep != " ":
        stem = stem.replace(" ", sep)
    return noise(stem, rng, 0.3), pn_used, "+".join(ops), text


# --------------------------------------------------------------------------- main build


def screen_files(files: list[str], workers: int, timeout: float) -> dict[str, dict]:
    out: dict[str, dict] = {}

    def cb(tid, status, payload, secs):
        if status == "ok":
            out[tid] = payload

    TimeoutPool("dataset_tasks:screen", workers, timeout).run([(f, f) for f in files], cb)
    return out


def remove_natural_duplicates(cands: list[str], fps: dict[str, dict]) -> tuple[list[str], int]:
    """Drop candidates whose geometry is within 15% (or a unit-factor scale) of an earlier one."""
    th = Thresholds(geo_near=0.15, near_max_face_ratio=1e9, near_max_type_dist=1e9)
    kept: list[str] = []
    logs: list[tuple[float, str]] = []
    dropped = 0
    norm_seen: set[str] = set()
    for f in cands:
        fp = fps[f]
        h = normalized_step_hash(bytes_to_text(Path(f).read_bytes()))
        if h in norm_seen:
            dropped += 1
            continue
        la = math.log(fp["area"])
        dup = False
        for lb, g in logs:
            d = abs(la - lb)
            scale_hit = any(abs(d - 2 * math.log(u)) < 0.02 for u in UNIT_FACTORS)
            if d > math.log(1.2) and not scale_hit:
                continue
            for scale in ([1.0] + [u for u in UNIT_FACTORS] + [1 / u for u in UNIT_FACTORS]):
                rel = compare_geometry(fp, fps[g], th, scale).relation
                if rel in ("identical", "unit_scaled", "near"):
                    dup = True
                    break
            if dup:
                break
        if dup:
            dropped += 1
            continue
        kept.append(f)
        logs.append((la, f))
        norm_seen.add(h)
    return kept, dropped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--abc", nargs="+", required=True, help="folders with extracted ABC STEP files")
    ap.add_argument("--n-base", type=int, default=250)
    ap.add_argument("--screen-factor", type=float, default=3.0)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--timeout", type=float, default=60)
    ap.add_argument("--rates", default="A=0.06,B=0.06,C=0.06,D=0.06,E=0.07,F=0.07",
                    help="planted variants per base part, by type")
    ap.add_argument("--hn", default="name=0.05,material=0.03,thickness=0.03,mirror=0.02",
                    help="hard negatives per base part, by kind")
    ap.add_argument("--mirror-candidates", type=int, default=8,
                    help="candidate bases checked per wanted mirror hard negative (most parts are symmetric)")
    a = ap.parse_args()
    t_start = time.time()
    rng = random.Random(a.seed)
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    cad_root = out / "cad"
    staging = out / "_staging"
    staging.mkdir(parents=True)
    manifest: dict = {"seed": a.seed, "abc_folders": a.abc, "args": vars(a)}

    # 1. screen
    pool = sorted(str(p) for d in a.abc for p in Path(d).rglob("*.step"))
    rng.shuffle(pool)
    n_screen = int(a.n_base * a.screen_factor)
    to_screen = pool[:n_screen]
    print(f"[screen] {len(to_screen)} of {len(pool)} ABC files", flush=True)
    t0 = time.time()
    fps = screen_files(to_screen, a.workers, a.timeout)
    good = [f for f in to_screen if f in fps and fps[f].get("ok") and fps[f]["n_solids"] == 1 and fps[f]["closed"]
            and fps[f]["valid"] and fps[f]["volume"] > 0 and fps[f]["n_faces"] >= 4]
    print(f"[screen] {len(fps)} read, {len(good)} single-body valid ({time.time() - t0:.0f}s)", flush=True)
    clean, n_nat = remove_natural_duplicates(good, fps)
    print(f"[dedup] removed {n_nat} natural duplicates/near-duplicates, {len(clean)} left", flush=True)
    manifest["screen"] = {"screened": len(to_screen), "readable": len(fps), "single_body_valid": len(good),
                          "natural_duplicates_removed": n_nat, "clean": len(clean)}
    if len(clean) < a.n_base:
        raise SystemExit(f"not enough clean parts ({len(clean)} < {a.n_base}); raise --screen-factor")
    bases = clean[:a.n_base]
    reserve = clean[a.n_base:]

    # 2. identities
    pnf = PNFactory(rng)
    idents = [make_identity(rng, pnf) for _ in bases]
    rates = {k: float(v) for k, v in (kv.split("=") for kv in a.rates.split(","))}
    hn_rates = {k: float(v) for k, v in (kv.split("=") for kv in a.hn.split(","))}

    # HN_name: pairs of different base parts with (near-)identical names
    hn_pairs: list[tuple[int, int, str]] = []
    idx = list(range(len(bases)))
    rng.shuffle(idx)
    n_hn_name = round(hn_rates.get("name", 0) * len(bases))
    for k in range(n_hn_name):
        i, j = idx[2 * k], idx[2 * k + 1]
        idents[j]["noun"], idents[j]["mods"] = idents[i]["noun"], list(idents[i]["mods"])
        if rng.random() < 0.5 and idents[i]["dims"]:
            idents[j]["dims"] = idents[i]["dims"]
            note = "same description"
        elif idents[i]["dims"]:
            idents[j]["dims"] = bump_last_number(idents[i]["dims"])
            note = "same description, different dimension"
        else:
            idents[j]["dims"] = ""
            note = "same description"
        nxt = pnf.next_after(idents[i]["pn"])
        if nxt and rng.random() < 0.6:
            pnf.used.discard(idents[j]["pn"])
            idents[j]["pn"] = nxt
            note += ", sequential part number"
        hn_pairs.append((i, j, note))

    # base files: copy ABC file + synthetic STEP product name
    files: list[dict] = []          # every output file
    import cadops  # noqa: E402 (heavy import only after screening)
    for i, (src, idt) in enumerate(zip(bases, idents)):
        stg = staging / f"base_{i:04d}.step"
        shutil.copyfile(src, stg)
        prod = idt["pn"] if rng.random() < 0.5 else f"{idt['pn']} {desc_en(idt)}"
        cadops.set_product_name(str(stg), idt["pn"], prod)
        files.append({"vid": f"base_{i:04d}", "stg": str(stg), "type": "base", "base": i, "group": f"G{i:04d}",
                      "pn": idt["pn"], "erp_pn": idt["pn"], "detail": "ABC part", "source": Path(src).name})

    # 3. plan planted variants
    specs: list[dict] = []
    per_base_count = [0] * len(bases)
    used_for_hn = {j for _, j, _ in hn_pairs}

    def pick_base(exclude=()) -> int:
        for _ in range(1000):
            b = rng.randrange(len(bases))
            if per_base_count[b] < 3 and b not in exclude:
                return b
        raise RuntimeError("no base available")

    vid = 0
    for t, rate in rates.items():
        for _ in range(round(rate * len(bases))):
            b = pick_base()
            per_base_count[b] += 1
            sp = {"vid": f"{t}_{vid:04d}", "type": t, "base": b, "seed": rng.randrange(10**9),
                  "schema": rng.choice(cadops.SCHEMAS)}
            vid += 1
            if t == "A":
                sp["kind"] = "copy"
            elif t == "B":
                sp["kind"] = "reexport"
            elif t == "C":
                sp["kind"] = "rigid"
            elif t == "D":
                sp["kind"] = "inch" if rng.random() < 0.5 else "unit_error"
            elif t == "E":
                sp["kind"] = "edit"
                ops = ["pushpull", "hole", "fillet", "chamfer"]
                rng.shuffle(ops)
                sp["ops"] = ops
            elif t == "F":
                sp["kind"] = "copy" if rng.random() < 0.5 else "reexport"
            specs.append(sp)
    for kind in ("material", "thickness", "mirror"):
        for _ in range(round(hn_rates.get(kind, 0) * len(bases)) * (a.mirror_candidates if kind == "mirror" else 1)):
            b = pick_base(exclude=used_for_hn)
            sp = {"vid": f"HN_{kind}_{vid:04d}", "type": f"HN_{kind}", "base": b, "seed": rng.randrange(10**9),
                  "schema": rng.choice(cadops.SCHEMAS),
                  "kind": {"material": rng.choice(["copy", "reexport"]), "thickness": "thickness",
                           "mirror": "mirror"}[kind]}
            vid += 1
            specs.append(sp)

    # mirror hard negatives need chiral bases (exact boolean test, independent of the audit's L3b)
    mirror_specs = [s for s in specs if s["type"] == "HN_mirror"]
    if mirror_specs:
        chir: dict[int, dict] = {}

        def ccb(tid, status, payload, secs):
            chir[int(tid)] = payload if status == "ok" else {"chiral": None, "reason": status}

        TimeoutPool("dataset_tasks:chirality", a.workers, max(a.timeout, 180)).run(
            [(str(s["base"]), files[s["base"]]["stg"]) for s in mirror_specs], ccb)
        keep, want = [], round(hn_rates.get("mirror", 0) * len(bases))
        for s in mirror_specs:
            if chir.get(s["base"], {}).get("chiral") and len(keep) < want and s["base"] not in [k["base"] for k in keep]:
                s["chirality"] = chir[s["base"]]
                keep.append(s)
        specs = [s for s in specs if s["type"] != "HN_mirror"] + keep
        manifest["chirality_checks"] = {str(k): v for k, v in chir.items()}

    # 4. generate variant files in worker processes
    for s in specs:
        s["src"] = files[s["base"]]["stg"]
        s["dst"] = str(staging / f"{s['vid']}.step")
    results: dict[str, dict] = {}

    def vcb(tid, status, payload, secs):
        results[tid] = payload if status == "ok" else {"ok": False, "detail": f"{status}: {payload}"}

    t0 = time.time()
    TimeoutPool("dataset_tasks:make_variant", a.workers, a.timeout).run([(s["vid"], s) for s in specs], vcb)
    # retry failed E / HN_thickness on other bases
    for attempt in range(4):
        failed = [s for s in specs if not results.get(s["vid"], {}).get("ok") and s["type"] in ("E", "HN_thickness")]
        if not failed:
            break
        for s in failed:
            s["base"] = pick_base(exclude=used_for_hn)
            s["src"] = files[s["base"]]["stg"]
            s["seed"] = rng.randrange(10**9)
        TimeoutPool("dataset_tasks:make_variant", a.workers, a.timeout).run([(s["vid"], s) for s in failed], vcb)
    print(f"[variants] {sum(1 for s in specs if results.get(s['vid'], {}).get('ok'))}/{len(specs)} generated "
          f"({time.time() - t0:.0f}s)", flush=True)

    # 5. names, folders, ERP
    erp: dict[str, dict] = {}

    def erp_row(pn, idt, desc=None, material=None, lang=None):
        lang = lang or idt["erp_lang"]
        d = desc if desc is not None else (desc_he(idt) if lang == "he" else desc_en(idt))
        m = MATERIALS[material if material is not None else idt["material"]][idt["material_style"]]
        erp[pn] = {"part_number": pn, "description": d, "unit": idt["unit"], "material": m, "supplier": idt["supplier"]}

    for i, idt in enumerate(idents):
        erp_row(idt["pn"], idt)
    placed: set[str] = set()

    def place(folder: str, stem: str) -> str:
        stem = safe(stem)[:120]
        ext = rng.choice([".step", ".step", ".stp", ".STEP", ".STP"])
        rel = f"{folder}/{stem}{ext}"
        k = 2
        while rel.lower() in placed:
            rel = f"{folder}/{stem} ({k}){ext}"
            k += 1
        placed.add(rel.lower())
        return rel

    for f in files:  # bases
        idt = idents[f["base"]]
        f["file_id"] = place(rng.choice(FOLDERS_BASE), noise(base_filename(idt, rng), rng, 0.1))
    for s in specs:
        r = results.get(s["vid"], {})
        if not r.get("ok"):
            continue
        b = s["base"]
        idt = idents[b]
        t = s["type"]
        rec = {"vid": s["vid"], "stg": s["dst"], "type": t, "base": b, "detail": r["detail"],
               "source": files[b]["source"], "kind": s["kind"]}
        new_pn = None
        if t in ("A", "B", "C", "D"):
            p_new = {"A": 0.6, "B": 0.3, "C": 0.3, "D": 0.5}[t]
            if rng.random() < p_new:
                new_pn = pnf.new()
            pn = new_pn or idt["pn"]
            tag = {"A": "", "B": rng.choice(["_reexport", "_AP242", "_from customer", ""]),
                   "C": rng.choice(["_pos", "_in_assy", "_moved", ""]),
                   "D": rng.choice(["_inch", "_INCH", "_imperial", "_US supplier"])}[t]
            stem = (f"{pn}_{desc_en(idt).replace(' ', '-')}" if rng.random() < 0.6 else f"{pn} {desc_en(idt).lower()}") + tag
            rec.update(group=f"G{b:04d}", pn=pn)
            folder = "from_supplier" if t == "D" and rng.random() < 0.5 else rng.choice(FOLDERS_DUP)
            rec["file_id"] = place(folder, noise(stem, rng, 0.5))
            if new_pn and rng.random() < 0.75:
                lang = rng.choice(["en", "en", "he"])
                erp_row(new_pn, idt, lang=lang)
            if t == "B" or t == "C" or t == "D":
                cadops.set_product_name(rec["stg"], pn, pn)
        elif t == "E":
            if rng.random() < 0.65:
                new_pn = pnf.next_after(idt["pn"]) or pnf.new()
                stem = f"{new_pn} {desc_en(idt)} {rng.choice(['MOD', 'MODIFIED', 'NEW', 'V2', ''])}".strip()
                rec["pn"] = new_pn
                if rng.random() < 0.8:
                    erp_row(new_pn, idt, desc=f"{desc_en(idt)} MOD")
            else:
                stem = f"{idt['pn']}_{desc_en(idt).replace(' ', '-')}_rev{rng.choice('BCD')}"
                rec["pn"] = idt["pn"]
            rec["group"] = f"G{b:04d}"
            rec["file_id"] = place(rng.choice(FOLDERS_DUP + FOLDERS_BASE), stem)
            cadops.set_product_name(rec["stg"], rec["pn"], rec["pn"])
        elif t == "F":
            stem, pn_used, ops, text = name_variant(idt, rng, pnf)
            rec.update(group=f"G{b:04d}", pn=pn_used, detail=f"{r['detail']}; name variant: {ops}")
            rec["file_id"] = place(rng.choice(FOLDERS_DUP), stem)
            cadops.set_product_name(rec["stg"], pn_used or stem, stem)
            if pn_used and pn_used != idt["pn"] and rng.random() < 0.75:
                erp_row(pn_used, idt, desc=text)
        elif t.startswith("HN_"):
            new_pn = pnf.next_after(idt["pn"]) if rng.random() < 0.5 else None
            new_pn = new_pn or pnf.new()
            rec.update(group=f"H{s['vid'][-4:]}", pn=new_pn)
            if t == "HN_material":
                other = (idt["material"] + rng.randrange(1, len(MATERIALS))) % len(MATERIALS)
                stem = f"{new_pn}_{desc_en(idt).replace(' ', '-')}-{MATERIALS[other][0].replace(' ', '')}"
                erp_row(new_pn, idt, desc=f"{desc_en(idt)} {MATERIALS[other][0]}", material=other)
                rec["detail"] += f"; ERP material {MATERIALS[other][0]} vs {MATERIALS[idt['material']][0]}"
            elif t == "HN_thickness":
                stem = f"{new_pn}_{desc_en(idt).replace(' ', '-')}-THICK"
                erp_row(new_pn, idt, desc=f"{desc_en(idt)} THICK")
            else:  # mirror: base becomes the right-hand version
                idt["suffix"] = "RH"
                erp_row(idt["pn"], idt)
                lh = dict(idt, suffix="LH")
                stem = f"{new_pn}_{desc_en(lh).replace(' ', '-')}"
                erp_row(new_pn, lh)
            rec["file_id"] = place(rng.choice(FOLDERS_BASE + FOLDERS_DUP), stem)
            cadops.set_product_name(rec["stg"], new_pn, stem)
        files.append(rec)

    # ERP-only items (no CAD) and a few CAD items missing from the ERP
    for _ in range(round(0.06 * len(bases))):
        idt = make_identity(rng, pnf)
        erp_row(idt["pn"], idt)
    drop = [f["pn"] for f in files if f["type"] == "base"]
    rng.shuffle(drop)
    for pn in drop[:round(0.04 * len(bases))]:
        erp.pop(pn, None)

    # 6. move files into the tree, write ERP, ground truth, manifest
    for f in files:
        dst = cad_root / f["file_id"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(f["stg"], dst)
        if f["type"] == "base":
            f["group"] = f"G{f['base']:04d}"
    shutil.rmtree(staging)
    base_file = {f["base"]: f["file_id"] for f in files if f["type"] == "base"}
    rows = list(erp.values())
    rng.shuffle(rows)
    with open(out / "erp_export.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["part_number", "description", "unit", "material", "supplier"])
        w.writeheader()
        w.writerows(rows)
    with open(out / "ground_truth.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["file_id", "group_id", "type", "base_file_id", "pn", "variant", "abc_source"])
        for f in sorted(files, key=lambda x: x["file_id"]):
            w.writerow([f["file_id"], f["group"], f["type"], "" if f["type"] == "base" else base_file[f["base"]],
                        f.get("pn", ""), f.get("detail", ""), f.get("source", "")])
    with open(out / "hard_negative_pairs.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["file_a", "file_b", "kind", "note"])
        for i, j, note in hn_pairs:
            w.writerow([base_file[i], base_file[j], "HN_name", note])
        for f in files:
            if f["type"].startswith("HN_"):
                w.writerow([base_file[f["base"]], f["file_id"], f["type"], f["detail"]])
    counts: dict[str, int] = {}
    for f in files:
        counts[f["type"]] = counts.get(f["type"], 0) + 1
    planted = sum(v for k, v in counts.items() if k in "ABCDEF")
    manifest.update({"counts": counts, "files": len(files), "planted_A_to_F": planted,
                     "planted_share": round(planted / len(files), 4), "hn_name_pairs": len(hn_pairs),
                     "erp_rows": len(rows), "failed_variants": [s["vid"] for s in specs if not results.get(s["vid"], {}).get("ok")],
                     "build_seconds": round(time.time() - t_start, 1)})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("counts", "files", "planted_share", "hn_name_pairs", "erp_rows")},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
