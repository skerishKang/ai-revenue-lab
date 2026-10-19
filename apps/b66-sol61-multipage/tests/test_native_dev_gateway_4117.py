"""#4117 Windows loopback actual native PDF proof, never deployed."""
from __future__ import annotations

import hashlib
import http.client
import importlib.util
import json
import sys
import threading
from pathlib import Path

import pytest
from pypdf import PdfReader
from io import BytesIO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from native_dev_gateway import create_dev_server


@pytest.fixture(scope="module")
def server():
    httpd, token = create_dev_server(0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd, token
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


def call(server, method, path, payload=None, *, headers=None):
    httpd, token = server
    conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=30)
    request_headers = {"Host": f"127.0.0.1:{httpd.server_port}",
                       "Origin": f"http://127.0.0.1:{httpd.server_port}",
                       "X-B66-Dev-Token": token, "Content-Type": "application/json"}
    request_headers.update(headers or {})
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    conn.request(method, path, body, headers=request_headers)
    response = conn.getresponse()
    data = response.read()
    result = response.status, dict(response.getheaders()), data
    conn.close()
    return result


def changes(n):
    return {"changes": {
        "recipient": "목포대학교", "project": "통신공사 검증용",
        "issueDate": "2022-06-21", "quoteNo": "LOCAL-DEV-PROOF",
        "items": [
            {"name": f"검증품목 {i+1}", "spec": "규격", "unit": "식",
             "qty": 1, "unitPrice": (i + 1) * 100000, "note": ""}
            for i in range(n)
        ],
    }}


@pytest.mark.parametrize("n,expected_pages", [(1, 1), (4, 2)])
def test_4117_dev_http_returns_real_native_sol_pdf_bytes(server, n, expected_pages):
    status, headers, data = call(server, "POST", "/dev/render", changes(n))
    assert status == 200
    assert headers["Content-Type"] == "application/pdf"
    assert headers["X-B66-Dev-Release"] == "NOT_CERTIFIED"
    assert headers["Cache-Control"] == "no-store"
    assert "X-B66-Sol-Certificate-Sha256" not in headers
    assert "X-B66-Sol-Renderer" not in headers
    assert data.startswith(b"%PDF-")
    assert len(PdfReader(BytesIO(data), strict=True).pages) == expected_pages
    assert headers["X-B66-Dev-Pdf-Sha256"] == hashlib.sha256(data).hexdigest()
    assert headers["X-B66-Dev-Pages"] == str(expected_pages)


@pytest.mark.parametrize("headers", [
    {"X-B66-Dev-Token": "wrong"},
    {"Origin": "https://remote.example"},
    {"Host": "attacker.example"},
])
def test_4117_dev_server_rejects_remote_or_unauthorized_requests(server, headers):
    status, response, _ = call(server, "POST", "/dev/render", changes(1), headers=headers)
    assert status in (403, 404)
    assert response["X-B66-Dev-Release"] == "NOT_CERTIFIED"


@pytest.mark.parametrize("payload", [
    {"render_model": {}},
    {"changes": {"items": []}},
    {"changes": {"items": [{"name": "bad", "qty": -1, "unitPrice": 20}]}},
    {"changes": {"items": [{"name": "bad", "qty": 1, "unitPrice": 20}], "totals": {"grand": 42}}},
])
def test_4117_dev_server_fail_closed_on_untrusted_payload(server, payload):
    status, _headers, data = call(server, "POST", "/dev/render", payload)
    assert status in (413, 422)
    assert not data.startswith(b"%PDF-")


def test_4117_dev_server_explicit_loopback_only_and_untrusted_html(server):
    with pytest.raises(ValueError, match="loopback_only"):
        create_dev_server(0, host="0.0.0.0")
    status, headers, data = call(server, "GET", "/")
    assert status == 200
    assert headers["X-B66-Dev-Release"] == "NOT_CERTIFIED"
    assert b"__DEV_TOKEN__" not in data
    assert b"Google Drive API" in data
    assert b"NOT_CERTIFIED" in data


def test_4117_dev_health_no_customer_certification(server):
    status, _headers, data = call(server, "GET", "/health")
    assert status == 200
    assert json.loads(data) == {"ok": True, "release": "NOT_CERTIFIED"}
