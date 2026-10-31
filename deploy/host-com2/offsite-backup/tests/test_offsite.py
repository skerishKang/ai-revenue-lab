"""#5093 rehearsal — upload → download → restore against a local R2 double.

No network, no Cloudflare: `FileSystemR2` is the same store surface the S3
client implements, so every branch the real run takes is exercised — including
a stored byte flipped after upload, which must refuse before decryption.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "offsite.py"
SPEC = importlib.util.spec_from_file_location("offsite_backup", TOOL)
offsite = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(offsite)

SECRET_KEY_HEX = "ab" * 32
SUNDAY = datetime(2026, 11, 1, 5, 10, tzinfo=timezone.utc)   # a Sunday
MONDAY = datetime(2026, 11, 2, 5, 10, tzinfo=timezone.utc)
#: Generation fixtures are anchored to MONDAY, so freshness tests never rot.
MAX_AGE_HOURS_FOR_TEST = 26 * 24


def _make_db(path: Path, rows: int, *, table: str = "t") -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.executemany(
            f"INSERT INTO {table} (value) VALUES (?)",
            [(f"row-{index}",) for index in range(rows)],
        )
        connection.commit()
    finally:
        connection.close()


def _generation_id(moment: datetime) -> str:
    return moment.strftime("%Y%m%dT%H%M%S%fZ")


def _publish_generation(
    root: Path, generation: str, *, chat_rows: int = 12, engine_rows: int = 4,
    tamper_chat: bool = False, publish_pointer: bool = True,
) -> dict:
    """Publish one generation exactly the way `refresh_d1.py` does.

    Seeds and metadata go into `generations/<id>/` first, then the pointer is
    replaced atomically (`publish_pointer=False` stages the directory only, for the
    test that watches a swap mid-flight). `tamper_chat` records the honest hash and
    then flips a byte, which is how a half-written seed reaches a reader.
    """
    snapshot = root / "snapshots" / "generations" / generation
    snapshot.mkdir(parents=True)
    records: dict[str, dict] = {}
    for label, rows, database in (
        ("chat", chat_rows, "padiem-chat-db"), ("engine", engine_rows, "padiem-engine"),
    ):
        path = snapshot / f"{label}.sqlite3"
        _make_db(path, rows, table=f"{label}_row")
        payload = path.read_bytes()
        records[label] = {
            "database": database, "file": path.name, "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(), "tables": 1,
        }
        if tamper_chat and label == "chat":
            path.write_bytes(payload[:-1] + bytes([payload[-1] ^ 0xFF]))
    metadata = {
        "generation": generation, "databases": records, "captured_utc": generation,
        "production_bound": False, "cross_database_transaction": False,
        "source": "cloudflare_d1_remote_export",
    }
    (snapshot / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    temporary = root / "snapshots" / "current_generation.next.json"
    temporary.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    if publish_pointer:
        os.replace(temporary, root / "snapshots" / "current_generation.json")
    return records


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

    def test_stale_backup_is_a_failure_for_that_service_only(self):
        self.db.unlink()
        old = self.root / "backups" / "chat-20260101T000000Z.sqlite3"
        _make_db(old, 5)
        os.utime(old, (0, 0))
        rows = offsite.run_upload(self.env, services=["chat"], now=MONDAY)
        self.assertEqual(rows[0]["status"], offsite.STATUS_FAIL)
        self.assertEqual(rows[0]["reason"], "backup_stale")
        self.assertEqual(offsite.run_outcome(rows)["status"], "FAIL")
        self.assertFalse(any(self.r2.rglob("*.cbe1")))


class ServiceStateSeparation(unittest.TestCase):
    """An absent service is reported. An installed service with nothing to back up fails."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        key = self.root / "offsite.key"
        key.write_text(SECRET_KEY_HEX, encoding="utf-8")
        os.chmod(key, 0o600)
        live = self.root / "chat-backups"
        live.mkdir()
        _make_db(live / "chat-20261102T042000Z.sqlite3", 5)
        self.units = self.root / "units"
        self.units.mkdir()
        self.env = {
            "OFFSITE_R2_DIR": str(self.root / "r2"),
            "OFFSITE_STATE_DIR": str(self.root / "state"),
            "COM2_OFFSITE_KEY_FILE": str(key),
            "COM2_OFFSITE_KEY_ID": "com2-2026-11",
            "OFFSITE_QUEUE_BACKUP_DIR": str(self.root / "no-queue"),
            "OFFSITE_CHAT_BACKUP_DIR": str(live),
            "OFFSITE_BROKER_BACKUP_DIR": str(self.root / "no-broker"),
            "OFFSITE_D1_GENERATIONS_DIR": str(self.root / "no-snapshots" / "generations"),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _rows(self, services):
        return offsite.run_upload(
            self.env, services=services, now=MONDAY, unit_dirs=(str(self.units),)
        )

    def test_absent_service_is_reported_and_the_run_still_passes(self):
        rows = self._rows(["queue", "chat"])
        by_name = {row["service"]: row for row in rows}
        self.assertEqual(by_name["queue"]["status"], offsite.STATUS_NOT_INSTALLED)
        self.assertEqual(by_name["chat"]["status"], offsite.STATUS_OK)
        outcome = offsite.run_outcome(rows)
        self.assertEqual(outcome["status"], "PASS")
        self.assertEqual(outcome["uploaded"], 1)

    def test_installed_service_without_a_backup_is_a_failure(self):
        # The 2026-10-29 first run: the queue was installed minutes earlier and had
        # no snapshot yet. That is a FAIL for the queue — and it must not decide the
        # fate of the copies that are actually there.
        (self.units / "padiem-mesh-queue.service").write_text("[Unit]\n", encoding="utf-8")
        rows = self._rows(["queue", "chat"])
        by_name = {row["service"]: row for row in rows}
        self.assertEqual(by_name["queue"]["status"], offsite.STATUS_FAIL)
        self.assertTrue(by_name["queue"]["reason"].startswith("backup_missing"))
        self.assertEqual(by_name["chat"]["status"], offsite.STATUS_OK)
        outcome = offsite.run_outcome(rows)
        self.assertEqual(outcome["status"], "FAIL")
        self.assertEqual(outcome["failed"], ["queue"])

    def test_a_run_that_uploaded_nothing_is_unknown_not_a_pass(self):
        rows = self._rows(["queue", "broker", "d1-chat"])
        self.assertEqual(
            {row["status"] for row in rows}, {offsite.STATUS_NOT_INSTALLED}
        )
        outcome = offsite.run_outcome(rows)
        self.assertEqual(outcome["status"], "UNKNOWN")
        self.assertEqual(outcome["failed"], ["no_service_produced_a_backup"])


class GenerationTargets(unittest.TestCase):
    """d1-chat / d1-engine: the published generation is the only acceptable source."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.storage = self.root / "storage"
        (self.storage / "snapshots" / "generations").mkdir(parents=True)
        key = self.root / "offsite.key"
        key.write_text(SECRET_KEY_HEX, encoding="utf-8")
        os.chmod(key, 0o600)
        self.env = {
            "OFFSITE_R2_DIR": str(self.root / "r2"),
            "OFFSITE_STATE_DIR": str(self.root / "state"),
            "COM2_OFFSITE_KEY_FILE": str(key),
            "COM2_OFFSITE_KEY_ID": "com2-2026-11",
            "OFFSITE_D1_GENERATIONS_DIR": str(self.storage / "snapshots" / "generations"),
            # On COM2 this is /mnt/d: the mounted Windows drive is what says this host
            # is the one expected to hold the D1 pair.
            "OFFSITE_D1_MOUNT_ROOT": str(self.root),
        }
        self.generation = _generation_id(MONDAY - timedelta(minutes=25))
        self.records = _publish_generation(
            self.storage, self.generation, chat_rows=17, engine_rows=5
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _rows(self, services=("d1-chat", "d1-engine")):
        return offsite.run_upload(self.env, services=list(services), now=MONDAY)

    def test_the_published_generation_pair_uploads(self):
        rows = self._rows()
        self.assertEqual([row["status"] for row in rows], [offsite.STATUS_OK] * 2)
        self.assertEqual({row["generation"] for row in rows}, {self.generation})
        self.assertEqual(rows[0]["source_file"], "chat.sqlite3")
        self.assertEqual(rows[1]["source_file"], "engine.sqlite3")
        for service, stored in (("d1-chat", rows[0]), ("d1-engine", rows[1])):
            manifest = json.loads(
                (self.root / "r2" / f"offsite/v1/{service}/daily/20261102.json").read_text()
            )
            self.assertEqual(manifest["generation"], self.generation)
            self.assertEqual(manifest["source_file"], stored["source_file"])
            self.assertEqual(
                manifest["database"], "padiem-chat-db" if service == "d1-chat" else "padiem-engine"
            )
            self.assertNotIn(
                "PADIEM-Servers", json.dumps(manifest), "the Windows root is not in a manifest"
            )

    def test_generation_older_than_26_hours_is_a_failure(self):
        stale = _generation_id(MONDAY - timedelta(hours=27))
        _publish_generation(self.storage, stale)
        rows = self._rows()
        self.assertEqual({row["status"] for row in rows}, {offsite.STATUS_FAIL})
        self.assertTrue(rows[0]["reason"].startswith("generation_stale"))
        self.assertFalse(any((self.root / "r2").rglob("*.cbe1")))

    def test_generation_id_that_is_not_an_instant_is_unknown_not_success(self):
        # The authority accepts any safe id string; freshness cannot be judged
        # without an instant, and "unknown" must never be reported as a success.
        pointer = self.storage / "snapshots" / "current_generation.json"
        payload = json.loads(pointer.read_text(encoding="utf-8"))
        generation = payload["generation"]
        moved = self.storage / "snapshots" / "generations" / "manual-reseed"
        (self.storage / "snapshots" / "generations" / generation).rename(moved)
        for label in ("chat", "engine"):
            payload["databases"][label]["file"] = f"{label}.sqlite3"
        payload["generation"] = "manual-reseed"
        payload["captured_utc"] = "manual-reseed"
        pointer.write_text(json.dumps(payload), encoding="utf-8")
        rows = self._rows(["d1-chat"])
        self.assertEqual(rows[0]["status"], offsite.STATUS_UNKNOWN)
        self.assertEqual(offsite.run_outcome(rows)["status"], "FAIL")

    def test_torn_seed_bytes_are_refused_for_the_whole_generation(self):
        # The authority validates a generation as a published pair, so a seed whose
        # bytes are not the manifest's blocks both labels: backing up half a pair
        # would hand the bucket two files from different moments.
        corrupt = _generation_id(MONDAY - timedelta(minutes=5))
        _publish_generation(self.storage, corrupt, tamper_chat=True)
        rows = offsite.run_upload(self.env, services=["d1-chat", "d1-engine"], now=MONDAY)
        self.assertEqual({row["status"] for row in rows}, {offsite.STATUS_FAIL})
        for row in rows:
            self.assertIn("generation_chat_integrity_failed", row["reason"])
        self.assertFalse(any((self.root / "r2").rglob("*.cbe1")))

    def test_a_pending_generation_is_never_selected(self):
        pending = self.storage / "snapshots" / "generations" / (_generation_id(MONDAY) + ".pending")
        pending.mkdir()
        _make_db(pending / "chat.sqlite3", 1)
        rows = self._rows(["d1-chat"])
        self.assertEqual(rows[0]["generation"], self.generation)
        self.assertEqual(rows[0]["status"], offsite.STATUS_OK)

    def test_pointer_replacement_is_all_or_nothing(self):
        # The publisher writes the next pointer beside the live one and only then
        # os.replace()s it. Until that rename, the reader must still resolve the old
        # generation completely — a half-published swap has no visible effect.
        second = _generation_id(MONDAY - timedelta(minutes=10))
        records = _publish_generation(self.storage, second, publish_pointer=False)
        pointer = self.storage / "snapshots" / "current_generation.json"
        staged = self.storage / "snapshots" / "current_generation.next.json"
        resolve = lambda: offsite._resolve_generation(
            self.env, max_age_hours=MAX_AGE_HOURS_FOR_TEST, reference=MONDAY
        )
        self.assertTrue(staged.is_file(), "the swap is staged beside the live pointer")
        before = resolve()
        self.assertEqual(before["generation"], self.generation)
        self.assertEqual(before["databases"]["chat"]["sha256"], self.records["chat"]["sha256"])
        os.replace(staged, pointer)
        after = resolve()
        self.assertEqual(after["generation"], second)
        self.assertEqual(after["databases"]["engine"]["sha256"], records["engine"]["sha256"])

    @unittest.skipIf(os.name == "nt", "Windows denies rename while a reader holds the file")
    def test_reader_never_sees_a_half_published_pointer(self):
        # The publisher writes the next pointer beside the live one and os.replace()s
        # it in. A reader running the whole time must therefore only ever resolve a
        # complete generation — never a torn file and never an unpublished directory.
        second = _generation_id(MONDAY - timedelta(minutes=10))
        _publish_generation(self.storage, second)
        names = {self.generation, second}
        seen: list[str] = []
        errors: list[str] = []
        stop = threading.Event()

        def publisher() -> None:
            while not stop.is_set():
                for generation in (self.generation, second):
                    pointer = self.storage / "snapshots" / "current_generation.json"
                    payload = json.loads(
                        (self.storage / "snapshots" / "generations" / generation / "metadata.json")
                        .read_text(encoding="utf-8")
                    )
                    temporary = self.storage / "snapshots" / "current_generation.next.json"
                    temporary.write_text(json.dumps(payload), encoding="utf-8")
                    os.replace(temporary, pointer)

        thread = threading.Thread(target=publisher, daemon=True)
        thread.start()
        try:
            for _ in range(60):
                try:
                    seen.append(
                        offsite._resolve_generation(
                            self.env, max_age_hours=MAX_AGE_HOURS_FOR_TEST, reference=MONDAY
                        )["generation"]
                    )
                except offsite.SourceUnresolved as exc:
                    errors.append(exc.reason)
        finally:
            stop.set()
            thread.join(timeout=5)
        self.assertEqual(errors, [], "a swap was observed as a broken pointer")
        self.assertTrue(set(seen) <= names, sorted(set(seen) - names))
        self.assertGreaterEqual(len(set(seen)), 1)

    def test_drive_without_a_generation_root_is_not_installed(self):
        env = dict(self.env)
        env["OFFSITE_D1_MOUNT_ROOT"] = str(self.root / "drive-not-attached")
        rows = offsite.run_upload(env, services=["d1-chat", "d1-engine"], now=MONDAY)
        self.assertEqual({row["status"] for row in rows}, {offsite.STATUS_NOT_INSTALLED})

    def test_mounted_drive_with_no_published_generation_is_a_failure(self):
        # The 04:20 task stopped (or its directory moved) while the drive is mounted.
        # That is exactly the case NOT_INSTALLED must never absorb.
        env = dict(self.env)
        env["OFFSITE_D1_GENERATIONS_DIR"] = str(self.root / "empty" / "generations")
        rows = offsite.run_upload(env, services=["d1-chat"], now=MONDAY)
        self.assertEqual(rows[0]["status"], offsite.STATUS_FAIL)
        self.assertIn("generation_manifest_missing", rows[0]["reason"])
        self.assertEqual(offsite.run_outcome(rows)["status"], "FAIL")

    def test_generation_authority_absent_is_a_failure_for_that_target_only(self):
        env = dict(self.env)
        env["OFFSITE_GENERATION_OPS_PATH"] = str(self.root / "no-such-authority.py")
        rows = offsite.run_upload(env, services=["d1-chat", "chat"], now=MONDAY)
        by_name = {row["service"]: row for row in rows}
        self.assertEqual(by_name["d1-chat"]["status"], offsite.STATUS_FAIL)
        self.assertEqual(by_name["d1-chat"]["reason"], "generation_ops_missing")
        # chat's own backups dir is absent here, so it reports its own state instead
        # of being swallowed by the generation failure.
        self.assertEqual(by_name["chat"]["status"], offsite.STATUS_NOT_INSTALLED)

    def test_rehearse_proves_the_round_trip_table_by_table(self):
        result = offsite.rehearse(self.env, service="d1-chat", now=MONDAY)
        self.assertEqual(result["generation"], self.generation)
        self.assertEqual(result["source_file"], "chat.sqlite3")
        self.assertEqual(result["tables"], 1)
        self.assertEqual(result["rows"], 17)
        self.assertEqual(result["integrity"], "ok")
        staged = Path(result["staged"])
        self.assertEqual(offsite.table_row_counts(staged), {"chat_row": 17})
        source = self.storage / "snapshots" / "generations" / self.generation / "chat.sqlite3"
        self.assertEqual(result["plaintext_sha256"], offsite._sha256(source.read_bytes()))

    def test_rehearse_refuses_to_write_anywhere_but_the_local_double(self):
        env = {key: value for key, value in self.env.items() if key != "OFFSITE_R2_DIR"}
        env["OFFSITE_R2_ENDPOINT"] = "https://account.r2.cloudflarestorage.com"
        env["OFFSITE_R2_BUCKET"] = "padiem-com2"
        with self.assertRaises(offsite.OffsiteError) as caught:
            offsite.rehearse(env, service="d1-chat", now=MONDAY)
        self.assertEqual(str(caught.exception), "rehearse_requires_local_bucket")


if __name__ == "__main__":
    unittest.main()
