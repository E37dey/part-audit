"""Low-level, text-only helpers for ISO 10303-21 (STEP) files.

Nothing here needs OpenCascade: it works on the raw text so that hashing and
name extraction stay fast and run even when geometry cannot be read.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# A string literal ('' is an escaped quote) or a /* comment */.
_STR_OR_COMMENT = re.compile(r"'(?:[^']|'')*'|/\*.*?\*/", re.S)
_STR = re.compile(r"'(?:[^']|'')*'")
_WS = re.compile(r"\s+")
_FLOAT = re.compile(r"(?<![#\w.])[-+]?\d+\.\d*(?:[eE][-+]?\d+)?")
_DEF = re.compile(r"#(\d+)=")
_REF = re.compile(r"#(\d+)")
_COLOUR = re.compile(r"COLOUR_RGB\('',[^)]*\)")

# ISO 8859-x code pages selectable with \P?\ (A=1 ... I=9). H = ISO 8859-8 (Hebrew).
_CODEPAGES = {c: f"iso8859_{i}" for i, c in enumerate("ABCDEFGHI", start=1)}


def strip_comments(text: str) -> str:
    """Remove /* */ comments but keep string literals intact."""
    return _STR_OR_COMMENT.sub(lambda m: m.group(0) if m.group(0).startswith("'") else " ", text)


def decode_step_string(raw: str) -> str:
    """Decode the content of a STEP string literal (without surrounding quotes).

    Handles '' escapes, \\\\, \\S\\c, \\P?\\ code pages, \\X\\HH, \\X2\\...\\X0\\ and
    \\X4\\...\\X0\\. Unknown or malformed escapes are kept verbatim.
    """
    s = raw.replace("''", "'")
    if "\\" not in s:
        return s
    out: list[str] = []
    codepage = "latin-1"
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        if s.startswith("\\\\", i):
            out.append("\\")
            i += 2
        elif s.startswith("\\X2\\", i) or s.startswith("\\X4\\", i):
            width = 4 if s[i + 2] == "2" else 8
            end = s.find("\\X0\\", i + 4)
            if end < 0:
                out.append(s[i:])
                break
            hexpart = s[i + 4:end]
            try:
                out.append("".join(chr(int(hexpart[k:k + width], 16)) for k in range(0, len(hexpart), width)))
            except ValueError:
                out.append(s[i:end + 4])
            i = end + 4
        elif s.startswith("\\X\\", i) and i + 5 <= n:
            try:
                out.append(bytes([int(s[i + 3:i + 5], 16)]).decode(codepage, errors="replace"))
            except ValueError:
                out.append(s[i:i + 5])
            i += 5
        elif s.startswith("\\S\\", i) and i + 4 <= n:
            out.append(bytes([(ord(s[i + 3]) + 128) & 0xFF]).decode(codepage, errors="replace"))
            i += 4
        elif s.startswith("\\P", i) and i + 4 <= n and s[i + 3] == "\\":
            codepage = _CODEPAGES.get(s[i + 2], codepage)
            i += 4
        elif s.startswith("\\N\\", i):
            out.append("\n")
            i += 3
        else:
            out.append(c)
            i += 1
    return "".join(out)


def encode_step_string(text: str) -> str:
    """Encode text as STEP string content (inverse of decode_step_string)."""
    out: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            out.append("\\X2\\" + "".join(f"{ord(ch):04X}" for ch in buf) + "\\X0\\")
            buf.clear()

    for ch in text:
        if 32 <= ord(ch) < 127:
            flush()
            out.append({"'": "''", "\\": "\\\\"}.get(ch, ch))
        elif ord(ch) <= 0xFFFF:
            buf.append(ch)
        else:  # outside the BMP
            flush()
            out.append(f"\\X4\\{ord(ch):08X}\\X0\\")
    flush()
    return "".join(out)


def bytes_to_text(data: bytes) -> str:
    """Decode file bytes. STEP should be 7-bit ASCII; tolerate UTF-8 and latin-1."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _args(call_text: str) -> list[str]:
    """Top-level string literals of a call like FILE_NAME('a','b',(''),...)."""
    return [decode_step_string(m.group(0)[1:-1]) for m in _STR.finditer(call_text)]


@dataclass
class StepInfo:
    is_step: bool = False
    schema: str = ""
    header_file_name: str = ""
    timestamp: str = ""
    originating_system: str = ""
    preprocessor: str = ""
    products: list[tuple[str, str, str]] = field(default_factory=list)  # (id, name, description)
    length_unit: str = ""          # 'mm', 'inch', 'm', ... as declared in the file
    n_entities: int = 0
    parse_warning: str = ""


_UNIT_PREFIX = {"$": "", ".MILLI.": "m", ".CENTI.": "c", ".DECI.": "d", ".MICRO.": "u", ".KILO.": "k", ".NANO.": "n"}
_CONVERSION_NAMES = {
    "INCH": "inch", "IN": "inch", "FOOT": "ft", "FT": "ft", "MILLIMETRE": "mm", "MILLIMETER": "mm",
    "METRE": "m", "METER": "m", "CENTIMETRE": "cm", "CENTIMETER": "cm", "MIL": "mil", "YARD": "yd",
}


def _instance_text(data: str, ref: int) -> str:
    m = re.search(rf"#{ref}\s*=\s*(.*?);", data, re.S)
    return m.group(1) if m else ""


def _decode_length_unit(inst: str) -> str:
    up = inst.upper()
    if "LENGTH_UNIT" not in up:
        return ""
    m = re.search(r"CONVERSION_BASED_UNIT\s*\(\s*'([^']*)'", inst, re.I)
    if m:
        name = m.group(1).strip().upper()
        return _CONVERSION_NAMES.get(name, name.lower())
    m = re.search(r"SI_UNIT\s*\(\s*(\$|\.\w+\.)\s*,\s*\.METRE\.\s*\)", up)
    if m:
        return _UNIT_PREFIX.get(m.group(1), "?") + "m"
    return ""


def parse_step_text(text: str) -> StepInfo:
    """Extract header fields, PRODUCT names and the declared length unit."""
    info = StepInfo()
    head = text[:200]
    if "ISO-10303-21" not in head.upper():
        return info
    info.is_step = True
    clean = strip_comments(text)
    hs = clean.find("HEADER;")
    he = clean.find("ENDSEC;", hs + 1) if hs >= 0 else -1
    header = clean[hs:he] if hs >= 0 and he > hs else ""
    m = re.search(r"FILE_NAME\s*\((.*?)\)\s*;", header, re.S)
    if m:
        a = _args(m.group(1))
        # name, time_stamp, author(s)..., organization(s)..., preprocessor, originating system, authorisation
        if a:
            info.header_file_name = a[0]
        if len(a) > 1:
            info.timestamp = a[1]
        if len(a) >= 5:
            info.preprocessor, info.originating_system = a[-3], a[-2]
    m = re.search(r"FILE_SCHEMA\s*\(\s*\((.*?)\)\s*\)", header, re.S)
    if m:
        info.schema = " ".join(_args(m.group(1)))
    ds = clean.find("DATA;", he if he > 0 else 0)
    data = clean[ds:] if ds >= 0 else ""
    info.n_entities = len(re.findall(r"#\d+\s*=", data))
    for pm in re.finditer(r"(?<![A-Z0-9_])PRODUCT\s*\(\s*('(?:[^']|'')*')\s*,\s*('(?:[^']|'')*')\s*,\s*('(?:[^']|'')*')", data):
        pid, name, desc = (decode_step_string(g[1:-1]) for g in pm.groups())
        info.products.append((pid, name, desc))
    gm = re.search(r"GLOBAL_UNIT_ASSIGNED_CONTEXT\s*\(\s*\(([^)]*)\)", data)
    if gm:
        for ref in _REF.findall(gm.group(1)):
            unit = _decode_length_unit(_instance_text(data, int(ref)))
            if unit:
                info.length_unit = unit
                break
    if not info.length_unit:  # fall back to any LENGTH_UNIT instance
        lm = re.search(r"#\d+\s*=\s*\(([^;]*LENGTH_UNIT[^;]*)\)\s*;", data)
        if lm:
            info.length_unit = _decode_length_unit(lm.group(1))
    return info


def normalized_data_section(text: str) -> str:
    """Canonical form of the DATA section used for the L1 'normalized' hash.

    Drops the HEADER (file name, timestamp, author, originating system), comments,
    every string literal (product names, labels), colour values, whitespace; rounds reals to 10
    significant digits and renumbers entity ids in order of appearance. Two files
    that differ only in those respects get the same canonical text.
    """
    clean = strip_comments(text)
    ds = clean.find("DATA;")
    if ds < 0:
        return ""
    data = clean[ds + 5:]
    end = data.rfind("ENDSEC;")
    if end >= 0:
        data = data[:end]
    data = _STR.sub("''", data)
    data = _WS.sub("", data)
    # presentation only: colours do not change the part
    data = _COLOUR.sub("COLOUR_RGB('',0,0,0)", data)
    data = _FLOAT.sub(lambda m: _fmt_real(m.group(0)), data)
    mapping: dict[str, str] = {}
    for m in _DEF.finditer(data):
        mapping.setdefault(m.group(1), str(len(mapping) + 1))
    return _REF.sub(lambda m: "#" + mapping.get(m.group(1), "x" + m.group(1)), data)


def _fmt_real(tok: str) -> str:
    try:
        v = float(tok)
    except ValueError:
        return tok
    if v == 0.0:
        return "0."
    return format(v, ".10g")
