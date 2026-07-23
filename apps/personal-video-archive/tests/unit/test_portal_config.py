"""Strict contracts for the PORTAL_BASE_URL configuration policy."""

from __future__ import annotations

from app.config import Settings, safe_portal_base


class TestSafePortalBase:
    def test_absent_value_returns_empty(self):
        assert safe_portal_base("") == ""
        assert safe_portal_base("   ") == ""

    def test_https_base_accepted_and_normalized(self):
        assert (
            safe_portal_base("https://portal.example.com")
            == "https://portal.example.com"
        )
        assert (
            safe_portal_base("https://portal.example.com/")
            == "https://portal.example.com"
        )
        assert (
            safe_portal_base("https://portal.example.com/base/")
            == "https://portal.example.com/base"
        )

    def test_insecure_remote_http_fails_closed(self):
        assert safe_portal_base("http://portal.example.com") == ""
        assert safe_portal_base("http://portal.example.com/") == ""

    def test_loopback_http_allowed_for_local_development(self):
        assert safe_portal_base("http://localhost:8000") == "http://localhost:8000"
        assert safe_portal_base("http://127.0.0.1:9000/") == "http://127.0.0.1:9000"

    def test_relative_garbage_and_other_schemes_rejected(self):
        assert safe_portal_base("/portal") == ""
        assert safe_portal_base("not a url") == ""
        assert safe_portal_base("ftp://portal.example.com") == ""
        assert safe_portal_base("javascript:alert(1)") == ""

    def test_embedded_credentials_rejected(self):
        assert safe_portal_base("https://user:pass@portal.example.com") == ""


class TestSettingsPortalHrefs:
    def test_configured_https_base_produces_portal_hrefs(self):
        s = Settings(portal_base_url="https://portal.example.com/")
        assert s.portal_base == "https://portal.example.com"
        assert s.portal_home_href == "https://portal.example.com/"
        assert s.portal_account_href == "https://portal.example.com/account"

    def test_absent_base_produces_empty_hrefs(self):
        s = Settings(portal_base_url="")
        assert s.portal_home_href == ""
        assert s.portal_account_href == ""

    def test_insecure_production_base_fails_closed(self):
        s = Settings(portal_base_url="http://portal.example.com")
        assert s.portal_home_href == ""
        assert s.portal_account_href == ""
