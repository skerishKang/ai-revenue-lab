"""#7563 contract: a claim is a request, and only observation promotes a link.

Until #7563 both runtimes wired ``pc_pairing_verifier`` so a typed-code claim
could become `active` as soon as the named node looked online. That proof was
the caller's own node id plus a liveness check: account B's code plus account
A's online PC produced an active link for B. The verifier is gone, and the two
runtimes must not wire one back:

* a claim always stores `pending_verification`, whatever its body says;
* the executor's observation of the install tag is the only promotion, and it
  is a conditional UPDATE so two observers promote once;
* the claim body's drives are never granted.

The store behaviour itself (real SQL, promotion once, TTL, throttling) is
pinned by ``test_7563_pc_claim_proof.py`` and ``test_5573_pc_device_pairing.py``.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent
while REPO != REPO.parent and not (REPO / "apps" / "padiem-chat" / "app").exists():
    REPO = REPO.parent
HOST = REPO / "apps" / "padiem-chat" / "app" / "local_cpython.py"
WORKER = REPO / "apps" / "padiem-chat" / "worker.py"
ROUTES = REPO / "apps" / "padiem-chat" / "app" / "pc_device_pairing_routes.py"
STORE = REPO / "apps" / "padiem-chat" / "app" / "pc_device_pairing_store.py"


def test_the_routes_no_longer_offer_a_liveness_verifier() -> None:
    source = ROUTES.read_text(encoding="utf-8")
    assert "presence_pairing_verifier" not in source
    assert "pc_pairing_verifier" not in source
    # The claim can only ever ask the store for a pending link.
    assert "verified=False" in source
    assert "drives=None" in source


def test_neither_runtime_injects_a_claim_verifier() -> None:
    for path in (HOST, WORKER):
        source = path.read_text(encoding="utf-8")
        assert "pc_pairing_verifier" not in source, path.name


def test_promotion_is_one_conditional_update() -> None:
    source = STORE.read_text(encoding="utf-8")
    assert "_promote_pending_link" in source
    assert "WHERE user_id=? AND mesh_node_id=? AND pairing_code_id=? AND state=? " in source
    assert "RETURNING link_id" in source
    # The tag's expiry is checked before any promotion.
    assert "pairing code expired" in source
