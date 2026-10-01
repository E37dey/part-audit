"""L1 - exact duplicate detection by hashing.

* ``sha256``      - hash of the raw file bytes (byte-identical copies).
* ``norm_sha256`` - hash of the canonical DATA section of a STEP file
                    (same geometry/topology entities; header, timestamps,
                    names, comments, whitespace and entity numbering ignored).
"""
from __future__ import annotations

import hashlib

from .stepfile import normalized_data_section


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalized_step_hash(text: str) -> str:
    """SHA-256 of :func:`normalized_data_section`, or '' if there is no DATA section."""
    canon = normalized_data_section(text)
    if not canon:
        return ""
    return hashlib.sha256(canon.encode("utf-8", "surrogatepass")).hexdigest()


def group_by(values: dict[str, str]) -> dict[str, list[str]]:
    """Invert {file_id: hash} into {hash: [file_ids]} keeping only hashes shared by 2+ files."""
    groups: dict[str, list[str]] = {}
    for fid, h in values.items():
        if h:
            groups.setdefault(h, []).append(fid)
    return {h: sorted(ids) for h, ids in groups.items() if len(ids) > 1}
