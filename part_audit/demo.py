"""The built-in demo environment: source configurations pointing at the local simulators."""
from __future__ import annotations

from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent.parent / "demo" / "factory"
DEMO_LOGIN = {"username": "demo", "password": "demo123"}


def demo_sources(base_url: str, factory_dir: str | Path = DEMO_DIR, include_alt_erps: bool = True) -> list[dict]:
    """Source configurations for the demo group (4 sites, legacy folder, ERP). base_url = this app's URL."""
    u = base_url.rstrip("/")
    f = Path(factory_dir)
    src = [
        {"id": "center-pdm", "kind": "swpdm_web", "name": "SOLIDWORKS PDM – אתר מרכז", "simulated": True, "enabled": True,
         "config": {"base_url": f"{u}/sim/swpdm/api/", "vault": "EngVault", **DEMO_LOGIN}},
        {"id": "north-vault", "kind": "vault", "name": "Autodesk Vault – אתר צפון", "simulated": True, "enabled": True,
         "config": {"server_url": f"{u}/sim/vault", "vault": "Vault-North", **DEMO_LOGIN}},
        {"id": "hq-windchill", "kind": "windchill", "name": "PTC Windchill – מטה", "simulated": True, "enabled": True,
         "config": {"base_url": f"{u}/sim/windchill/Windchill/servlet/odata", **DEMO_LOGIN}},
        {"id": "south-tc", "kind": "teamcenter", "name": "Siemens Teamcenter – אתר דרום", "simulated": True,
         "enabled": True, "config": {"base_url": f"{u}/sim/teamcenter/tc", **DEMO_LOGIN}},
        {"id": "archive", "kind": "folder", "name": "ארכיון קבצים ישן (תיקיית רשת)", "simulated": False, "enabled": True,
         "config": {"path": str(f / "archive")}},
        {"id": "erp-priority", "kind": "priority", "name": "Priority ERP", "simulated": True, "enabled": True,
         "config": {"service_root": f"{u}/sim/priority/odata/Priority/tabula.ini/demo", **DEMO_LOGIN}},
    ]
    if include_alt_erps:  # the same ERP data behind other ERP interfaces, off by default (one ERP per company)
        src += [
            {"id": "erp-sap-s4", "kind": "sap_s4", "name": "SAP S/4HANA (חלופה)", "simulated": True, "enabled": False,
             "config": {"host": u, "base_path": "/sim/s4/sap/opu/odata/sap", **DEMO_LOGIN}},
            {"id": "erp-sap-b1", "kind": "sap_b1", "name": "SAP Business One (חלופה)", "simulated": True, "enabled": False,
             "config": {"base_url": f"{u}/sim/b1/b1s/v1", "company_db": "SBODEMO_IL", "supplier_field": "U_Supplier",
                        **DEMO_LOGIN}},
        ]
    return src
