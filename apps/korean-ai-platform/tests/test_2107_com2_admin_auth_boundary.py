"""Authentication boundary for the COM2-only B14 admin routes."""
import pytest
from starlette.testclient import TestClient
from app.local_runtime import create_local_app

@pytest.mark.no_b14_service_proof
def test_every_local_admin_route_requires_service_proof():
    routes = [
        ("GET", "/com2/admin/secrets"), ("POST", "/com2/admin/secrets"),
        ("POST", "/com2/admin/secrets/delete"), ("GET", "/com2/admin/providers/new"),
        ("POST", "/com2/admin/providers"), ("POST", "/com2/admin/providers/test"),
    ]
    with TestClient(create_local_app()) as client:
        for method, path in routes:
            response = client.request(method, path)
            assert response.status_code == 401, (method, path, response.status_code)
            assert response.json()["error"]["code"] == "b14_service_proof_required"

def test_local_admin_accepts_existing_signed_caller():
    with TestClient(create_local_app()) as client:
        assert client.get("/com2/admin/secrets").status_code == 200

def test_local_service_state_paths_match_systemd():
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    unit = (root / "deploy/host-com2/b14/padiem-b14.service.example").read_text(encoding="utf-8")
    assert "User=padiem-b14" in unit and "Group=padiem-b14" in unit
    assert "Environment=B14_HOST=127.0.0.1" in unit and "Environment=B14_PORT=8789" in unit
    assert "StateDirectory=padiem-b14/b14-secrets padiem-b14/b14-registry" in unit
    assert "StateDirectoryMode=0700" in unit
    assert "Environment=B14_SECRET_DIR=/var/lib/padiem-b14/b14-secrets" in unit
    assert "Environment=B14_REGISTRY_PATH=/var/lib/padiem-b14/b14-registry/b14_models.json" in unit
