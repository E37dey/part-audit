"""End to end on a small plant: a folder of STEP files + an ERP export, through the pipeline, the decisions, the
Excel export and the local web API (no simulators involved)."""
import json
import random
import shutil
import time

import pytest

pytest.importorskip("OCP")
pytest.importorskip("fastapi")

import cadops  # noqa: E402  (tools/cadops.py)
from part_audit.decisions import effective_mapping  # noqa: E402
from part_audit.excel_he import write_workbook  # noqa: E402
from part_audit.project import ProjectSettings, audit_snapshot, collect  # noqa: E402

ERP_CSV = """מק"ט,תיאור,מלאי,עלות,סטטוס,חומר
100-0001,תושבת פלדה,10,50,פעיל,פלדה
100-0002,BRACKET STEEL,5,48,פעיל,STEEL
100-0003,תושבת עם חור,2,55,פעיל,פלדה
200-0001,פלטה אלומיניום,3,20,פעיל,אלומיניום
999-9999,פריט ללא מודל,7,5,פעיל,
"""


@pytest.fixture(scope="module")
def plant(tmp_path_factory):
    root = tmp_path_factory.mktemp("plant")
    cad = root / "cad"
    (cad / "old").mkdir(parents=True)
    base = cadops.chiral_test_part()
    rng = random.Random(4)
    cadops.write_step(base, str(cad / "100-0001 - תושבת.step"))
    cadops.write_step(cadops.transform(base, cadops.random_rigid(rng)), str(cad / "100-0002 - BRACKET.step"))
    hole, _ = cadops.drill_hole(base, random.Random(2), 0.08)
    cadops.write_step(hole, str(cad / "100-0003 - תושבת עם חור.step"))
    cadops.write_step(cadops.plate_with_hole(), str(cad / "200-0001 - פלטה.step"))
    shutil.copy(cad / "100-0001 - תושבת.step", cad / "old" / "100-0001_revA.stp")
    (cad / "old" / "מסגרת.dwg").write_bytes(b"AC1027")
    (cad / "broken.step").write_text("ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n")
    (root / "erp.csv").write_text(ERP_CSV, encoding="utf-8")
    return root


def _sources(plant):
    return [{"id": "cad", "kind": "folder", "name": "תיקיית CAD", "config": {"path": str(plant / "cad")}, "enabled": True},
            {"id": "erp", "kind": "erp_file", "name": "ERP", "config": {"path": str(plant / "erp.csv")}, "enabled": True}]


@pytest.fixture(scope="module")
def result(plant, tmp_path_factory):
    cache = tmp_path_factory.mktemp("cache")
    snap = collect(_sources(plant), cache)
    return audit_snapshot(snap, ProjectSettings(workers=1), cache)


def _uid(res, pn, contains=""):
    return next(p["uid"] for p in res["parts"] if p["pn"] == pn and contains in p["uid"])


def test_pipeline_finds_the_duplicate_and_the_near_part(result):
    s = result["summary"]
    assert s["parts"] == 6 and s["erp_items"] == 5
    by_pns = {tuple(g["pns"]): g for g in result["groups"]}
    g = by_pns[("100-0001", "100-0002")]
    assert g["category"] == "geometry"
    assert g["master_pn"] == "100-0001"                           # more stock, same state -> stays
    assert len(g["members"]) == 3                                  # the old copy with the same PN joins the group
    assert g["redundant_pns"] == 1 and g["redundant_stock_value"] == pytest.approx(5 * 48)
    near = [p for p in result["pairs"] if p["category"] == "near_identical"]
    pns = {(result["parts"][[q["uid"] for q in result["parts"]].index(p["a"])]["pn"],
            result["parts"][[q["uid"] for q in result["parts"]].index(p["b"])]["pn"]) for p in near}
    assert any("100-0003" in x for x in pns)
    assert not any("200-0001" in g["pns"] for g in result["groups"])


def test_mapping_has_only_real_part_number_changes(result):
    rows = result["mapping"]
    assert [(m["old_pn"], m["new_pn"]) for m in rows] == [("100-0002", "100-0001")]


def test_quality_findings(result):
    types = {q["type"] for q in result["quality"] + result["erp_issues"]}
    assert "erp_without_cad" in types                            # 999-9999 has no model
    assert any(x["reason"] for x in result["skipped"])            # the .dwg is listed as skipped
    assert "geometry_error" in types                              # the broken STEP file is reported


def test_engineer_can_choose_another_target(result):
    g = next(x for x in result["groups"] if "100-0002" in x["pns"])
    other = _uid(result, "100-0002")
    dec = {f"group:{g['id']}": {"decision": "approve", "master_uid": other, "user": "דנה", "note": "", "created": ""}}
    rows = effective_mapping(result, dec)
    assert [(m["old_pn"], m["new_pn"]) for m in rows] == [("100-0001", "100-0002")]
    assert rows[0]["target_overridden"] and rows[0]["id"] != result["mapping"][0]["id"]


def test_excel_is_hebrew_rtl_and_carries_decisions(result, tmp_path):
    from openpyxl import load_workbook
    m = result["mapping"][0]
    dec = {f"mapping:{m['id']}": {"decision": "approve", "user": "דנה", "note": "נבדק", "created": "2026-10-04T10:00:00",
                                  "master_uid": ""}}
    out = write_workbook(result, dec, tmp_path / "r.xlsx", demo=False, user="דנה")
    wb = load_workbook(out)
    assert all(ws.sheet_view.rightToLeft for ws in wb.worksheets)
    ws = wb['מיפוי מק"טים']
    row = [c.value for c in ws[3]]
    assert row[1] == "100-0002" and row[4] == "100-0001" and row[11] == "מאושר" and row[12] == "דנה"


# ------------------------------------------------------------------------------------------------ web API

@pytest.fixture(scope="module")
def client(plant, tmp_path_factory):
    from fastapi.testclient import TestClient
    from part_audit.server.app import create_app
    app = create_app(tmp_path_factory.mktemp("ws"), factory_dir=None, demo=False)
    with TestClient(app) as c:
        yield c


def _scan(client):
    jid = client.post("/api/scan").json()["job_id"]
    for _ in range(600):
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.2)
    raise AssertionError("scan did not finish")


def test_api_flow(client, plant):
    st = client.get("/api/status").json()
    assert st["demo_available"] is False and st["latest_run"] is None
    assert client.get("/api/runs/latest/summary").status_code == 404
    for s in _sources(plant):
        sid = client.post("/api/sources", json=s).json()["id"]
        t = client.post(f"/api/sources/{sid}/test").json()
        assert t["ok"], t
    j = _scan(client)
    assert j["status"] == "done", j.get("error")
    summ = client.get("/api/runs/latest/summary").json()
    assert summ["summary"]["groups"] == 1 and summ["decisions"]["pending_groups"] == 1
    groups = client.get("/api/runs/latest/groups").json()
    gid = groups[0]["id"]
    g = client.get(f"/api/runs/latest/groups/{gid}").json()
    assert len(g["parts"]) == 3 and g["pairs"]

    # 3D: mesh, display alignment and deviation map
    a, b = g["parts"][0]["uid"], g["parts"][1]["uid"]
    mesh = client.get(f"/api/mesh/latest/{a}")
    assert mesh.status_code == 200 and mesh.content[:4] == b"PAM1"
    al = client.get("/api/align/latest", params={"a": a, "b": b}).json()
    assert len(al["matrix"]) == 16 and al["mirror"] is False
    cmp = client.get("/api/compare/latest", params={"a": a, "b": b})
    assert cmp.content[:4] == b"PAC2"

    # decisions: a target that is not in the group is refused; a member is accepted and applied
    bad = client.post("/api/decisions", json={"target_type": "group", "target_id": gid, "decision": "approve",
                                              "master_uid": "nope"})
    assert bad.status_code == 400
    target = next(p["uid"] for p in g["parts"] if p["pn"] == "100-0002")
    ok = client.post("/api/decisions", json={"target_type": "group", "target_id": gid, "decision": "approve",
                                             "master_uid": target, "note": "בדיקה"})
    assert ok.json()["saved"] == 1
    g2 = client.get(f"/api/runs/latest/groups/{gid}").json()
    assert g2["decision"] == "approve" and g2["final_master_pn"] == "100-0002" and len(g2["history"]) == 1
    rows = client.get("/api/runs/latest/mapping").json()
    assert [(r["old_pn"], r["new_pn"], r["decision"], r.get("inherited")) for r in rows] == [("100-0001", "100-0002", "approve", True)]

    # findings, parts search and a part card
    for kind in ("names", "quality", "erp_issues"):
        assert isinstance(client.get(f"/api/runs/latest/findings/{kind}").json(), list)
    found = client.get("/api/runs/latest/parts", params={"q": "100-000"}).json()
    assert found["total"] == 4                                   # 100-0001 (two files), 100-0002, 100-0003
    card = client.get(f"/api/runs/latest/parts/{a}").json()
    assert card["uid"] == a and "issues" in card and "pairs" in card

    # export
    x = client.get(f"/api/runs/{st['latest_run'] or 'latest'}/export.xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK"

    # settings round trip, unknown keys ignored
    client.put("/api/settings", json={"user_name": "דנה", "evil": 1})
    s = client.get("/api/settings").json()
    assert s["user_name"] == "דנה" and "evil" not in s

    # the UI is served
    assert "PartAudit" in client.get("/").text


def test_passwords_are_not_returned(client):
    sid = client.post("/api/sources", json={"kind": "windchill", "name": "WC", "config": {
        "base_url": "https://plm.example/Windchill/servlet/odata", "username": "u", "password": "secret"}}).json()["id"]
    listed = json.dumps(client.get("/api/sources").json())
    assert "secret" not in listed
    client.delete(f"/api/sources/{sid}")
