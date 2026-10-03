"""Read-only connectors to PDM/PLM systems, ERPs, folders and export files."""
from __future__ import annotations

from .base import Collected, Connector, Field
from .erp import PriorityErp, SapB1, SapS4
from .files import ErpFile, FolderSource
from .swpdm import SwPdmCom, SwPdmWeb
from .teamcenter import TeamcenterRest
from .vault import VaultRest
from .windchill import WindchillWrs

CONNECTORS: dict[str, type[Connector]] = {c.kind: c for c in (
    SwPdmWeb, SwPdmCom, VaultRest, WindchillWrs, TeamcenterRest, FolderSource, PriorityErp, SapS4, SapB1, ErpFile)}


def get(kind: str) -> type[Connector]:
    if kind not in CONNECTORS:
        raise KeyError(f"unknown connector kind: {kind}")
    return CONNECTORS[kind]


__all__ = ["CONNECTORS", "Collected", "Connector", "Field", "get"]
