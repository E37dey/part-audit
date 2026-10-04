"""Changes between two scans, the scan schedule and the optional e-mail (no mail is sent: the SMTP class is faked)."""
import datetime as dt

import pytest

from part_audit import notify
from part_audit.changes import compare_runs
from part_audit.schedule import Scheduler, is_due, last_slot, next_slot


def _part(uid, pn, src="pdm", **kw):
    return {"uid": uid, "pn": pn, "name": kw.pop("name", f"part {pn}"), "source": "PDM", "source_id": src,
            "source_kind": "folder", "kind": "part", "state": "Released", "state_class": "released", "has_step": True,
            "volume_mm3": kw.pop("volume_mm3", 1000.0), "material": kw.pop("material", "steel"), **kw}


def _group(gid, members, pns):
    return {"id": gid, "members": members, "pns": pns, "name": f"group {gid}", "category": "geometry",
            "sources": ["PDM"], "master_pn": pns[0], "redundant_pns": len(pns) - 1, "redundant_stock_value": 10.0,
            "currency": "ILS", "spec": ""}


def _res(rid, parts, groups, quality=(), sources=None, summary=None):
    return {"run_id": rid, "created": f"2026-10-0{rid[-1]}T06:00:00", "parts": parts, "groups": groups, "pairs": [],
            "quality": list(quality), "erp_issues": [], "names": [],
            "summary": summary or {"groups": len(groups), "parts": len(parts), "currency": "ILS",
                                   "redundant_stock_value": 10.0 * len(groups)},
            "sources": sources or [{"id": "pdm", "name": "PDM", "errors": [], "stats": {"records": len(parts)}}]}


def test_new_grown_shrunk_and_resolved_groups_and_records():
    old = _res("r1", [_part("a", "1"), _part("b", "2"), _part("c", "3"), _part("d", "4"), _part("e", "5"),
                      _part("f", "6"), _part("g", "7")],
               [_group("G1", ["a", "b"], ["1", "2"]), _group("G2", ["c", "d", "e"], ["3", "4", "5"]),
                _group("G3", ["f", "g"], ["6", "7"])],
               quality=[{"type": "missing_material", "type_he": "חומר חסר", "severity": "medium", "uids": ["c"],
                         "message": "x"}])
    new = _res("r2", [_part("a", "1"), _part("b", "2"), _part("n", "8"), _part("c", "3"), _part("d", "4"),
                      _part("f", "6", name="renamed"), _part("g", "7"), _part("h", "9"), _part("k", "10")],
               [_group("G1x", ["a", "b", "n"], ["1", "2", "8"]), _group("G2x", ["c", "d"], ["3", "4"]),
                _group("G4", ["h", "k"], ["9", "10"])],
               quality=[{"type": "missing_material", "type_he": "חומר חסר", "severity": "medium", "uids": ["h"],
                         "message": "y"}])
    c = compare_runs(old, new)
    g = c["groups"]
    assert [x["id"] for x in g["new"]] == ["G4"]
    assert [x["id"] for x in g["grown"]] == ["G1x"] and g["grown"][0]["joined"][0]["new_record"]
    assert [x["id"] for x in g["shrunk"]] == ["G2x"] and g["shrunk"][0]["left"][0]["removed"]
    assert [x["id"] for x in g["resolved"]] == ["G3"] and g["resolved"][0]["how"] == "no_longer_matching"
    r = c["records"]
    assert {x["uid"] for x in r["added"]} == {"n", "h", "k"} and [x["uid"] for x in r["removed"]] == ["e"]
    assert [(x["uid"], x["changes"][0]["field"]) for x in r["changed"]] == [("f", "name")]
    q = c["findings"]["quality"]
    assert q["n_new"] == 1 and q["n_resolved"] == 1
    assert c["summary"]["groups"] == {"before": 3, "after": 3, "delta": 0}
    assert c["alert"] and c["headline"].startswith("כפילות חדשה אחת")


def test_an_unreadable_source_is_not_counted_as_removed():
    parts = [_part("a", "1"), _part("b", "2"), _part("x", "3", src="erp")]
    old = _res("r1", parts, [_group("G1", ["a", "b"], ["1", "2"])],
               sources=[{"id": "pdm", "name": "PDM", "errors": [], "stats": {"records": 2}}])
    new = _res("r2", [], [], sources=[{"id": "pdm", "name": "PDM", "errors": ["ConnectError: down"], "stats": {"records": 0}}])
    c = compare_runs(old, new)
    assert c["records"]["n_removed"] == 1 and c["records"]["n_not_read"] == 2       # only the ERP-source record
    assert c["groups"]["resolved"] == [] and c["groups"]["unknown"] == 1
    assert c["unread_sources"] == ["PDM"] and "PDM לא היה זמין" in c["headline"]


def test_money_in_two_currencies_is_not_subtracted():
    old = _res("r1", [], [], summary={"currency": "USD", "redundant_stock_value": 5.0, "groups": 0})
    new = _res("r2", [], [], summary={"currency": "ILS", "redundant_stock_value": 9.0, "groups": 0})
    c = compare_runs(old, new)
    assert c["summary"]["redundant_stock_value"]["delta"] is None
    assert c["headline"] == "לא השתנה דבר מאז הסריקה הקודמת." and not c["alert"]


# ------------------------------------------------------------------------------------------------ schedule

def test_weekly_and_daily_slots_on_the_israeli_week():
    sunday_6 = {"enabled": True, "frequency": "weekly", "weekday": 0, "time": "06:00"}
    tue = dt.datetime(2026, 10, 6, 9, 30)                     # Tuesday
    assert last_slot(sunday_6, tue) == dt.datetime(2026, 10, 4, 6, 0)            # the Sunday before
    assert next_slot(sunday_6, tue) == dt.datetime(2026, 10, 11, 6, 0)
    daily = {"enabled": True, "frequency": "daily", "time": "18:15"}
    assert last_slot(daily, tue) == dt.datetime(2026, 10, 5, 18, 15)
    assert last_slot(daily, tue.replace(hour=19)) == dt.datetime(2026, 10, 6, 18, 15)


def test_due_once_after_a_missed_time_and_not_before_it_was_turned_on():
    s = {"enabled": True, "frequency": "daily", "time": "06:00", "since": "2026-10-05T10:00:00"}
    assert not is_due(s, None, dt.datetime(2026, 10, 5, 12, 0))      # turned on after today's 06:00
    assert is_due(s, None, dt.datetime(2026, 10, 6, 7, 0))           # the next morning
    assert not is_due(s, "2026-10-06T07:00:00", dt.datetime(2026, 10, 6, 23, 0))
    assert is_due(s, "2026-10-06T07:00:00", dt.datetime(2026, 10, 9, 8, 0))      # missed days: caught up once
    assert not is_due(dict(s, enabled=False), None, dt.datetime(2026, 10, 9, 8, 0))


def test_scheduler_tick_starts_one_scan_and_remembers_it():
    state = {"last": None, "started": 0, "busy": False}
    sch = Scheduler(get_schedule=lambda: {"enabled": True, "frequency": "daily", "time": "06:00"},
                    get_last=lambda: state["last"], set_last=lambda t: state.update(last=t),
                    start_scan=lambda: not state["busy"] and bool(state.update(started=state["started"] + 1) or True))
    now = dt.datetime(2026, 10, 6, 7, 0)
    state["busy"] = True
    assert not sch.tick(now) and state["last"] is None                 # a scan is running: try again later
    state["busy"] = False
    assert sch.tick(now) and state["started"] == 1 and sch.tick(now) is False


# ------------------------------------------------------------------------------------------------ e-mail

class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout=None, **kw):
        self.host, self.port, self.calls = host, port, []

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, pw):
        self.calls.append(("login", user, pw))

    def send_message(self, msg):
        FakeSMTP.sent.append((self.host, self.port, self.calls, msg))

    def quit(self):
        pass


def test_mail_is_composed_in_hebrew_and_sent_only_to_the_configured_server(monkeypatch):
    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    FakeSMTP.sent.clear()
    old = _res("r1", [_part("a", "1"), _part("b", "2")], [])
    new = _res("r2", [_part("a", "1"), _part("b", "2")], [_group("G1", ["a", "b"], ["1", "2"])])
    ch = compare_runs(old, new)
    cfg = {**notify.DEFAULT_EMAIL, "enabled": True, "host": "mail.local", "port": 587, "user": "u", "to": "a@x.co; b@x.co"}
    assert notify.should_send(cfg, ch, "schedule") and not notify.should_send(cfg, ch, "manual")
    assert not notify.should_send(dict(cfg, enabled=False), ch, "schedule")
    subject, text, body = notify.compose(ch, new["summary"], app_url="http://127.0.0.1:8765")
    assert "שינויים" in subject and "כפילות חדשה אחת" in text and 'dir="rtl"' in body and "#/changes" in body
    notify.send(cfg, "pw", notify.build_message(cfg, subject, text, body))
    host, port, calls, msg = FakeSMTP.sent[0]
    assert (host, port) == ("mail.local", 587) and calls[:2] == ["ehlo", "starttls"] and ("login", "u", "pw") in calls
    assert msg["To"] == "a@x.co, b@x.co"
    with pytest.raises(ValueError):
        notify.send(dict(cfg, host=""), "pw", notify.build_message(cfg, subject, text, body))


# ------------------------------------------------------------------------------------------------ app + command line

@pytest.fixture
def plant(tmp_path):
    pytest.importorskip("OCP")
    import cadops
    cad = tmp_path / "cad"
    cad.mkdir()
    cadops.write_step(cadops.chiral_test_part(), str(cad / "100-0001 - תושבת.step"))
    cadops.write_step(cadops.plate_with_hole(), str(cad / "200-0001 - פלטה.step"))
    return tmp_path


def _wait(client, jid):
    import time
    for _ in range(600):
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def test_two_scans_their_changes_settings_and_the_command_line(plant, tmp_path, monkeypatch):
    import random

    import cadops
    from fastapi.testclient import TestClient

    from part_audit.cli import main
    from part_audit.server.app import create_app
    ws = tmp_path / "ws"
    with TestClient(create_app(ws, factory_dir=None, demo=False), base_url="http://127.0.0.1:8765") as client:
        client.post("/api/sources", json={"kind": "folder", "name": "CAD", "config": {"path": str(plant / "cad")}})
        assert _wait(client, client.post("/api/scan").json()["job_id"])["status"] == "done"
        first = client.get("/api/runs/latest/changes").json()
        assert first == {"available": False, "reason": "first", "to": {"run_id": first["to"]["run_id"]}}
        # someone saves a copy of the bracket under a new number
        cadops.write_step(cadops.transform(cadops.chiral_test_part(), cadops.random_rigid(random.Random(3))),
                          str(plant / "cad" / "100-0009 - תושבת חדשה.step"))
        assert _wait(client, client.post("/api/scan").json()["job_id"])["status"] == "done"
        ch = client.get("/api/runs/latest/changes").json()
        assert ch["available"] and len(ch["groups"]["new"]) == 1 and ch["records"]["n_added"] == 1
        assert ch["groups"]["new"][0]["joined"] and ch["alert"] and ch["notify"] is None     # e-mail is off
        runs = client.get("/api/runs").json()
        assert [r["trigger"] for r in runs] == ["manual", "manual"]
        assert client.get("/api/runs/latest/changes", params={"base": "../../x"}).status_code == 404
        # the engineer approves the new group; it counts from the next scan on
        gid = client.get("/api/runs/latest/groups").json()[0]["id"]
        assert client.post("/api/decisions", json={"target_type": "group", "target_id": gid, "decision": "approve"}).json()["ok"]

        # schedule and e-mail settings: checked, the password never comes back
        bad = client.put("/api/settings", json={"schedule": {"enabled": True, "frequency": "hourly"}})
        assert bad.status_code == 400
        s = client.put("/api/settings", json={"schedule": {"enabled": True, "frequency": "weekly", "weekday": 0, "time": "06:00"},
                                              "email": {"enabled": True, "host": "mail.local", "port": "587", "user": "u",
                                                        "to": "a@x.co", "password": "secret-pw"}}).json()
        assert s["schedule"]["since"] and s["schedule_info"]["next"] and s["email"]["port"] == 587
        assert s["email"]["password"] == "••••••" and "secret-pw" not in client.get("/api/settings").text
        assert "secret-pw" not in client.get("/api/status").text
        monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
        FakeSMTP.sent.clear()
        assert client.post("/api/notify/test").json() == {"ok": True, "to": ["a@x.co"]}
        assert FakeSMTP.sent[0][2][-1] == ("login", "u", "secret-pw")
        # another server: the stored password is dropped, not sent there
        s2 = client.put("/api/settings", json={"email": {"host": "other.example"}}).json()
        assert s2["email"]["password"] == ""

    # the OS scheduler's scan: same pipeline, compared with the scan before, e-mailed when turned on
    FakeSMTP.sent.clear()
    client2 = TestClient(create_app(ws, factory_dir=None, demo=False), base_url="http://127.0.0.1:8765")
    client2.put("/api/settings", json={"email": {"host": "mail.local", "password": "pw2", "on": "always"}})
    assert main(["rescan", "--workspace", str(ws)]) == 0
    runs = client2.get("/api/runs").json()
    assert runs[0]["trigger"] == "cli" and len(runs) == 3
    ch = client2.get("/api/runs/latest/changes").json()
    assert ch["headline"] == "לא השתנה דבר מאז הסריקה הקודמת."
    assert ch["notify"]["sent"] and FakeSMTP.sent and FakeSMTP.sent[0][0] == "mail.local"
    assert main(["rescan", "--workspace", str(tmp_path / "empty")]) == 2

    # trends: every scan oldest first, what changed since the one before, the decisions in effect at each
    tr = client2.get("/api/trends").json()["runs"]
    assert [r["trigger"] for r in tr] == ["manual", "manual", "cli"]
    assert [r["summary"]["groups"] for r in tr] == [0, 1, 1] and [r["summary"]["parts"] for r in tr] == [2, 3, 3]
    assert tr[0]["changes"] is None
    assert tr[1]["changes"]["new_groups"] == 1 and tr[1]["changes"]["added"] == 1 and tr[1]["changes"]["resolved_groups"] == 0
    assert tr[2]["changes"]["new_groups"] == tr[2]["changes"]["added"] == tr[2]["changes"]["removed"] == 0
    assert [r["approved_groups"] for r in tr] == [0, 0, 1]
