"""Pre-release check: a new STEP file against a finished scan (engine level, then the local web API)."""
import json
import random
import time

import pytest

pytest.importorskip("OCP")

import cadops  # noqa: E402  (tools/cadops.py)
from part_audit.precheck import CheckError, build_index, check_file  # noqa: E402
from part_audit.project import ProjectSettings, audit_snapshot, collect  # noqa: E402

ERP_CSV = """מק"ט,תיאור,מלאי,עלות,סטטוס,חומר
100-0001,תושבת פלדה,10,50,פעיל,פלדה
100-0002,BRACKET STEEL,5,48,פעיל,STEEL
200-0001,פלטה אלומיניום,3,20,פעיל,אלומיניום
999-9999,פריט ללא מודל,7,5,פעיל,
"""


@pytest.fixture(scope="module")
def scan(tmp_path_factory):
    """A small plant scanned like the app does: the snapshot, the STEP records it read, the result."""
    root = tmp_path_factory.mktemp("plant")
    cad = root / "cad"
    cad.mkdir()
    base = cadops.chiral_test_part()
    cadops.write_step(base, str(cad / "100-0001 - תושבת.step"))
    cadops.write_step(cadops.transform(base, cadops.random_rigid(random.Random(4))), str(cad / "100-0002 - BRACKET.step"))
    cadops.write_step(cadops.plate_with_hole(), str(cad / "200-0001 - פלטה.step"))
    (root / "erp.csv").write_text(ERP_CSV, encoding="utf-8")
    sources = [{"id": "cad", "kind": "folder", "name": "תיקיית CAD", "config": {"path": str(cad)}, "enabled": True},
               {"id": "erp", "kind": "erp_file", "name": "ERP", "config": {"path": str(root / "erp.csv")}, "enabled": True}]
    cache = root / "cache"
    snap = collect(sources, cache / "connectors")
    run = root / "run"
    run.mkdir()
    snap.save(run / "snapshot.json")
    files: dict = {}
    res = audit_snapshot(snap, ProjectSettings(workers=1), cache, files_out=files)
    (run / "files.json").write_text(json.dumps(files), encoding="utf-8")
    new = root / "new"
    new.mkdir()
    return {"root": root, "run": run, "cache": cache, "res": res, "base": base, "new": new,
            "parts": {p["uid"]: p for p in res["parts"]}}


@pytest.fixture(scope="module")
def index(scan):
    return build_index(scan["run"], scan["cache"], run_id="r1")


def _check(scan, index, shape, fname, **kw):
    path = scan["new"] / fname
    if shape is not None:
        cadops.write_step(shape, str(path))
    return check_file(index, path, scan["parts"], cache_dir=scan["cache"], own_cache=scan["new"] / f"fp_{fname}", **kw)


def _pns(res, category):
    return sorted(m["part"]["pn"] for m in res["matches"] if m["category"] == category)


def test_the_scan_keeps_its_file_records_and_the_index_uses_them(scan, index):
    assert index.n_parts == 3 and index.n_with_step == 3 and index.n_geometry == 3
    files = json.loads((scan["run"] / "files.json").read_text(encoding="utf-8"))
    assert len(files) == 3 and all(f["sha256"] for f in files.values())
    # an older scan without the records reads the files again and gets the same index
    (scan["run"] / "files.json").rename(scan["run"] / "files.bak")
    try:
        slow = build_index(scan["run"], scan["cache"], run_id="r1")
    finally:
        (scan["run"] / "files.bak").rename(scan["run"] / "files.json")
    assert slow.n_geometry == index.n_geometry and sorted(slow.by_sha) == sorted(index.by_sha)


def test_the_same_shape_moved_and_renamed_already_exists(scan, index):
    moved = cadops.transform(scan["base"], cadops.random_rigid(random.Random(11)))
    r = _check(scan, index, moved, "new_bracket.step", name="תושבת חדשה")
    assert r["verdict"]["kind"] == "exists" and r["verdict"]["tone"] == "bad"
    assert _pns(r, "identical") == ["100-0001", "100-0002"]
    assert r["verdict"]["use"]["pn"] in ("100-0001", "100-0002")
    assert "100-0001" in r["verdict"]["text"] or "100-0002" in r["verdict"]["text"]
    assert r["coverage"] == {"parts": 3, "with_step": 3, "with_geometry": 3}
    # the duplicate group of the scan: its target part number is the one to use
    g = next(g for g in scan["res"]["groups"] if "100-0002" in g["pns"])
    target = scan["parts"][g["master_uid"]]
    targets = {g["id"]: {"uid": target["uid"], "pn": target["pn"], "name": target["name"], "source": target["source"],
                         "source_kind": target["source_kind"], "approved": False, "pns": g["pns"]}}
    r2 = _check(scan, index, None, "new_bracket.step", name="תושבת חדשה", group_targets=targets)
    assert r2["verdict"]["use"]["pn"] == target["pn"] and "קבוצת כפילות" in r2["verdict"]["text"]


def test_the_planned_number_of_the_same_part_is_not_reported_as_free(scan, index):
    r = _check(scan, index, None, "new_bracket.step", pn="100-0001")
    kinds = [n["kind"] for n in r["notes"]]
    assert r["verdict"]["kind"] == "exists" and "pn_same_part" in kinds and "pn_free" not in kinds


def test_the_same_file_is_found_by_its_bytes(scan, index):
    src = next(p for p in (scan["root"] / "cad").iterdir() if p.name.startswith("200-0001"))
    (scan["new"] / "copy.step").write_bytes(src.read_bytes())
    r = _check(scan, index, None, "copy.step")
    m = next(m for m in r["matches"] if m["part"]["pn"] == "200-0001")
    assert m["l1"] == "raw" and m["category"] == "identical" and r["verdict"]["kind"] == "exists"


def test_a_file_in_the_wrong_units_is_found_and_flagged(scan, index):
    r = _check(scan, index, cadops.uniform_scale(scan["base"], 1 / 25.4), "inch.step")
    assert r["verdict"]["kind"] == "exists"
    assert {m["geo_relation"] for m in r["matches"] if m["category"] == "identical"} == {"unit_scaled"}
    assert any(n["kind"] == "unit" and "25.4" in n["text"] for n in r["notes"])


def test_a_small_change_is_near_identical(scan, index):
    holed, _ = cadops.drill_hole(scan["base"], random.Random(2), 0.08)
    r = _check(scan, index, holed, "holed.step")
    assert r["verdict"]["kind"] == "near" and r["verdict"]["tone"] == "warn"
    assert _pns(r, "near_identical") == ["100-0001", "100-0002"] and not _pns(r, "identical")


def test_a_mirror_image_is_reported_as_the_other_hand(scan, index):
    r = _check(scan, index, cadops.mirror(scan["base"]), "mirrored.step")
    assert r["verdict"]["kind"] == "mirror" and _pns(r, "mirror") == ["100-0001", "100-0002"]


def test_a_new_part_and_the_planned_part_number(scan, index):
    shape = cadops.plate_with_hole(w=120.0, h=33.0, t=4.0, d=7.0)
    free = _check(scan, index, shape, "plate_new.step", pn="555-0000", name="פלטה צרה")
    assert free["verdict"]["kind"] == "new" and free["verdict"]["tone"] == "ok"
    assert "pn_free" in [n["kind"] for n in free["notes"]] and not [n for n in free["notes"] if n["tone"] == "bad"]
    taken = _check(scan, index, None, "plate_new.step", pn="100-0002", name="פלטה צרה")
    assert taken["verdict"]["kind"] == "new" and taken["verdict"]["tone"] == "warn"
    assert _pns(taken, "conflict") == ["100-0002"] and any(n["kind"] == "pn_taken" for n in taken["notes"])
    in_erp = _check(scan, index, None, "plate_new.step", pn="999-9999")
    assert any(n["kind"] == "pn_in_erp" and "פריט ללא מודל" in n["text"] for n in in_erp["notes"])


def test_a_file_that_is_not_step_is_refused(scan, index):
    (scan["new"] / "notes.step").write_text("just text", encoding="utf-8")
    with pytest.raises(CheckError):
        _check(scan, index, None, "notes.step")


# ------------------------------------------------------------------------------------------------ web API

@pytest.fixture(scope="module")
def client(scan, tmp_path_factory):
    from fastapi.testclient import TestClient
    from part_audit.server.app import create_app
    app = create_app(tmp_path_factory.mktemp("ws"), factory_dir=None, demo=False)
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        c.app_store = app.state.store
        yield c


def _wait(client, jid):
    for _ in range(600):
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def test_check_api(client, scan):
    moved = scan["new"] / "api_bracket.step"
    cadops.write_step(cadops.transform(scan["base"], cadops.random_rigid(random.Random(21))), str(moved))
    files = {"file": ("new_bracket.step", moved.read_bytes(), "application/octet-stream")}
    # nothing to compare with before the first scan
    assert client.post("/api/checks", files=files, data={"name": "תושבת"}).status_code == 400
    for s in ({"kind": "folder", "name": "CAD", "config": {"path": str(scan["root"] / "cad")}},
              {"kind": "erp_file", "name": "ERP", "config": {"path": str(scan["root"] / "erp.csv")}}):
        client.post("/api/sources", json=s)
    assert _wait(client, client.post("/api/scan").json()["job_id"])["status"] == "done"
    rid = client.get("/api/status").json()["latest_run"]
    assert (client.app_store.run_dir(rid) / "files.json").exists()

    r = client.post("/api/checks", files=files, data={"name": "תושבת חדשה", "pn": "555-1"})
    assert r.status_code == 200, r.text
    cid = r.json()["check_id"]
    assert _wait(client, r.json()["job_id"])["status"] == "done"
    c = client.get(f"/api/checks/{cid}").json()
    assert c["status"] == "done" and c["verdict"]["kind"] == "exists" and c["input"]["pn"] == "555-1"
    assert c["run_id"] == rid and {m["part"]["pn"] for m in c["matches"]} >= {"100-0001", "100-0002"}
    listed = client.get("/api/checks").json()
    assert listed[0]["id"] == cid and listed[0]["verdict"]["kind"] == "exists" and listed[0]["use_pn"]

    # 3D: the new file, its alignment with an existing part, the deviation map
    b = c["matches"][0]["uid"]
    assert client.get(f"/api/checks/{cid}/mesh").content[:4] == b"PAM1"
    assert len(client.get(f"/api/checks/{cid}/align", params={"b": b}).json()["matrix"]) == 16
    assert client.get(f"/api/checks/{cid}/compare", params={"b": b}).content[:4] == b"PAC2"
    assert client.get(f"/api/checks/{cid}/compare", params={"b": "nope"}).status_code == 404

    # only STEP files, only from this app's own page
    bad = client.post("/api/checks", files={"file": ("a.txt", b"x", "text/plain")})
    assert bad.status_code == 400
    fake = client.post("/api/checks", files={"file": ("a.step", b"not a step file", "application/octet-stream")})
    assert fake.status_code == 400
    evil = client.post("/api/checks", files=files, headers={"Origin": "http://evil.example"})
    assert evil.status_code == 403
    assert client.get("/api/checks/../../etc").status_code == 404

    # samples exist only with the demo data
    assert client.get("/api/checks/samples").json() == []
    assert client.post("/api/checks/sample/motor-mount").status_code == 404

    assert client.delete(f"/api/checks/{cid}").json()["ok"]
    assert client.get(f"/api/checks/{cid}").status_code == 404

    # the same check from the command line, against the app's latest scan (exit codes for a workflow script)
    from part_audit.cli import main
    ws = str(client.app_store.ws)
    plate = scan["new"] / "api_plate.step"
    cadops.write_step(cadops.plate_with_hole(w=120.0, h=33.0, t=4.0, d=7.0), str(plate))
    (scan["new"] / "api_text.step").write_text("just text", encoding="utf-8")
    assert main(["check", str(moved), "--workspace", ws]) == 1
    assert main(["check", str(plate), "--workspace", ws, "--pn", "555-0000"]) == 0
    assert main(["check", str(plate), "--workspace", ws, "--pn", "100-0002"]) == 1
    assert main(["check", str(scan["new"] / "api_text.step"), "--workspace", ws]) == 2
    assert not any(client.app_store.ws.glob("checks/*/fingerprint"))     # the command line stores nothing


# ------------------------------------------------------------------------------------------------ shape search

def _shapes(scan, index):
    from part_audit.geometry import FingerprintCache
    from part_audit.similar import ShapeIndex
    return ShapeIndex.build(index.items, FingerprintCache(str(scan["cache"] / "fingerprints")))


def test_shape_search_ranks_the_same_shape_first_and_ignores_position(scan, index):
    shapes = _shapes(scan, index)
    assert len(shapes) == 3
    uid = next(u for u, p in scan["parts"].items() if p["pn"] == "100-0001")
    near = shapes.nearest_to(uid, k=2)
    assert scan["parts"][near[0][0]]["pn"] == "100-0002" and near[0][1] < 0.05      # the moved copy
    assert scan["parts"][near[1][0]]["pn"] == "200-0001" and near[1][1] > 0.3       # the plate
    # a new file: the same bracket twice as big is still the closest shape (size only breaks ties)
    r = _check(scan, index, cadops.uniform_scale(scan["base"], 2.0), "big_bracket.step", shapes=shapes)
    assert r["verdict"]["kind"] == "new"            # twice the size is not a unit factor: a different part
    assert [x["part"]["pn"] for x in r["similar"][:2]] in (["100-0001", "100-0002"], ["100-0002", "100-0001"])
    assert r["similar"][0]["relation"] == "similar"


def test_similar_api(client, scan):
    uid = next(p["uid"] for p in client.get("/api/runs/latest/parts", params={"q": "100-0001"}).json()["rows"])
    r = client.get(f"/api/runs/latest/similar/{uid}").json()
    assert r["available"] and r["compared"] == 2
    assert r["rows"][0]["part"]["pn"] == "100-0002" and r["rows"][0]["relation"] == "same_group"
    assert client.get("/api/runs/latest/similar/nope").status_code == 404
