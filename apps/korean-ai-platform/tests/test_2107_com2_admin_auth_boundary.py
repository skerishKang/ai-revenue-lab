"""Security boundary for the separate local B14 management app."""
import os
from pathlib import Path
import re
import pytest
from starlette.testclient import TestClient
from app.com2_admin_runtime import create_admin_app
from app.local_runtime import create_local_app
from app.factory import create_app

TEST_TOKEN = "synthetic-" + "a" * 48
BASE = "http://127.0.0.1:8781"

@pytest.fixture
def admin_token(tmp_path, monkeypatch):
    path = tmp_path / "admin-token"
    path.write_text(TEST_TOKEN, encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setenv("B14_ADMIN_TOKEN_FILE", str(path))
    return path

def test_missing_or_unsafe_token_file_fails_startup(tmp_path, monkeypatch):
    path = tmp_path / "missing"
    monkeypatch.setenv("B14_ADMIN_TOKEN_FILE", str(path))
    with pytest.raises(RuntimeError):
        create_admin_app()
    if os.name == "posix":
        path.write_text(TEST_TOKEN, encoding="utf-8")
        path.chmod(0o644)
        with pytest.raises(RuntimeError):
            create_admin_app()

def test_login_required_wrong_token_and_session_cookie(admin_token):
    with TestClient(create_admin_app(), base_url=BASE) as client:
        assert client.get("/com2/admin/secrets").status_code == 401
        bad = client.post("/login", data={"token": "wrong"}, follow_redirects=False)
        assert bad.status_code == 401
        assert client.get("/com2/admin/secrets").status_code == 401
        ok = client.post("/login", data={"token": TEST_TOKEN}, follow_redirects=False)
        assert ok.status_code == 303
        cookie = ok.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie
        page = client.get("/com2/admin/secrets")
        assert page.status_code == 200
        assert TEST_TOKEN not in page.text and TEST_TOKEN not in str(ok.headers)
        assert re.search(r'name="csrf_token" value="[^"]+"', page.text)

def test_missing_csrf_denied_for_each_state_change(admin_token):
    with TestClient(create_admin_app(), base_url=BASE) as client:
        client.post("/login", data={"token": TEST_TOKEN})
        for path in ("/com2/admin/secrets", "/com2/admin/secrets/delete",
                     "/com2/admin/providers", "/com2/admin/providers/test"):
            assert client.post(path, data={}, follow_redirects=False).status_code == 403

def test_untrusted_host_and_cross_origin_login_rejected(admin_token):
    with TestClient(create_admin_app(), base_url=BASE) as client:
        assert client.get("/login", headers={"host": "attacker.example:8781"}).status_code == 400
        assert client.post("/login", data={"token": TEST_TOKEN}, headers={"origin":"https://attacker.example"}).status_code == 403

def test_main_and_worker_do_not_mount_management():
    paths = ("/com2/admin/secrets", "/com2/admin/secrets/delete", "/com2/admin/providers",
             "/com2/admin/providers/new", "/com2/admin/providers/test")
    for app in (create_local_app(), create_app()):
        with TestClient(app) as client:
            for path in paths:
                assert client.get(path).status_code == 404
                assert client.post(path).status_code == 404

def test_unit_fixed_loopback_and_tunnel_examples_exclude_admin():
    root = Path(__file__).resolve().parents[3]
    entry = (root / "apps/korean-ai-platform/admin_asgi.py").read_text(encoding="utf-8")
    assert 'host="127.0.0.1", port=8781' in entry and '0.0.0.0' not in entry
    unit = (root / "deploy/host-com2/b14/padiem-b14-admin.service.example").read_text(encoding="utf-8")
    assert "User=padiem-b14" in unit and "admin_asgi.py" in unit
    assert "admin-token" in unit and "8781" not in unit
    examples = [p for p in (root / "deploy/host-com2").rglob("*")
                if p.is_file() and ("cloudflared" in p.name.lower() or "tunnel" in p.name.lower())
                and p.suffix.lower() in (".yml", ".yaml", ".json", ".jsonc", ".toml", ".example")]
    assert examples
    for example in examples:
        assert not re.search(r"(?<!\d)8781(?!\d)", example.read_text(encoding="utf-8")), str(example)
