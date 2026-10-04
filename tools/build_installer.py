"""Build the Windows installer: stage the program (the committed tree, the demo factory with its notice, the icon),
then run makensis on installer/PartAudit.nsi. Needs NSIS 3 (Linux: apt install nsis; Windows: winget install NSIS).

    python tools/build_installer.py --out dist/          # -> dist/PartAudit-Setup-<version>.exe

The installer is not signed. Its contents can be listed with 7-Zip (7z l PartAudit-Setup-<version>.exe).
"""
from __future__ import annotations

import argparse
import io
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTICE = """Demo factory for PartAudit. Business data (part numbers, names, stock, prices, people) is synthetic.
Standard-part geometry was generated with CadQuery from ISO/DIN dimensions.
Five models are NIST MBE PMI test cases (CTC/FTC), U.S. government works of the National Institute of
Standards and Technology, included with acknowledgement.
"""


def version() -> str:
    m = re.search(r'__version__ = "([^"]+)"', (ROOT / "part_audit" / "__init__.py").read_text(encoding="utf-8"))
    return m.group(1)


def icon(path: Path) -> None:
    """The PartAudit mark (util.js LOGO): a dark tile, a brass P, a blue dot - drawn at 256 px, saved in all sizes."""
    from PIL import Image, ImageDraw
    s = 8                                    # the logo is drawn on a 32 x 32 grid
    im = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((4, 4, 252, 252), radius=64, fill=(22, 32, 43, 255), outline=(255, 255, 255, 30), width=4)
    brass, w = (226, 180, 94, 255), int(2.6 * s)
    pts = [(9 * s, 23 * s), (9 * s, 9 * s), (17.6 * s, 9 * s)]
    d.line(pts, fill=brass, width=w, joint="curve")
    d.arc((12.6 * s, 9 * s, 22.6 * s, 19 * s), start=-90, end=90, fill=brass, width=w)
    d.line([(17.6 * s, 19 * s), (13 * s, 19 * s)], fill=brass, width=w)
    for x, y in ((9, 23), (13, 19)):         # round line ends
        d.ellipse((x * s - w / 2, y * s - w / 2, x * s + w / 2, y * s + w / 2), fill=brass)
    d.ellipse((20.3 * s, 20.3 * s, 24.7 * s, 24.7 * s), fill=(91, 140, 255, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def stage(dst: Path) -> None:
    """The committed tree (git archive applies .gitattributes: Windows line ends for .bat), plus the demo factory."""
    archive = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=zip", "HEAD"], capture_output=True,
                             check=True).stdout
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        z.extractall(dst)
    fac = ROOT / "demo" / "factory"
    if fac.exists():
        shutil.copytree(fac, dst / "demo" / "factory", dirs_exist_ok=True)
        (dst / "demo" / "factory" / "NOTICE.txt").write_text(NOTICE, encoding="utf-8")
    icon(dst / "installer" / "partaudit.ico")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist")
    ap.add_argument("--makensis", default=shutil.which("makensis") or "makensis")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    exe = out / f"PartAudit-Setup-{version()}.exe"
    with tempfile.TemporaryDirectory(prefix="pa-setup-") as tmp:
        src = Path(tmp) / "PartAudit"
        stage(src)
        subprocess.run([args.makensis, "-V2", f"-DVERSION={version()}", f"-DSRC={src}", f"-DOUTFILE={exe}",
                        str(src / "installer" / "PartAudit.nsi")], check=True)
    print(f"{exe} ({exe.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
