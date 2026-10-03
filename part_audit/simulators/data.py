"""Demo factory data shared by all simulators (loaded once per factory folder)."""
from __future__ import annotations

import hashlib
import json
import threading
from collections import defaultdict
from functools import cached_property
from pathlib import Path

_LOCK = threading.Lock()
_CACHE: dict[str, "FactoryData"] = {}

DEMO_USER = "demo"
DEMO_PASSWORD = "demo123"

FASTENER_FAMS = {"shcs", "hexscrew", "nut", "washer", "csk", "setscrew", "pin", "key"}


def factory(path: str | Path) -> "FactoryData":
    key = str(Path(path).resolve())
    with _LOCK:
        if key not in _CACHE:
            _CACHE[key] = FactoryData(Path(key))
        return _CACHE[key]


class FactoryData:
    def __init__(self, root: Path):
        self.root = root
        d = json.loads((root / "factory.json").read_text(encoding="utf-8"))
        self.about = d["about"]
        self.sites = d["sites"]
        self.records: list[dict] = d["records"]
        self.erp: dict = d["erp"]
        self.truth = d.get("truth", [])
        self.by_rid = {r["rid"]: r for r in self.records}
        self.by_system: dict[str, list[dict]] = defaultdict(list)
        for r in self.records:
            self.by_system[r["system"]].append(r)
        self.parents: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for r in self.records:
            for line in r.get("bom", []):
                self.parents[line["child"]].append((r["rid"], line["qty"]))

    def step_file(self, rec: dict) -> Path | None:
        f = rec.get("step_file")
        if not f:
            return None
        p = self.root / f
        return p if p.exists() else None

    @cached_property
    def erp_items(self) -> list[dict]:
        return self.erp["items"]

    @cached_property
    def erp_by_pn(self) -> dict[str, dict]:
        return {i["pn"]: i for i in self.erp["items"]}

    @cached_property
    def erp_bom_by_parent(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = defaultdict(list)
        for b in self.erp["bom"]:
            out[b["parent"]].append(b)
        return out


def token(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()


def basic_ok(auth_header: str | None) -> bool:
    import base64
    if not auth_header or not auth_header.lower().startswith("basic "):
        return False
    try:
        user, _, pw = base64.b64decode(auth_header.split(" ", 1)[1]).decode("utf-8").partition(":")
    except Exception:
        return False
    return (user == DEMO_USER and pw == DEMO_PASSWORD) or pw == "PAT" and user.startswith("demo-token")
