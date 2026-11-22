"""Pending PC delivery shared test preparation (#8061).

Moved out of test_4139_pending_pc_delivery_adapter so the test-to-test
import ratchet does not grow: the hub and its consumers all import these
names from here. Storage is a real in-memory SQLite store with the durable
pending-PC-link schema installed; Socket is a recording fake.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from padiem_control_plane.pending_pc_link import (
    DurablePendingPcLink, VerifiedPendingPc, MIGRATION_ID,
    install_pending_pc_link_schema,
)

__all__ = [
    "DEVICE", "KEY_FINGERPRINT", "REQUEST",
    "BrokerPort", "Cursor", "Socket", "Storage",
]

REQUEST = "link." + "a"*32
DEVICE = "windows.device.1"
KEY_FINGERPRINT = "f"*64


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor
    def toArray(self):
        if self.cursor.description is None:
            return []
        return [
            dict(zip((column[0] for column in self.cursor.description), record))
            for record in self.cursor.fetchall()
        ]


class Storage:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.sql = self
    def exec(self, query, *values):
        return Cursor(self.connection.execute(query, values))
    def transactionSync(self, fn):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            result = fn()
            self.connection.execute("COMMIT")
            return result
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise


class BrokerPort:
    def __init__(self):
        self.store = Storage()
        install_pending_pc_link_schema(
            storage=self.store, migration_id=MIGRATION_ID, operator_gate=True,
        )
        self.online = True
        self.ledger = DurablePendingPcLink(
            storage=self.store, canonical_broker_storage=self.store,
            ref_factory=lambda: REQUEST,
            channel_verified=lambda ref, device, key: (
                self.online and ref == REQUEST and device == DEVICE
                and key == KEY_FINGERPRINT
            ),
        )
        self.ledger.offer(
            attested=VerifiedPendingPc(
                device_id=DEVICE, possession_key_sha256=KEY_FINGERPRINT,
            ),
            now=datetime.now(timezone.utc),
        )
    async def reserve_once(self, *, request_ref):
        return self.ledger.reserve_once(
            request_ref=request_ref, now=datetime.now(timezone.utc),
        )
    async def claim_delivery_once(self, *, request_ref, device_id):
        self.ledger.claim_delivery_once(
            request_ref=request_ref, device_id=device_id,
            now=datetime.now(timezone.utc),
        )
    def state(self):
        return self.store.exec(
            "SELECT state FROM canonical_broker_pending_pc_link"
        ).toArray()[0]["state"]


class Socket:
    def __init__(self):
        self.calls = []
        self.fail = False
    async def send_once(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("credential prefix must not leak")


