"""#7293 follow-up contract: the typed-code pairing claim can actually activate.

One gap, two sides, pinned together:

* the claim route reads ``app.state.pc_pairing_verifier`` and no runtime ever
  injected one — so every typed-code claim landed in ``pending_verification``
  forever and no self-service pairing could ever become an executable target
  (found 2026-11-09 pairing the QA check PC: the claim answered 202 and the
  link never activated). The route's own comment names the intended proof:
  the PR-2 Mesh presence directory.
* both runtimes (the COM2 host and the Worker) must now inject the verifier
  built from whichever presence store they selected, and the verifier may only
  say yes for a node the directory currently sees as online — a claim alone
  still never becomes executable, and a runtime with no presence store stays
  fail-closed exactly as before.

The route-side behaviour (a claim without a verifier stays pending, a verified
claim activates, a later verified claim promotes) is already pinned by
``test_5573_pc_device_pairing.py``; this file pins the wiring and the
verifier's liveness rule.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from app.pc_device_pairing_routes import presence_pairing_verifier

REPO = Path(__file__).resolve().parent
while REPO != REPO.parent and not (REPO / "apps" / "padiem-chat" / "app").exists():
    REPO = REPO.parent
HOST = REPO / "apps" / "padiem-chat" / "app" / "local_cpython.py"
WORKER = REPO / "apps" / "padiem-chat" / "worker.py"
ROUTES = REPO / "apps" / "padiem-chat" / "app" / "pc_device_pairing_routes.py"


def _presence_row(*, connected: bool, age_seconds: float) -> SimpleNamespace:
    received = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return SimpleNamespace(
        device_id="node/qa",
        connected=connected,
        received_at=received.isoformat(),
        last_connected_at=received.isoformat(),
    )


class FakePresenceStore:
    def __init__(self, row):
        self._row = row

    def load(self, *, device_id: str):
        if self._row is None or device_id != self._row.device_id:
            return None
        return {
            "device_id": self._row.device_id,
            "connected": self._row.connected,
            "received_at": self._row.received_at,
            "last_connected_at": self._row.last_connected_at,
        }


def _verdict(store, node: str = "node/qa") -> bool:
    return asyncio.run(
        presence_pairing_verifier(store)(mesh_node_id=node, code="whatever"))


def test_a_connected_fresh_node_is_verified():
    assert _verdict(FakePresenceStore(_presence_row(connected=True, age_seconds=5)))


def test_a_stale_or_disconnected_or_unknown_node_is_never_verified():
    stale = _presence_row(connected=True, age_seconds=10_000)
    offline = _presence_row(connected=False, age_seconds=5)
    assert not _verdict(FakePresenceStore(stale))
    assert not _verdict(FakePresenceStore(offline))
    assert not _verdict(FakePresenceStore(_presence_row(connected=True, age_seconds=5)),
                        node="node/other")
    assert not _verdict(FakePresenceStore(None))
    assert not _verdict(None)


def test_the_host_runtime_wires_the_verifier_from_its_presence_store():
    source = HOST.read_text(encoding="utf-8")
    assert re.search(r"app\.state\.pc_pairing_verifier = presence_pairing_verifier\(", source)
    # The verifier must be wired after the queue-backed replacement so it reads
    # the store this runtime actually selected.
    store_line = source.index("app.state.mesh_device_presence_store = QueueBackedPresenceStore")
    wire_line = source.index("app.state.pc_pairing_verifier = presence_pairing_verifier")
    assert wire_line > store_line


def test_the_worker_runtime_wires_the_verifier_from_its_presence_store():
    source = WORKER.read_text(encoding="utf-8")
    assert re.search(
        r"worker_app\.state\.pc_pairing_verifier = presence_pairing_verifier\(", source)
    wire_line = source.index("worker_app.state.pc_pairing_verifier = presence_pairing_verifier")
    queue_line = source.index("QueueBackedPresenceStore(queue_client)")
    assert wire_line > queue_line


def test_the_claim_route_still_consults_the_verifier():
    source = ROUTES.read_text(encoding="utf-8")
    assert "pc_pairing_verifier" in source, (
        "the claim route must keep reading the injected verifier — removing "
        "that read would reintroduce the trust-on-claim this route refuses")
