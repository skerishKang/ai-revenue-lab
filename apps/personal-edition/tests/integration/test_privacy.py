import pytest
from starlette.testclient import TestClient

from app.privacy import (
    NO_INDEX_HEADERS,
    RESTRICTIVE_CACHE_HEADERS,
    no_index_response,
    private_json_response,
    restrictive_cache_response,
)


class TestNoIndexHeaders:
    def test_contains_robots_tag(self):
        assert "X-Robots-Tag" in NO_INDEX_HEADERS
        assert "noindex" in NO_INDEX_HEADERS["X-Robots-Tag"]

    def test_no_cache_control_conflict(self):
        assert "Cache-Control" not in NO_INDEX_HEADERS


class TestRestrictiveCacheHeaders:
    def test_no_store_no_cache(self):
        assert "no-store" in RESTRICTIVE_CACHE_HEADERS["Cache-Control"]
        assert "no-cache" in RESTRICTIVE_CACHE_HEADERS["Cache-Control"]
        assert "private" in RESTRICTIVE_CACHE_HEADERS["Cache-Control"]
        assert "max-age=0" in RESTRICTIVE_CACHE_HEADERS["Cache-Control"]
        assert "s-maxage=0" in RESTRICTIVE_CACHE_HEADERS["Cache-Control"]

    def test_has_pragma(self):
        assert RESTRICTIVE_CACHE_HEADERS["Pragma"] == "no-cache"

    def test_has_expires(self):
        assert RESTRICTIVE_CACHE_HEADERS["Expires"] == "0"


class TestRestrictiveCacheResponse:
    def test_returns_json_with_headers(self):
        resp = restrictive_cache_response({"status": "ok"})
        assert resp.status_code == 200
        body = resp.body
        assert b'"status"' in body
        assert b'"ok"' in body

    def test_custom_status_code(self):
        resp = restrictive_cache_response({"error": "not found"}, 404)
        assert resp.status_code == 404

    def test_no_index_header_present(self):
        resp = restrictive_cache_response({"data": 1})
        assert resp.headers.get("X-Robots-Tag") == "noindex, nofollow"

    def test_cache_control_contains_all_directives(self):
        resp = restrictive_cache_response({"data": 1})
        cc = resp.headers.get("Cache-Control", "")
        assert "no-store" in cc
        assert "no-cache" in cc
        assert "private" in cc
        assert "max-age=0" in cc
        assert "s-maxage=0" in cc

    def test_none_content(self):
        resp = restrictive_cache_response(None, 204)
        assert resp.status_code == 204


class TestNoIndexResponse:
    def test_returns_json_with_no_index(self):
        resp = no_index_response({"result": True})
        assert resp.status_code == 200
        assert resp.headers.get("X-Robots-Tag") == "noindex, nofollow"

    def test_custom_status(self):
        resp = no_index_response(None, 403)
        assert resp.status_code == 403


class TestPrivateJsonResponse:
    def test_returns_json_with_restrictive_headers(self):
        resp = private_json_response({"private": True})
        assert resp.status_code == 200
        cc = resp.headers.get("Cache-Control", "")
        assert "no-store" in cc
        assert "max-age=0" in cc
        assert resp.headers.get("X-Robots-Tag") == "noindex, nofollow"
        assert "application/json" in resp.headers.get("Content-Type", "")
