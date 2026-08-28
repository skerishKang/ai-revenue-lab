from __future__ import annotations

import re
from pathlib import Path

from app.worker_config import CONTENT_SECURITY_POLICY, PERMISSIONS_POLICY, response_headers_for_path


def _parse_csp(value: str) -> dict[str, tuple[str, ...]]:
    directives: dict[str, tuple[str, ...]] = {}
    for raw in value.split(";"):
        part = raw.strip()
        if not part:
            continue
        pieces = part.split()
        name, values = pieces[0], tuple(pieces[1:])
        assert name not in directives, f"duplicate CSP directive: {name}"
        directives[name] = values
    return directives


def test_csp_is_fail_closed_for_code_execution_and_browser_network():
    csp = _parse_csp(CONTENT_SECURITY_POLICY)

    assert csp["default-src"] == ("'self'",)
    assert csp["script-src"] == ("'self'",)
    assert csp["connect-src"] == ("'self'",)
    assert csp["base-uri"] == ("'none'",)
    assert csp["object-src"] == ("'none'",)
    assert csp["frame-src"] == ("'none'",)
    assert csp["frame-ancestors"] == ("'none'",)
    assert csp["form-action"] == ("'self'",)

    all_tokens = {token for values in csp.values() for token in values}
    assert "'unsafe-eval'" not in all_tokens
    assert "http:" not in all_tokens
    assert "https:" not in all_tokens


def test_csp_allows_only_current_static_font_dependencies_and_attachment_previews():
    csp = _parse_csp(CONTENT_SECURITY_POLICY)

    assert csp["img-src"] == ("'self'", "data:", "blob:")
    assert csp["style-src"] == (
        "'self'",
        "'unsafe-inline'",
        "https://cdn.jsdelivr.net",
        "https://fonts.googleapis.com",
    )
    assert csp["font-src"] == (
        "'self'",
        "data:",
        "https://cdn.jsdelivr.net",
        "https://fonts.gstatic.com",
    )

    # Existing inline style/runtime style assignments require style-only unsafe-inline.
    assert "'unsafe-inline'" not in csp["script-src"]
    assert "'unsafe-inline'" not in csp["connect-src"]


def test_static_markup_is_compatible_with_self_only_script_policy():
    root = Path(__file__).resolve().parents[1]
    html = (root / "static/index.html").read_text(encoding="utf-8")

    script_tags = re.findall(r"<script\b([^>]*)>", html, flags=re.IGNORECASE)
    assert script_tags
    assert all(re.search(r"\bsrc\s*=", attrs, flags=re.IGNORECASE) for attrs in script_tags)
    assert re.search(r"<style\b", html, flags=re.IGNORECASE)
    assert not re.search(r"\son[a-z]+\s*=", html, flags=re.IGNORECASE)


def test_permissions_policy_denies_unshipped_sensitive_capabilities():
    assert PERMISSIONS_POLICY == "camera=(), microphone=(), geolocation=()"
    headers = response_headers_for_path("/")
    assert headers["Permissions-Policy"] == PERMISSIONS_POLICY
    assert headers["Content-Security-Policy"] == CONTENT_SECURITY_POLICY


def test_api_and_auth_no_store_remains_additive_to_security_policy():
    for path in ("/api/chat", "/api/auth/status", "/auth/google/callback", "/health"):
        headers = response_headers_for_path(path)
        assert headers["Cache-Control"] == "no-store"
        assert headers["Content-Security-Policy"] == CONTENT_SECURITY_POLICY
        assert headers["Permissions-Policy"] == PERMISSIONS_POLICY
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["Referrer-Policy"] == "no-referrer"
