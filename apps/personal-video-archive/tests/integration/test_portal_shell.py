"""Integration contracts for the two-level AI Revenue Lab portal shell.

The global portal layer (AI Revenue Lab) and the Business 13 product layer
must stay semantically distinct, and portal/account destinations must follow
the PORTAL_BASE_URL configuration contract (Issue #83 / Draft PR #84).
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app import config
from app.factory import create_app

_PRIVATE_MATERIAL = re.compile(
    r"(token|api[_-]?key|uid|secret|password|invite[_-]?code)=", re.IGNORECASE
)


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "portal-shell.db")
    app = create_app(db_path=db_path)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


class TestGlobalShellDefault:
    def test_global_and_product_shell_present_korean(self, client):
        response = client.get("/")
        assert response.status_code == 200
        body = response.text
        assert 'class="portalbar"' in body
        assert 'class="productbar"' in body
        assert "AI Revenue Lab" in body
        assert "Business 13" in body
        assert "나의 영상 아카이브" in body

    def test_global_and_product_shell_present_english(self, client):
        response = client.get("/en/")
        assert response.status_code == 200
        body = response.text
        assert 'class="portalbar"' in body
        assert 'class="productbar"' in body
        assert "AI Revenue Lab" in body
        assert "Business 13" in body
        assert "Personal Video Archive" in body
        assert "All services" in body
        assert "Account" in body

    def test_absent_portal_base_renders_safe_placeholders(self, client):
        body = client.get("/").text
        assert '<span class="portal-brand"' in body
        assert '<span class="service-switcher"' in body
        assert '<span class="account-button"' in body
        assert '<a class="portal-brand"' not in body
        assert '<a class="account-button"' not in body
        assert "portal.html" not in body
        assert "account.html" not in body

    def test_global_and_product_nav_are_distinct_containers(self, client):
        body = client.get("/").text
        portal_start = body.index('class="portalbar"')
        product_start = body.index('class="productbar"')
        page_start = body.index('class="page"')
        assert portal_start < product_start < page_start
        global_block = body[portal_start:product_start]
        assert "service-switcher" in global_block
        assert "account-button" in global_block
        assert 'class="main-nav"' not in global_block
        assert 'class="main-nav"' in body[product_start:page_start]

    def test_product_nav_reference_items_korean(self, client):
        body = client.get("/").text
        for label in ("홈", "토픽", "기록", "다시 보기"):
            assert f">{label}</a>" in body, f"Missing product nav item {label}"

    def test_product_nav_reference_items_english(self, client):
        body = client.get("/en/").text
        for label in ("Home", "Topics", "Notes", "Resurface"):
            assert f">{label}</a>" in body, f"Missing product nav item {label}"

    def test_mobile_bottom_nav_is_product_local(self, client):
        body = client.get("/").text
        nav_block = body[body.index('class="mobile-nav"'):]
        assert "AI Revenue Lab" not in nav_block
        assert "service-switcher" not in nav_block
        assert "account-button" not in nav_block
        assert "다시 보기" in nav_block

    def test_no_private_material_in_shell_urls(self, client):
        assert not _PRIVATE_MATERIAL.search(client.get("/").text)
        assert not _PRIVATE_MATERIAL.search(client.get("/en/").text)


class TestConfiguredPortalBase:
    def test_https_portal_base_renders_real_links(self, client, monkeypatch):
        monkeypatch.setattr(
            config.settings, "portal_base_url", "https://portal.example.com"
        )
        body = client.get("/").text
        assert '<a class="portal-brand" href="https://portal.example.com/"' in body
        assert (
            '<a class="account-button" href="https://portal.example.com/account"'
            in body
        )
        assert "https://portal.example.com/" in body

    def test_https_portal_links_carry_no_private_material(
        self, client, monkeypatch
    ):
        monkeypatch.setattr(
            config.settings, "portal_base_url", "https://portal.example.com"
        )
        body = client.get("/").text
        assert not _PRIVATE_MATERIAL.search(body)
        for href in re.findall(r'href="(https://portal\.example\.com[^"]*)"', body):
            assert "?" not in href, f"Portal href must not carry a query: {href}"

    def test_insecure_portal_url_fails_closed(self, client, monkeypatch):
        monkeypatch.setattr(
            config.settings, "portal_base_url", "http://portal.example.com"
        )
        body = client.get("/").text
        assert "http://portal.example.com" not in body
        assert '<span class="portal-brand"' in body
        assert '<a class="portal-brand"' not in body

    def test_loopback_http_portal_allowed_for_local_dev(self, client, monkeypatch):
        monkeypatch.setattr(
            config.settings, "portal_base_url", "http://localhost:8080"
        )
        body = client.get("/").text
        assert '<a class="portal-brand" href="http://localhost:8080/"' in body
