"""The web UI: every page the router loads exists, and every script parses (when Node.js is installed)."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[1] / "part_audit" / "ui"


def test_every_routed_page_exists():
    app = (UI / "js" / "app.js").read_text(encoding="utf-8")
    pages = re.findall(r'import\("\./(pages/[a-z0-9_]+\.js)"\)', app)
    assert len(pages) >= 15
    missing = [p for p in pages if not (UI / "js" / p).exists()]
    assert not missing
    # every navigation entry has a page
    nav = re.findall(r'\["([a-z]+)", "[^"]+", ICON\.', app)
    routed = set(re.findall(r'(\w+): \(\) => import\(', app))
    assert nav and set(nav) <= routed, set(nav) - routed


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_every_script_parses():
    bad = []
    for f in sorted((UI / "js").rglob("*.js")):
        r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
        if r.returncode:
            bad.append(f"{f.name}: {r.stderr.strip()[:200]}")
    assert not bad, bad
