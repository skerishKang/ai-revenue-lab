"""Synthetic web XLSX ingestion and owner-scoped provider fixtures."""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from io import BytesIO
import hashlib
import json
from zipfile import ZipFile

import httpx

from _support.workspace_storage_fakes import MemoryMetadata, MemoryR2
from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.file_lane import FileLaneClient
from app.workspace_storage import WorkspaceDocumentStore, XLSX_MEDIA_TYPE


ORIGIN = "https://chat.example.test"
OWNER = "usr_web_xlsx_owner"
FOREIGN = "usr_web_xlsx_other"
NOW = datetime.now(timezone.utc)


def workbook():
    out = BytesIO()
    with ZipFile(out, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>')
        z.writestr("xl/worksheets/sheet1.xml",
                   '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData/></worksheet>')
    return out.getvalue()


def harness(*, available=True):
    settings = Settings(
        session_secret="web-xlsx-e2e-test-secret", auth_mode="mock", public_base_url=ORIGIN,
    )
    metadata, r2 = MemoryMetadata(), MemoryR2()
    async def list_web_xlsx(*, tenant_id, key_prefix, now, limit=40):
        return sorted(
            [row for row in metadata.rows.values()
             if row.tenant_id == tenant_id
             and row.object_key.startswith(key_prefix)
             and row.expires_at > now],
            key=lambda row: (row.created_at, row.document_id), reverse=True,
        )[:limit]
    metadata.list_web_xlsx = list_web_xlsx
    store = WorkspaceDocumentStore(metadata, r2)
    class ReadyHistory:
        async def get_user(self, user_id):
            return None
        async def list_projects(self, user_id):
            return []
    app = create_app(settings, history_store=ReadyHistory())
    # Same composition object as D1/R2 pair; fixture only bypasses fake D1 wiring.
    app.state.workspace_document_store = store if available else None
    return app, settings, metadata, r2, store


async def request(app, settings, *, owner=OWNER, method="GET", path="/api/claw/office/web-sources",
                  payload=None, headers=None):
    h = {"Origin": ORIGIN, **(headers or {})}
    if owner:
        h["Cookie"] = SESSION_COOKIE + "=" + create_session_token(settings, owner, canonical_session_id="session_test_a")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url=ORIGIN) as c:
        if method == "GET":
            return await c.get(path, headers=h)
        if path == "/api/claw/office/web-sources" and isinstance(payload, dict) and set(payload) == {"name", "base64"}:
            try:
                raw = base64.b64decode(payload["base64"], validate=True)
            except (ValueError, base64.binascii.Error):
                raw = None
            if raw is not None:
                h["Content-Type"] = "application/octet-stream"
                h["X-Padiem-Filename"] = __import__("urllib.parse", fromlist=["quote"]).quote(payload["name"], safe="")
                return await c.post(path, headers=h, content=raw)
        return await c.post(path, headers=h, json=payload)


LANE_ORIGIN = "https://lane.example.test"
LANE_SECRET = "web-xlsx-lane-ticket-secret-0123456789abcdef"
LANE_FILE_ID = "file_" + "a" * 32
UPLOAD_TICKET = "/api/claw/office/web-sources/upload-ticket"


def register_path(file_id=LANE_FILE_ID):
    return "/api/claw/office/web-sources/" + file_id + "/register"


class FakeFileLane:
    """Owner-scoped COM2 lane double: tickets, /meta and a gated /raw stream."""

    def __init__(self):
        self.rows = {}
        self.gate = None
        self.raw_opens = 0

    def add(self, body, *, owner=OWNER, name="big.xlsx", kind="xlsx",
            file_id=LANE_FILE_ID, size_bytes=None, sha256=None):
        row = {"owner": owner, "file_id": file_id, "name": name, "kind": kind,
               "size_bytes": len(body) if size_bytes is None else size_bytes,
               "sha256": sha256 or hashlib.sha256(body).hexdigest()}
        self.rows[file_id] = (row, body)
        return row

    def client(self):
        return FileLaneClient(
            LANE_ORIGIN, LANE_SECRET, transport=httpx.MockTransport(self._handle))

    @staticmethod
    def _claim(request):
        raw = request.headers.get("x-padiem-file-ticket")
        if not raw:
            return None
        padded = raw + "=" * (-len(raw) % 4)
        try:
            claim = json.loads(base64.urlsafe_b64decode(padded))
        except (ValueError, UnicodeError):
            return None
        return claim if isinstance(claim, dict) else None

    async def _raw(self, body):
        self.raw_opens += 1
        if self.gate is None:
            yield body
            return
        yield body[:32]
        await self.gate.wait()
        yield body[32:]

    def _handle(self, request):
        claim = self._claim(request)
        parts = request.url.path.strip("/").split("/")
        found = self.rows.get(parts[1]) if len(parts) >= 2 else None
        if claim is None or found is None or found[0]["owner"] != claim.get("user_id"):
            return httpx.Response(404, json={"ok": False, "error": {"code": "not_found"}})
        row, body = found
        if parts[-1] == "meta":
            return httpx.Response(200, json={
                key: row[key] for key in ("file_id", "name", "kind", "size_bytes", "sha256")
            })
        if parts[-1] == "raw":
            return httpx.Response(200, content=self._raw(body),
                                  headers={"Content-Type": XLSX_MEDIA_TYPE})
        return httpx.Response(404, json={"ok": False, "error": {"code": "not_found"}})


async def asgi_messages(app, settings, path, *, owner=OWNER):
    """Drive the ASGI app directly: httpx's ASGITransport buffers the body."""
    messages = asyncio.Queue()
    idle = asyncio.Event()
    received = []

    async def receive():
        # Starlette keeps listening for a disconnect while streaming; returning
        # request messages in a tight loop would starve the event loop.
        if not received:
            received.append(True)
            return {"type": "http.request", "body": b"", "more_body": False}
        await idle.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        await messages.put(message)

    headers = [(b"host", b"chat.example.test"), (b"origin", ORIGIN.encode())]
    if owner:
        token = create_session_token(settings, owner, canonical_session_id="session_test_a")
        headers.append((b"cookie", (SESSION_COOKIE + "=" + token).encode()))
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "GET", "scheme": "https", "path": path, "raw_path": path.encode(),
        "query_string": b"", "headers": headers, "server": (b"chat.example.test".decode(), 443),
        "client": ("127.0.0.1", 1), "root_path": "", "state": {},
    }
    task = asyncio.create_task(app(scope, receive, send))
    return task, messages
