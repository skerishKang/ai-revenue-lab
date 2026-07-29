from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "businesses.js"


VALID_AUTHORITY = {
    "canonical", "proposed-number", "candidate",
    "existing-project", "reserved", "number-reconciliation-required",
}

VALID_UI = {
    "NOT_STARTED", "IN_PROGRESS", "UI_NOT_READY",
    "UI_CONDITIONALLY_READY", "UI_APPROVED", "NOT_APPLICABLE",
}

VALID_UX = {
    "BLOCKED_BY_UI", "NOT_STARTED", "IN_PROGRESS",
    "UX_NOT_READY", "UX_CONDITIONALLY_READY", "UX_APPROVED",
    "NOT_APPLICABLE",
}

VALID_BACKEND = {
    "FROZEN", "DECISION_PENDING", "DEFERRED", "AUTHORIZED",
    "IN_PROGRESS", "IMPLEMENTED", "NOT_APPLICABLE",
}


class BusinessRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = REGISTRY.read_text(encoding="utf-8")

    def _all_numbers(self):
        """Extract all number values in order from rec({ n: ... })."""
        return [
            int(v)
            for v in re.findall(r"\bn:\s*(\d+)", self.script)
        ]

    def _resolve_value(self, raw):
        """Resolve a raw JS value string to its actual value.
        Handles 'NUMBER_AUTHORITY.PROPOSED' -> 'proposed-number', etc."""
        if raw == "null" or raw is None:
            return None
        if raw.startswith('"') and raw.endswith('"'):
            return raw[1:-1]

        # Map OBJECT.KEY references to their actual string values
        value_map = {
            "NUMBER_AUTHORITY.CANONICAL": "canonical",
            "NUMBER_AUTHORITY.PROPOSED": "proposed-number",
            "NUMBER_AUTHORITY.CANDIDATE": "candidate",
            "NUMBER_AUTHORITY.EXISTING_PROJECT": "existing-project",
            "NUMBER_AUTHORITY.RESERVED": "reserved",
            "NUMBER_AUTHORITY.RECONCILIATION": "number-reconciliation-required",
            "UI_STATUS.NOT_STARTED": "NOT_STARTED",
            "UI_STATUS.IN_PROGRESS": "IN_PROGRESS",
            "UI_STATUS.NOT_READY": "UI_NOT_READY",
            "UI_STATUS.CONDITIONALLY_READY": "UI_CONDITIONALLY_READY",
            "UI_STATUS.APPROVED": "UI_APPROVED",
            "UI_STATUS.NOT_APPLICABLE": "NOT_APPLICABLE",
            "UX_STATUS.BLOCKED_BY_UI": "BLOCKED_BY_UI",
            "UX_STATUS.NOT_STARTED": "NOT_STARTED",
            "UX_STATUS.IN_PROGRESS": "IN_PROGRESS",
            "UX_STATUS.NOT_READY": "UX_NOT_READY",
            "UX_STATUS.CONDITIONALLY_READY": "UX_CONDITIONALLY_READY",
            "UX_STATUS.APPROVED": "UX_APPROVED",
            "UX_STATUS.NOT_APPLICABLE": "NOT_APPLICABLE",
            "BACKEND_STATUS.FROZEN": "FROZEN",
            "BACKEND_STATUS.DECISION_PENDING": "DECISION_PENDING",
            "BACKEND_STATUS.DEFERRED": "DEFERRED",
            "BACKEND_STATUS.AUTHORIZED": "AUTHORIZED",
            "BACKEND_STATUS.IN_PROGRESS": "IN_PROGRESS",
            "BACKEND_STATUS.IMPLEMENTED": "IMPLEMENTED",
            "BACKEND_STATUS.NOT_APPLICABLE": "NOT_APPLICABLE",
        }
        return value_map.get(raw, raw)

    def _records(self):
        """Parse each rec({...}) block and extract key fields."""
        records = []
        blocks = re.findall(
            r"rec\(\{(.*?)\}\)",
            self.script,
            re.DOTALL,
        )
        for block in blocks:
            def get_short(k):
                """Extract value for short key like 'a', 'ui', 'ux', 'be'."""
                m = re.search(
                    rf"\b{k}:\s*((\"[^\"]*\")|null|NUMBER_AUTHORITY\.\w+|UI_STATUS\.\w+|UX_STATUS\.\w+|BACKEND_STATUS\.\w+|\d+)",
                    block,
                )
                if not m:
                    return None
                return self._resolve_value(m.group(1))

            def get_long(k):
                """Extract value for long key like 'n', 's', 't', 'k'."""
                m = re.search(rf"\b{k}:\s*(\"[^\"]*\")", block)
                if not m:
                    return None
                return self._resolve_value(m.group(1))

            rec_num = get_short("n")
            if rec_num is None:
                continue
            records.append({
                "number": int(rec_num) if isinstance(rec_num, str) and rec_num.isdigit() else rec_num,
                "slug": get_long("s"),
                "title": get_long("t"),
                "koreanTitle": get_long("k"),
                "authority": get_short("a"),
                "ui": get_short("ui"),
                "ux": get_short("ux"),
                "backend": get_short("be"),
            })
        return records

    def test_registry_has_exact_ordered_unique_numbers_one_through_fiftyfive(self) -> None:
        numbers = self._all_numbers()
        expected = list(range(1, 56))
        self.assertEqual(numbers, expected)

    def test_no_duplicate_numbers(self) -> None:
        numbers = self._all_numbers()
        self.assertEqual(len(numbers), len(set(numbers)))

    def test_all_numbers_present(self) -> None:
        numbers = set(self._all_numbers())
        for i in range(1, 56):
            self.assertIn(i, numbers, f"Business {i} missing")

    def test_fifteen_is_reserved(self) -> None:
        records = self._records()
        b15 = next(r for r in records if r["number"] == 15)
        self.assertEqual(b15["authority"], "reserved")

    def test_no_progress_field(self) -> None:
        """No impressionistic progress field should exist."""
        self.assertNotIn("progress:", self.script)

    def test_all_records_have_required_fields(self) -> None:
        records = self._records()
        self.assertEqual(len(records), 55)
        for r in records:
            self.assertIsNotNone(r["number"], f"Missing number")
            self.assertIsNotNone(r["slug"], f"B{r['number']} missing slug")
            self.assertIsNotNone(r["title"], f"B{r['number']} missing title")
            self.assertIsNotNone(r["authority"], f"B{r['number']} missing authority")

    def test_valid_number_authority_vocabulary(self) -> None:
        records = self._records()
        bad = []
        for r in records:
            if r["authority"] not in VALID_AUTHORITY:
                bad.append(f"B{r['number']}: invalid authority '{r['authority']}'")
        self.assertEqual([], bad)

    def test_valid_ui_vocabulary(self) -> None:
        records = self._records()
        bad = []
        for r in records:
            if r["ui"] is not None and r["ui"] not in VALID_UI:
                bad.append(f"B{r['number']}: invalid uiStatus '{r['ui']}'")
        self.assertEqual([], bad)

    def test_valid_ux_vocabulary(self) -> None:
        records = self._records()
        bad = []
        for r in records:
            if r["ux"] is not None and r["ux"] not in VALID_UX:
                bad.append(f"B{r['number']}: invalid uxStatus '{r['ux']}'")
        self.assertEqual([], bad)

    def test_valid_backend_vocabulary(self) -> None:
        records = self._records()
        bad = []
        for r in records:
            if r["backend"] is not None and r["backend"] not in VALID_BACKEND:
                bad.append(f"B{r['number']}: invalid backendStatus '{r['backend']}'")
        self.assertEqual([], bad)

    def test_candidates_not_labeled_canonical(self) -> None:
        records = self._records()
        for r in records:
            if r["authority"] == "candidate":
                self.assertNotEqual(
                    r.get("numberAuthority", r["authority"]),
                    "canonical",
                    f"B{r['number']}: candidate labeled canonical",
                )

    def test_ui_approval_does_not_imply_ux_approval(self) -> None:
        records = self._records()
        for r in records:
            if r["ui"] == "UI_APPROVED" and r["ux"] == "UX_APPROVED":
                self.assertIn(
                    r["authority"],
                    {"existing-project"},
                    f"B{r['number']}: UI_APPROVED and UX_APPROVED on non-existing project",
                )

    def test_ux_approval_does_not_imply_backend_authorization(self) -> None:
        records = self._records()
        for r in records:
            if r["ux"] == "UX_APPROVED" and r["backend"] == "IMPLEMENTED":
                self.assertIn(
                    r["authority"],
                    {"existing-project", "canonical"},
                    f"B{r['number']}: UX_APPROVED and backend IMPLEMENTED without authority",
                )

    def test_no_secret_like_literals(self) -> None:
        forbidden = ("api_key", "private_key", "password",
                     "database_url", "firebase_service_account",
                     "GITHUB_APP_ID", "GITHUB_APP_INSTALLATION_ID",
                     "GITHUB_APP_PRIVATE_KEY")
        text = self.script.lower()
        for token in forbidden:
            self.assertNotIn(token.lower(), text)

    def test_no_absolute_local_paths(self) -> None:
        forbidden = ("G:\\\\", "C:\\\\", "D:\\\\", "Users\\\\")
        for token in forbidden:
            self.assertNotIn(token, self.script)

    def test_verified_surfaces_use_https(self) -> None:
        urls = re.findall(r"surfaceUrl:\s*\"([^\"]+)\"", self.script)
        for url in urls:
            self.assertTrue(url.startswith("https://"), f"Non-https URL: {url}")

    def test_external_links_safe(self) -> None:
        hrefs = re.findall(r"https?://[^\"]+", self.script)
        for href in hrefs:
            self.assertTrue(href.startswith("https://"), f"Non-https link: {href}")

    def test_business_one_is_canonical(self) -> None:
        records = self._records()
        b1 = next(r for r in records if r["number"] == 1)
        self.assertEqual(b1["authority"], "canonical")

    def test_business_fourteen_is_canonical(self) -> None:
        records = self._records()
        b14 = next(r for r in records if r["number"] == 14)
        self.assertEqual(b14["authority"], "canonical")

    def test_business_twentythree_is_existing_project(self) -> None:
        records = self._records()
        b23 = next(r for r in records if r["number"] == 23)
        self.assertEqual(b23["authority"], "existing-project")

    def test_business_thirty_six_is_proposed(self) -> None:
        records = self._records()
        b36 = next(r for r in records if r["number"] == 36)
        self.assertEqual(b36["authority"], "proposed-number")

    def test_business_forty_four_is_existing_project(self) -> None:
        records = self._records()
        b44 = next(r for r in records if r["number"] == 44)
        self.assertEqual(b44["authority"], "existing-project")

    def test_business_six_is_reconciliation(self) -> None:
        records = self._records()
        b6 = next(r for r in records if r["number"] == 6)
        self.assertEqual(b6["authority"], "number-reconciliation-required")

    def test_no_canonical_in_candidates_sixteen_to_twentytwo(self) -> None:
        records = self._records()
        for n in range(16, 23):
            r = next(rec for rec in records if rec["number"] == n)
            self.assertEqual(r["authority"], "candidate")

    def test_no_canonical_in_candidates_twentysix_to_thirtyfive(self) -> None:
        records = self._records()
        for n in range(26, 36):
            r = next(rec for rec in records if rec["number"] == n)
            self.assertEqual(r["authority"], "candidate")

    def test_no_canonical_in_candidates_fortyfive_to_fiftyfive(self) -> None:
        records = self._records()
        for n in range(45, 56):
            r = next(rec for rec in records if rec["number"] == n)
            self.assertEqual(r["authority"], "candidate")


if __name__ == "__main__":
    unittest.main()
