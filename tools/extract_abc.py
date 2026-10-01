"""Extract only the STEP files of an ABC chunk whose size is within limits (saves ~10 GB per chunk).

    python tools/extract_abc.py abc_0000_step_v00.7z RAW/abc0 --max-mb 3 --sevenzip 7zz

Needs the 7-Zip command line tool (7zz / 7z). The archives are listed at
https://deep-geometry.github.io/abc-dataset/data/step_v00.txt
"""
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("archive")
    ap.add_argument("out")
    ap.add_argument("--min-kb", type=float, default=5)
    ap.add_argument("--max-mb", type=float, default=3)
    ap.add_argument("--sevenzip", default="7zz")
    a = ap.parse_args()
    listing = subprocess.run([a.sevenzip, "l", "-slt", a.archive], capture_output=True, text=True, check=True).stdout
    keep = []
    for block in listing.split("\n\n"):
        d = dict(line.split(" = ", 1) for line in block.splitlines() if " = " in line)
        if d.get("Path", "").endswith(".step") and d.get("Size", "").isdigit():
            if a.min_kb * 1024 <= int(d["Size"]) <= a.max_mb * 1e6:
                keep.append(d["Path"])
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        fh.write("\n".join(keep) + "\n")
    Path(a.out).mkdir(parents=True, exist_ok=True)
    subprocess.run([a.sevenzip, "x", "-y", f"-o{a.out}", a.archive, f"-i@{fh.name}"], check=True,
                   stdout=subprocess.DEVNULL)
    print(f"extracted {len(keep)} STEP files to {a.out}")


if __name__ == "__main__":
    main()
