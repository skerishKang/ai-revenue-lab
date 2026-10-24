"""#5568 PDF to Markdown utility — the original-PDF preview frame policy.

The util page previews the owner's original PDF by framing
``/api/document-conversions/items/{item_id}/original``. The worker applies
``response_headers_for_path`` to every response, so that policy function is the
only place a frame exception can live: a route-level ``SAMEORIGIN`` header is
overwritten before the response leaves the worker. These tests pin the exact
exception shape and prove every other path keeps the strict deny-all default.
"""

from __future__ import annotations

import pytest

from app.worker_config import response_headers_for_path


ORIGINAL_PATH = "/api/document-conversions/items/dci_be4cb85394134b8dbdd81886dae0682a/original"


def test_original_preview_path_may_be_framed_by_its_own_origin():
    headers = response_headers_for_path(ORIGINAL_PATH)
    assert headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" not in headers["Content-Security-Policy"]


def test_original_preview_path_keeps_every_other_directive_and_no_store():
    headers = response_headers_for_path(ORIGINAL_PATH)
    strict = response_headers_for_path("/")
    for name, value in strict.items():
        if name in {"X-Frame-Options", "Content-Security-Policy"}:
            continue
        assert headers[name] == value
    assert headers["Cache-Control"] == "no-store"
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert "default-src 'self'" in headers["Content-Security-Policy"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/document-conversions",
        "/api/document-conversions/items",
        "/api/document-conversions/items/",
        "/api/document-conversions/items/dci_abc123",
        "/api/document-conversions/items/dci_abc123/original/extra",
        "/api/document-conversions/items/../admin/original",
        "/api/document-conversions/items/dci_abc123/markdown",
        "/api/document-conversions/unknown/original",
        "//evil.example.test/api/document-conversions/items/dci_abc123/original",
        "/health",
        "/util-pdfmd.js",
    ],
)
def test_every_other_path_keeps_the_deny_all_frame_default(path):
    headers = response_headers_for_path(path)
    assert headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]


async def test_item_id_shape_matches_the_route_contract():
    """New work is paused (#5711); the pinned item-id frame shape still holds."""
    from test_5568_document_convert_routes import build_client

    client, _app = await build_client()
    try:
        blocked = await client.post("/api/document-conversions", json={"mode": "fast"})
        assert blocked.status_code == 503
        assert blocked.json()["error"]["code"] == "pdfmd_migration_paused"
    finally:
        await client.aclose()

    # A pinned route item id keeps the preview frame exception while paused.
    headers = response_headers_for_path(ORIGINAL_PATH)
    assert headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in headers["Content-Security-Policy"]
