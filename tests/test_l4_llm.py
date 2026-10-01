"""L4: optional LLM hook - off by default, local-only by default, sends only candidate names."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from part_audit.audit import AuditConfig, run_audit
from part_audit.llm import explain_mappings, is_local
from tests.test_report import _folder


class _Fake(BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Fake.seen.append(body)
        out = json.dumps({"choices": [{"message": {"content": "Same bracket saved under two numbers."}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def test_is_local():
    assert is_local("http://localhost:11434/v1") and is_local("http://127.0.0.1:8000/v1")
    assert not is_local("https://api.example.com/v1")


def test_off_by_default_and_remote_refused(tmp_path):
    root, erp = _folder(tmp_path)
    res = run_audit(AuditConfig(root=str(root), erp_csv=str(erp), use_geometry=False, verbose=False))
    assert res.llm_notes == {} and res.config.llm_endpoint is None
    with pytest.raises(ValueError):
        explain_mappings(res, "https://api.example.com/v1", "m")


def test_local_endpoint_gets_names_only(tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), _Fake)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        root, erp = _folder(tmp_path)
        cfg = AuditConfig(root=str(root), erp_csv=str(erp), use_geometry=False, verbose=False,
                          llm_endpoint=f"http://127.0.0.1:{srv.server_port}/v1", llm_model="local")
        res = run_audit(cfg)
        assert res.llm_notes["mapping"] == {0: "Same bracket saved under two numbers."}
        sent = json.dumps(_Fake.seen, ensure_ascii=False)
        assert "PA-20871" in sent and "ISO-10303" not in sent and str(root) not in sent
    finally:
        srv.shutdown()
