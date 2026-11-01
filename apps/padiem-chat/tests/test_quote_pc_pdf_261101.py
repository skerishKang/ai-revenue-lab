"""Owner-scoped PDF proxy: fail safely while keeping the XLSX separate."""
from types import SimpleNamespace

import httpx
import pytest
from starlette.requests import Request

from app import b66_pc_template_routes as routes


def make_request(transport, query="file_id=file_" + "a" * 32):
    client = SimpleNamespace(
        ready=True, origin="https://file.example.test", _transport=transport,
        read_ticket=lambda uid: ({"X-Padiem-File-Ticket": uid}, 0),
    )
    app = SimpleNamespace(state=SimpleNamespace(file_lane_client=client))
    return Request({"type": "http", "method": "GET", "path": "/api/b66/pc-quote/pdf",
                    "query_string": query.encode(), "headers": [], "app": app})


@pytest.mark.asyncio
async def test_pdf_proxy_uses_authenticated_owner_ticket(monkeypatch):
    monkeypatch.setattr(routes, "_owner", lambda request: "synthetic-owner")
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(200, content=b"%PDF-1.7\nsynthetic")
    response = await routes.pc_quote_pdf(make_request(httpx.MockTransport(handle)))
    assert response.status_code == 200 and response.body.startswith(b"%PDF-")
    assert seen[0].headers["X-Padiem-File-Ticket"] == "synthetic-owner"
    assert seen[0].url.path.endswith("/pdf")


@pytest.mark.asyncio
async def test_pdf_proxy_returns_unavailable_without_disclosing_error(monkeypatch):
    monkeypatch.setattr(routes, "_owner", lambda request: "synthetic-owner")
    transport = httpx.MockTransport(lambda _: httpx.Response(503, json={"error": "internal"}))
    response = await routes.pc_quote_pdf(make_request(transport))
    assert response.status_code == 503
    assert b"internal" not in response.body
    invalid = await routes.pc_quote_pdf(make_request(transport, "file_id=../other"))
    assert invalid.status_code == 404
