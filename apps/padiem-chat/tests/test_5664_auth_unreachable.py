"""#5664 - a platform-level auth failure is not a rejected password.

**The production failure.** On 2026-10-24 a member clicked ``비밀번호 설정하기``
on the reset-confirm screen and the screen showed
``로그인 처리에 실패했습니다. 다시 시도해 주세요.`` The Chat Worker tail for the
same request recorded, on ``POST /api/auth/password/reset/confirm``:

* ``outcome=exception`` with ``cpuTime=1`` and ``wallTime=2`` (milliseconds),
* ``NoGilError: Attempted to use PyProxy when Python GIL not held`` raised in
  ``preparePython`` -> ``initPyInstance`` -> ``Proxy``, and
* a ``500 text/plain`` body of ``error code: 1101``.

The exception is raised by the Cloudflare runtime while it initializes a Python
instance (``cloudflare/workerd#6624``), so the route never ran: the reset token
stayed at ``attempts=0``/``consumed_at IS NULL``, the audit ledger recorded no
event after ``delivered``, and the account's stored password did not move. The
same tail window recorded the identical exception on ``/health``,
``/api/auth/status``, ``/api/admin/session`` and several ``/api/claw/*`` routes,
so the trigger is not this route and not this account.

**The client defect.** ``passwordAuthRequest`` parsed the body as JSON and, when
that failed, showed ``auth-error-generic``. A body the route never produced was
therefore presented as a failed sign-in, and a ``2xx`` whose body did not parse
would have been read as success. The member could not tell a rejected password
from a request that never reached the server.

**The contract pinned here.**

1. a response without the route's JSON envelope is ``auth_server_unreachable``
   with its own copy, never the generic sign-in message,
2. only the reset confirm replays it, exactly once, because its one-time token
   makes the replay apply at most once; every other auth write keeps one attempt,
3. a route answer, success or refusal, is final and never replayed,
4. a ``2xx`` without a route answer is never success.

The Node test evaluates the shipped ``static/app.js`` bytes; the tests below
pin the call sites and the copy that ships with them.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
APP_JS = STATIC / "app.js"
LOCALE_JS = STATIC / "locale.js"
NODE_TEST = ROOT / "tests" / "test_5664_auth_unreachable_node.mjs"


def test_the_shipped_auth_transport_contract():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")
    completed = subprocess.run(
        [node, "--test", str(NODE_TEST)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_only_the_reset_confirm_may_replay_a_platform_failure():
    app_js = APP_JS.read_text(encoding="utf-8")
    confirm = app_js.split('passwordAuthRequest("/api/auth/password/reset/confirm"', 1)
    assert len(confirm) == 2, "the reset confirm call site is missing"
    assert "{ retryUnreachable: true }" in confirm[1].split(");", 1)[0]
    for path in (
        "/api/auth/password/login",
        "/api/auth/password/register",
        "/api/auth/password/reset/request",
        "/api/auth/password/change",
    ):
        call = app_js.split(f'passwordAuthRequest("{path}"', 1)
        assert len(call) == 2, f"the {path} call site is missing"
        assert "retryUnreachable" not in call[1].split(");", 1)[0]


def test_the_unreachable_copy_is_not_the_generic_sign_in_message():
    source = LOCALE_JS.read_text(encoding="utf-8").split("const promptCopy", 1)[0]
    ko, en = source.split("\n    en: {")
    for block in (ko, en):
        assert '"auth-server-unreachable"' in block
        assert '"auth-error-generic"' in block
    assert "서버가 잠시" in ko.split('"auth-server-unreachable":', 1)[1].split("\n", 1)[0]
    assert "did not answer" in en.split('"auth-server-unreachable":', 1)[1].split("\n", 1)[0]


def test_the_worker_startup_race_is_documented_as_the_trigger():
    """The copy's reason is the runtime race, not a guess about the account."""
    app_js = APP_JS.read_text(encoding="utf-8")
    note = app_js.split("// #5664:", 1)[1].split("const AUTH_SERVER_UNREACHABLE", 1)[0]
    assert "NoGilError" in note
    assert "cloudflare/workerd#6624" in note
