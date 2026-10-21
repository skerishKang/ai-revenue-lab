"""#5034 — the browser side of the Web Push opt-in.

Two contracts are pinned here:

- the server reports the push capability truthfully (with no push authority
  configured the answer is ``enabled=false``, so the browser is not offered a
  toggle that could never deliver);
- the browser module never breaks the web inbox: a denied, unsupported or
  unconfigured push is a bounded state, and a successful opt-in registers the
  device with the existing server subscription surface.

The browser part runs in Node with a small fake browser, so no real push
provider, no real subscription and no network is involved.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

CAPABILITY_PATH = "/api/claw/inbox/push/capability"
SIGNED_IN_USER_ID = "usr_" + "7" * 32


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="claw-push-cap-client.apps.googleusercontent.com",
        google_client_secret="claw-push-cap-google-secret",
        session_secret="claw-push-cap-session-secret-not-real-00000",
        session_max_age_seconds=3600,
    )


def _client() -> TestClient:
    settings = _settings()
    app = create_app(settings=settings, history_store=MagicMock())
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(settings, SIGNED_IN_USER_ID),
        domain="chat.example.test",
        path="/",
    )
    return client


def test_the_capability_is_reported_truthfully_without_a_push_authority():
    with _client() as client:
        response = client.get(CAPABILITY_PATH)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    # No push authority is configured, so the honest answer is "not available".
    assert body["enabled"] is False
    assert body["public_key"] is None
    assert body["scope"] == "https://chat.example.test/"


def test_a_configured_public_key_is_advertised():
    settings = _settings()
    app = create_app(settings=settings, history_store=MagicMock())
    app.state.claw_push_public_key = "BO1x-public-key-value"
    with TestClient(app, base_url="https://chat.example.test") as client:
        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(settings, SIGNED_IN_USER_ID),
            domain="chat.example.test",
            path="/",
        )
        response = client.get(CAPABILITY_PATH)
    body = response.json()
    assert body["enabled"] is True
    assert body["public_key"] == "BO1x-public-key-value"


HARNESS = r"""
const fs = require("fs");
const vm = require("vm");

const PUSH = process.env.PUSH_MODULE;
const scenario = process.env.PUSH_SCENARIO;

function makeResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

const state = {
  calls: [],
  permission: scenario === "denied" ? "denied" : "granted",
  supported: scenario !== "unsupported",
  capability: scenario === "not_configured"
    ? { ok: true, enabled: false, public_key: null }
    : { ok: true, enabled: true, public_key: "BPublicKeyValue", scope: "https://chat.example.test/" },
  registered: false,
  subscribed: false,
  unsubscribed: false,
};

const sandbox = {
  console,
  setTimeout,
  btoa: (value) => Buffer.from(value, "binary").toString("base64"),
  atob: (value) => Buffer.from(value, "base64").toString("binary"),
  Uint8Array,
  fetch: async (url, options) => {
    state.calls.push({ url, method: (options && options.method) || "GET" });
    if (url.indexOf("/capability") >= 0) return makeResponse(200, state.capability);
    if (url.indexOf("/subscription") >= 0) return makeResponse(200, { ok: true });
    return makeResponse(404, {});
  },
  navigator: {
    get permissions() {
      return {
        query: async () => ({ state: state.permission }),
        request: async () => {
          state.calls.push({ url: "permission", method: "request" });
          return state.permission;
        },
      };
    },
    get serviceWorker() {
      if (!state.supported) return undefined;
      return {
        register: async (path, options) => {
          state.calls.push({ url: path, method: "register" });
          state.registered = true;
          return { scope: options.scope };
        },
        ready: Promise.resolve({
          pushManager: {
            subscribe: async (options) => {
              state.calls.push({ url: "subscribe", method: "subscribe" });
              state.subscribed = true;
              return {
                toJSON: () => ({
                  endpoint: "https://push.example.test/device/abc",
                  keys: { p256dh: "p256dh-key", auth: "auth-secret" },
                }),
              };
            },
            getSubscription: async () => ({
              unsubscribe: async () => { state.unsubscribed = true; },
            }),
          },
        }),
      };
    },
    get PushManager() {
      return state.supported ? function () {} : undefined;
    },
  },
};
sandbox.window = sandbox;
sandbox.self = sandbox;

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(PUSH, "utf8"), sandbox, { filename: "claw-push.js" });

(async () => {
  const api = sandbox.window.PadiemClawPush;
  let result = null;
  if (scenario === "disable") {
    result = await api.disable("push_existing_id");
  } else {
    result = await api.enable();
  }
  process.stdout.write(JSON.stringify({
    result,
    calls: state.calls,
    registered: state.registered,
    subscribed: state.subscribed,
    unsubscribed: state.unsubscribed,
  }));
})().catch((error) => {
  process.stderr.write(String(error && error.stack ? error.stack : error));
  process.exit(1);
});
"""


def _run_client(scenario: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is unavailable")
    directory = Path(tempfile.mkdtemp(prefix="5034-push-"))
    harness = directory / "harness.cjs"
    harness.write_text(HARNESS, encoding="utf-8")
    environment = {
        "PATH": __import__("os").environ.get("PATH", ""),
        "PUSH_MODULE": str(STATIC / "claw-push.js"),
        "PUSH_SCENARIO": scenario,
    }
    result = subprocess.run(
        [node, str(harness)],
        capture_output=True,
        text=True,
        timeout=60,
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_an_unsupported_browser_reports_unsupported_and_never_registers():
    out = _run_client("unsupported")
    assert out["result"]["state"] == "unsupported"
    assert out["registered"] is False
    assert out["subscribed"] is False


def test_a_denied_permission_reports_denied_and_never_registers():
    out = _run_client("denied")
    assert out["result"]["state"] == "denied"
    assert out["registered"] is False
    assert out["subscribed"] is False


def test_a_server_without_a_push_authority_reports_not_configured():
    out = _run_client("not_configured")
    assert out["result"]["state"] == "not_configured"
    assert out["registered"] is False
    assert out["subscribed"] is False


def test_an_opted_in_browser_registers_the_device_with_the_existing_surface():
    out = _run_client("granted")
    assert out["result"]["state"] == "ready"
    assert out["registered"] is True
    assert out["subscribed"] is True
    urls = [call["url"] for call in out["calls"]]
    assert any("/capability" in url for url in urls)
    assert any("/subscription" in url for url in urls)
    # The service worker is registered from the site origin.
    assert any(call.get("method") == "register" for call in out["calls"])


def test_opting_out_removes_the_server_side_subscription():
    out = _run_client("disable")
    assert out["result"]["ok"] is True
    deletes = [
        call for call in out["calls"]
        if call.get("method") == "DELETE" and "/subscription" in call["url"]
    ]
    assert deletes, out["calls"]


def test_the_client_never_owns_a_notification():
    """The web inbox stays the authority: the client only reports a state."""
    source = (STATIC / "claw-push.js").read_text(encoding="utf-8")
    # The module talks to the existing inbox surfaces only.
    assert "/api/claw/inbox/push/capability" in source
    assert "/api/claw/inbox/push/subscription" in source
    # It never posts a notification of its own.
    assert "showNotification" not in source
    # The service worker shows what the inbox already persisted.
    worker = (STATIC / "claw-push-sw.js").read_text(encoding="utf-8")
    assert "showNotification" in worker
    assert "api/chat" not in worker
    assert "api/claw" not in worker
