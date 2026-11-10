"""#7078: every client moves to the common login when the switch says so.

The web/admin/native clients are source-checked here because only the web module
has a browser-free unit harness. The React clone has its own vitest case.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
AUTH_JS = STATIC / "chat-auth-module.js"
ADMIN_JS = STATIC / "admin-model-ext.js"
NATIVE = ROOT.parent / "padiem-chat-claw-native" / "src" / "auth" / "AuthContext.tsx"
MESSAGE = "로그인 방식이 바뀌었어요. 공통 로그인으로 이동합니다"


def test_web_login_and_register_follow_the_switch_login_url():
    node = shutil.which("node")
    assert node, "node is required for the browser-module contract"
    harness = textwrap.dedent(
        r"""
        const assert = require("node:assert/strict");
        const fs = require("node:fs");
        const vm = require("node:vm");
        const source = fs.readFileSync(process.argv[process.argv.length - 1], "utf8");
        const notes = [];
        const location = { assigned: null, assign(url) { this.assigned = url; } };
        const ctx = {
          window: null,
          document: { documentElement: { lang: "ko" } },
          fetch: async (path) => ({
            ok: false,
            status: 409,
            json: async () => ({
              error: { code: "email_login_moved", message: "moved" },
              login_url: "/auth/shared/start",
            }),
          }),
          setTimeout, clearTimeout, console, Error, Object, Array, String,
          Number, Boolean, Promise, Map, Set, JSON, Date, URL,
        };
        ctx.window = ctx;
        ctx.location = location;
        vm.createContext(ctx);
        vm.runInContext(source, ctx);
        const deps = {
          authMethodEnabled: () => true,
          passwordLoginForm: {},
          passwordLoginError: {},
          passwordLoginSubmit: { disabled: false },
          passwordLoginIdentifier: { value: "owner@example.test" },
          passwordLoginPassword: { value: "not-real" },
          passwordRegisterForm: {},
          passwordRegisterError: {},
          passwordRegisterSubmit: { disabled: false },
          passwordRegisterEmail: { value: "new@example.test" },
          passwordRegisterName: { value: "N" },
          passwordRegisterPassword: { value: "not-real" },
          authHandoff: null,
          setAuthFormError: (node, message) => notes.push(String(message)),
          uiT: (key) => key === "auth-email-login-moved"
            ? "로그인 방식이 바뀌었어요. 공통 로그인으로 이동합니다" : key,
          closeAuthDialog: () => {},
          loadAuthStatus: async () => {},
          AUTH_UNREACHABLE_RETRY_DELAY_MS: 0,
        };
        const api = ctx.window.PadiemChatAuthModule.create(deps);
        deps.passwordAuthRequest = api.passwordAuthRequest;
        deps.passwordAuthAnswer = api.passwordAuthAnswer;
        (async () => {
          await api.submitPasswordLogin({ preventDefault() {} });
          assert.equal(location.assigned, "/auth/shared/start");
          assert.equal(notes.at(-1), "로그인 방식이 바뀌었어요. 공통 로그인으로 이동합니다");
          location.assigned = null;
          await api.submitPasswordRegister({ preventDefault() {} });
          assert.equal(location.assigned, "/auth/shared/start");
          assert.equal(notes.at(-1), "로그인 방식이 바뀌었어요. 공통 로그인으로 이동합니다");
          console.log(JSON.stringify({ ok: true }));
        })().catch((error) => { console.error(error); process.exit(1); });
        """
    )
    completed = subprocess.run(
        [node, "-e", harness, str(AUTH_JS)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(completed.stdout.strip().splitlines()[-1]) == {"ok": True}


def test_admin_reauth_follows_the_switch_login_url():
    source = ADMIN_JS.read_text(encoding="utf-8")
    assert 'data?.error?.code === "email_login_moved"' in source
    assert 'window.location.assign(data.login_url)' in source
    assert MESSAGE in source


def test_native_login_opens_the_common_login():
    source = NATIVE.read_text(encoding="utf-8")
    assert "email_login_moved" in source
    assert "Linking.openURL" in source
    assert "DEFAULT_API_BASE_URL" in source
    assert MESSAGE in source


def test_web_message_key_exists_in_both_languages():
    locale = (STATIC / "locale.js").read_text(encoding="utf-8")
    assert locale.count('"auth-email-login-moved"') == 2
