"""#5574 issue harness: production frontend transport over the production B62 app.

Rebuild of the corrupted prior draft. Every contract in this file was re-read
from source on this branch before writing:

* ``static/app.js`` builds ``payload.pc_run_id`` from ``await
  chatTransport.requestStreaming(payload, signal)`` and no lane internals
  are monkeypatched here.
* ``static/chat-transport.js``: ``createChatPcRunId`` mints
  ``chat_pcq_ + 32 hex, ``requestStreaming`` adds calendar fields, tries
  /api/orchestration first (after GET /api/orchestration/status), falls back
  to /api/chat/stream (real SSE), synthetic-SSE-composes JSON orchestration
  answers, and errorFor carries only ``error.code``.
* ``app/orchestration_routes.py`` / ``chat_routes.py``: contract validation
  (malformed pc_run_id -> 422 invalid_request), the pc lane entry
  conditions, error envelope shapes and the pc lane JSON/SSE shapes.
* ``app/chat_pc_drive.py.execute_chat_pc_files_lane``: staging, the single
  Engine call args, the executor-result-summary contract and the
  terminal seal.

The harness replaces only deployment seams (authority, Broker, Mesh,
B14 model, Engine bridge, BYOK provider) with fakes; everything else is
production code, including the real identity bridge mint of the B62/B54
sessions and the real device-selection store semantics.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
import uvicorn

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.control_plane_identity import (
    TrustedProductAuthEvidence,
    bridge_trusted_product_auth,
)
from app.history import PRODUCT_SCOPE_CHAT
from app.main import create_app
from app.orchestration_bridge import B62EngineOrchestrationBridge
from app.orchestration_routes import install_orchestration_routes
from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    CanonicalSubjectRef,
    IdentityLinkState,
    ProductIdentityLink,
    SubjectType,
)
from padiem_control_plane.b54_identity_bridge import (
    B54_PRODUCT_ID,
    TrustedB54ServerAuthEvidence,
    bridge_trusted_b54_server_auth,
)

OWNER = "usr_" + "5" * 32
SUBJECT_ID = "sub-padiem-owner-5574"
TENANT_ID = "tenant-5574"
ACCOUNT_REF = "acct-5574"
DEVICE_ID = "office-pc"
WORKSPACE_ID = "memory-5574"
CHROME_5574_TEXT = "내PC office-pc 폴더에서 파일 목록 보여줘"
FOLLOWUP_5574_TEXT = "그 폴더 안에 뭐 있어?"
GENERAL_5574_TEXT = "보고서 배경캐릭터 배치를 상의하고 싶어"


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example-5574.test",
        google_client_id="5574-client-id.apps.googleusercontent.com",
        google_client_secret="5574-client-secret",
        session_secret="5574-issue-session-secret-not-a-real-credential",
        session_max_age_seconds="3600",
    )


class _ProhibitB14:
    """B14 is a forbidden seam on the PC-driven paths; record and refuse."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name: str):
        def _forbidden(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            raise AssertionError(f"B14 seam {name} must not be reached in this flow")

        return _forbidden


class _AnsweringB14:
    """B14 stand-in for the ordinary Chat stream leg (stream_text_auto)."""

    def __init__(self, answer: str = "일반 모델 답변입니다.") -> None:
        self.answer = answer
        self.calls: list[dict[str, Any]] = []

    async def stream_text_auto(self, messages, *, skill, additional_system_context=None):
        self.calls.append(
            {
                "messages": [dict(item) for item in messages],
                "skill": skill,
                "additional_system_context": additional_system_context,
            }
        )
        yield SimpleNamespace(delta_content=self.answer[:4], done=False)
        yield SimpleNamespace(delta_content=self.answer[4:], done=False)
        yield SimpleNamespace(delta_content="", done=True)


class _ShadowStore:
    """Mirror of the B62 canonical shadow projection this owner has."""

    def __init__(self, authority: "_IdentityAuthority") -> None:
        self._authority = authority

    async def load_projection(self, product_user_id: str):  # noqa: ANN201
        session = self._authority.session_by_id(
            self._authority.sessions[("b62", product_user_id)].session_id
        )
        from app.control_plane_identity_shadow import IdentityShadowRecord

        return IdentityShadowRecord(
            product_user_id=product_user_id,
            canonical_subject_id=SUBJECT_ID,
            auth_session_id=session.session_id,
            session_revision=session.revision,
            session_state="active",
            session_expires_at=session.expires_at,
            observed_at=datetime.now(timezone.utc),
        )


class _MirrorHistoryStore:
    """D1-shaped mirror of the history surfaces the routes touched.

    Conversations hold the owner-scoped assistant-visible rows: the lane
    stages the user turn, the executor stamps ``result_summary`` on the run
    row BEFORE any seal, and the seal appends the assistant row (#5015).
    """

    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.messages: list[dict[str, str]] = []   # every owner-visible row
        self.conversations: dict[str, list[dict[str, str]]] = {}
        self.general_pairs: list[tuple[str, str]] = []
        self._counter = 0

    def _new_conversation_id(self) -> str:
        self._counter += 1
        return "chat_" + format(self._counter, "032x")

    async def get_user(self, user_id):  # noqa: ANN201
        return None

    async def append_exchange(
        self, user_id, conversation_id, user_text, assistant_text,
        project_id=None, *, product_scope,
    ):
        assert product_scope == PRODUCT_SCOPE_CHAT
        cid = conversation_id
        created = cid is None
        if created:
            cid = self._new_conversation_id()
        rows = self.conversations.setdefault(cid, [])
        rows.append({"role": "user", "content": user_text})
        rows.append({"role": "assistant", "content": assistant_text})
        self.general_pairs.append((user_text, assistant_text))
        return cid

    async def get_conversation(self, user_id, conversation_id, *, product_scope):
        assert product_scope == PRODUCT_SCOPE_CHAT
        if conversation_id is None or conversation_id not in self.conversations:
            return None
        return {"id": conversation_id, "user_id": user_id, "project_id": None}

    async def get_conversation_model_context(self, user_id, conversation_id, *, product_scope):
        assert product_scope == PRODUCT_SCOPE_CHAT
        if conversation_id is None or conversation_id not in self.conversations:
            return None
        return {
            "id": conversation_id,
            "user_id": user_id,
            "project_id": None,
            "messages": list(self.conversations[conversation_id]),
        }

    async def record_chat_pc_drive_run(
        self, *, user_id, run_id, workspace_id, user_text, conversation_id,
        action="pc_files_query", title_prefix=None,
    ):
        assert isinstance(run_id, str) and run_id
        assert isinstance(workspace_id, str) and workspace_id
        cid = conversation_id or self._new_conversation_id()
        self.runs[run_id] = {
            "user_id": user_id,
            "run_id": run_id,
            "workspace_id": workspace_id,
            "action": action,
            "conversation_id": cid,
            "status": "pending",
            "result_summary": None,
            "result_content": None,
        }
        self.conversations.setdefault(cid, []).append(
            {"role": "user", "content": user_text}
        )
        return cid

    async def get_claw_run(self, user_id, run_id):
        row = self.runs.get(run_id)
        if row is None or row["user_id"] != user_id:
            return None
        return dict(row)

    async def seal_run_terminal(
        self, *, user_id, run_id, message_id=None, summary="", content=None, status,
    ):
        row = self.runs.get(run_id)
        if row is None or row["user_id"] != user_id:
            return False
        if row["result_summary"] is None:
            return False  # the executor leg must stamp first (#5015)
        row["status"] = status
        row["result_summary"] = summary
        row["result_content"] = content
        assistant_row = {"role": "assistant", "content": content or summary}
        self.conversations.setdefault(row["conversation_id"], []).append(assistant_row)
        return True

    async def append_local_task_result(self, **fields):
        # The pc_files_query row always takes the seal branch (#5015 multi).
        raise AssertionError("append_local_task_result must not be used here")


class _PcDeviceSelectionStore:
    """Mirror of the owner-scoped pc device selection read.

    The fixture account has the PC chooser's saved target: office-pc. The
    orchestration surface does not carry the browser hint, so the server
    restored preference is the realistic target source there.
    """

    configured = True

    def __init__(self, saved: str | None) -> None:
        self.saved = saved

    async def load(self, owner_id: str, workspace_id: str):  # noqa: ANN201
        assert isinstance(owner_id, str) and owner_id
        assert isinstance(workspace_id, str) and workspace_id
        return self.saved


class _BrokerDirectory:
    """Mirror of the Broker device directory source API."""

    configured = True

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, Any]] = []

    async def list_devices(self, *, owner_id, workspace_id, now):  # noqa: ANN201
        self.calls.append({"owner_id": owner_id, "workspace_id": workspace_id})
        return list(self.rows)


class _MeshReturnSource:
    """Mirror of the Mesh owner-scope command-target read."""

    configured = True
    execution_mode = "mesh"

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, Any]] = []

    def command_target(self, *, account_ref, device_id=None):  # noqa: ANN201
        self.calls.append({"account_ref": account_ref, "device_id": device_id})
        matches = [
            row for row in self.rows
            if row["account_ref"] == account_ref
            and row.get("command_exec", True) is True
            and (
                device_id is None
                or row.get("device_id") == device_id
                or row.get("device_id") is None
                or row["node_ref"] == device_id
            )
        ]
        return dict(matches[0]) if len(matches) == 1 else None


class _IdentityAuthority:
    """One async authority serving: b62 login mint, current-session reads,
    the shadow-refresh read and the connector owner scope."""

    def __init__(self, *, authenticated_at, expires_at) -> None:
        self.authenticated_at = authenticated_at
        self.expires_at = expires_at
        self.links: dict[tuple[str, str], ProductIdentityLink] = {}
        self.sessions: dict[tuple[str, str], AuthSessionSnapshot] = {}
        self.session_ids: set[str] = set()
        self._counter = 0

    def resolve_or_create_product_link(
        self, *, product_id, product_user_id, auth_provider, provider_subject,
    ):
        key = (product_id, product_user_id)
        row = self.links.get(key)
        if row is None:
            self._counter += 1
            row = ProductIdentityLink(
                product_id=product_id,
                product_user_id=product_user_id,
                canonical_subject_id=SUBJECT_ID,
                state=IdentityLinkState.ACTIVE,
            )
            self.links[key] = row
        return row

    def resolve_active_memberships(self, *, canonical_subject_id):
        assert canonical_subject_id == SUBJECT_ID
        return (TENANT_ID,)

    def establish_auth_session(
        self, *, product_id, subject, authenticated_at, not_after,
    ):
        assert subject.subject_id == SUBJECT_ID
        assert subject.subject_type is SubjectType.USER
        self._counter += 1
        session = AuthSessionSnapshot(
            session_id=f"authsession:{self._counter:032x}",
            product_id=product_id,
            subject=subject,
            issued_at=authenticated_at,
            expires_at=not_after,
            state=AuthSessionState.ACTIVE,
            revision=1,
            tenant_id=TENANT_ID,
        )
        # The harness mints one session per product for the single owner.
        for (existing_product, _owner), existing in self.sessions.items():
            if existing_product == product_id:
                del self.sessions[(existing_product, _owner)]
                self.session_ids.discard(existing.session_id)
        self.session_ids.add(session.session_id)
        self.sessions[(product_id, OWNER)] = session
        return session

    async def resolve_current_auth_session(self, *, product_id, product_user_id):
        return self.sessions.get((product_id, product_user_id))

    def session_by_id(self, session_id: str):
        for session in self.sessions.values():
            if session.session_id == session_id:
                return session
        return None

    async def resolve_auth_session(self, *, session_id):
        return self.session_by_id(session_id)

    async def resolve_connector_owner_scope(self, *, session_id):
        if session_id not in self.session_ids:
            raise RuntimeError("unknown canonical session")
        return {"account_ref": ACCOUNT_REF, "workspace_ref": "ws-connector"}


class _RecordingEngineBridge(B62EngineOrchestrationBridge):
    """Engine seam stand-in mirroring the one-call pc contract.

    The real executor stores the verified result summary on the staged run
    row before the lane may seal it; the fake mirrors that leg. b14 stays
    untouched on this path because the lane itself never reads it.
    """

    def __init__(self, *, store: _MirrorHistoryStore) -> None:
        super().__init__(client=object(), store=object())
        self.store = store
        self.requests: list[dict[str, Any]] = []
        self._answer_index = 0

    async def start(self, **fields):
        self.requests.append(dict(fields))
        self._answer_index += 1
        session_id = fields.get("session_id")
        run = self.store.runs.get(session_id) if session_id else None
        if run is not None and fields.get("agent_plan"):
            if not run["result_summary"]:
                run["result_summary"] = f"engine result payload {self._answer_index}"
        return SimpleNamespace(
            answer=f"PC-folder-answer-{self._answer_index}",
            public={"answer": f"PC-folder-answer-{self._answer_index}"},
        )


_DEVICE_ROW = {
    "deviceId": DEVICE_ID,
    "deviceName": "Office PC 5574",
    "state": "CONNECTED",
    "usable": True,
}

_MESH_ROW = {
    "account_ref": ACCOUNT_REF,
    "device_id": DEVICE_ID,
    "node_ref": "node-office-5574",
    "command_exec": True,
}


class _PcHarness:
    """One harness instance per flow family; every seam is recorded."""

    def __init__(self, *, device_rows: list[dict[str, Any]] | None = None,
                 mesh_rows: list[dict[str, Any]] | None = None,
                 saved_device: str | None = DEVICE_ID) -> None:
        self.authority = _IdentityAuthority(
            authenticated_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
        )
        self.store = _MirrorHistoryStore()
        self.selection_store = _PcDeviceSelectionStore(saved_device)
        self.directory = _BrokerDirectory(list(device_rows if device_rows is not None else [_DEVICE_ROW]))
        self.mesh = _MeshReturnSource(list(mesh_rows if mesh_rows is not None else [_MESH_ROW]))
        self.b14: Any = _ProhibitB14()  # swapped for _AnsweringB14 on b30 flows
        self.bridge = _RecordingEngineBridge(store=self.store)

    async def seed_identity(self) -> None:
        ev = TrustedProductAuthEvidence(
            product_user_id=OWNER,
            provider="google",
            provider_subject="google-subject-5574",
            authenticated_at=self.authority.authenticated_at,
            expires_at=self.authority.expires_at,
        )
        await bridge_trusted_product_auth(
            self.authority, ev, ensure_personal_tenant=True,
        )
        b54_ev = TrustedB54ServerAuthEvidence(
            product_user_id=OWNER,
            provider="google",
            provider_subject="google-subject-5574",
            authenticated_at=self.authority.authenticated_at,
            expires_at=self.authority.expires_at,
        )
        await bridge_trusted_b54_server_auth(self.authority, b54_ev)

    def create_app(self, *, orchestration: bool) -> Any:
        config = _settings()
        app = create_app(
            config,
            history_store=self.store,
            claw_device_directory_source=self.directory,
            claw_pc_device_selection_store=self.selection_store,
        )
        app.state.oracle_mesh_return_source = self.mesh
        app.state.control_plane_identity_authority = self.authority
        app.state.identity_shadow_store = _ShadowStore(self.authority)
        app.state.b14_client = self.b14
        app.state.auto_grounding = _NoopAutoGrounding()
        app.state.calendar_store = None
        app.state.orchestration_bridge = self.bridge
        if orchestration:
            install_orchestration_routes(app, self.bridge)
        return app, config


class _NoopAutoGrounding:
    def decide(self, messages, *, skill):  # noqa: ANN201
        return None

    async def prepare(self, messages, *, skill, additional_system_context):  # noqa: ANN201
        return None


_NODE_DRIVER = r"""
"use strict";
const fs = require("node:fs");
const http = require("node:http");
const vm = require("node:vm");

const ORIGIN = process.env.ORIGIN;
const TARGET = process.env.TARGET || ORIGIN;
const COOKIE = process.env.COOKIE;
const STEPS = JSON.parse(process.env.STEPS);
const calls = [];

function viaHttp(method, pathname, headers, bodyString) {
  return new Promise((resolve, reject) => {
    const target = new URL(TARGET + pathname);
    const req = http.request(
      { hostname: target.hostname, port: target.port, path: target.pathname + (target.search || ""), method, headers },
      (res) => {
        const chunks = [];
        res.on("data", (chunk) => chunks.push(chunk));
        res.on("end", () => {
          const wireHeaders = {};
          for (const [name, value] of Object.entries(res.headers)) {
            wireHeaders[name.toLowerCase()] = Array.isArray(value) ? value.join(", ") : String(value);
          }
          resolve({ status: res.statusCode, headers: wireHeaders, text: Buffer.concat(chunks).toString("utf8") });
        });
      },
    );
    req.on("error", reject);
    if (bodyString !== null) req.write(bodyString);
    req.end();
  });
}

async function shimFetch(url, init) {
  init = init || {};
  const target = new URL(url, TARGET);
  const method = String(init.method || "GET").toUpperCase();
  const headers = Object.assign({}, init.headers);
  headers["Cookie"] = COOKIE;
  headers["Origin"] = ORIGIN;
  const body = init.body === undefined || init.body === null ? null : String(init.body);
  const record = { method, path: target.pathname + (target.search || ""), body, status: null };
  calls.push(record);
  const reply = await viaHttp(method, record.path, headers, body);
    record.status = reply.status;
    const encoded = new TextEncoder().encode(reply.text);
    return {
    ok: reply.status >= 200 && reply.status < 300,
    status: reply.status,
    headers: {
      get(name) { const got = reply.headers[String(name).toLowerCase()]; return got === undefined ? null : got; },
    },
    text: async () => reply.text,
    json: async () => JSON.parse(reply.text),
    body: new ReadableStream({
      start(controller) { controller.enqueue(encoded); controller.close(); },
    }),
  };
}

const window = { location: { origin: ORIGIN } };
window.padiemSelectedDeviceId = () => deviceHint;
window.padiemClawSelectedDeviceId = () => deviceHint;
let deviceHint = null;
const sandbox = {
  window,
  fetch: shimFetch,
  TextDecoder: globalThis.TextDecoder,
  TextEncoder: globalThis.TextEncoder,
  Response: globalThis.Response,
  Headers: globalThis.Headers,
  ReadableStream: globalThis.ReadableStream,
  WritableStream: globalThis.WritableStream,
  AbortSignal: globalThis.AbortSignal,
  crypto: globalThis.crypto,
  Intl: globalThis.Intl,
  URL: globalThis.URL,
  URLSearchParams: globalThis.URLSearchParams,
  console,
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.env.TRANSPORT_PATH, "utf8"), sandbox, { filename: "chat-transport.js" });
const transport = sandbox.window.PadiemChatTransport;
if (!transport) {
  console.error("PadiemChatTransport was not installed by the real module");
  process.exit(3);
}

(async () => {
  const steps = [];
  for (const step of STEPS) {
    const before = calls.length;
    // claw-device-manager.js wires the same hint; false mirrors no selection.
    deviceHint = step.selectedDevice === false ? null : "office-pc";
    const payload = { messages: step.messages, mode: "auto", skill: "auto" };
    let pcRunId = null;
    if (step.mint === true) {
      pcRunId = transport.createChatPcRunId();
      if (!/^chat_pcq_[0-9a-f]{32}$/.test(pcRunId)) throw new Error("bad minted pc_run_id: " + pcRunId);
      payload.pc_run_id = pcRunId;
    }
    if (typeof step.replayPcRunIdOf === "number") {
      const prior = steps[step.replayPcRunIdOf];
      if (!prior || !prior.pc_run_id) throw new Error("replay step has no prior pc run id");
      pcRunId = prior.pc_run_id;
      payload.pc_run_id = pcRunId;
    }
    if (typeof step.setPcRunId === "string") {
      pcRunId = step.setPcRunId;
      payload.pc_run_id = pcRunId;
    }
    if (typeof step.conversationCarryOf === "number") {
      const prior = steps[step.conversationCarryOf];
      if (!prior || !prior.conversation_id) throw new Error("carry step has no prior conversation id");
      payload.conversation_id = prior.conversation_id;
    }
    if (typeof step.threadCarryOf === "number") {
      const prior = steps[step.threadCarryOf];
      payload.messages = [
        ...((prior && prior.messages) || []),
        ...((prior && prior.answer) ? [{ role: "assistant", content: prior.answer }] : []),
        ...step.messages,
      ];
    }
    if (step.custom) payload.custom = step.custom;
    const record = {
      pc_run_id: pcRunId,
      conversation_id: null,
      generic_error: null,
      answer: "",
      events: [],
      wire: { payloadKeys: null, postBodyKeys: null },
      calls: [],
      status: [],
    };
    try {
      const response = await transport.requestStreaming(payload, null);
      record.postBody = null;
      record.wire.payloadKeys = Object.keys(payload).sort();
      record.wire.postBodyKeys = null;  // wire built inside the transport
      const sawCalls = [];
      for (let i = before; i < calls.length; i++) {
        const call = calls[i];
        sawCalls.push({ method: call.method, path: call.path, status: call.status, body: call.body });
      }
      record.calls = sawCalls.map((call) => ({ method: call.method, path: call.path, status: call.status }));
      const lastCall = sawCalls[sawCalls.length - 1];
      if (lastCall && lastCall.method === "POST") {
        try { record.wire.postBodyKeys = Object.keys(JSON.parse(lastCall.body)).sort(); } catch (_) { /* not json */ }
        record.status.push(lastCall.status);
        record.postBody = lastCall.body;
      }
      record.contentType = (response && response.headers) ? response.headers.get("content-type") : null;
      await transport.readSseEvents(response, async (frame) => {
        const parsed = JSON.parse(frame.data);
        record.events.push(frame.event);
        if (frame.event === "delta") record.answer += typeof parsed.delta === "string" ? parsed.delta : "";
        if (frame.event === "done") {
          record.conversation_id = typeof parsed.conversation_id === "string" ? parsed.conversation_id : null;
        }
        return false;
      });
    } catch (error) {
      record.generic_error = { name: error && error.name, message: String(error && error.message || ""), code: error && error.code || null };
      for (let i = before; i < calls.length; i++) {
        const call = calls[i];
        record.calls.push({ method: call.method, path: call.path, status: call.status });
        record.status.push(call.status);
      }
    }
    steps.push(record);
  }
  console.log(JSON.stringify({ steps, calls }));
})();
"""


def _node_executable() -> str:
    found = shutil.which("node")
    if not found:
        raise RuntimeError("node is not available on PATH")
    return found


_DRIVER_CACHE: list[str] = []


def _driver_path() -> str:
    if _DRIVER_CACHE:
        return _DRIVER_CACHE[0]
    base = tempfile.mkdtemp(prefix="issue5574-node-")
    path = os.path.join(base, "driver.js")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(_NODE_DRIVER)
    _DRIVER_CACHE.append(path)
    return path


async def _serve(app) -> tuple[int, Any]:
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", lifespan="on")
    )
    task = asyncio.create_task(server.serve())
    for _ in range(600):
        await asyncio.sleep(0.05)
        if server.started:
            break
    else:
        task.cancel()
        raise RuntimeError("uvicorn did not start serving in time")
    port = None
    for candidate in getattr(server, "servers", []):
        sockets = candidate.sockets or []
        if sockets:
            port = sockets[0].getsockname()[1]
            break
    if not port:
        server.should_exit = True
        raise RuntimeError("could not read the bound uvicorn port")
    return int(port), (server, task)


async def _stop(server_and_task) -> None:
    server, task = server_and_task
    server.should_exit = True
    try:
        await asyncio.wait_for(task, timeout=10)
    except Exception:
        task.cancel()


async def _run_flow(harness: _PcHarness, steps: list[dict[str, Any]], *,
                    orchestration: bool) -> dict[str, Any]:
    await harness.seed_identity()
    app, config = harness.create_app(orchestration=orchestration)
    cookie_token = create_session_token(config, OWNER)

    port, server_and_task = await _serve(app)

    driver = _driver_path()
    env = {
        **os.environ,
        "TRANSPORT_PATH": os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "static", "chat-transport.js",
        ),
        "ORIGIN": "https://chat.example-5574.test",
        "TARGET": f"http://127.0.0.1:{port}",
        "COOKIE": f"{SESSION_COOKIE}={cookie_token}",
        "STEPS": json.dumps(steps, ensure_ascii=False),
    }
    completed = await asyncio.to_thread(
        subprocess.run,
        [_node_executable(), driver],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=240,
        check=False,
    )
    await _stop(server_and_task)

    if completed.returncode != 0:
        tail = (completed.stdout or "")[-1200:] + "\n--- STDERR ---\n" + (completed.stderr or "")[-2000:]
        raise AssertionError(f"node driver failed (exit {completed.returncode}):\n{tail}")
    lines = [line for line in (completed.stdout or "").splitlines() if line.strip()]
    if not lines:
        raise AssertionError(f"node driver produced no output\nSTDERR:{(completed.stderr or '')[-2000:]}")
    return json.loads(lines[-1])


def _has_call(record: dict[str, Any], method: str, path: str) -> bool:
    return any(c["method"] == method and c["path"] == path for c in record["calls"])


def _demand_no_engine_calls(harness) -> None:
    assert harness.bridge.requests == [], (
        f"the pc files lane must not reach the engine, got {harness.bridge.requests}"
    )


def _assert_pc_run_completed(harness, pc_run_id: str) -> dict[str, Any]:
    row = harness.store.runs.get(pc_run_id)
    assert row is not None, f"staged run row missing for {pc_run_id}"
    assert row["status"] == "completed", row
    assert row["result_summary"], row  # the executor result leg summary
    assert row["conversation_id"], row
    return row


def _assert_b14_untouched(harness: _PcHarness) -> None:
    assert harness.b14.calls == [], harness.b14.calls


def test_create_chat_pc_run_id_contract_is_self_consistent() -> None:
    """The transport handle prefix is the canonical ``chat_pcq_`` one."""

    transport_code = (
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "static", "chat-transport.js")
    )
    with open(transport_code, encoding="utf-8") as handle:
        source = handle.read()
    assert '"chat_pcq_"' in source


def test_no_device_account_pc_turn_falls_through_to_general_without_lane_work() -> None:
    """An account with zero Broker devices never reaches the Engine.

    The explicit pc_run_id openers the lane on /api/chat/stream, but the
    directory truth (no devices) is a fall-through, not a refusal: the
    ordinary B14 stream leg answers, paying exactly one B14 call and no
    Engine call and no staged pc run.
    """

    async def flow():
        harness = _PcHarness(device_rows=[], saved_device=None)
        harness.b14 = _AnsweringB14()
        steps = [
            {
                "messages": [{"role": "user", "content": CHROME_5574_TEXT}],
                "mint": True,
                "selectedDevice": False,
            },
        ]
        result = await _run_flow(harness, steps, orchestration=False)
        return harness, result

    harness, result = asyncio.run(flow())
    step = result["steps"][0]
    assert step["pc_run_id"] and step["pc_run_id"].startswith("chat_pcq_")
    assert not _has_call(step, "POST", "/api/orchestration"), step["calls"]
    assert _has_call(step, "POST", "/api/chat/stream"), step["calls"]
    assert step["answer"].strip() != "", step
    assert len(step["events"]) >= 2
    assert harness.bridge.requests == [], harness.bridge.requests
    assert harness.store.runs == {}, harness.store.runs
    assert len(harness.b14.calls) == 1, harness.b14.calls
    call = harness.b14.calls[0]
    assert call["skill"].id == "auto"
    assert call["messages"][-1]["content"] == CHROME_5574_TEXT


def test_pc_list_turn_runs_one_lane_call_with_the_saved_target_and_completes() -> None:
    async def flow():
        harness = _PcHarness()
        steps = [
            {
                "messages": [{"role": "user", "content": CHROME_5574_TEXT}],
                "mint": True,
            },
        ]
        result = await _run_flow(harness, steps, orchestration=True)
        return harness, result

    harness, result = asyncio.run(flow())
    step = result["steps"][0]
    minted = step["pc_run_id"]
    assert _has_call(step, "POST", "/api/orchestration")
    assert _has_call(step, "GET", "/api/orchestration/status")
    assert step["answer"].strip() != "", step
    assert step["events"] == ["delta", "done"], step["events"]
    assert step["conversation_id"] is not None, step

    # The one Engine call carries the pc plan, the server-owned target and
    # the minted session id; the Executor result leg was stamped pre-seal.
    assert len(harness.bridge.requests) == 1, harness.bridge.requests
    call = harness.bridge.requests[0]
    assert call["user_id"] == OWNER
    assert call["subject_id"] == SUBJECT_ID
    assert call["session_id"] == minted
    assert list(call["messages"]) == [
        {"role": "user", "content": CHROME_5574_TEXT}
    ]
    assert call["agent_plan"]  # engine decides the steps
    assert call["tool_arguments"] == {"files": {"device_id": DEVICE_ID}}
    assert call["conversation_id"] == step["conversation_id"]

    # MEASURED (#5574 negative case): a listing-only request is NOT narrowed
    # by the server. The lane ships the trusted legacy list+read scope hint
    # and a two-step plan, so the Engine's read gate starts open and the
    # model's own intent is the only narrowing (engine side evidence:
    # apps/padiem-ai-engine/tests/test_5574_pc_read_scope_leak.py).
    assert [s["tool_id"] for s in call["agent_plan"]["steps"]] == [
        "claw.pc.list_files",
        "claw.pc.read_file",
    ]

    row = _assert_pc_run_completed(harness, minted)
    assert row["conversation_id"] == step["conversation_id"]
    staged_rows = harness.store.conversations[step["conversation_id"]]
    assert [r["role"] for r in staged_rows] == ["user", "assistant"]
    assert staged_rows[0]["content"] == CHROME_5574_TEXT
    assert staged_rows[1]["content"] == step["answer"]
    _assert_b14_untouched(harness)
    assert harness.directory.calls and harness.directory.calls[0]["owner_id"] == ACCOUNT_REF
    assert harness.mesh.calls and harness.mesh.calls[0]["device_id"] == DEVICE_ID


def test_visual_general_turn_is_priced_exactly_like_any_pc_turn() -> None:
    """The files lane runs for every turn of a pc-connected account.

    The pc store row and the single Engine call are the same for a plain
    discussion turn as for a pc request: the Engine decides inside its one
    call. The pc row is still staged and completed either way.
    """

    async def flow():
        harness = _PcHarness()
        steps = [
            {
                "messages": [{"role": "user", "content": GENERAL_5574_TEXT}],
                "mint": True,
            },
        ]
        result = await _run_flow(harness, steps, orchestration=True)
        return harness, result

    harness, result = asyncio.run(flow())
    step = result["steps"][0]
    minted = step["pc_run_id"]
    assert _has_call(step, "POST", "/api/orchestration")
    assert len(harness.bridge.requests) == 1, harness.bridge.requests
    call = harness.bridge.requests[0]
    assert call["tool_arguments"] == {"files": {"device_id": DEVICE_ID}}
    assert call["agent_plan"]
    assert call["subject_id"] == SUBJECT_ID
    row = _assert_pc_run_completed(harness, minted)
    assert row["status"] == "completed"
    _assert_b14_untouched(harness)


def test_followup_reuses_conversation_and_leaves_more_prior_turns_in_the_call() -> None:
    async def flow():
        harness = _PcHarness()
        steps = [
            {
                "messages": [{"role": "user", "content": CHROME_5574_TEXT}],
                "mint": True,
            },
            {
                "messages": [{"role": "user", "content": FOLLOWUP_5574_TEXT}],
                "mint": True,
                "conversationCarryOf": 0,
                "threadCarryOf": 0,
            },
        ]
        result = await _run_flow(harness, steps, orchestration=True)
        return harness, result

    harness, result = asyncio.run(flow())
    first, second = result["steps"]
    assert first["pc_run_id"] != second["pc_run_id"]
    assert second["conversation_id"] == first["conversation_id"]
    assert second["answer"].strip() != "", second
    assert len(harness.bridge.requests) == 2, harness.bridge.requests

    followup_call = harness.bridge.requests[1]
    assert followup_call["session_id"] == second["pc_run_id"]
    assert list(followup_call["messages"]) == [{"role": "user", "content": FOLLOWUP_5574_TEXT}]

    context = followup_call["additional_system_context"]
    assert isinstance(context, str)
    assert "Recent conversation:" in context
    # the prior turn's assistant answer, then this turn's line, in one call
    assert "PC-folder-answer-1" in context, context
    assert FOLLOWUP_5574_TEXT in context, context

    _assert_pc_run_completed(harness, first["pc_run_id"])
    second_row = _assert_pc_run_completed(harness, second["pc_run_id"])
    assert second_row["conversation_id"] == first["conversation_id"]
    _assert_b14_untouched(harness)


def test_malformed_pc_run_id_is_refused_by_the_contract_as_invalid_request() -> None:
    async def flow():
        harness = _PcHarness()
        steps = [
            {
                "messages": [{"role": "user", "content": CHROME_5574_TEXT}],
                "setPcRunId": "chat_pcq_NOT_HEX",
            },
        ]
        result = await _run_flow(harness, steps, orchestration=True)
        return harness, result

    harness, result = asyncio.run(flow())
    step = result["steps"][0]
    assert step["generic_error"]["code"] == "invalid_request", step
    assert any(
        call["method"] == "POST" and call["path"] == "/api/orchestration" and call["status"] == 422
        for call in step["calls"]
    ), step["calls"]
    _demand_no_engine_calls(harness)
    assert harness.store.runs == {}
    _assert_b14_untouched(harness)


def test_replayed_pc_run_id_is_refused_as_a_conflict_and_never_repayed() -> None:
    async def flow():
        harness = _PcHarness()
        steps = [
            {"messages": [{"role": "user", "content": CHROME_5574_TEXT}], "mint": True},
            {
                "messages": [{"role": "user", "content": CHROME_5574_TEXT}],
                "replayPcRunIdOf": 0,
            },
        ]
        result = await _run_flow(harness, steps, orchestration=True)
        return harness, result

    harness, result = asyncio.run(flow())
    first, replay = result["steps"]
    assert first["generic_error"] is None
    assert replay["generic_error"] is not None
    assert replay["generic_error"]["code"] == "chat_pc_run_id_conflict", replay
    assert any(
        call["method"] == "POST" and call["path"] == "/api/orchestration" and call["status"] == 409
        for call in replay["calls"]
    ), replay["calls"]
    assert first["pc_run_id"] == replay["pc_run_id"]

    # Only the FIRST turn ever paid engine work: the replay was refused on
    # the same staged id before any new stage or engine kick.
    assert len(harness.bridge.requests) == 1, harness.bridge.requests
    assert list(harness.store.runs) == [first["pc_run_id"]]
    row = _assert_pc_run_completed(harness, first["pc_run_id"])
    assert row["status"] == "completed"
    _assert_b14_untouched(harness)


def test_stream_route_lane_call_with_budgeted_candidates() -> None:
    """The fallback /api/chat/stream route keeps the same lane contract."""

    async def flow():
        harness = _PcHarness()
        steps = [
            {"messages": [{"role": "user", "content": CHROME_5574_TEXT}], "mint": True},
        ]
        result = await _run_flow(harness, steps, orchestration=False)
        return harness, result

    harness, result = asyncio.run(flow())
    step = result["steps"][0]
    assert _has_call(step, "POST", "/api/chat/stream")
    assert not _has_call(step, "POST", "/api/orchestration")
    assert step["answer"].strip() != "", step
    assert step["events"] == ["delta", "done"], step["events"]
    assert step["conversation_id"] is not None, step
    minted = step["pc_run_id"]
    assert minted
    assert len(harness.bridge.requests) == 1, harness.bridge.requests
    call = harness.bridge.requests[0]
    assert call["session_id"] == minted
    assert call["tool_arguments"] == {"files": {"device_id": DEVICE_ID}}
    assert call["agent_plan"]
    row = _assert_pc_run_completed(harness, minted)
    assert row["conversation_id"] == step["conversation_id"]
    _assert_b14_untouched(harness)


def test_bring_your_own_key_turn_never_reads_padiem_orchestration() -> None:
    """The custom selection is PADIEM-brand-free for pci: same transport."""

    harness = _PcHarness()
    recorded: list[dict[str, Any]] = []

    class _ProviderClient:
        async def complete(self, *, selection, api_key, endpoint, messages, system_context=None):
            recorded.append(
                {
                    "model_id": selection.model_id,
                    "upstream_model": selection.upstream_model,
                    "provider_id": selection.provider.provider_id,
                    "api_key": api_key,
                    "endpoint": endpoint,
                    "messages": [dict(item) for item in messages],
                }
            )
            return {"answer": "BYOK 답변입니다."}

    class _CredentialStore:
        async def credential(self, user_id, provider_id):
            assert user_id == OWNER
            assert provider_id == "opencode-go"
            return ("byok-5574-key", None)

    async def flow():
        app, config = harness.create_app(orchestration=False)
        app.state.custom_credential_store = _CredentialStore()
        app.state.custom_provider_client = _ProviderClient()
        cookie_token = create_session_token(config, OWNER)
        port, server_and_task = await _serve(app)
        env = {
            **os.environ,
            "TRANSPORT_PATH": os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "static", "chat-transport.js",
            ),
            "ORIGIN": "https://chat.example-5574.test",
            "TARGET": f"http://127.0.0.1:{port}",
            "COOKIE": f"{SESSION_COOKIE}={cookie_token}",
            "STEPS": json.dumps(
                [
                    {
                        "messages": [{"role": "user", "content": GENERAL_5574_TEXT}],
                        "custom": {
                            "provider": "opencode-go",
                            "model": "opencode-go/beam-free",
                        },
                    }
                ],
                ensure_ascii=False,
            ),
        }
        completed = await asyncio.to_thread(
            subprocess.run,
            [_node_executable(), _driver_path()],
            capture_output=True, text=True, encoding="utf-8", env=env,
            timeout=240, check=False,
        )
        await _stop(server_and_task)
        if completed.returncode != 0:
            raise AssertionError(
                "node driver failed:\n"
                + (completed.stdout or "")[-800:]
                + "\n--- STDERR ---\n" + (completed.stderr or "")[-2000:]
            )
        lines = [line for line in (completed.stdout or "").splitlines() if line.strip()]
        return json.loads(lines[-1])

    result = asyncio.run(flow())
    step = result["steps"][0]
    # The custom payload is never routed through /api/orchestration.
    assert not _has_call(step, "POST", "/api/orchestration"), step["calls"]
    assert not _has_call(step, "GET", "/api/orchestration/status"), step["calls"]
    assert _has_call(step, "POST", "/api/chat/stream"), step["calls"]
    assert step["answer"] == "BYOK 답변입니다.", step
    assert len(recorded) == 1, recorded
    call = recorded[0]
    assert call["provider_id"] == "opencode-go"
    assert call["model_id"] == "opencode-go/beam-free"
    assert call["upstream_model"] == "beam-free"
    assert call["api_key"] == "byok-5574-key"
    assert call["messages"][0]["content"] == GENERAL_5574_TEXT
    _assert_b14_untouched(harness)
    assert harness.bridge.requests == []
    assert harness.store.runs == {}
