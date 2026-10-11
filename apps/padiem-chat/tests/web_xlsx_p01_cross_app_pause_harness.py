"""#3936 cross-application harness: the REAL B62 P01 route against the REAL Engine.

This is the boundary that was never proven in Production: a signed-in owner's
web XLSX P01 start, dispatched through the B62 private Engine client, authenticated
by the Engine caller registry, and materialized by the Engine's real
``ToolExecutionEngineService`` as a durable Core approval pause.

It runs entirely offline and hermetically:

* synthetic in-memory XLSX bytes (never a customer file),
* in-memory sqlite standing in for both D1 databases (B62 + Engine continuation),
* the exact canonical Engine caller-registry overlay payload the rotation gate
  PUTs (apps/padiem-ai-engine/app/identity_enforcement.authenticate_request),
* no Cloudflare API, no model call, no Browser/PDF, no R2, no Drive/Telegram.

Two app packages are loaded in one interpreter: the Engine's ``app`` first (its
submodules use absolute ``app.*`` imports) and B62's ``app`` under the alias
``chatapp`` (B62's modules use only relative imports). That is why this harness
runs as a subprocess from ``test_3936_web_xlsx_p01_cross_app.py`` instead of
inside the pytest process.

Before the #3936 fix (the web XLSX P01 app id missing from the overlay
``allowed_app_ids``) this harness stops with Engine 403
``service_app_not_authorized`` and no continuation row; afterwards it must
report ``WEB_XLSX_P01_CROSS_APP_PAUSE=PASS``.
"""
from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import sqlite3
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

CHAT = Path(__file__).resolve().parents[1]
ROOT = CHAT.parents[1]
ENGINE = ROOT / "apps" / "padiem-ai-engine"
sys.path.insert(0, str(ENGINE))

# The Engine's ``app`` package must be imported BEFORE B62's alias below.
import app.identity_enforcement as IDENTITY  # noqa: E402
import app.tool_execution_service as ENGINE_SERVICE  # noqa: E402
import app.web_xlsx_p01_tool_binding as ENGINE_BINDING  # noqa: E402
import app.web_xlsx_p01_trusted_scope_d1 as ENGINE_SCOPE  # noqa: E402
import app.web_xlsx_tool_pending_d1 as ENGINE_PENDING  # noqa: E402
from app.approval_verifier import (  # noqa: E402
    AuthenticatedFirstPartyApprovalDecisionVerifier,
)


def _load_b62_app():
    spec = importlib.util.spec_from_file_location(
        "chatapp", CHAT / "app" / "__init__.py",
        submodule_search_locations=[str(CHAT / "app")],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["chatapp"] = module
    spec.loader.exec_module(module)
    return module


_load_b62_app()

import httpx  # noqa: E402
from chatapp.app_factory import create_app  # noqa: E402
from chatapp.auth import SESSION_COOKIE, create_session_token  # noqa: E402
from chatapp.claw_web_xlsx_p01_owner_decision import (  # noqa: E402
    D1WebXlsxP01OwnerDecisionStore,
)
from chatapp.claw_web_xlsx_p01_request import D1WebXlsxP01RequestStore  # noqa: E402
from chatapp.claw_web_xlsx_selection_store import (  # noqa: E402
    D1WebXlsxSelectionStore,
)
from chatapp.config import Settings  # noqa: E402
from chatapp.history import D1HistoryStore  # noqa: E402
from chatapp.web_xlsx_p01_engine_client import (  # noqa: E402
    CloudflareWebXlsxP01EngineClient,
)
from chatapp.workspace_storage import (  # noqa: E402
    D1ClawDocumentMetadataStore, WorkspaceDocumentStore,
)

ORIGIN = "https://chat.example.test"
OWNER = "usr_web_xlsx_owner"
WORKSPACE = "owner:" + OWNER
CALLER_ID = "b54-p01-overlay-20260914-a1"
CREDENTIAL = "cross-app-harness-credential-0000000000"
SENTINELS = (OWNER, WORKSPACE, CALLER_ID, CREDENTIAL)

MIGRATIONS = (
    "001_auth_history.sql", "002_projects.sql", "008_claw_document_metadata.sql",
    "009_claw_run_history.sql", "014_claw_run_history_conversation.sql",
    "015_claw_run_history_workspace.sql", "029_claw_web_xlsx_selection.sql",
    "030_claw_web_xlsx_p01_requests.sql",
    "031_claw_web_xlsx_p01_decision_receipts.sql",
)


class RealSQLiteD1:
    def __init__(self, conn):
        self.conn = conn

    def prepare(self, query):
        return D1Statement(self.conn, query)


class D1Statement:
    def __init__(self, conn, query):
        self.conn, self.query, self.args = conn, query, ()

    def bind(self, *args):
        self.args = args
        return self

    async def run(self):
        self.conn.execute(self.query, self.args)
        return {}

    async def first(self):
        row = self.conn.execute(self.query, self.args).fetchone()
        return dict(row) if row else None

    async def all(self):
        return [dict(row) for row in self.conn.execute(self.query, self.args).fetchall()]


class MemoryR2:
    def __init__(self):
        self.objects = {}

    async def put(self, key, body, **kwargs):
        self.objects[key] = bytes(body)

    async def get(self, key):
        body = self.objects.get(key)
        return None if body is None else SimpleNamespace(body=body)

    async def delete(self, key):
        self.objects.pop(key, None)


class FakeResponse:
    def __init__(self, status, payload: bytes):
        self.status = status
        self.body = None
        self._payload = payload

    async def text(self):
        return self._payload.decode("utf-8")


class WorkerBinding:
    """Stand-in for the Engine Service Binding: the real Engine handler runs.

    It repeats the Worker's own pre-dispatch authentication boundary
    (``worker._authenticate_non_health_request``: read the requested app id from
    the body, then ``identity_enforcement.authenticate_request``) so the Engine
    caller-registry app authority is exercised exactly as in Production.
    """

    def __init__(self, service, env):
        self.service = service
        self.env = env
        self.calls = []

    async def fetch(self, request):
        payload = json.loads(request["body"])
        headers = dict(request.get("headers") or {})
        self.calls.append({"payload": payload, "headers": headers})
        IDENTITY.authenticate_request(
            env=self.env,
            headers={
                IDENTITY.CALLER_ID_HEADER: headers.get("x-padiem-engine-caller"),
                IDENTITY.CALLER_CREDENTIAL_HEADER: headers.get(
                    "x-padiem-engine-credential"),
            },
            requested_app_id=payload.get("app_id"),
        )
        response = await self.service.execute_payload(payload)
        self.calls[-1]["engine_status"] = response.status_code
        return FakeResponse(
            response.status_code,
            json.dumps(response.body, separators=(",", ":")).encode("utf-8"),
        )


def request_stub(url, *, method, headers, body):
    return SimpleNamespace(
        js_object={"url": url, "method": method, "headers": headers, "body": body}
    )


def workbook() -> bytes:
    out = BytesIO()
    with ZipFile(out, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        z.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>',
        )
        z.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData/></worksheet>',
        )
    return out.getvalue()


def overlay_env() -> object:
    """The canonical #3936 Engine caller-registry overlay, as the gate PUTs it."""
    spec = importlib.util.spec_from_file_location(
        "b54_overlay_rotation_for_cross_app",
        ROOT / ".github/scripts/b54_engine_caller_registry_overlay_rotation.py",
    )
    assert spec is not None and spec.loader is not None
    rotation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rotation)
    overlay = rotation.build_overlay_put_body(
        rotation.build_overlay_payload(credential=CREDENTIAL)
    )["text"]
    base = {
        "version": 1,
        "callers": [
            {"caller_id": "storymemory-b61", "credential": "b" * 40,
             "allowed_app_ids": ["b61"]},
        ],
    }
    return type("Env", (), {
        IDENTITY.CALLER_REGISTRY_V1_ENV: json.dumps(base),
        IDENTITY.CALLER_REGISTRY_V1_OVERLAY_ENV: overlay,
    })()


def build_database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    for name in MIGRATIONS:
        conn.executescript(
            (CHAT / "migrations" / name).read_text(encoding="utf-8")
        )
    conn.executescript((
        ENGINE / "migrations" / "0009_web_xlsx_tool_continuations.sql"
    ).read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO users (id,auth_provider,provider_subject,email,display_name,"
        "picture_url,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
        (OWNER, "google", "owner@example", "owner@example.test", "Owner", "", now, now),
    )
    return conn


async def call(app, settings, *, method="GET", path, payload=None, owner=OWNER):
    headers = {"Origin": ORIGIN}
    if owner:
        headers["Cookie"] = SESSION_COOKIE + "=" + create_session_token(settings, owner)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url=ORIGIN) as client:
        if method == "GET":
            return await client.get(path, headers=headers)
        return await client.post(path, headers=headers, json=payload)


class HarnessFailure(AssertionError):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise HarnessFailure(message)


async def run() -> int:
    conn = build_database()
    d1 = RealSQLiteD1(conn)
    settings = Settings(session_secret="cross-app-harness-secret",
                        auth_mode="mock", public_base_url=ORIGIN)
    history = D1HistoryStore(d1)
    app = create_app(settings, history_store=history)
    r2 = MemoryR2()
    app.state.workspace_document_store = WorkspaceDocumentStore(
        D1ClawDocumentMetadataStore(d1), r2,
    )
    app.state.claw_web_xlsx_selection_store = D1WebXlsxSelectionStore(d1)
    app.state.web_xlsx_p01_request_store = D1WebXlsxP01RequestStore(d1)
    app.state.web_xlsx_p01_owner_decision_store = D1WebXlsxP01OwnerDecisionStore(d1)
    app.state.history_store = history
    events = []
    app.state.web_xlsx_p01_refusal_emitter = events.append

    # Production Engine composition (worker_identity._engine_services_for_env).
    env = overlay_env()
    resolver = ENGINE_BINDING.with_web_xlsx_p01_tool_binding(
        None, enabled=True,
        selection_resolver=ENGINE_SCOPE.D1WebXlsxTrustedScopeResolver(d1),
        approved_selection_resolver=ENGINE_SCOPE.D1WebXlsxTrustedScopeResolver(
            d1, required_status="waiting_p01",
        ),
    )
    service = ENGINE_SERVICE.ToolExecutionEngineService(
        tool_binding_resolver=resolver,
        continuation_store=ENGINE_PENDING.D1WebXlsxToolPendingStore(d1),
        approval_decision_verifier=AuthenticatedFirstPartyApprovalDecisionVerifier(),
    )
    binding = WorkerBinding(service, env)
    app.state.web_xlsx_p01_pause_client = CloudflareWebXlsxP01EngineClient(
        binding, caller_id=CALLER_ID, credential=CREDENTIAL,
        request_factory=request_stub,
    )

    # The Engine caller-registry app authority must authorize the exact app id
    # this lane sends; a foreign app id on the same caller must be refused.
    IDENTITY.authenticate_request(
        env=env,
        headers={IDENTITY.CALLER_ID_HEADER: CALLER_ID,
                 IDENTITY.CALLER_CREDENTIAL_HEADER: CREDENTIAL},
        requested_app_id=ENGINE_BINDING.APP_ID,
    )
    print("CROSS_APP_ENGINE_CALLER_AUTH=PASS")
    try:
        IDENTITY.authenticate_request(
            env=env,
            headers={IDENTITY.CALLER_ID_HEADER: CALLER_ID,
                     IDENTITY.CALLER_CREDENTIAL_HEADER: CREDENTIAL},
            requested_app_id="b62",
        )
    except IDENTITY.ServiceIdentityError as exc:
        check(exc.code == "service_app_not_authorized", str(exc.code))
        print("CROSS_APP_FOREIGN_APP_REFUSED=PASS")
    else:
        raise HarnessFailure("a foreign app id must stay unauthorized")

    source = workbook()
    upload = await call(
        app, settings, method="POST", path="/api/claw/office/web-sources",
        payload={"name": "quote.xlsx",
                 "base64": base64.b64encode(source).decode()},
    )
    check(upload.status_code == 201, f"upload {upload.status_code}")
    file = upload.json()["file"]
    check(file["original_immutable"] is True, "original must stay immutable")
    check(file["processing_authorized"] is False, "no processing grant at upload")
    print("CROSS_APP_OWNER_UPLOAD=PASS")

    download = await call(
        app, settings,
        path=f"/api/claw/office/web-sources/{file['document_id']}/download",
    )
    check(download.status_code == 200 and download.content == source,
          "original bytes must be preserved")
    print("CROSS_APP_ORIGINAL_SHA_PRESERVED=PASS")

    selection = await call(
        app, settings, method="POST", path="/api/claw/office/web-selections",
        payload={"document_id": file["document_id"]},
    )
    check(selection.status_code == 201, f"selection {selection.status_code}")
    ref = selection.json()["selection"]["selection_ref"]
    before = await call(
        app, settings, path=f"/api/claw/office/web-selections/{ref}/p01-status",
    )
    check(before.json()["status"] == "not_requested", "pre-start status")
    check(before.json()["owner_request_enabled"] is True, "request must be offered")
    print("CROSS_APP_OWNER_SELECTION=PASS")

    started = await call(
        app, settings, method="POST",
        path=f"/api/claw/office/web-selections/{ref}/start-p01", payload={},
    )
    check(started.status_code == 202,
          f"start {started.status_code} {started.text[:200]}")
    check(started.json()["status"] == "waiting_p01", "start status")
    check(started.json()["processing_started"] is False, "no processing")
    check(started.json()["workcopy_created"] is False, "no workcopy at READ consent")
    check(binding.calls and binding.calls[0]["engine_status"] == 202,
          "Engine must answer the real pause contract")
    check(binding.calls[0]["payload"]["app_id"] == "padiem-web-xlsx-p01",
          "the lane's app id must be dispatched")
    print("CROSS_APP_ENGINE_PAUSE_ISSUED=PASS")

    after = await call(
        app, settings, path=f"/api/claw/office/web-selections/{ref}/p01-status",
    )
    check(after.json()["status"] == "waiting_p01", "post-start status")
    check(after.json()["owner_decision_enabled"] in (True, False),
          "owner decision projection must be boolean")

    rows = conn.execute(
        "SELECT status, continuation_ref, pause_id FROM claw_web_xlsx_p01_requests"
    ).fetchall()
    check(len(rows) == 1 and rows[0]["status"] == "waiting_p01",
          "exactly one committed B62 request")
    check(bool(rows[0]["continuation_ref"]) and bool(rows[0]["pause_id"]),
          "Engine continuation must be recorded")
    continuations = conn.execute(
        "SELECT app_id, state FROM padiem_web_xlsx_tool_continuations"
    ).fetchall()
    check(len(continuations) == 1 and continuations[0]["state"] == "active",
          "exactly one durable Engine continuation")

    # Read consent is not a workcopy/edit grant, and the original stays intact.
    workcopies = conn.execute(
        "SELECT COUNT(*) FROM claw_document_metadata WHERE tenant_id=?",
        (WORKSPACE,),
    ).fetchone()[0]
    check(workcopies == 1, "no workcopy document may be created by READ consent")
    check(r2.objects and list(r2.objects.values())[0] == source,
          "stored original bytes must be unchanged")

    # No request material may appear in the bounded dispatch attribution.
    emitted = json.dumps(events, ensure_ascii=False)
    for sentinel in SENTINELS:
        check(sentinel not in emitted, "attribution event leaked request material")
    for row in conn.execute("SELECT request_ref, run_id FROM claw_web_xlsx_p01_requests"):
        check(row["request_ref"] not in emitted and row["run_id"] not in emitted,
              "attribution event leaked a server-issued reference")
    conn.close()

    print("CROSS_APP_B62_REQUEST_COMMITTED=PASS")
    print("CROSS_APP_ENGINE_CONTINUATION_DURABLE=PASS")
    print("CROSS_APP_DIAGNOSTIC_NO_LEAK=PASS")
    print("READ_IS_NOT_WRITE=PASS")
    print("WEB_XLSX_P01_CROSS_APP_PAUSE=PASS")
    return 0


def main() -> int:
    try:
        return asyncio.run(run())
    except HarnessFailure as exc:
        print("WEB_XLSX_P01_CROSS_APP_PAUSE=FAIL", file=sys.stderr)
        print(f"REASON={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
