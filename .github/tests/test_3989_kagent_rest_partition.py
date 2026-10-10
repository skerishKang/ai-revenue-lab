"""Regression contract for #3989 KAgent rest module balancing (Linux/Windows)."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from collections import Counter

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/kagent_parallel_contract_tests.py"
WORKFLOW = ROOT / ".github/workflows/validate-b54-kagent.yml"

spec = importlib.util.spec_from_file_location("kagent_partition_3989", SCRIPT)
assert spec is not None and spec.loader is not None
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class FakeCase:
    def __init__(self, module: str, idx: int):
        self._id = f"{module}.Example.test_case_{idx:04d}"
    def id(self):
        return self._id


class KAgentRestPartitionTests(unittest.TestCase):
    def setUp(self):
        self.cases = [
            FakeCase(module, i)
            for module, count in (
                ("test_hwpx_skill_create", 7),
                ("test_hwpx_skill_template_fill", 11),
                ("test_hwpx_skill_edit", 13),
                ("test_hwpx_skill_insert_table", 5),
                ("test_big_module_one", 80),
                ("test_big_module_two", 70),
                ("test_medium", 51),
                ("test_misc_one", 10),
                ("test_misc_two", 4),
                ("test_new_module_future", 1),
            )
            for i in range(count)
        ]

    def test_all_cases_disjoint_exact_count_and_digest(self):
        self.assertEqual(
            runner._GROUPS,
            ("hwpx_create_fill", "hwpx_edit_table", "rest_a", "rest_b"),
        )
        splits = {g: runner._select(self.cases, g) for g in runner._GROUPS}
        original = Counter(t.id() for t in self.cases)
        gathered = Counter(t.id() for group in splits.values() for t in group)
        self.assertEqual(original, gathered)
        self.assertTrue(all(splits.values()))
        self.assertEqual(sum(map(len, splits.values())), len(self.cases))
        for group in runner._GROUPS:
            self.assertEqual(
                runner._digest(splits[group]),
                runner._digest(runner._select(list(reversed(self.cases)), group)),
            )

    def test_module_is_never_split_between_rest_processes(self):
        rest_a = runner._select(self.cases, "rest_a")
        rest_b = runner._select(self.cases, "rest_b")
        modules_a = {t.id().split(".", 1)[0] for t in rest_a}
        modules_b = {t.id().split(".", 1)[0] for t in rest_b}
        self.assertFalse(modules_a & modules_b)
        self.assertTrue(modules_a)
        self.assertTrue(modules_b)
        self.assertLessEqual(abs(len(rest_a) - len(rest_b)), 80)
        self.assertNotIn("test_hwpx_skill_create", modules_a | modules_b)

    def test_fail_closed_guards_and_linux_windows_still_mandatory(self):
        source = SCRIPT.read_text(encoding="utf-8")
        workflow = WORKFLOW.read_text(encoding="utf-8")
        for text in (
            "KAGENT_PARALLEL_COUNT_MISMATCH",
            "KAGENT_PARALLEL_ID_MISMATCH",
            "KAGENT_PARALLEL_DISCOVERY_MISMATCH",
            "expected_count",
            "expected_digest",
            "KAGENT_PARALLEL_EMPTY_PARTITION",
            "KAGENT_PARALLEL_FAILURE",
            "KAGENT_FULL_SUITE_PASS total={expected} groups=4",
        ):
            self.assertIn(text, source)
        for text in (
            "os: [ubuntu-latest, windows-latest]",
            "fail-fast: false",
            "kagent_parallel_contract_tests.py",
            "test_3989_kagent_rest_partition.py",
            "Download the approved Pillow wheel",
            "Verify the downloaded Pillow wheel against the receipt",
            "Install the verified local Pillow wheel",
        ):
            self.assertIn(text, workflow)
        self.assertNotIn("continue-on-error: true", workflow)


if __name__ == "__main__":
    unittest.main()
