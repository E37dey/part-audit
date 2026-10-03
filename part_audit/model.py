"""Canonical records that every connector produces (PDM/PLM parts, ERP items, BOM lines).

Connectors translate each system's own vocabulary into these records; everything after
collection (audit, quality checks, impact, UI, Excel) works on them only.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

STATE_CLASSES = ("released", "in_work", "review", "obsolete", "")

_STATE_WORDS = [
    (re.compile(r"obsol|withdrawn|cancel|superseded|לא\s*פעיל|מבוטל|הוצא", re.I), "obsolete"),
    (re.compile(r"releas|approved|production|frozen|משוחרר|מאושר|שוחרר", re.I), "released"),
    (re.compile(r"review|pending|approval|check|בבדיקה|ממתין|לאישור", re.I), "review"),
    (re.compile(r"work|progress|edit|draft|design|בעבודה|בעריכה|טיוטה", re.I), "in_work"),
]


def classify_state(state: str, extra_map: dict[str, str] | None = None) -> str:
    """Map a system's lifecycle/workflow state name to released | in_work | review | obsolete | ''."""
    s = (state or "").strip()
    if not s:
        return ""
    if extra_map and s in extra_map:
        return extra_map[s]
    for rx, cls in _STATE_WORDS:
        if rx.search(s):
            return cls
    return ""


@dataclass
class PartRecord:
    uid: str                         # unique across sources: '<source_id>:<native id>'
    source_id: str
    source_kind: str                 # swpdm | vault | windchill | teamcenter | folder
    native_id: str
    kind: str = "part"               # part | assembly
    pn: str = ""
    name: str = ""
    description: str = ""
    name_en: str = ""
    revision: str = ""
    version: str = ""
    state: str = ""                  # as the system shows it
    state_class: str = ""            # released | in_work | review | obsolete | ''
    material: str = ""
    finish: str = ""
    mass_kg: float | None = None     # mass property recorded in the PDM/PLM
    mass_text: str = ""              # the mass value as stored (keeps its displayed precision)
    make_buy: str = ""               # make | buy | ''
    author: str = ""
    created: str = ""
    modified: str = ""
    native_file: str = ""            # file name in the source system
    folder: str = ""
    cad_app: str = ""
    step_path: str = ""              # local cached neutral (STEP) file, absolute
    step_name: str = ""              # file name of the STEP in the source
    step_note: str = ""              # why there is no STEP, if none
    url: str = ""                    # link into the source system, if known
    props: dict = field(default_factory=dict)
    children: list = field(default_factory=list)   # [{'child': uid-or-pn, 'qty': float, 'by': 'uid'|'pn'}]
    history: list = field(default_factory=list)    # [{'version','revision','date','comment'}]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ErpItem:
    source_id: str
    pn: str
    description: str = ""
    description_en: str = ""
    uom: str = ""
    family: str = ""
    status: str = ""
    active: bool = True
    make_buy: str = ""
    stock: dict = field(default_factory=dict)       # warehouse -> qty
    stock_total: float = 0.0
    unit_cost: float | None = None
    currency: str = ""
    supplier: str = ""
    supplier_pn: str = ""
    lead_time_days: float | None = None
    created: str = ""
    material: str = ""
    props: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def stock_value(self) -> float | None:
        if self.unit_cost is None:
            return None
        return self.stock_total * self.unit_cost


@dataclass
class BomLine:
    source_id: str
    parent: str                      # PN (ERP) or uid (PDM)
    child: str
    qty: float = 1.0


@dataclass
class SourceInfo:
    id: str
    kind: str                        # connector kind
    name: str                        # display name (Hebrew)
    role: str                        # pdm | erp
    url: str = ""
    simulated: bool = False
    stats: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)


@dataclass
class Snapshot:
    """Everything collected from the connected systems at one point in time."""
    created: str
    sources: list[SourceInfo] = field(default_factory=list)
    records: list[PartRecord] = field(default_factory=list)
    erp_items: list[ErpItem] = field(default_factory=list)
    erp_bom: list[BomLine] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps({"created": self.created, "sources": [asdict(s) for s in self.sources],
                           "records": [r.to_dict() for r in self.records],
                           "erp_items": [e.to_dict() for e in self.erp_items],
                           "erp_bom": [asdict(b) for b in self.erp_bom], "skipped": self.skipped},
                          ensure_ascii=False)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @staticmethod
    def load(path: str | Path) -> "Snapshot":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return Snapshot(created=d["created"], sources=[SourceInfo(**s) for s in d.get("sources", [])],
                        records=[PartRecord(**r) for r in d.get("records", [])],
                        erp_items=[ErpItem(**e) for e in d.get("erp_items", [])],
                        erp_bom=[BomLine(**b) for b in d.get("erp_bom", [])], skipped=d.get("skipped", []))
