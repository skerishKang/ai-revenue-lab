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
DIALOG_JS = STATIC / "chat-login-dialog-module.js"
INDEX = STATIC / "index.html"
ADMIN_JS = STATIC / "admin-model-ext.js"
NATIVE = ROOT.parent / "padiem-chat-claw-native" / "src" / "auth" / "AuthContext.tsx"
MESSAGE = "로그인 방식이 바뀌었어요. 공통 로그인으로 이동합니다"


def test_web_email_entry_is_a_link_to_the_common_login():
    # #7777: the dialog keeps no email/password inputs. The single email entry
    # is a plain link to the common login (Chat skin), so the web client never
    # sends a password body from this dialog.
    markup = INDEX.read_text(encoding="utf-8")
    assert 'id="passwordLoginContinue"' in markup
    assert 'href="/auth/shared/start"' in markup
    assert 'id="passwordLoginForm"' not in markup
    assert 'id="passwordRegisterSection"' not in markup
    source = AUTH_JS.read_text(encoding="utf-8")
    assert "submitPasswordLogin" not in source
    assert "submitPasswordRegister" not in source


def test_web_server_gate_still_moves_old_screens_to_the_common_login():
    # The server 409 gate stays for old screens: an old browser that still
    # posts to the password endpoints is moved to the common login.
    node = shutil.which("node")
    assert node, "node is required for the browser-module contract"
    harness = textwrap.dedent(
        r"""
        const assert = require("node:assert/strict");
        const fs = require("node:fs");
        const vm = require("node:vm");
        const source = fs.readFileSync(process.argv[process.argv.length - 1], "utf8");
        const location = { assigned: null, assign(url) { this.assigned = url; } };
        const ctx = {
          window: null,
          document: { documentElement: { lang: "ko" }, getElementById: () => null, createElement: () => ({ append() {}, setAttribute() {}, dataset: {}, hidden: true }) },
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
        vm.runInContext(fs.readFileSync(process.argv[process.argv.length - 2], "utf8"), ctx);
        const deps = {
          uiT: (key) => key,
          AUTH_UNREACHABLE_RETRY_DELAY_MS: 0,
        };
        const dialogDeps = { uiT: (key) => key, renderAndroidHandoff() {} };
        const api = ctx.window.PadiemChatLoginDialogModule.create(dialogDeps);
        (async () => {
          // The reset paths still go through passwordAuthRequest, so a 409
          // there still carries the switch login url for an old screen.
          let caught = null;
          try {
            await api.passwordAuthRequest("/api/auth/password/reset/request", { email: "owner@example.test" });
          } catch (error) {
            caught = error;
          }
          assert.ok(caught, "the password request must surface the 409");
          assert.equal(caught.code, "email_login_moved");
          assert.equal(caught.loginUrl, "/auth/shared/start");
          console.log(JSON.stringify({ ok: true }));
        })().catch((error) => { console.error(error); process.exit(1); });
        """
    )
    completed = subprocess.run(
        [node, "-e", harness, str(DIALOG_JS), str(AUTH_JS)],
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
