"""#3933: the manual-intake Claw lane must not report a model HOLD as a failed run.

`POST /api/claw/manual-intake/execute` refuses a tier whose route is not
executable **before** it dispatches, and projects that pre-dispatch product state
as bounded ``503 tier_unavailable`` (``app/claw_routes.py``). The browser already
had one approved code→copy authority for that family
(``CLAW_BOUNDED_REFUSAL_COPY`` in ``static/app.js``), but
``safeClawErrorMessage()`` — the mapper the manual-intake lane uses — did not
consult it, so the user saw the generic "the run failed" sentence for a request
that never started.

Contract pinned here:

- the route really does refuse pre-dispatch with ``503 tier_unavailable``;
- ``safeClawErrorMessage`` resolves that code through the ONE shared authority, so
  the manual lane shows the same model guidance the composer and live SSE lanes
  already show;
- no second wording is invented (locale keys are reused verbatim, ko + en);
- an unlisted/spoofed code still gets the existing generic copy, and no raw server
  message, provider text or private code ever reaches the user.

Network-free and provider-free: the adapter is never reached, and no Engine, B14
or provider endpoint is contacted.
"""

from __future__ import annotations

import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings

APP_DIR = Path(__file__).resolve().parents[1]
STATIC = APP_DIR / "static"
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
LOCALE_JS = (STATIC / "locale.js").read_text(encoding="utf-8")

EXECUTE_PATH = "/api/claw/manual-intake/execute"
SIGNED_IN_USER_ID = "usr_" + "9" * 32

HOLD_MESSAGE_KEY = "claw-general-model-unavailable"
HOLD_NOTE_KEY = "claw-general-model-unavailable-note"
GENERIC_KEY = "claw-error-generic"


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="claw-hold-copy-client.apps.googleusercontent.com",
        google_client_secret="claw-hold-copy-google-secret",
        session_secret="claw-hold-copy-session-secret-not-a-real-credential",
        session_max_age_seconds=3600,
    )


class _AuthStore:
    async def get_user(self, user_id: str):
        return None

    async def get_conversation(self, user_id: str, conversation_id: str):
        return None


@contextmanager
def _client():
    app = create_app(settings=_settings(), history_store=_AuthStore())
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(_settings(), SIGNED_IN_USER_ID),
        domain="chat.example.test",
        path="/",
    )
    with client:
        yield client


def _payload(**extra) -> dict:
    payload = {"content": "A업체 견적 요청", "channel": "kakao", "action": "quote", "tier": "plus"}
    payload.update(extra)
    return payload


# ── server: the pre-dispatch refusal really is `503 tier_unavailable` ───────


def test_execute_route_refuses_model_unavailable_pre_dispatch_as_tier_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reproduce the exact server state the user-visible bug came from."""
    import app.claw_routes as claw_routes

    # No executable route for the selected tier -> the route's own pre-dispatch
    # refusal, exactly as a real unrouted tier behaves. Nothing is dispatched.
    monkeypatch.setattr(claw_routes, "active_route_for", lambda label: None)
    with _client() as client:
        response = client.post(EXECUTE_PATH, json=_payload())

    assert response.status_code == 503
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "tier_unavailable"
    # The public body carries no provider/Engine detail and no private code.
    for forbidden in ("tier_hold", "max_tier_hold", "P01", "kagent", "B14", "provider"):
        assert forbidden not in response.text, forbidden


def test_execute_route_projects_the_tier_config_failure_as_tier_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sibling pre-dispatch branch projects the same public code family."""
    import app.claw_routes as claw_routes
    from padiem_control_plane.product_tier_routes import ProductTierRoutesError

    def _raise(label):
        raise ProductTierRoutesError("no reviewed tier route table")

    monkeypatch.setattr(claw_routes, "active_route_for", _raise)
    with _client() as client:
        response = client.post(EXECUTE_PATH, json=_payload())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "tier_unavailable"


# ── client: the shared authority is the only copy source ───────────────────


def _safe_message_source() -> str:
    start = APP_JS.index("  function safeClawErrorMessage(")
    return APP_JS[start : APP_JS.index("\n  }", start) + 4]


def test_safe_message_mapper_consults_the_shared_bounded_refusal_authority() -> None:
    mapper = _safe_message_source()
    assert "clawBoundedRefusalCopy(code)" in mapper
    # The bounded branch must precede the generic fallback, so it can actually win.
    assert mapper.index("clawBoundedRefusalCopy(code)") < mapper.index(f'clawT("{GENERIC_KEY}")')
    # Reuse, never a second literal: no refusal sentence is inlined here.
    assert "사용할 수 없습니다" not in mapper
    assert HOLD_MESSAGE_KEY not in mapper


def test_the_execute_failure_branch_shows_the_not_executed_guidance() -> None:
    body = APP_JS[APP_JS.index("async function runClawExecution()"):]
    body = body[: body.index("if (clawExecuteButton) {")]
    assert "const boundedFailure = clawBoundedRefusalCopy(" in body
    assert "`${boundedFailure.message} ${boundedFailure.hint}`" in body
    # A bounded refusal is excluded from the uncertain-run latch at the call site.
    assert "else if (!boundedFailure && isAmbiguousClawFailure(data, response)) showClawAmbiguousRecoveryHint();" in body


def test_no_second_wording_or_locale_key_is_introduced() -> None:
    for key in (HOLD_MESSAGE_KEY, HOLD_NOTE_KEY):
        # Exactly one Korean and one English label per key: reused, not added.
        assert LOCALE_JS.count(f'"{key}":') == 2, key
    # The one code→copy map holds only the public refusal code.
    region = APP_JS[APP_JS.index("  const CLAW_BOUNDED_REFUSAL_COPY"):]
    region = region[: region.index("\n  function buildRetryBox(")]
    assert "tier_unavailable: Object.freeze({" in region
    for internal in ("tier_hold", "max_tier_hold", "engine_execution_failed"):
        assert internal not in region, internal


NODE = r"""
const fs = require("fs");
const vm = require("vm");
const path = require("path");
const root = process.argv[1];
const app = fs.readFileSync(path.join(root, "app.js"), "utf8");

function assert(condition, label) { if (!condition) throw Error(label); }

// The locale layer is stubbed to its identity function so the assertion is on the
// KEY the app selects, not on a copy this test would have to duplicate. A key
// returned verbatim proves the sentence is resolved by the shipped locale table.
let lang = "ko";
const context = {
  Object,
  window: {},
  document: { documentElement: { lang: "ko" } },
  uiT: (key) => lang + ":" + key,
  clawT: (key) => lang + ":" + key,
};

// The REAL map + helper + selector, and the REAL safeClawErrorMessage.
const mapStart = app.indexOf("  const CLAW_BOUNDED_REFUSAL_COPY");
const mapEnd = app.indexOf("\n  function buildRetryBox(", mapStart);
assert(mapStart >= 0 && mapEnd > mapStart, "map located");
const mapperStart = app.indexOf("  function safeClawErrorMessage(");
const mapperEnd = app.indexOf("\n  }", mapperStart) + 4;
assert(mapperStart >= 0 && mapperEnd > mapperStart, "mapper located");
const api = vm.runInNewContext(
  "(function(){" + app.slice(mapStart, mapEnd) + "\n" + app.slice(mapperStart, mapperEnd)
    + "\nreturn { clawBoundedRefusalCopy, clawGeneralFailure, safeClawErrorMessage };\n})()",
  context,
);

const HOLD_MESSAGE = "ko:claw-general-model-unavailable";
const GENERIC = "ko:claw-error-generic";
const call = (code, status, extra) =>
  api.safeClawErrorMessage({ error: Object.assign({ code }, extra) }, { status });

// 1. The HOLD code resolves to the bounded model copy for every status it can
//    arrive with, and never to the generic run-failure sentence.
for (const status of [503, 500, 0]) {
  assert(call("tier_unavailable", status) === HOLD_MESSAGE, "HOLD copy for status " + status);
  assert(call("tier_unavailable", status) !== GENERIC, "HOLD must not be the generic copy");
}

// 2. Both lanes now share one authority, so the wording cannot drift.
assert(api.clawGeneralFailure("tier_unavailable").message === call("tier_unavailable", 503),
  "manual lane and composer lane agree");

// 3. Locale-driven: the same key resolves per language, with no inlined sentence.
lang = "en";
assert(call("tier_unavailable", 503) === "en:claw-general-model-unavailable", "english HOLD copy");
assert(call("tier_unavailable", 503) !== HOLD_MESSAGE, "copy is not hardcoded");
lang = "ko";

// 4. Fail closed: an unlisted or spoofed code keeps the existing generic copy and
//    never selects copy through the prototype chain.
for (const spoof of ["", null, undefined, 0, {}, "tier_hold", "max_tier_hold",
                     "engine_execution_failed", "tier_unavailable ", "toString",
                     "constructor", "__proto__"]) {
  assert(call(spoof, 502) === GENERIC, "unlisted code stays generic: " + String(spoof));
}

// 5. A raw server string is never echoed: only the closed code is consulted.
const raw = "SECRET_PROVIDER_BODY tier_hold P01AdapterError";
assert(!call("tier_unavailable", 503, { message: raw }).includes("SECRET_PROVIDER_BODY"),
  "raw server message never surfaces");
assert(!api.safeClawErrorMessage({ error: { message: raw } }, { status: 503 })
  .includes("SECRET_PROVIDER_BODY"), "message without a code never surfaces");
assert(call("workspace_scope_unavailable", 503) === "ko:claw-error-auth-unavailable",
  "existing scope copy unchanged");

console.log("MANUAL_HOLD_COPY_FROM_SHARED_AUTHORITY=PASS");
console.log("MANUAL_HOLD_COPY_FAILS_CLOSED=PASS");
console.log("MANUAL_HOLD_COPY_LOCALE_DRIVEN=PASS");
console.log("MANUAL_HOLD_NO_RAW_SERVER_TEXT=PASS");
"""


def test_manual_intake_hold_copy_network_free_browser_behavior() -> None:
    if shutil.which("node") is None:
        pytest.skip("Node runtime unavailable; run CI for the behavioral browser contract")
    result = subprocess.run(
        ["node", "-e", NODE, str(STATIC)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for marker in (
        "MANUAL_HOLD_COPY_FROM_SHARED_AUTHORITY=PASS",
        "MANUAL_HOLD_COPY_FAILS_CLOSED=PASS",
        "MANUAL_HOLD_COPY_LOCALE_DRIVEN=PASS",
        "MANUAL_HOLD_NO_RAW_SERVER_TEXT=PASS",
    ):
        assert marker in result.stdout
