"""Standard-part specifications parsed from names (fasteners, pins, keys, ball bearings).

Two files of a standard part are the *same item* when their designation agrees (type, size,
length, and - when both state them - strength class / stainless grade / bearing seal type),
even if the CAD libraries that drew them differ in small details (edge rounding, socket depth).
Two standard parts of the same type with a different size are deliberately different items,
however similar their geometry looks. And identical geometry with a different grade or seal
type (8.8 vs 12.9, A2 vs 12.9, 2RS vs ZZ) is a different purchased item.

The DIN<->ISO pairs below are the usual replacements (DIN 912 -> ISO 4762, DIN 933 -> ISO 4017,
DIN 934 -> ISO 4032, DIN 125 -> ISO 7089, DIN 7991 -> ISO 10642, DIN 913 -> ISO 4026,
DIN 6325 / ISO 8734 dowel pins, DIN 7 -> ISO 2338). Nominal differences between a DIN and its
ISO successor (e.g. a few hex nut heights) are below what the item master distinguishes.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# standard number -> part type
STANDARDS = {
    "DIN 912": "shcs", "ISO 4762": "shcs", "DIN 933": "hex_screw", "ISO 4017": "hex_screw", "DIN 931": "hex_bolt",
    "ISO 4014": "hex_bolt", "DIN 934": "nut", "ISO 4032": "nut", "ISO 4033": "nut", "DIN 985": "lock_nut",
    "ISO 7040": "lock_nut", "DIN 125": "washer", "ISO 7089": "washer", "ISO 7090": "washer",
    "DIN 7991": "csk", "ISO 10642": "csk", "DIN 913": "set_screw", "ISO 4026": "set_screw", "DIN 916": "set_screw_cup",
    "ISO 4029": "set_screw_cup", "DIN 6325": "pin", "ISO 8734": "pin", "DIN 7": "pin_m6", "ISO 2338": "pin_m6",
    "DIN 6885": "key", "DIN 127": "spring_washer", "DIN 471": "circlip_ext", "DIN 472": "circlip_int",
    "ISO 7380": "button_head", "ISO 15": "bearing",
}
# words (already lower-cased, Hebrew without final forms) -> part type
_TYPE_WORDS = [
    (r"socket\s*head|cap\s*screw|shcs|\bאלנ\b|ראש\s*גלילי", "shcs"),
    (r"countersunk|\bcsk\b|flat\s*head\s*socket|שקוע", "csk"),
    (r"set\W*screw|screw\W+set|grub|אל[-\s]?ראש|תולעת", "set_screw"),
    (r"hex\s*head|hex\s*bolt|ראש\s*משושה", "hex_screw"),
    (r"lock\s*nut|nyloc|אומ\s*נעילה", "lock_nut"),
    (r"\bnut\b|\bאומ\b", "nut"),
    (r"spring\s*washer|דיסקית\s*קפיצ", "spring_washer"),
    (r"washer|דיסקית|דסקית", "washer"),
    (r"dowel|פינ\s*מכוונ|\bpin\b|\bפינ\b", "pin"),
    (r"parallel\s*key|\bkey\b|שגמ|פינ\s*טריז", "key"),
    (r"bearing|מסב|מיסב", "bearing"),
]
_TYPE_RES = [(re.compile(p), t) for p, t in _TYPE_WORDS]
_SCREW_TYPES = {"shcs", "csk", "set_screw", "set_screw_cup", "hex_screw", "hex_bolt", "button_head"}
_STD_RE = re.compile(r"\b(DIN|ISO|EN\s*ISO)\s*[-:]?\s*(\d{1,5})\b", re.I)
_METRIC = re.compile(r"(?<![a-z0-9])m\s?(\d{1,2}(?:[.,]\d)?)(?:\s*[x×*]\s*(\d{1,3}(?:[.,]\d)?))?(?![0-9])", re.I)
_DIMS = re.compile(r"(?<![0-9.])(\d{1,2}(?:[.,]\d)?)\s*[x×*]\s*(\d{1,3}(?:[.,]\d)?)(?:\s*[x×*]\s*(\d{1,3}))?(?![0-9])")
_BEARING = re.compile(r"(?<![0-9])((?:6|16|60|62|63|64|618|619)\d{2})(?:[\s-]*(2rs1?|2rsh|2rz|2z|zz|rs1?|z|rz|n|nr))?"
                      r"(?![0-9a-z])", re.I)
_GRADE = re.compile(r"(?<![0-9.])(4\.6|5\.6|8\.8|10\.9|12\.9)(?![0-9])|(?<![a-z0-9])(a[24])(?:[\s-]*(?:70|80))?(?![0-9a-z])",
                    re.I)
_STAINLESS = re.compile(r"stainless|inox|נירוסטה|\bss\b|aisi\s*3\d\d", re.I)
_SEAL_NORM = {"2rs": "2RS", "2rs1": "2RS", "2rsh": "2RS", "rs": "RS", "rs1": "RS", "2z": "ZZ", "zz": "ZZ", "z": "Z",
              "2rz": "2RZ", "rz": "RZ", "n": "N", "nr": "NR"}
_FINALS = str.maketrans({"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"})


@dataclass(frozen=True)
class StdSpec:
    kind: str                 # shcs | nut | washer | pin | key | bearing | ...
    size: str                 # M6 | 6204 | 6 (pin d) | 6x6 (key b x h)
    length: str = ""          # 20 | ''
    standard: str = ""        # 'ISO 4762' as written (first found)
    grade: str = ""           # 8.8 | 10.9 | 12.9 | A2 | A4 | ''
    seal: str = ""            # bearings: 2RS | ZZ | RS | Z | ''

    @property
    def label(self) -> str:
        s = self.size + (f"x{self.length}" if self.length else "")
        if self.kind == "bearing":
            s = self.size + (f"-{self.seal}" if self.seal else "")
        extra = " ".join(x for x in (self.standard, self.grade) if x)
        return f"{s} {extra}".strip()


def _num(x: str | None) -> str:
    if not x:
        return ""
    x = x.replace(",", ".")
    return x[:-2] if x.endswith(".0") else x


def _clean(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").translate(_FINALS)
    return t.lower().replace("_", " ")


def parse_spec(*texts: str) -> StdSpec | None:
    """Standard-part spec from one or more texts of the same record (name, description, material...).
    Returns None if the record does not look like a standard part."""
    raw = " | ".join(t for t in texts if t)
    if not raw.strip():
        return None
    t = _clean(raw)
    standard, std_kind = "", ""
    for m in _STD_RE.finditer(raw):
        key = f"{'ISO' if 'iso' in m.group(1).lower() else 'DIN'} {int(m.group(2))}"
        if key in STANDARDS:
            standard, std_kind = standard or key, std_kind or STANDARDS[key]
    kind = ""
    for rx, k in _TYPE_RES:
        if rx.search(t):
            kind = k
            break
    if std_kind and kind not in ("lock_nut", "spring_washer"):
        kind = std_kind  # the standard number is the most reliable type information
    if not kind:
        return None
    grade = ""
    g = _GRADE.search(t)
    if g:
        grade = g.group(1) or g.group(2).upper()
    elif _STAINLESS.search(t):
        grade = "A2"  # unspecified stainless fastener: A2 is the default grade
    if kind == "bearing":
        best = None
        for m in _BEARING.finditer(t):
            code = m.group(1)
            if len(code) == 4 or len(code) == 5:
                best = m
                break
        if not best:
            return None
        seal = _SEAL_NORM.get((best.group(2) or "").lower(), "")
        return StdSpec("bearing", best.group(1), "", standard, "", seal)
    if kind in _SCREW_TYPES or kind in ("nut", "lock_nut", "washer", "spring_washer"):
        m = _METRIC.search(t)
        if not m:
            return None
        size = f"M{_num(m.group(1))}"
        length = _num(m.group(2)) if kind in _SCREW_TYPES else ""
        if kind in _SCREW_TYPES and not length:
            return None
        return StdSpec(kind, size, length, standard, grade, "")
    if kind in ("pin", "pin_m6"):
        m = _DIMS.search(t)
        if not m:
            return None
        return StdSpec("pin", _num(m.group(1)), _num(m.group(2)), standard, grade, "")
    if kind == "key":
        m = _DIMS.search(t)
        if not m or not m.group(3):
            return None
        return StdSpec("key", f"{_num(m.group(1))}x{_num(m.group(2))}", _num(m.group(3)), standard, "", "")
    return None


def compare_specs(a: StdSpec | None, b: StdSpec | None) -> tuple[str, str]:
    """('same' | 'different_size' | 'spec_conflict' | 'different_type' | '', explanation)."""
    if a is None or b is None:
        return "", ""
    if a.kind != b.kind:
        return "different_type", f"{a.kind} / {b.kind}"
    if a.size != b.size or a.length != b.length:
        return "different_size", f"{a.label} / {b.label}"
    if a.grade and b.grade and _grade_family(a.grade) != _grade_family(b.grade):
        return "spec_conflict", f"{a.grade} / {b.grade}"
    if a.grade and b.grade and a.grade != b.grade:
        return "spec_conflict", f"{a.grade} / {b.grade}"
    if a.kind == "bearing" and a.seal and b.seal and a.seal != b.seal:
        return "spec_conflict", f"{a.seal} / {b.seal}"
    note = ""
    if a.kind == "bearing" and bool(a.seal) != bool(b.seal):
        note = "seal type stated on one side only"
    elif bool(a.grade) != bool(b.grade):
        note = "grade stated on one side only"
    return "same", note


def _grade_family(g: str) -> str:
    return "stainless" if g.upper().startswith("A") else "steel"
