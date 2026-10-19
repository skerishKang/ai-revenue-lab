"""Saved script library contract tests (all-local, no telephony)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from phone_mock import TaskError
from phone_scripts import ScriptStore, MAX_SCRIPTS


class ScriptLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / "scripts.json"
        self.store = ScriptStore(self.file)
        self.payload = {
            "title": "입고 확인",
            "destination": "가상 거래처",
            "goal": "출고 진행 상태를 알려줘",
            "questions": "언제 도착하나요?",
            "notes": "주문 변경을 승인하지 마세요",
        }

    def test_examples_are_read_only(self):
        scripts = self.store.list()
        self.assertEqual(len(scripts), 3)
        self.assertTrue(all(x["built_in"] for x in scripts))
        self.assertEqual(self.store.resolve("sample-vendor")["title"], "거래처 확인")
        with self.assertRaises(TaskError) as err:
            self.store.delete("sample-vendor", 1)
        self.assertEqual(err.exception.status, 404)

    def test_persists_across_restart(self):
        saved = self.store.create(self.payload)
        self.assertTrue(self.file.exists())
        reopened = ScriptStore(self.file)
        self.assertEqual(reopened.resolve(saved["script_id"]), saved)
        self.assertEqual(len(reopened.list()), 4)
        self.assertEqual(saved["revision"], 1)

    def test_update_with_version_and_immutable_copies(self):
        saved = self.store.create(self.payload)
        revised = self.store.update(saved["script_id"], {**self.payload, "title": "수정된 제목", "revision": 1})
        self.assertEqual(revised["revision"], 2)
        self.assertEqual(ScriptStore(self.file).resolve(saved["script_id"])["title"], "수정된 제목")
        revised["title"] = "tamper"
        self.assertEqual(self.store.resolve(saved["script_id"])["title"], "수정된 제목")
        with self.assertRaises(TaskError) as err:
            self.store.update(saved["script_id"], {**self.payload, "revision": 1})
        self.assertEqual(err.exception.status, 409)

    def test_delete_with_version(self):
        saved = self.store.create(self.payload)
        with self.assertRaises(TaskError):
            self.store.delete(saved["script_id"], 2)
        deleted = self.store.delete(saved["script_id"], 1)
        self.assertEqual(deleted["deleted"], True)
        self.assertEqual(len(ScriptStore(self.file).list()), 3)

    def test_validation_blocks_controls_types_size(self):
        for payload in [
            {}, [],
            {**self.payload, "title": "x"},
            {**self.payload, "questions": "x\nmalicious"},
            {**self.payload, "notes": "x" * 401},
            {**self.payload, "goal": 123},
        ]:
            with self.subTest(payload=str(payload)[:35]), self.assertRaises(TaskError):
                self.store.create(payload)
        self.assertEqual(len(self.store.list()), 3)

    def test_hard_capacity_limit(self):
        for n in range(MAX_SCRIPTS):
            self.store.create({**self.payload, "title": f"대본 {n}"})
        with self.assertRaises(TaskError) as err:
            self.store.create(self.payload)
        self.assertEqual(err.exception.status, 429)

    def test_corrupt_store_is_not_silently_reset(self):
        self.file.write_text('{"version": 1, "scripts": "wrong"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            ScriptStore(self.file)

    def test_invalid_revision_rejected(self):
        saved = self.store.create(self.payload)
        for value in [None, True, "1", 0]:
            with self.subTest(value=value), self.assertRaises(TaskError):
                self.store.update(saved["script_id"], {**self.payload, "revision": value})
        with self.assertRaises(TaskError):
            self.store.delete(saved["script_id"], "1")


if __name__ == "__main__":
    unittest.main()
