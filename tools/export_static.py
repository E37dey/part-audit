"""Export a finished scan as a static, read-only copy of the app (the online demo).

The same UI runs with window.PA_STATIC: every GET of the REST API is answered from data/*.json, 3D meshes and
deviation maps come from a few pack files, and decisions stay in the viewer's tab. Nothing in the copy can reach
a PDM/PLM/ERP system.

    python tools/export_static.py --workspace ~/PartAudit --out out/static_demo

The workspace must contain a finished scan of the demo sources.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT)]

MARKER = ".partaudit-static"
PACK_LIMIT = 6_000_000          # bytes per pack file (well below the hosting limit per file)
# pairs that get a deviation map online (identical-shape spec conflicts would show an all-blue map)
COMPARE_CATEGORIES = ("near_identical", "mirror", "conflict")
THREE_CDN = "https://cdn.jsdelivr.net/npm/three@0.170.0"   # the same version as part_audit/ui/vendor
GOOGLE_FONTS = ("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500"
                "&family=IBM+Plex+Sans+Hebrew:wght@400;500;600;700&display=swap")


class Packer:
    """Concatenates binary blobs into pack files of about PACK_LIMIT bytes; index: key -> [file, offset, length].
    Packs are written as base64 text (.txt): the hosting serves only web file types, and the page decodes a pack
    once and slices it."""

    def __init__(self, folder: Path, prefix: str):
        self.folder, self.prefix = folder, prefix
        self.index: dict[str, list] = {}
        self.n, self.buf = 0, bytearray()

    def add(self, key: str, data: bytes) -> None:
        if self.buf and len(self.buf) + len(data) > PACK_LIMIT:
            self.flush()
        self.index[key] = [f"{self.prefix}_{self.n}.txt", len(self.buf), len(data)]
        self.buf += data

    def flush(self) -> None:
        import base64
        if self.buf:
            (self.folder / f"{self.prefix}_{self.n}.txt").write_bytes(base64.b64encode(bytes(self.buf)))
            self.n, self.buf = self.n + 1, bytearray()


def pam2(pam1: bytes) -> bytes:
    """Smaller model file for the online copy: positions and edge points as 16-bit integers inside the model's box,
    triangle indices as 16-bit when they fit. Same header as PAM1 (counts + box)."""
    import struct

    import numpy as np
    from part_audit.viewer import parse_mesh
    m = parse_mesh(pam1)
    lo, hi = np.array(m["bbox"][:3], float), np.array(m["bbox"][3:], float)
    sc = np.where(hi - lo > 0, (hi - lo) / 65535.0, 1.0)
    q = lambda a: np.clip(np.round((np.asarray(a, float).reshape(-1, 3) - lo) / sc), 0, 65535).astype("<u2")  # noqa: E731
    out = bytearray(b"PAM2" + pam1[4:40])
    out += q(m["v"]).tobytes()
    out.extend(b"\0" * (-len(out) % 4))
    out += np.asarray(m["t"]).astype("<u2" if len(m["v"]) < 65536 else "<u4").tobytes()
    out.extend(b"\0" * (-len(out) % 4))
    out += q(m["e"]).tobytes()
    out.extend(b"\0" * (-len(out) % 4))
    return bytes(out)


def pac3(pac2: bytes) -> bytes:
    """Smaller deviation-map file for the online copy: positions and deviations as 16-bit integers relative to the
    mesh's box and the largest deviation, triangle indices as 16-bit when they fit. Same header as PAC2."""
    import struct

    import numpy as np
    from part_audit.viewer import parse_compare
    c = parse_compare(pac2)
    out = bytearray(b"PAC3" + pac2[4:100])

    def pad():
        out.extend(b"\0" * (-len(out) % 4))
    for key in ("a", "b"):
        v, t, d = c["mesh_" + key]["v"].astype(np.float64), c["mesh_" + key]["t"], c["dev_" + key].astype(np.float64)
        lo, hi = v.min(0), v.max(0)
        sc = np.where(hi - lo > 0, (hi - lo) / 65535.0, 1.0)
        out += struct.pack("<6f", *lo, *sc)
        out += np.round((v - lo) / sc).astype("<u2").tobytes()
        pad()
        out += t.astype("<u2" if len(v) < 65536 else "<u4").tobytes()
        pad()
        dmax = float(d.max()) if len(d) else 0.0
        out += struct.pack("<f", dmax)
        out += (np.round(d / dmax * 65535) if dmax > 0 else np.zeros(len(d))).astype("<u2").tobytes()
        pad()
    return bytes(out)


def dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ui-only", action="store_true", help="refresh only the UI files of an earlier export")
    args = ap.parse_args()
    if args.ui_only:
        if not (Path(args.out) / MARKER).exists():
            raise SystemExit("--ui-only needs an earlier export in --out")
        write_ui(Path(args.out))
        return

    from fastapi.testclient import TestClient
    from part_audit.server.app import create_app

    out = Path(args.out)
    if out.exists():
        # only ever replace a folder this tool wrote before (never a workspace or anything else)
        if any(out.iterdir()) and not (out / MARKER).exists():
            raise SystemExit(f"{out} exists and is not an earlier static export - choose an empty or new folder")
        shutil.rmtree(out)
    data = out / "data"
    data.mkdir(parents=True)
    (out / MARKER).write_text("written by tools/export_static.py\n", encoding="utf-8")
    client = TestClient(create_app(args.workspace), base_url="http://127.0.0.1:8765")   # loopback only

    def get(path, **params):
        r = client.get(path, params=params)
        r.raise_for_status()
        return r.json()

    def binary(path, **params):
        r = client.get(path, params=params)
        r.raise_for_status()
        return r.content

    status = get("/api/status")
    if not status["latest_run"]:
        raise SystemExit("no finished scan in this workspace")
    from part_audit.demo import DEMO_DIR

    def is_demo(src):
        if src["simulated"]:
            return True
        path = Path(src["config"].get("path") or "/nonexistent").resolve()
        return src["kind"] == "folder" and DEMO_DIR.resolve() in path.parents
    real = [s["name"] for s in get("/api/sources") if not is_demo(s)]
    if real:
        raise SystemExit("this workspace reads real systems (" + ", ".join(real) + "): the online copy is for the demo only")
    status.update({"latest_run": "latest", "workspace": "", "running": None, "static": True})
    dump(data / "status.json", status)
    dump(data / "connectors.json", get("/api/connectors"))
    # the online copy shows which systems were read, not how to reach them
    dump(data / "sources.json", [{**s, "config": {k: v for k, v in s["config"].items() if k == "vault"}}
                                 for s in get("/api/sources")])
    dump(data / "runs.json", get("/api/runs"))
    # field discovery results stored by the app (pilot kit), shown read-only online
    disc = {}
    for src in get("/api/sources"):
        r = client.get(f"/api/sources/{src['id']}/discovery")
        if r.status_code == 200:
            disc[src["id"]] = r.json()
    dump(data / "discovery.json", disc)
    summary = get("/api/runs/latest/summary")
    summary["sources"] = [{k: v for k, v in x.items() if k != "url"} for x in summary["sources"]]   # no addresses
    dump(data / "summary.json", summary)

    groups = get("/api/runs/latest/groups")
    dump(data / "groups.json", groups)
    gdet = {g["id"]: get(f"/api/runs/latest/groups/{g['id']}") for g in groups}
    dump(data / "group_details.json", gdet)
    pairs = get("/api/runs/latest/pairs")
    dump(data / "pairs.json", pairs)
    pdet = {p["id"]: get(f"/api/runs/latest/pairs/{p['id']}") for p in pairs}
    dump(data / "pair_details.json", pdet)
    for kind in ("names", "quality", "erp_issues"):
        dump(data / f"findings_{kind}.json", get(f"/api/runs/latest/findings/{kind}"))
    dump(data / "mapping.json", get("/api/runs/latest/mapping"))
    parts = get("/api/runs/latest/parts", limit=1_000_000)["rows"]
    dump(data / "parts.json", parts)
    dump(data / "part_details.json", {p["uid"]: get(f"/api/runs/latest/parts/{p['uid']}") for p in parts})
    # pre-release checks the app ran on the demo's own sample files (the online copy cannot upload files);
    # a check of any other file stays out of the copy
    order = [s["key"] for s in get("/api/checks/samples")]
    checks = sorted((c for c in get("/api/checks") if c["status"] == "done" and c["sample"] in order),
                    key=lambda c: (order.index(c["sample"]), c["at"]))
    checks = list({c["sample"]: c for c in checks}.values())          # the latest run of every sample
    cdet = {c["id"]: get(f"/api/checks/{c['id']}") for c in checks}
    dump(data / "checks.json", checks)
    dump(data / "check_details.json", cdet)
    print(f"json: {len(groups)} groups, {len(pairs)} pairs, {len(parts)} records, {len(checks)} sample checks")

    # 3D: every model, the display alignment used by the group and pair pages, and the deviation maps
    meshes = Packer(data, "mesh")
    for p in parts:
        if p["has_step"]:
            meshes.add(p["uid"], pam2(binary(f"/api/mesh/latest/{p['uid']}")))
    for cid in cdet:
        meshes.add(f"check:{cid}", pam2(binary(f"/api/checks/{cid}/mesh")))
    meshes.flush()
    dump(data / "mesh_index.json", meshes.index)
    align = {}
    for g in gdet.values():
        ordered = sorted(g["parts"], key=lambda p: (p["uid"] != g["master_uid"], p["source"]))  # as in group.js
        shown = [p for p in ordered if p["has_step"]][:6]
        for p in shown[1:]:
            align[f"{shown[0]['uid']}|{p['uid']}"] = get("/api/align/latest", a=shown[0]["uid"], b=p["uid"])
    compares = Packer(data, "compare")
    for p in pairs:
        if p["category"] in COMPARE_CATEGORIES and p["has_step"]:
            align[f"{p['a']}|{p['b']}"] = get("/api/align/latest", a=p["a"], b=p["b"])
            compares.add(f"{p['a']}|{p['b']}", pac3(binary("/api/compare/latest", a=p["a"], b=p["b"])))
    for cid, c in cdet.items():
        for m in c["matches"]:
            if m["part"]["has_step"]:
                align[f"check:{cid}|{m['uid']}"] = get(f"/api/checks/{cid}/align", b=m["uid"])
                compares.add(f"check:{cid}|{m['uid']}", pac3(binary(f"/api/checks/{cid}/compare", b=m["uid"])))
    compares.flush()
    dump(data / "align.json", align)
    dump(data / "compare_index.json", compares.index)
    print(f"3D: {len(meshes.index)} models in {meshes.n} packs, {len(compares.index)} deviation maps in {compares.n} packs,"
          f" {len(align)} alignments")

    write_ui(out)


def write_ui(out: Path) -> None:
    """The UI, with fonts from Google Fonts, three.js from the jsDelivr CDN (pinned version), and the static flag
    set before the app starts."""
    ui = ROOT / "part_audit" / "ui"
    if (out / "assets").exists():
        shutil.rmtree(out / "assets")
    shutil.copytree(ui, out / "assets", ignore=shutil.ignore_patterns("index.html", "fonts", "vendor"))
    css = (out / "assets" / "css" / "app.css").read_text(encoding="utf-8")
    css = re.sub(r"@font-face \{[^}]*\}\n", "", css)
    css = css.replace('--font: "Plex Hebrew",', '--font: "IBM Plex Sans Hebrew",').replace('--mono: "Plex Mono",', '--mono: "IBM Plex Mono",')
    (out / "assets" / "css" / "app.css").write_text(css, encoding="utf-8")
    v3d = out / "assets" / "js" / "viewer3d.js"
    v3d.write_text(v3d.read_text(encoding="utf-8").replace('from "./../vendor/OrbitControls.js";',
                                                           'from "three/addons/controls/OrbitControls.js";'), encoding="utf-8")
    html = (ui / "index.html").read_text(encoding="utf-8")
    head = re.search(r"<head>(.*)</head>", html, re.S).group(1)
    body = re.search(r"<body>(.*)</body>", html, re.S).group(1)
    head = re.sub(r'<meta charset="utf-8">\s*', "", head)
    head = re.sub(r"<meta name=\"viewport\"[^>]*>\s*", "", head)
    head = head.replace("<title>PartAudit</title>", "<title>PartAudit Demo</title>")
    head = head.replace('<link rel="stylesheet" href="assets/css/app.css">',
                        f'<link rel="stylesheet" href="{GOOGLE_FONTS}">\n<link rel="stylesheet" href="assets/css/app.css">')
    head = re.sub(r'<script type="importmap">.*?</script>', '<script type="importmap">' + json.dumps({"imports": {
        "three": f"{THREE_CDN}/build/three.module.min.js", "three/addons/": f"{THREE_CDN}/examples/jsm/"}}) + "</script>",
        head, flags=re.S)
    page = (f"{head.strip()}\n<script>window.PA_STATIC = true; document.documentElement.lang = 'he'; "
            f"document.documentElement.dir = 'rtl';</script>\n{body.strip()}\n")
    (out / "index.html").write_text(page, encoding="utf-8")
    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    size = sum((out / f).stat().st_size for f in files)
    big = max(files, key=lambda f: (out / f).stat().st_size)
    print(f"static site: {len(files)} files, {size / 1e6:.1f} MB (largest {big}: {(out / big).stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
