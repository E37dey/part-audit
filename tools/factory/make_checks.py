"""Sample files for the pre-release check in the demo (demo/factory/checks/): new parts an engineer might be about
to release, each a different case. Synthetic like the rest of the demo factory; built from its own parts.

    python tools/factory/make_checks.py --factory demo/factory

* motor_mount_v2.step   - a "new" motor mount that is the same shape as one already in two systems (moved, rotated,
                          exported as AP242 with another product name)
* shcs_m10x25.step      - a socket head cap screw from another CAD library (the same standard part, four records)
* adapter_plate_hole.step - an existing adapter plate with one extra hole (near-identical)
* sensor_bracket.step   - a sheet-metal Z bracket that does not exist yet (also used with a part number that is taken)
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path[:0] = [str(HERE), str(ROOT), str(ROOT / "tools")]

import cadops  # noqa: E402
import parts as P  # noqa: E402

SAMPLES = [
    {"key": "motor-mount", "file": "motor_mount_v2.step", "title": "תושבת מנוע חדשה", "pn": "",
     "name": "תושבת מנוע NEMA23", "material": "", "expect": "אותה צורה כבר קיימת בשתי מערכות"},
    {"key": "screw", "file": "shcs_m10x25.step", "title": "בורג אלן M10x25", "pn": "",
     "name": "בורג אלן M10x25 DIN 912", "material": "", "expect": "אותו חלק תקני כבר קיים בארבע מערכות"},
    {"key": "plate-hole", "file": "adapter_plate_hole.step", "title": "פלטת מתאם עם חור נוסף", "pn": "",
     "name": "פלטת מתאם 150x150x15 עם חור נוסף", "material": "", "expect": "חלק כמעט זהה כבר קיים"},
    {"key": "sensor-bracket", "file": "sensor_bracket.step", "title": "תושבת חיישן חדשה", "pn": "200-5120",
     "name": "תושבת חיישן Z 35x45", "material": "פח מגולוון DX51D", "expect": "חלק חדש – אפשר לפתוח מק\"ט"},
    {"key": "pn-taken", "file": "sensor_bracket.step", "title": "תושבת חיישן עם מק\"ט תפוס", "pn": "200-4954",
     "name": "תושבת חיישן Z 35x45", "material": "פח מגולוון DX51D", "expect": "המק\"ט שתוכנן כבר שייך לחלק אחר"},
]


def step_of(factory: Path, records: list[dict], pn: str) -> str:
    r = next(r for r in records if r.get("pn") == pn and r.get("step_file"))
    return str(factory / r["step_file"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--factory", default=str(ROOT / "demo" / "factory"))
    args = ap.parse_args()
    factory = Path(args.factory)
    records = json.loads((factory / "factory.json").read_text(encoding="utf-8"))["records"]
    out = factory / "checks"
    out.mkdir(exist_ok=True)
    rng = random.Random(20261004)

    mount = cadops.read(step_of(factory, records, "200-4954"))
    cadops.write_step(cadops.transform(mount, cadops.random_rigid(rng)), str(out / "motor_mount_v2.step"),
                      schema="AP242DIS", product="MOTOR MOUNT V2")
    screw = P.socket_head_cap_screw(10, 25, style="D")
    cadops.write_step(screw.val().wrapped, str(out / "shcs_m10x25.step"), schema="AP214IS", product="SHCS M10X25")
    plate = cadops.read(step_of(factory, records, "200-9036"))
    holed, _ = cadops.drill_hole(plate, random.Random(5), 0.05)
    cadops.write_step(holed, str(out / "adapter_plate_hole.step"), product="ADAPTER PLATE 150 REV2")
    z = P.sheet_z_bracket(35, 45, 22, 30, 2.0)
    cadops.write_step(z.val().wrapped, str(out / "sensor_bracket.step"), schema="AP214CD", product="SENSOR BRACKET Z")
    (out / "checks.json").write_text(json.dumps(SAMPLES, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "README.md").write_text(
        "# Sample files for the pre-release check\n\nSynthetic parts made from the demo factory's own parts by "
        "`tools/factory/make_checks.py`; each one shows a different answer of the check (see `checks.json`).\n",
        encoding="utf-8")
    print(f"{len(SAMPLES)} samples in {out}")


if __name__ == "__main__":
    main()
