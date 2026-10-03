"""Read-only connectors: the write guard (no network needed) and a full read against the API simulators
(runs when the demo factory is present: it ships with the app, or rebuild it with tools/factory/build.py)."""
import pytest

from part_audit import connectors
from part_audit.connectors.http import ReadOnlyHttp, WriteBlocked
from part_audit.demo import DEMO_DIR, demo_sources

REST_KINDS = ("swpdm_web", "vault", "windchill", "teamcenter", "priority", "sap_s4", "sap_b1")


def _connector(src, tmp_path):
    C = connectors.get(src["kind"])
    return C(src["id"], src["name"], src["config"], tmp_path)


@pytest.mark.parametrize("kind", REST_KINDS)
def test_write_requests_never_leave_the_machine(kind, tmp_path):
    src = next(s for s in demo_sources("http://127.0.0.1:9") if s["kind"] == kind)
    h = _connector(src, tmp_path)._http()
    for method in ("PUT", "PATCH", "DELETE", "POST"):
        with pytest.raises(WriteBlocked):
            h.request(method, "Parts('X')")          # blocked before any connection is attempted
    assert h.calls == 0


def test_only_listed_calls_pass_the_guard():
    h = ReadOnlyHttp("http://127.0.0.1:9/b1s/v1/", allowed=[("POST", r"/Login$"), ("POST", r"/Logout$")])
    h._check("GET", h.url("Items"))
    h._check("POST", h.url("Login"))
    with pytest.raises(WriteBlocked):
        h._check("POST", h.url("Items"))
    with pytest.raises(WriteBlocked):
        h._check("PATCH", h.url("Items('A1')"))
    with pytest.raises(WriteBlocked):
        h._check("POST", h.url("Login/../Items"))   # the allow-list is anchored on the path end


needs_factory = pytest.mark.skipif(not (DEMO_DIR / "factory.json").exists(), reason="demo factory not built")


@pytest.fixture(scope="module")
def sim_url():
    from part_audit.simulators import ServerThread, create_sim_app
    with ServerThread(create_sim_app(DEMO_DIR)) as srv:
        yield srv.url


@needs_factory
@pytest.mark.parametrize("sid", ["center-pdm", "north-vault", "hq-windchill", "south-tc", "archive", "erp-priority",
                                 "erp-sap-s4", "erp-sap-b1"])
def test_connector_reads_its_simulator(sid, sim_url, tmp_path):
    src = next(s for s in demo_sources(sim_url) if s["id"] == sid)
    con = _connector(src, tmp_path)
    t = con.test()
    assert t["ok"], t
    got = con.collect()
    assert not got.errors
    if con.role == "erp":
        assert len(got.erp_items) > 100
        assert all(e.pn for e in got.erp_items)
        assert any(e.stock_total > 0 and e.unit_cost for e in got.erp_items)
    else:
        assert len(got.records) > 20
        parts = [r for r in got.records if r.kind == "part"]
        assert all(r.uid.startswith(sid + ":") for r in got.records)
        with_step = [r for r in parts if r.step_path]
        assert len(with_step) > 0.5 * len(parts)
        assert sum(1 for r in parts if r.pn) > 0.8 * len(parts) or sid == "archive"
