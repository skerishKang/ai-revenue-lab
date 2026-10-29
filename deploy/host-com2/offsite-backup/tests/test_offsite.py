"""#5093 rehearsal — upload → download → restore against a local R2 double.

No network, no Cloudflare: `FileSystemR2` is the same store surface the S3
client implements, so every branch the real run takes is exercised — including
a stored byte flipped after upload, which must refuse before decryption.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "offsite.py"
SPEC = importlib.util.spec_from_file_location("offsite_backup", TOOL)
offsite = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(offsite)

SECRET_KEY_HEX = "ab" * 32
SUNDAY = datetime(2026, 11, 1, 5, 10, tzinfo=timezone.utc)   # a Sunday
MONDAY = datetime(2026, 11, 2, 5, 10, tzinfo=timezone.utc)


def _make_db(path: Path, rows: int) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO t (value) VALUES (?)", [(f"row-{index}",) for index in range(rows)],
        )
        connection.commit()
    finally:
        connection.close()


class Rehearsal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.r2 = self.root / "r2"
        self.state = self.root / "state"
        self.key_file = self.root / "offsite.key"
        self.key_file.write_text(SECRET_KEY_HEX, encoding="utf-8")
        os.chmod(self.key_file, 0o600)
        self.backups = self.root / "backups"
        self.backups.mkdir()
        self.db = self.backups / "chat-20261102T042000Z.sqlite3"
        _make_db(self.db, 300)
        self.env = {
            "OFFSITE_R2_DIR": str(self.r2),
            "OFFSITE_STATE_DIR": str(self.state),
            "COM2_OFFSITE_KEY_FILE": str(self.key_file),
            "COM2_OFFSITE_KEY_ID": "com2-2026-11",
            "OFFSITE_CHAT_BACKUP_DIR": str(self.backups),
            "OFFSITE_QUEUE_BACKUP_DIR": str(self.backups),
            "OFFSITE_BROKER_BACKUP_DIR": str(self.backups),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_upload_stores_only_ciphertext_and_a_manifest(self):
        results = offsite.run_upload(self.env, services=["chat"], now=MONDAY)
        self.assertEqual(results[0]["backup_id"], "20261102")
        payload_key = "offsite/v1/chat/daily/20261102.cbe1"
        stored = (self.r2 / payload_key).read_bytes()
        self.assertTrue(offsite.is_encrypted_payload(stored) if hasattr(offsite, "is_encrypted_payload") else stored.startswith(b"PADIEM-CBE1\n"))
        self.assertNotIn(self.db.read_bytes()[:512], stored)
        self.assertNotIn(bytes.fromhex(SECRET_KEY_HEX), stored)
        manifest = json.loads((self.r2 / "offsite/v1/chat/daily/20261102.json").read_text())
        self.assertEqual(manifest["source_file"], self.db.name)
        self.assertEqual(manifest["key_id"], "com2-2026-11")
        self.assertEqual(manifest["plaintext_sha256"], offsite._sha256(self.db.read_bytes()))
        # Every key ever written is a backup or manifest — never the key file.
        for key in self.r2.rglob("*"):
            if key.is_file():
                text = key.name.lower()
                self.assertNotIn("key", text)
        ledger = (self.state / "ledger.jsonl").read_text(encoding="utf-8")
        self.assertIn(manifest["ciphertext_sha256"], ledger)

    def test_a_byte_flipped_in_storage_is_refused_before_any_manifest_trust(self):
        offsite.run_upload(self.env, services=["chat"], now=MONDAY)
        payload = self.r2 / "offsite/v1/chat/daily/20261102.cbe1"
        tampered = bytearray(payload.read_bytes())
        tampered[-1] ^= 0xFF
        payload.write_bytes(bytes(tampered))

        with self.assertRaises(offsite.OffsiteError) as caught:
            offsite.restore_generation(
                self.env, service="chat", backup_id="20261102", weekly_week=None,
                target=None, replace=False,
            )
        self.assertEqual(str(caught.exception), "restore_hash_mismatch")

    def test_upload_verification_catches_storage_corruption(self):
        store = offsite.FileSystemR2(self.r2)
        store.corrupt_on_read("offsite/v1/chat/daily/20261102.cbe1")
        original = offsite._store_from_env
        offsite._store_from_env = lambda env: store
        try:
            with self.assertRaises(offsite.OffsiteError) as caught:
                offsite.run_upload(self.env, services=["chat"], now=MONDAY)
        finally:
            offsite._store_from_env = original
        self.assertEqual(str(caught.exception), "verify_mismatch_payload")

    def test_restore_round_trip_checks_integrity_and_rows(self):
        offsite.run_upload(self.env, services=["chat"], now=MONDAY)
        target = self.root / "restored.sqlite3"
        result = offsite.restore_generation(
            self.env, service="chat", backup_id="20261102", weekly_week=None,
            target=target, replace=True,
        )
        self.assertTrue(result["replaced"])
        self.assertGreater(result["tables"], 0)
        connection = sqlite3.connect(target)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM t").fetchone()[0], 300)
            self.assertEqual(
                connection.execute("PRAGMA integrity_check").fetchone()[0], "ok",
            )
        finally:
            connection.close()
        self.assertEqual(target.read_bytes(), self.db.read_bytes())

    def test_sunday_writes_a_weekly_copy_and_retention_prunes(self):
        # Seed 9 older daily generations and 5 older weekly ones (payload+manifest).
        for index in range(9):
            for suffix in ("cbe1", "json"):
                path = self.r2 / f"offsite/v1/chat/daily/202601{index:02d}.{suffix}"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x" * 8)
        for index in range(5):
            for suffix in ("cbe1", "json"):
                path = self.r2 / f"offsite/v1/chat/weekly/2026-W{index:02d}.{suffix}"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"y" * 8)

        results = offsite.run_upload(self.env, services=["chat"], now=SUNDAY)
        self.assertEqual(len(results), 1)
        daily = sorted(p.name for p in (self.r2 / "offsite/v1/chat/daily").glob("*.cbe1"))
        weekly = sorted(p.name for p in (self.r2 / "offsite/v1/chat/weekly").glob("*.cbe1"))
        self.assertEqual(len(daily), 7)
        self.assertEqual(len(weekly), 4)
        self.assertIn("2026-W44.cbe1", weekly)
        # Pruned generations leave no orphan manifest behind.
        self.assertEqual(
            len(list((self.r2 / "offsite/v1/chat/daily").glob("*.json"))), 7,
        )

    def test_missing_key_file_is_a_failure_not_a_plaintext_upload(self):
        env = dict(self.env)
        env["COM2_OFFSITE_KEY_FILE"] = str(self.root / "absent.key")
        with self.assertRaises(offsite.OffsiteError) as caught:
            offsite.run_upload(env, services=["chat"], now=MONDAY)
        self.assertIn("key_unreadable", str(caught.exception))
        self.assertFalse(self.r2.exists() and any(self.r2.rglob("*.cbe1")))

    def test_stale_backup_is_refused(self):
        self.db.unlink()
        old = self.root / "backups" / "chat-20260101T000000Z.sqlite3"
        _make_db(old, 5)
        os.utime(old, (0, 0))
        with self.assertRaises(offsite.OffsiteError) as caught:
            offsite.run_upload(self.env, services=["chat"], now=MONDAY)
        self.assertEqual(str(caught.exception), "backup_stale")


if __name__ == "__main__":
    unittest.main()
