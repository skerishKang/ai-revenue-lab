"""#3094 — one real local-access truth source and the guarded Web adapter.

The #3084 "Connect this computer" panel was, by design, a projection surface
with an internal fixture model and an injected model seam. Nothing outside a
test could fill it, which the #3084 self-audit recorded as the
``real_source`` and ``open_guard`` gaps. This slice closes both without moving
any authority:

    canonical device truth (#3080 lifecycle, read-only)
        -> project_local_access_projection   (G4: translation, never state)
        -> GET /api/claw/local-access        (owner-scoped, read-only, opaque)
        -> static/claw-local-adapter.js      (G5: consume + G1/G2/G3: open guard)
        -> window.__padiemClawLocalHandoff.project(...)   (#3084 renders)

The Web vocabulary (``PAIRING`` / ``CONNECTED`` / ...) stays owned by #3084.
This slice adds a second consumer of the canonical ``DeviceLifecycle`` enum and
a translation that follows the already-published #3080 rule table. It mints no
token, signs nothing, parses no handoff payload, holds no device session and
opens the desktop app only from a guarded user-activation path.

    DEVICE_SESSION_TRUST_BORROWING=FORBIDDEN
    SECOND_SERVER_DEVICE_TRUTH=FORBIDDEN
    TOKEN_CONSTRUCTION_OR_PARSING_IN_WEB=FORBIDDEN
    DEVICE_TO_DEVICE_SESSION_LATERALITY=FORBIDDEN
    OPEN_FROM_PROJECTION_OR_PAGE_SCRIPT=FORBIDDEN
    PERSISTED_HANDOFF_OR_SESSION_MATERIAL=FORBIDDEN

Failure posture: an unconfigured, faulting or malformed source answers
``available: false`` with a bounded reason code, and the adapter then projects
"nothing known" so #3084 hides the panel. A projection that could not be read
is never replaced with a guess or left on screen as a stale claim.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.claw_local_access_routes import (
    CLAW_LOCAL_ACCESS_PATH,
    CLAW_LOCAL_ACCESS_PROJECTION_VERSION,
    LOCAL_ACCESS_UNCONFIGURED_REASON,
    UnconfiguredClawLocalAccessTruthSource,
)
from app.claw_local_projection import (
    CANONICAL_DEVICE_STATES,
    MAX_HANDOFF_VALUE_LENGTH,
    SAFE_FALLBACK_WEB_STATE,
    WEB_HANDOFF_CONTRACT_VERSION,
    WEB_LIFECYCLE_STATES,
    WEB_STATE_ACTION_REQUIRED,
    WEB_STATE_CONNECTED,
    WEB_STATE_OFFLINE,
    WEB_STATE_PAIRING,
    WEB_STATE_REVOKED,
    canonical_device_states,
    handoff_projection,
    translate_device_lifecycle,
    web_lifecycle_states,
    web_state_for_canonical_state,
)
from app.config import Settings
from app.main import create_app
from kagent.local_agent_pairing import DeviceLifecycle

APP_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = APP_ROOT / "static" / "claw-local-adapter.js"
HANDOFF_PATH = APP_ROOT / "static" / "claw-local-handoff.js"
APP_JS_PATH = APP_ROOT / "static" / "app.js"
INDEX_PATH = APP_ROOT / "static" / "index.html"
FACTORY_PATH = APP_ROOT / "app" / "app_factory.py"

BASE_URL = "https://chat.example.test"
USER_ID = "usr_3094_owner"
CONVERSATION_ID = "conv_3094_01"
RUN_ID = "run_3094_01"
TASK_ID = "task_3094_01"
DEVICE_NAME = "MacBook-Pro-3094"
DESKTOP_HANDOFF = "padiem://local-handoff/AgA1opaque-token-value"
WIDE_HANDOFF = "padiem://local-handoff/" + "a" * 600

REASON_NO_OWNER = "owner_session_required"
REASON_SOURCE_FAILED = "local_access_source_failed"
INVALID_CONVERSATION_CODE = "invalid_conversation_id"

# Every canonical lifecycle member the server owns, paired with the single Web
# state #3094 is allowed to present for it, and whether that state may be
# reported as a usable device. `online` is the only usable answer.
CANONICAL_TRANSLATION_TABLE = (
    (DeviceLifecycle.UNPAIRED, WEB_STATE_PAIRING, False),
    (DeviceLifecycle.PAIRED_OFFLINE, WEB_STATE_OFFLINE, False),
    (DeviceLifecycle.ONLINE, WEB_STATE_CONNECTED, True),
    (DeviceLifecycle.REVOKED, WEB_STATE_REVOKED, False),
    (DeviceLifecycle.CREDENTIAL_EXPIRED, WEB_STATE_ACTION_REQUIRED, False),
    (DeviceLifecycle.UPDATE_REQUIRED, WEB_STATE_ACTION_REQUIRED, False),
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class ProjectionSource:
    """Stand-in for the #3080 composition: reports canonical truth, nothing more.

    It records what the route asked for so a test can prove the route passes the
    session-derived owner id rather than anything the browser supplied.
    """

    configured = True

    def __init__(self, *, result: dict[str, Any] | None = None, raises: bool = False,
                 returns_none: bool = False):
        self.calls: list[dict[str, Any]] = []
        self.raises = raises
        self.returns_none = returns_none
        self.result = {
            "requires_local_access": True,
            "required_capabilities": ["local_computer"],
            "desktop_installed": True,
            "canonical_state": DeviceLifecycle.ONLINE.value,
            "device_name": DEVICE_NAME,
            "platform": "darwin",
            "handoff_value": DESKTOP_HANDOFF,
            "run_id": RUN_ID,
            "task_id": TASK_ID,
        }
        if result is not None:
            self.result.update(result)

    async def project_local_access(self, *, owner_id: str, conversation_id: str, now: Any) -> Any:
        self.calls.append({"owner_id": owner_id, "conversation_id": conversation_id})
        if self.raises:
            raise RuntimeError("internal broker storage detail must not leak")
        if self.returns_none:
            return None
        return dict(self.result)


class NoMethodSource:
    """Configured but not a valid source: the route must fail closed anyway."""

    configured = True


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=BASE_URL,
        session_secret="claw-local-access-3094-session-secret-not-real",
        session_max_age_seconds=3600,
    )


def _get(
    *,
    source: Any = None,
    conversation_id: str | None = CONVERSATION_ID,
    signed_in: bool = True,
    raw_query: str | None = None,
) -> tuple[httpx.Response, Any]:
    """Perform one request against a freshly composed app, return response+app."""

    settings = _settings()
    app = create_app(settings, history_store=MagicMock())
    if source is not None:
        app.state.claw_local_access_source = source

    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            if signed_in:
                client.cookies.set(SESSION_COOKIE, create_session_token(settings, USER_ID))
            if raw_query is not None:
                return await client.get(f"{CLAW_LOCAL_ACCESS_PATH}{raw_query}")
            params = None if conversation_id is None else {"conversationId": conversation_id}
            return await client.get(CLAW_LOCAL_ACCESS_PATH, params=params)

    return asyncio.run(run()), app


# ---------------------------------------------------------------------------
# G4 — the single canonical-to-Web translation
# ---------------------------------------------------------------------------


def test_the_translation_covers_every_canonical_state_and_invents_none() -> None:
    """The table is total over the canonical enum and adds no new state."""

    assert CANONICAL_DEVICE_STATES == tuple(member.value for member in DeviceLifecycle)
    assert canonical_device_states() == CANONICAL_DEVICE_STATES
    assert len(CANONICAL_TRANSLATION_TABLE) == len(DeviceLifecycle)
    translated = {item[0].value for item in CANONICAL_TRANSLATION_TABLE}
    assert translated == set(CANONICAL_DEVICE_STATES)
    # Every produced Web state is one #3084 already owns: no hidden sixth state.
    for _member, web_state, _usable in CANONICAL_TRANSLATION_TABLE:
        assert web_state in WEB_LIFECYCLE_STATES


@pytest.mark.parametrize(
    "member,expected_web_state,expected_usable",
    CANONICAL_TRANSLATION_TABLE,
)
def test_each_canonical_state_projects_the_paired_web_state(
    member: DeviceLifecycle, expected_web_state: str, expected_usable: bool
) -> None:
    projected = translate_device_lifecycle(member.value, device_name=DEVICE_NAME, platform="darwin")

    assert projected["state"] == expected_web_state
    assert projected["usable"] is expected_usable
    assert projected["canonicalState"] == member.value
    assert projected["unrecognised"] is False
    assert projected["deviceName"] == DEVICE_NAME
    # A variant is never claimed by the server: only a genuinely usable CONNECTED
    # device could carry one, and that is #3084's decision, not this translation's.
    assert projected["variant"] is None


def test_only_canonical_online_may_be_reported_as_a_usable_device() -> None:
    """The exact false-connected failure, closed at translation level."""

    usable_states = [
        member.value for member, _web, usable in CANONICAL_TRANSLATION_TABLE if usable
    ]
    assert usable_states == [DeviceLifecycle.ONLINE.value]
    for member in DeviceLifecycle:
        projected = translate_device_lifecycle(member.value)
        if member is not DeviceLifecycle.ONLINE:
            assert projected["usable"] is False
            assert projected["state"] != WEB_STATE_CONNECTED


def test_unrecognised_or_absent_canonical_state_fails_closed() -> None:
    for unknown in ("ONLINE_BUT_TRUSTED", "CONNECTED ", "", None, 7, ["CONNECTED"]):
        projected = translate_device_lifecycle(unknown)
        assert projected["state"] == SAFE_FALLBACK_WEB_STATE
        assert projected["usable"] is False
        assert projected["unrecognised"] is True
        assert projected["canonicalState"] is None
        assert web_state_for_canonical_state(unknown) == SAFE_FALLBACK_WEB_STATE


def test_expired_and_revoked_flags_cannot_be_dressed_as_connected() -> None:
    expired = translate_device_lifecycle(DeviceLifecycle.CREDENTIAL_EXPIRED.value)
    assert expired["expired"] is True
    assert expired["state"] == WEB_STATE_ACTION_REQUIRED

    revoked = translate_device_lifecycle(DeviceLifecycle.REVOKED.value)
    assert revoked["revoked"] is True
    assert revoked["state"] == WEB_STATE_REVOKED


def test_the_web_vocabulary_mirror_matches_the_3084_javascript_literal() -> None:
    """The #3084 module owns the vocabulary; this module may only mirror it."""

    handoff_source = HANDOFF_PATH.read_text(encoding="utf-8")

    literal = re.search(
        r"const CANONICAL_DEVICE_STATES = Object\.freeze\(\[(.*?)\]\);",
        handoff_source,
        re.DOTALL,
    )
    assert literal, "#3084 device-state literal not found"
    js_states = tuple(re.findall(r'"([A-Z_]+)"', literal.group(1)))
    assert js_states == WEB_LIFECYCLE_STATES
    assert web_lifecycle_states() == WEB_LIFECYCLE_STATES

    fallback = re.search(r'const SAFE_FALLBACK_STATE = "([A-Z_]+)";', handoff_source)
    assert fallback and fallback.group(1) == SAFE_FALLBACK_WEB_STATE

    version = re.search(r'const CONTRACT_VERSION = "([^"]+)";', handoff_source)
    assert version and version.group(1) == WEB_HANDOFF_CONTRACT_VERSION


# ---------------------------------------------------------------------------
# Opaque handoff handling
# ---------------------------------------------------------------------------


def test_handoff_value_is_forwarded_verbatim_never_rewritten() -> None:
    projected = handoff_projection(value=DESKTOP_HANDOFF, conversation_id=CONVERSATION_ID)

    assert projected["value"] == DESKTOP_HANDOFF
    assert projected["kind"] == "deep_link"
    assert projected["conversationId"] == CONVERSATION_ID


@pytest.mark.parametrize("value", [None, 7, {"value": DESKTOP_HANDOFF}, "", "   ", True])
def test_absent_or_non_string_handoff_offers_no_value(value: Any) -> None:
    projected = handoff_projection(value=value)

    assert "value" not in projected
    assert projected["unavailableReason"] in {"absent", "empty"}


def test_over_length_handoff_is_dropped_whole_never_truncated() -> None:
    assert MAX_HANDOFF_VALUE_LENGTH == 512
    projected = handoff_projection(value=WIDE_HANDOFF)

    assert "value" not in projected
    assert projected["unavailableReason"] == "too_long"
    assert WIDE_HANDOFF[:40] not in json.dumps(projected)


# ---------------------------------------------------------------------------
# Route: authentication, validation, fail-closed default
# ---------------------------------------------------------------------------


def test_anonymous_request_is_rejected_before_any_source_call() -> None:
    source = ProjectionSource()

    response, _app = _get(source=source, signed_in=False)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == REASON_NO_OWNER
    assert source.calls == []


@pytest.mark.parametrize(
    "raw_query",
    [
        "",
        "?conversationId=",
        "?conversationId=%20%20",
        "?conversationId=" + "c" * 129,
        "?conversationId=conv%20with%20space",
        "?conversationId=..%2F..%2Fetc",
        "?conversationId=conv%3Cscript%3E",
    ],
)
def test_malformed_conversation_id_is_rejected_without_a_source_call(raw_query: str) -> None:
    source = ProjectionSource()

    response, _app = _get(source=source, raw_query=raw_query)

    assert response.status_code == 400, raw_query
    assert response.json()["error"]["code"] == INVALID_CONVERSATION_CODE
    assert source.calls == []


def test_the_composed_default_source_fails_closed_without_guessing() -> None:
    response, app = _get()

    assert isinstance(app.state.claw_local_access_source, UnconfiguredClawLocalAccessTruthSource)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["available"] is False
    assert body["reason"] == LOCAL_ACCESS_UNCONFIGURED_REASON

    projection = body["projection"]
    assert projection["device"] is None
    assert projection["requiresLocalAccess"] is False
    assert "value" not in projection["handoff"]
    assert projection["contractVersion"] == WEB_HANDOFF_CONTRACT_VERSION


def test_a_configured_flag_false_source_is_treated_as_unconfigured() -> None:
    class DisabledSource(ProjectionSource):
        configured = False

    source = DisabledSource()

    response, _app = _get(source=source)

    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["reason"] == LOCAL_ACCESS_UNCONFIGURED_REASON
    assert source.calls == []


def test_a_source_without_the_contract_method_fails_closed() -> None:
    response, _app = _get(source=NoMethodSource())

    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["projection"]["device"] is None


# ---------------------------------------------------------------------------
# Route: the available projection
# ---------------------------------------------------------------------------


def test_available_projection_is_the_shape_3084_consumes() -> None:
    source = ProjectionSource()

    response, _app = _get(source=source)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["available"] is True
    assert body["projectionVersion"] == CLAW_LOCAL_ACCESS_PROJECTION_VERSION

    projection = body["projection"]
    assert set(projection) == {
        "contractVersion",
        "conversationId",
        "runId",
        "taskId",
        "requiresLocalAccess",
        "requiredCapabilities",
        "desktopInstalled",
        "device",
        "handoff",
    }
    assert projection["contractVersion"] == WEB_HANDOFF_CONTRACT_VERSION
    assert projection["conversationId"] == CONVERSATION_ID
    assert projection["runId"] == RUN_ID
    assert projection["taskId"] == TASK_ID
    assert projection["requiresLocalAccess"] is True
    assert projection["requiredCapabilities"] == ["local_computer"]
    assert projection["desktopInstalled"] is True
    assert projection["device"]["state"] == WEB_STATE_CONNECTED
    assert projection["device"]["usable"] is True
    assert projection["handoff"]["value"] == DESKTOP_HANDOFF

    # The single call the route made used the session-derived owner, never a
    # browser-supplied one: an owner id from the query cannot widen the scope.
    assert source.calls == [{"owner_id": USER_ID, "conversation_id": CONVERSATION_ID}]


def test_the_response_carries_no_owner_identifier_at_all() -> None:
    response, _app = _get(source=ProjectionSource())

    assert USER_ID not in response.text
    assert "owner_id" not in response.text


def test_offline_canonical_state_never_reaches_the_browser_as_connected() -> None:
    source = ProjectionSource(result={"canonical_state": DeviceLifecycle.PAIRED_OFFLINE.value})

    response, _app = _get(source=source)

    device = response.json()["projection"]["device"]
    assert device["state"] == WEB_STATE_OFFLINE
    assert device["usable"] is False
    assert device["canonicalState"] == DeviceLifecycle.PAIRED_OFFLINE.value


def test_a_faulting_source_reports_a_bounded_code_not_its_detail() -> None:
    response, _app = _get(source=ProjectionSource(raises=True))

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["reason"] == REASON_SOURCE_FAILED
    assert "broker" not in response.text
    assert "storage" not in response.text
    assert body["projection"]["device"] is None


def test_a_source_that_answers_nothing_is_reported_as_unavailable() -> None:
    response, _app = _get(source=ProjectionSource(returns_none=True))

    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["reason"] == REASON_SOURCE_FAILED


def test_raw_process_material_cannot_reach_the_response_even_if_a_source_carries_it() -> None:
    source = ProjectionSource(
        result={
            "argv": ["cmd.exe", "/c", "dir"],
            "command": "Get-ChildItem C:\\Users",
            "stderr": "C:\\Users\\secret-path",
            "stdout": "bearer-abc123",
            "credentials": {"access_token": "bearer-abc123"},
            "stack": "Traceback (most recent call last)",
        }
    )

    response, _app = _get(source=source)

    assert response.status_code == 200
    for leak in ("cmd.exe", "Get-ChildItem", "secret-path", "bearer-abc123", "Traceback"):
        assert leak not in response.text, leak
    for key in ("argv", "command", "stderr", "stdout", "credentials", "stack", "token"):
        assert f'"{key}"' not in response.text, key


def test_an_over_length_handoff_is_dropped_while_the_device_truth_is_kept() -> None:
    source = ProjectionSource(result={"handoff_value": WIDE_HANDOFF})

    response, _app = _get(source=source)

    projection = response.json()["projection"]
    assert projection["device"]["usable"] is True
    assert "value" not in projection["handoff"]
    assert WIDE_HANDOFF[:40] not in response.text


def test_the_endpoint_is_registered_once_and_read_only() -> None:
    _response, app = _get()

    matches = [
        route
        for route in app.routes
        if getattr(route, "path", None) == CLAW_LOCAL_ACCESS_PATH
    ]
    assert len(matches) == 1
    methods = set(matches[0].methods or set())
    assert "GET" in methods
    assert methods <= {"GET", "HEAD"}, methods


def test_the_projection_response_is_not_cacheable_and_sends_no_referrer() -> None:
    response, _app = _get(source=ProjectionSource())

    assert "no-store" in response.headers["cache-control"]
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"


# ---------------------------------------------------------------------------
# G1/G2/G3 — the guarded adapter, executed with Node and no browser
# ---------------------------------------------------------------------------


def _node(script: str) -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to run the Web adapter outside a browser")
    completed = subprocess.run(
        [node, "-e", script],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr.strip()[:2000]
    return completed.stdout.strip()


def _expect_js(script: str) -> None:
    """Run a harness that prints ``[[name, passed], ...]``; fail on any false."""

    checks = json.loads(_node(script))
    assert [name for name, passed in checks if not passed] == []


# The adapter is an IIFE: without a `window` it exports the pure guard and the
# injectable factory, which is exactly the DOM-free surface these tests need.
PURE_PRELUDE = (
    f"require({json.dumps(str(ADAPTER_PATH))});\n"
    "const A = globalThis.PadiemClawLocalAdapter;\n"
    "const C = A.GUARD_REASON_CODES;\n"
    "const checks = [];\n"
    "const expect = (name, passed) => checks.push([name, Boolean(passed)]);\n"
    "const done = () => console.log(JSON.stringify(checks));\n"
)

# A proceedable live projection, and the click detail that belongs to it.
JS_MODEL = """
const VALUE = %s;
const model = (over = {}) => Object.assign({
  canProceed: true,
  showConnected: true,
  desktopInstalled: true,
  device: { usable: true, state: "CONNECTED" },
  handoff: { available: true, value: VALUE, kind: "deep_link" },
  identity: { conversationId: "conv_a", runId: "run_a", taskId: "task_a" },
}, over);
const detail = (over = {}) => Object.assign({
  handoffValue: VALUE,
  conversationId: "conv_a",
  runId: "run_a",
  taskId: "task_a",
}, over);
const decide = (over = {}) => A.evaluateActivation(Object.assign(
  { detail: detail(), viewModel: model(), userActivated: true },
  over,
));
""" % json.dumps(DESKTOP_HANDOFF)


def test_the_guard_opens_only_for_a_live_proceedable_activated_click() -> None:
    _expect_js(
        PURE_PRELUDE
        + JS_MODEL
        + """
const happy = decide();
expect("happy allowed", happy.allowed === true);
expect("happy code", happy.code === C.OK);
expect("happy value is verbatim", happy.value === VALUE);
expect("guard is total", Object.keys(C).length > 10);
done();
"""
    )


def test_the_guard_refuses_any_scheme_that_is_not_the_desktop_app() -> None:
    _expect_js(
        PURE_PRELUDE
        + JS_MODEL
        + """
const scheme = (value) => A.evaluateActivation({
  detail: detail({ handoffValue: value }),
  viewModel: model({ handoff: { available: true, value } }),
  userActivated: true,
}).code;
expect("https refused", scheme("https://evil.example/x") === C.UNSUPPORTED_SCHEME);
expect("javascript refused", scheme("javascript:alert(1)") === C.UNSUPPORTED_SCHEME);
expect("data refused", scheme("data:text/html,hello") === C.UNSUPPORTED_SCHEME);
expect("blob refused", scheme("blob:https://x/y") === C.UNSUPPORTED_SCHEME);
expect("file refused", scheme("file:///C:/windows/system32/cmd.exe") === C.UNSUPPORTED_SCHEME);
expect("scheme-less refused", scheme("local-handoff/no-scheme") === C.UNSUPPORTED_SCHEME);
expect("only padiem is allowed", A.ALLOWED_HANDOFF_SCHEMES.join("|") === "padiem:");
expect("allow list is frozen", Object.isFrozen(A.ALLOWED_HANDOFF_SCHEMES) === true);
done();
"""
    )


def test_the_guard_refuses_a_projection_that_no_longer_supports_the_click() -> None:
    _expect_js(
        PURE_PRELUDE
        + JS_MODEL
        + """
const code = (modelOver, detailOver = {}, userActivated = true) => A.evaluateActivation({
  detail: detail(detailOver), viewModel: model(modelOver), userActivated,
}).code;

expect("no live model", A.evaluateActivation({
  detail: detail(), viewModel: null, userActivated: true,
}).code === C.STALE_PROJECTION);
expect("handoff withdrawn", code({ handoff: { available: false, reason: "unsupported_kind" } })
  === C.HANDOFF_MISMATCH);
expect("handoff rotated", code({ handoff: { available: true, value: "padiem://local-handoff/other" } })
  === C.HANDOFF_MISMATCH);
expect("forged value cannot ride a proceedable panel", code({}, { handoffValue: "padiem://local-handoff/forged" })
  === C.HANDOFF_MISMATCH);
expect("proceed revoked", code({ canProceed: false }) === C.NOT_PROCEEDABLE);
expect("device unusable", code({ device: { usable: false, state: "CONNECTED" } }) === C.NOT_PROCEEDABLE);
expect("offline device", code({
  canProceed: false, showConnected: false, device: { usable: false, state: "OFFLINE" },
}) === C.NOT_PROCEEDABLE);
expect("connected banner withdrawn", code({ showConnected: false }) === C.NOT_PROCEEDABLE);
expect("desktop unregistered", code({ desktopInstalled: false }) === C.DESKTOP_NOT_INSTALLED);
expect("device material absent", code({ device: undefined }) === C.NOT_PROCEEDABLE);

expect("projection without identity", code({ identity: {} }) === C.IDENTITY_MISMATCH);
expect("click from another conversation", code({}, { conversationId: "conv_b" }) === C.IDENTITY_MISMATCH);
expect("click without conversation", code({}, { conversationId: null }) === C.IDENTITY_MISMATCH);
expect("click from another run", code({}, { runId: "run_b" }) === C.IDENTITY_MISMATCH);
expect("click from another task", code({}, { taskId: "task_b" }) === C.IDENTITY_MISMATCH);
expect("run id absent on event is tolerated", A.evaluateActivation({
  detail: { handoffValue: VALUE, conversationId: "conv_a" },
  viewModel: model(), userActivated: true,
}).allowed === true);

expect("without user activation", code({}, {}, false) === C.NOT_USER_ACTIVATED);
expect("activation defaults to refused", A.evaluateActivation({
  detail: detail(), viewModel: model(),
}).code === C.NOT_USER_ACTIVATED);
done();
"""
    )


def test_the_adapter_reads_only_the_one_endpoint_and_projects_what_it_returns() -> None:
    _expect_js(
        PURE_PRELUDE
        + JS_MODEL
        + """
const envelope = {
  conversationId: "conv_a", runId: "run_a", taskId: "task_a",
  requiresLocalAccess: true, requiredCapabilities: ["local_computer"],
  desktopInstalled: true,
  device: { state: "CONNECTED", usable: true, deviceName: "pc", platform: "windows" },
  handoff: { kind: "deep_link", value: VALUE, conversationId: "conv_a" },
};
const response = (body) => ({ ok: true, json: async () => body });

(async () => {
  const calls = [];
  const projected = [];
  const seam = {
    project: (value) => projected.push(value),
    getViewModel: () => null,
    getConversationId: () => "conv_a",
  };
  const adapter = A.createLocalHandoffAdapter({
    getSeam: () => seam,
    getConversationId: () => "conv_a",
    fetcher: async (url, init) => {
      calls.push([url, init]);
      return response({ ok: true, available: true, projection: envelope });
    },
  });

  const result = await adapter.refresh();
  expect("refresh is ok", result.code === C.OK);
  expect("exactly one call", calls.length === 1);
  expect("one endpoint only", calls[0][0] === A.LOCAL_ACCESS_ENDPOINT + "?conversationId=conv_a");
  expect("read only", calls[0][1].method === "GET");
  expect("same origin", calls[0][1].credentials === "same-origin");
  expect("uncached", calls[0][1].cache === "no-store");
  expect("server envelope is projected untouched", projected[0] === envelope);
  expect("result carries identity",
    result.conversationId === "conv_a" && result.runId === null);
  expect("nothing is persisted", !globalThis.localStorage && !globalThis.sessionStorage);

  const hung = [];
  const hungAdapter = A.createLocalHandoffAdapter({
    getSeam: () => ({ project: (value) => hung.push(value) }),
    getConversationId: () => "conv_a",
    fetcher: async () => ({ ok: false, json: async () => ({}) }),
  });
  expect("http failure", (await hungAdapter.refresh()).code === C.SOURCE_UNAVAILABLE);
  expect("failure hides panel", hung[0] && Object.keys(hung[0]).length === 0);

  const threw = [];
  const throwAdapter = A.createLocalHandoffAdapter({
    getSeam: () => ({ project: (value) => threw.push(value) }),
    getConversationId: () => "conv_a",
    fetcher: async () => { throw new Error("network down"); },
  });
  expect("transport failure", (await throwAdapter.refresh()).code === C.SOURCE_UNAVAILABLE);
  expect("transport failure hides panel", threw[0] && Object.keys(threw[0]).length === 0);

  const malformed = [];
  const malformedAdapter = A.createLocalHandoffAdapter({
    getSeam: () => ({ project: (value) => malformed.push(value) }),
    getConversationId: () => "conv_a",
    fetcher: async () => response({ ok: false, error: { code: "boom" } }),
  });
  expect("rejected envelope", (await malformedAdapter.refresh()).code === C.SOURCE_UNAVAILABLE);
  expect("rejected envelope hides panel",
    malformed[0] && Object.keys(malformed[0]).length === 0);

  const unconfigured = [];
  const unconfiguredAdapter = A.createLocalHandoffAdapter({
    getSeam: () => ({ project: (value) => unconfigured.push(value) }),
    getConversationId: () => "conv_a",
    fetcher: async () => response({
      ok: true, available: false, reason: "local_access_unconfigured",
      projection: { conversationId: "conv_a", device: null, handoff: { kind: "deep_link" } },
    }),
  });
  expect("unconfigured server", (await unconfiguredAdapter.refresh()).code === C.SOURCE_UNAVAILABLE);
  expect("unconfigured projects nothing known",
    unconfigured[0] && unconfigured[0].device === null);

  const none = [];
  const noneAdapter = A.createLocalHandoffAdapter({
    getSeam: () => ({ project: (value) => none.push(value) }),
    getConversationId: () => () => null,
  });
  expect("no conversation", (await noneAdapter.refresh()).code === C.NO_CONVERSATION);
  expect("no conversation hides panel", none[0] && Object.keys(none[0]).length === 0);

  const gated = [];
  const painted = [];
  const racing = A.createLocalHandoffAdapter({
    getSeam: () => ({ project: (value) => painted.push(value) }),
    getConversationId: () => "conv_a",
    fetcher: () => new Promise((resolve) => gated.push(resolve)),
  });
  const stale = racing.refresh();
  const current = racing.refresh();
  gated[1](response({
    ok: true, available: true,
    projection: { conversationId: "conv_a", device: { state: "OFFLINE", usable: false } },
  }));
  expect("newer lands", (await current).code === C.OK);
  gated[0](response({ ok: true, available: true, projection: envelope }));
  expect("older is dropped", (await stale).code === C.SUPERSEDED);
  expect("stale device state never painted",
    painted.length === 1 && painted[0].device.state === "OFFLINE");
  done();
})();
"""
    )


def test_the_adapter_opens_once_from_activation_and_reports_only_a_reason() -> None:
    _expect_js(
        PURE_PRELUDE
        + JS_MODEL
        + """
(async () => {
  const opened = [];
  const events = [];
  const seam = { project: () => {}, getViewModel: () => model(), getConversationId: () => "conv_a" };
  const adapter = A.createLocalHandoffAdapter({
    getSeam: () => seam,
    opener: (value) => opened.push(value),
    dispatch: (name, detail) => events.push([name, detail]),
    isUserActivated: () => true,
  });

  expect("opens", (await adapter.activate(detail())).code === C.OK);
  expect("opened exactly once with the live value",
    opened.length === 1 && opened[0] === VALUE);
  expect("lastResult readable", adapter.lastResult().ok === true);
  expect("replayed event refused",
    (await adapter.activate(detail())).code === C.ALREADY_ACTIVATED && opened.length === 1);
  expect("drive-by refused",
    (await adapter.activate(detail(), { userActivated: false })).code === C.NOT_USER_ACTIVATED
      && opened.length === 1);
  expect("result event name", events[0][0] === "padiem:claw-local-adapter-result");
  expect("result is bounded",
    Object.keys(events[0][1]).join(",") === "ok,code,conversationId,runId,taskId");
  expect("handoff value never enters the reported result",
    JSON.stringify(events).indexOf(VALUE) === -1);

  const noSeam = A.createLocalHandoffAdapter({
    getSeam: () => null, opener: () => {}, isUserActivated: () => true,
  });
  expect("no seam refuses open", (await noSeam.activate(detail())).code === C.STALE_PROJECTION);

  const throwing = A.createLocalHandoffAdapter({
    getSeam: () => seam, opener: () => { throw new Error("no OS handler yet"); },
    isUserActivated: () => true,
  });
  expect("failed open is only reported", (await throwing.activate(detail())).code === C.OPEN_FAILED);

  const rejecting = A.createLocalHandoffAdapter({
    getSeam: () => seam, opener: async () => { throw new Error("refused"); },
    isUserActivated: () => true,
  });
  expect("rejected open is only reported",
    (await rejecting.activate(detail())).code === C.OPEN_FAILED);

  const missing = A.createLocalHandoffAdapter({ getSeam: () => seam, isUserActivated: () => true });
  expect("missing opener refuses", (await missing.activate(detail())).code === C.OPEN_FAILED);

  const awaited = [];
  const asyncOpener = A.createLocalHandoffAdapter({
    getSeam: () => seam,
    opener: async (value) => { await Promise.resolve(); awaited.push(value); },
    isUserActivated: () => true,
  });
  expect("async open is awaited before reporting",
    (await asyncOpener.activate(detail())).code === C.OK && awaited.length === 1);
  done();
})();
"""
    )

def test_a_click_carried_over_from_an_abandoned_conversation_is_refused() -> None:
    _expect_js(
        PURE_PRELUDE
        + JS_MODEL
        + """
(async () => {
  const opened = [];
  const urls = [];
  const seam = { project: () => {}, getViewModel: () => model() };
  let live = "conv_b";
  const adapter = A.createLocalHandoffAdapter({
    getSeam: () => seam,
    getConversationId: () => live,
    opener: (value) => opened.push(value),
    isUserActivated: () => true,
    fetcher: (url) => {
      urls.push(url);
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          ok: true,
          available: true,
          projection: { conversationId: "conv_b", device: { state: "CONNECTED", usable: true } },
        }),
      });
    },
  });

  // The panel still holds conv_a's projection while the user is already in
  // conv_b: the handoff is valid, the projection is live, and it is still the
  // wrong conversation, so nothing may be opened.
  const outcome = await adapter.activate(detail());
  expect("carried-over handoff never opens the app", opened.length === 0);
  expect("refusal is only a reason code", outcome.code === C.CONVERSATION_STALE);
  expect("refusal carries no handoff value", JSON.stringify(outcome).indexOf(VALUE) === -1);
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect("fresh truth was requested for the live conversation",
    urls.length === 1 && urls[0].indexOf("conversationId=conv_b") !== -1);

  live = "conv_a";
  expect("the click proceeds once the projection belongs to this conversation again",
    (await adapter.activate(detail())).code === C.OK && opened.length === 1);
  done();
})();
"""
    )




# The browser-shaped harness: a fake window, the real #3084 module, and the real
# JSON this slice's route serves. Neither the panel nor the guard is mocked here.
BROWSER_ENV = """
global.window = globalThis;
const bus = new EventTarget();
globalThis.addEventListener = (name, handler) => bus.addEventListener(name, handler);
globalThis.dispatchEvent = (event) => bus.dispatchEvent(event);
global.document = { readyState: 'complete', visibilityState: 'visible', addEventListener() {} };
const opened = [];
global.location = { assign: (value) => opened.push(value) };
globalThis.__served = [];
globalThis.fetch = async () => {
  const body = globalThis.__served.shift();
  return { ok: true, json: async () => body };
};
"""

# Wiring happens only after the constants exist, because the module's own
# first refresh already asks the seam who is talking.
BROWSER_WIRING = """
require(BROWSER_HANDOFF);
const H = globalThis.PadiemClawLocalHandoff;
const seam = {
  project(input) { this.model = H.deriveHandoffViewModel(input); },
  getViewModel() { return this.model || null; },
  getConversationId() { return CONV; },
};
globalThis.__padiemClawLocalHandoff = seam;
require(BROWSER_ADAPTER);
const A = globalThis.PadiemClawLocalAdapter;
const C = A.GUARD_REASON_CODES;
const panel = globalThis.__padiemClawLocalAdapter;
const checks = [];
const expect = (name, passed) => checks.push([name, Boolean(passed)]);
const done = () => console.log(JSON.stringify(checks));
"""
BROWSER_WIRING = BROWSER_WIRING.replace("BROWSER_HANDOFF", json.dumps(str(HANDOFF_PATH))).replace("BROWSER_ADAPTER", json.dumps(str(ADAPTER_PATH)))


def test_the_projection_this_route_serves_drives_the_real_panel_end_to_end() -> None:
    """Serve this route's own bytes into the real #3084 module and real adapter."""

    available, _app = _get(source=ProjectionSource())
    unconfigured, _app = _get(source=ProjectionSource(returns_none=True))

    _expect_js(
        BROWSER_ENV
        + "const AVAILABLE = "
        + available.text
        + ";\nconst UNCONFIGURED = "
        + unconfigured.text
        + ";\nconst PY_VALUE = "
        + json.dumps(DESKTOP_HANDOFF)
        + ";\nconst CONV = "
        + json.dumps(CONVERSATION_ID)
        + ";\nconst RUN = "
        + json.dumps(RUN_ID)
        + ";\nconst TASK = "
        + json.dumps(TASK_ID)
        + ";\n"
        + BROWSER_WIRING
        + """
(async () => {
  globalThis.__served.push(AVAILABLE);
  const refreshed = await panel.refresh(CONV);
  const model = seam.getViewModel();
  expect("refresh ok", refreshed.ok === true);
  expect("panel shows connected", model.showConnected === true);
  expect("panel may proceed", model.canProceed === true);
  expect("device state came from the server", model.device.state === "CONNECTED");
  expect("identity survived", model.identity.conversationId === CONV);
  expect("no identity mismatch", model.identityMismatch === false);
  expect("handoff offered",
    model.handoff.available === true && model.handoff.value === PY_VALUE);

  const click = { conversationId: CONV, runId: RUN, taskId: TASK, handoffValue: model.handoff.value };
  expect("proceed opens the desktop app",
    (await panel.activate(click, { userActivated: true })).ok === true);
  expect("one navigation with the served value",
    opened.length === 1 && opened[0] === PY_VALUE);

  expect("drive-by is refused",
    (await panel.activate(click, { userActivated: false })).ok === false);
  expect("still only one navigation", opened.length === 1);

  globalThis.__served.push(UNCONFIGURED);
  await panel.refresh(CONV);
  const after = seam.getViewModel();
  expect("panel no longer claims connected", after.showConnected === false);
  expect("panel no longer proceeds", after.canProceed === false);
  expect("handoff withdrawn", after.handoff.available === false);
  expect("stale click cannot open",
    (await panel.activate(click, { userActivated: true })).ok === false);
  expect("no navigation after withdrawal", opened.length === 1);
  done();
})();
"""
    )






def test_the_guard_refuses_bad_handoff_material_before_anything_else() -> None:
    _expect_js(
        PURE_PRELUDE
        + JS_MODEL
        + """
const bad = (value) => A.evaluateActivation({
  detail: detail({ handoffValue: value }), viewModel: model(), userActivated: true,
}).code;
const exactly_max = "padiem:" + "a".repeat(A.MAX_HANDOFF_LENGTH - 7);
expect("absent", bad(undefined) === C.HANDOFF_ABSENT);
expect("empty", bad("") === C.HANDOFF_ABSENT);
expect("whitespace", bad("   ") === C.HANDOFF_ABSENT);
expect("non-string", bad({ value: VALUE }) === C.HANDOFF_ABSENT);
expect("over length", bad("padiem://h/" + "a".repeat(600)) === C.HANDOFF_OVER_LENGTH);
expect("one under max still allowed", A.evaluateActivation({
  detail: detail({ handoffValue: exactly_max }),
  viewModel: model({ handoff: { available: true, value: exactly_max } }),
  userActivated: true,
}).allowed === true);
expect("leading space", bad(" " + VALUE) === C.HANDOFF_MALFORMED);
expect("trailing newline", bad(VALUE + "\\n") === C.HANDOFF_MALFORMED);
expect("nul byte", bad(VALUE + "\\u0000") === C.HANDOFF_MALFORMED);
done();
"""
    )







def test_a_cross_origin_post_cannot_smuggle_a_local_command() -> None:
    """The endpoint has no mutation surface, so a forged request hits nothing at all."""

    source = ProjectionSource()
    settings = _settings()
    app = create_app(settings, history_store=MagicMock())
    app.state.claw_local_access_source = source

    async def run() -> tuple[int, str]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            client.cookies.set(SESSION_COOKIE, create_session_token(settings, USER_ID))
            response = await client.post(
                CLAW_LOCAL_ACCESS_PATH,
                params={"conversationId": CONVERSATION_ID},
                json={
                    "canonicalState": DeviceLifecycle.ONLINE.value,
                    "handoffValue": DESKTOP_HANDOFF,
                },
                headers={"Origin": "https://attacker.example.test"},
            )
            return response.status_code, response.text

    status, body = asyncio.run(run())

    assert status == 405
    assert source.calls == []
    assert DESKTOP_HANDOFF not in body


def test_the_adapter_is_wired_last_and_holds_no_state_of_its_own() -> None:
    """Nothing but the live projection may drive the panel, and nothing may persist."""

    scripts = re.findall(
        r'<script[^>]*src="\./([^"]+)"',
        INDEX_PATH.read_text(encoding="utf-8"),
    )
    assert "claw-local-handoff.js" in scripts
    assert scripts[-1] == "claw-local-adapter.js", scripts[-1:]

    adapter = ADAPTER_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "document.cookie",
        "Date.now",
        "Math.random",
        "handoffToken",
        "XMLHttpRequest",
        "atob(",
        "btoa(",
        "http://",
        "https://",
    ):
        assert forbidden not in adapter, forbidden
    assert adapter.count("fetch(") == 1
    assert adapter.count(f'"{CLAW_LOCAL_ACCESS_PATH}"') == 1

    # The panel surface keeps owning rendering and never learns to fetch truth.
    app_js = APP_JS_PATH.read_text(encoding="utf-8")
    assert CLAW_LOCAL_ACCESS_PATH not in app_js
    assert "padiem:claw-local-connect-requested" in app_js

    # The server, not the page, decides who may serve this truth.
    factory = FACTORY_PATH.read_text(encoding="utf-8")
    assert "claw_local_access_source=None" in factory


def test_the_shipped_script_joins_the_existing_syntax_gate_and_nothing_else() -> None:
    """A new shipped script must be parsed by CI, and must not touch deployment."""

    workflow = (
        APP_ROOT.parent.parent / ".github" / "workflows" / "b62-padiem-chat-ci.yml"
    ).read_text(encoding="utf-8")
    assert "node --check static/claw-local-adapter.js" in workflow
    assert workflow.count("wrangler deploy") == 1, "a deploy step was added or removed"

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to parse the Web adapter")
    checked = subprocess.run([node, "--check", str(ADAPTER_PATH)], capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr.strip()[:500]


