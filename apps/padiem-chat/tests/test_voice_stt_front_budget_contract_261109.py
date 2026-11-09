"""#7293 contract: the voice STT writes survive their own mint budget.

One incident, two sides, pinned together in one test:

* the front (apps/padiem-chat-front) used to cut ``POST /api/voice/live-token``
  with the generic 8s write window while the host was still minting — the
  host's own journal shows a 200 answered at 7.575s on 2026-11-09 (and healthy
  mints of 5.7s before that), so the browser saw ``upstream_timeout`` for a
  token that existed. The mint rides the host→Chat-Worker RPC plus the STT
  Worker's bounded upstream call, so the front gives the two voice STT writes
  their own 30s allowance, exactly like the login write (#6957).
* the Chat route itself (apps/padiem-chat/app/voice_stt_routes.py) never
  produces a 504: its fail-closed statuses are 400/401/403/413/415/502/503.
  If a 504 shows up on this path again it can only come from the front, and
  the front half of this test is what guards that.

No network, no credential: both halves are source pins plus a synthetic
front run, mirroring test_auth_write_timeout.test.mjs.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent
while REPO != REPO.parent and not (REPO / "apps" / "padiem-chat-front" / "worker.mjs").exists():
    REPO = REPO.parent
FRONT = REPO / "apps" / "padiem-chat-front"
ROUTES = REPO / "apps" / "padiem-chat" / "app" / "voice_stt_routes.py"

VOICE_STT_WRITE_PATHS = ("/api/voice/live-token", "/api/voice/transcribe")


def _front_source() -> str:
    return (FRONT / "worker.mjs").read_text(encoding="utf-8")


def test_front_gives_the_voice_stt_writes_their_own_allowance():
    source = _front_source()
    assert re.search(r"DEFAULT_VOICE_STT_WRITE_TIMEOUT_MS = 30000", source), (
        "front must declare a 30s default for the voice STT writes")
    for path in VOICE_STT_WRITE_PATHS:
        assert path in source, f"front must branch on {path}"


def test_front_default_is_declared_in_wrangler():
    toml = (FRONT / "wrangler.toml").read_text(encoding="utf-8")
    assert re.search(r'VOICE_STT_WRITE_TIMEOUT_MS = "30000"', toml), (
        "wrangler.toml must declare the same contract the worker defaults to")


def test_voice_live_token_write_is_not_cut_by_the_generic_window():
    """Synthetic front run: a 60ms mint against a 10ms generic window.

    The old shape answered 504 upstream_timeout here; the allowance lets the
    mint finish. Mirrors test_auth_write_timeout.test.mjs.
    """
    import subprocess

    script = (
        "const { createFront } = await import('./worker.mjs');"
        " const sign = async (request) => new Headers(request.headers);"
        " const handle = createFront({ sign, fetchImpl: async (input) => {"
        "  await new Promise((r) => setTimeout(r, 60));"
        "  if (input.signal && input.signal.aborted) throw new DOMException('aborted', 'AbortError');"
        "  return new Response(JSON.stringify({ ok: true, session: {} }),"
        "    { status: 200, headers: { 'content-type': 'application/json' } });"
        " } });"
        " const env = { FRONT_ORIGIN: 'https://chat-com2.padiem.net',"
        "  FALLBACK_MODE: 'static', COM2_CANONICAL: 'off', HEALTH_TTL_MS: '10000',"
        "  UPSTREAM_TIMEOUT_MS: '10' };"
        " const response = await handle(new Request("
        "  'https://chat.padiem.net/api/voice/live-token',"
        "  { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' }), env);"
        " console.log('STATUS=' + response.status);"
    )
    node = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=FRONT, capture_output=True, text=True, timeout=60,
    )
    assert node.returncode == 0, node.stderr[-800:]
    assert "STATUS=200" in node.stdout, node.stdout[-400:]


def test_chat_live_token_route_never_produces_a_504():
    """The route's own fail-closed statuses are bounded; 504 is the front's."""
    source = ROUTES.read_text(encoding="utf-8")
    live_token = source.split("async def voice_live_token", 1)[1].split(
        "\nasync def ", 1)[0]
    statuses = set(re.findall(r"_error\([^)]*?,\s*(\d{3})\)", live_token))
    allowed = {"400", "401", "403", "413", "415", "502", "503"}
    unexpected = statuses - allowed
    assert not unexpected, (
        f"voice_live_token route now answers {sorted(unexpected)} — a 504 here "
        "would mean the route grew its own upstream deadline; keep the "
        "fail-closed mapping and let the front allowance carry the wait")
