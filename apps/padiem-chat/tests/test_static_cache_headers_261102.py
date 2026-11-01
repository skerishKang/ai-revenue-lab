"""#6460 4-1: static answers carry the session cache window, HTML does not.

The static URLs are not content-versioned, so the fresh window is short
(300s) with background revalidation instead of an immutable lifetime that
would pin a stale UI after a deploy.
"""
from starlette.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="unit-test-client.apps.googleusercontent.com",
        google_client_secret="unit-test-secret",
        session_secret="static-cache-header-test-secret-000000000000",
        session_max_age_seconds=3600,
    )


def _client() -> TestClient:
    return TestClient(create_app(settings=_settings()))


def test_static_script_and_style_carry_the_session_cache_window():
    client = _client()
    for path in ("/app.js", "/locale.js", "/util-menu.js", "/util-menu.css"):
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code)
        assert response.headers["cache-control"] == (
            "private, max-age=300, stale-while-revalidate=604800"
        ), path


def test_the_html_entry_is_not_static_cached():
    client = _client()
    home = client.get("/")
    assert home.status_code == 200
    assert "stale-while-revalidate=604800" not in home.headers.get("cache-control", "")
