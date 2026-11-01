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
    # One renewal can already be in flight when stop is set: the loop checks
    # the event at the top, so a thread descheduled between that check and its
    # post still lands once. Let the loop settle (well over several intervals)
    # before the count is fixed; after that it must be silent.
    time.sleep(0.02 * 10)
    quiet = len(posts)
    time.sleep(0.06)
    assert quiet >= 2, posts
    assert len(posts) == quiet, posts[quiet:]
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
