"""#5997 — the executor keeps renewing a claim for as long as the command runs.

The production loss was a 379,943 ms command whose one-minute claim expired mid-run,
so the lane re-delivered the work with a new nonce and the original result was refused.
These tests drive the executor's renewal thread itself: it posts the same dispatch and
the same nonce while the command runs, it stops the moment the command ends, and a
refused renewal (the lane already reassigned the work) stops it instead of retrying.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import kagent.local_agent_oracle_mesh_executor as executor

DISPATCH = "dsp_" + "a" * 32
NONCE = "b" * 32


def _runner(*, status=200):
    posts = []

    def post(path, payload):
        posts.append((path, payload))
        return status, {"ok": status == 200}

    return posts, post


def test_the_renewal_loop_holds_the_same_nonce_and_stops_with_the_command(monkeypatch):
    monkeypatch.setattr(executor, "RENEW_INTERVAL_SECONDS", 0.02)
    posts, post = _runner()
    stop = executor.OracleMeshExecutor.start_lease_renewal(
        SimpleNamespace(_post=post),
        SimpleNamespace(dispatch_id=DISPATCH, nonce=NONCE),
    )
    time.sleep(0.12)
    stop.set()
    seen = len(posts)
    time.sleep(0.06)
    assert seen >= 2, posts
    assert len(posts) == seen, posts[seen:]
    assert all(path == executor.LEASE_RENEW_PATH for path, _payload in posts)
    assert all(payload["dispatch_id"] == DISPATCH and payload["nonce"] == NONCE
               for _path, payload in posts)


def test_a_refused_renewal_stops_the_loop_instead_of_reviving_the_claim(monkeypatch):
    monkeypatch.setattr(executor, "RENEW_INTERVAL_SECONDS", 0.02)
    posts, post = _runner(status=409)
    stop = executor.OracleMeshExecutor.start_lease_renewal(
        SimpleNamespace(_post=post),
        SimpleNamespace(dispatch_id=DISPATCH, nonce=NONCE),
    )
    time.sleep(0.12)
    stop.set()
    assert len(posts) == 1, posts


# ── #7562: a renewal can never outlive the lease it renews ──────────────────


def _opener(record):
    class _Response:
        status = 200

        def read(self):
            return b'{"ok": true}'

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    class _Opener:
        def open(self, request, timeout=None):  # noqa: D102
            record.append((request.full_url, timeout))
            return _Response()

    return _Opener()


def test_a_renewal_request_gives_up_well_inside_the_server_lease(monkeypatch):
    """The ordinary channel deadline (90 s) is longer than the 60 s lease, so one
    held-up renewal used to let a live claim run out and be handed out again."""
    import urllib.request

    seen = []
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_a, **_k: _opener(seen))
    run = executor.OracleMeshExecutor(
        chat_origin="https://chat.padiem.net", channel_secret="s" * 32,
        read_port=SimpleNamespace(read_bytes=lambda **_k: b""),
    )
    run._https_post(executor.LEASE_RENEW_PATH, {"dispatch_id": DISPATCH, "nonce": NONCE})
    run._https_post(executor.POLL_PATH, None)

    lease = 60  # apps/padiem-chat/app/history.py ORACLE_MESH_CLAIM_LEASE_SECONDS
    renew_timeout = seen[0][1]
    assert seen[0][0].endswith(executor.LEASE_RENEW_PATH)
    assert renew_timeout == executor.RENEW_REQUEST_TIMEOUT_SECONDS
    # One full interval, then a held-up attempt, then two quick retries all
    # finish before the lease that the first claim recorded runs out.
    assert (executor.RENEW_INTERVAL_SECONDS + renew_timeout
            + 2 * (executor.RENEW_RETRY_SECONDS + renew_timeout)) <= lease
    # Every other leg keeps the ordinary channel deadline.
    assert seen[1][1] == executor.CHANNEL_SOCKET_TIMEOUT_SECONDS


def test_a_renewal_that_did_not_get_through_is_retried_sooner(monkeypatch):
    monkeypatch.setattr(executor, "RENEW_INTERVAL_SECONDS", 0.5)
    monkeypatch.setattr(executor, "RENEW_RETRY_SECONDS", 0.02)
    attempts = []

    def post(path, payload):
        attempts.append(time.monotonic())
        if len(attempts) < 3:
            raise executor.OracleMeshChannelRefused("held up", leg="chat")
        return 200, {"ok": True}

    stop = executor.OracleMeshExecutor.start_lease_renewal(
        SimpleNamespace(_post=post),
        SimpleNamespace(dispatch_id=DISPATCH, nonce=NONCE),
    )
    time.sleep(0.75)
    stop.set()
    # The first attempt waits one interval; the two that failed are each
    # followed by a short retry instead of another full interval.
    assert len(attempts) >= 3, attempts
    assert attempts[2] - attempts[0] < 0.3, attempts
