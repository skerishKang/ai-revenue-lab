"""Adoption resolves the account on Chat D1 even when the link store is queue-backed.

The queue database has no users table, so ``resolve_account_ref`` must not go
through the queue-backed pairing store. The route and the ops tool use the
Chat D1 resolver; the queue store only writes the link.
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_5573_pc_pairing_admin_adopt as adopt  # noqa: E402
from app.pc_device_pairing_routes import PC_PAIRING_ADOPT_PATH  # noqa: E402


class QueueBackedStore:
    """A queue-backed store whose account-ref call would fail (no users table)."""

    def __init__(self):
        self.adopted = []
        self.resolve_calls = 0

    async def resolve_account_ref(self, *, target):
        self.resolve_calls += 1
        raise RuntimeError("queue refused")

    async def drive_roots_for_node(self, *, mesh_node_id):
        return ["C:"]

    async def adopt_link(self, **kwargs):
        self.adopted.append(kwargs)
        return {
            "link_id": "pclink_queue",
            "user_id": kwargs["user_id"],
            "mesh_node_id": kwargs["mesh_node_id"],
            "label": "K_lipvoice · 컴2",
            "state": "active",
            "roots": [],
            "created_at": "2026-11-14T00:00:00.000Z",
            "updated_at": "2026-11-14T00:00:00.000Z",
        }


def test_admin_adopt_uses_chat_d1_resolver_with_queue_backed_store():
    d1_store, conn = adopt._store_with_users()
    queue = QueueBackedStore()
    app = adopt._app(store_value=queue, seen=(adopt.MESH_NODE,))
    app.state.account_ref_resolver = d1_store
    try:
        response = adopt._adopt(app, {
            "device_id": adopt.MESH_NODE,
            "target": adopt.CUSTOMER_ID,
            "drives": adopt.DRIVES,
        })
        assert response.status_code == 200, response.text
        assert response.json()["link"]["user_id"] == adopt.CUSTOMER_ID
        assert queue.resolve_calls == 0
        assert len(queue.adopted) == 1
        assert queue.adopted[0]["user_id"] == adopt.CUSTOMER_ID
    finally:
        conn.close()


def test_unknown_target_is_none_and_creates_no_link():
    d1_store, conn = adopt._store_with_users()
    queue = QueueBackedStore()
    app = adopt._app(store_value=queue, seen=(adopt.MESH_NODE,))
    app.state.account_ref_resolver = d1_store
    try:
        response = adopt._adopt(app, {
            "device_id": adopt.MESH_NODE,
            "target": "nobody@nowhere.invalid",
            "drives": adopt.DRIVES,
        })
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "pc_pairing_target_unknown"
        assert queue.resolve_calls == 0
        assert queue.adopted == []
    finally:
        conn.close()