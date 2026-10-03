"""Local simulators of PDM/PLM/ERP APIs, serving the demo factory (for demos and tests).

They imitate the request/response shapes documented by the vendors (see docs/research/) so the
real connectors can be exercised end to end without access to a customer's systems. They are
not the vendors' software and implement only the read calls the connectors use.
"""
from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

from fastapi import FastAPI

SIMULATORS = {
    "swpdm": "SOLIDWORKS PDM Web API",
    "vault": "Autodesk Vault Data API",
    "windchill": "PTC Windchill REST Services",
    "teamcenter": "Siemens Teamcenter JSON REST",
    "priority": "Priority ERP REST (OData)",
    "s4": "SAP S/4HANA OData",
    "b1": "SAP Business One Service Layer",
}


def mount_simulators(app: FastAPI, factory_dir: str | Path) -> None:
    from . import priority, sap_b1, sap_s4, swpdm, teamcenter, vault, windchill
    root = str(Path(factory_dir).resolve())
    for mod in (swpdm, vault, windchill, teamcenter, priority, sap_s4, sap_b1):
        app.include_router(mod.router(root))


def create_sim_app(factory_dir: str | Path) -> FastAPI:
    app = FastAPI(title="Part Audit – simulators")
    mount_simulators(app, factory_dir)
    return app


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerThread:
    """Run an ASGI app with uvicorn in a background thread (tests, demo)."""

    def __init__(self, app, port: int | None = None, host: str = "127.0.0.1"):
        import uvicorn
        self.port = port or free_port()
        self.host = host
        self.server = uvicorn.Server(uvicorn.Config(app, host=host, port=self.port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def __enter__(self):
        self.thread.start()
        t0 = time.time()
        while not self.server.started:
            if time.time() - t0 > 20:
                raise RuntimeError("server did not start")
            time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=10)
