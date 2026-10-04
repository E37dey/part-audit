"""Connector interface and helpers shared by all PDM/PLM/ERP connectors."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..model import BomLine, ErpItem, PartRecord

STEP_EXT = (".stp", ".step", ".p21")
CAD_PART_EXT = (".sldprt", ".ipt", ".prt", ".par", ".catpart", ".x_t", ".x_b")
CAD_ASM_EXT = (".sldasm", ".iam", ".asm", ".catproduct")


@dataclass
class Field:
    name: str
    label: str
    type: str = "text"            # text | password | number | bool | select | path | textarea
    default: Any = ""
    required: bool = False
    help: str = ""
    options: list | None = None
    group: str = "connection"     # connection | mapping | advanced
    secret: bool = False          # kept out of API answers (password fields always are)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class Collected:
    records: list[PartRecord] = field(default_factory=list)
    erp_items: list[ErpItem] = field(default_factory=list)
    bom: list[BomLine] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)


ProgressFn = Callable[[str, int, int], None]


class Connector:
    kind = ""
    role = "pdm"                  # pdm | erp
    title = ""
    vendor = ""
    description = ""
    interface = ""                # e.g. "REST (Web API)"
    fields: list[Field] = []
    # what is known about the interface (shown in the UI next to the connector)
    verification = ("נבנה לפי התיעוד הפומבי של היצרן ונבדק מול סימולטור מקומי שמחקה את ה-API. "
                    "טרם נבדק מול שרת אמיתי של לקוח.")
    unconfirmed: list[str] = []

    def __init__(self, source_id: str, name: str, config: dict, cache_dir: str | Path,
                 progress: ProgressFn | None = None, should_stop: Callable[[], bool] | None = None):
        self.source_id = source_id
        self.name = name
        self.cfg = {f.name: f.default for f in self.fields}
        self.cfg.update({k: v for k, v in (config or {}).items() if v is not None})
        self.cache_dir = Path(cache_dir) / safe_name(source_id)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._progress = progress
        self._should_stop = should_stop

    # ------------------------------------------------------------ API for subclasses
    def progress(self, text: str, done: int = 0, total: int = 0) -> None:
        if self._progress:
            self._progress(text, done, total)

    def stopped(self) -> bool:
        return bool(self._should_stop and self._should_stop())

    def uid(self, native_id) -> str:
        return f"{self.source_id}:{native_id}"

    def step_cache_path(self, native_id, version, filename: str) -> Path:
        ext = Path(filename).suffix.lower() or ".stp"
        key = hashlib.sha1(f"{native_id}|{version}|{filename}".encode()).hexdigest()[:10]
        return self.cache_dir / f"{safe_name(str(native_id))}_{key}{ext}"

    # ------------------------------------------------------------ to implement
    def test(self) -> dict:
        raise NotImplementedError

    def collect(self) -> Collected:
        raise NotImplementedError

    def sample(self, n: int = 40) -> dict:
        """A small read-only sample for field discovery: {"rows": [raw property dicts], "step": {checked, found},
        "notes": [...], "api_calls": int}. No files are downloaded."""
        raise NotImplementedError

    @classmethod
    def describe(cls) -> dict:
        return {"kind": cls.kind, "role": cls.role, "title": cls.title, "vendor": cls.vendor,
                "description": cls.description, "interface": cls.interface,
                "fields": [f.to_dict() for f in cls.fields], "verification": cls.verification,
                "unconfirmed": cls.unconfirmed}


def spread(items: list, n: int) -> list:
    """n items spread over the whole list (a sample from every folder, not only the first one)."""
    if len(items) <= n:
        return list(items)
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


def safe_name(s: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", s, flags=re.UNICODE)[:120]


def stem_key(filename: str) -> str:
    """Comparable stem of a CAD file name: 'PN - name.SLDPRT' and 'PN - name.STEP' -> same key."""
    st = Path(filename).stem.lower()
    return re.sub(r"[\s_]+", " ", st).strip()


def to_float(x) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(str(x).replace(",", ".").split()[0])
    except (ValueError, IndexError):
        return None


def mass_to_kg(value, unit_hint: str = "") -> float | None:
    """Mass property as stored by CAD systems: '0.553 kg', '553 g', 0.553 (kg assumed unless the hint says g)."""
    if value is None or value == "":
        return None
    s = str(value).strip().lower()
    num = to_float(s)
    if num is None:
        return None
    if re.search(r"(?<![a-z])g(?:r|ram)?s?\b", s) and "kg" not in s or unit_hint.lower() in ("g", "gram", "grams"):
        return num / 1000.0
    if "lb" in s or unit_hint.lower() in ("lb", "lbm"):
        return num * 0.45359237
    return num
