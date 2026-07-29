from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "businesses.js"
VOCAB = ROOT / "business-authority-vocabulary.js"


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

PRODUCT_DECISION_MAP = {
    15: 187, 16: 189, 17: 191, 18: 196, 19: 198, 20: 200,
    21: 204, 22: 222, 26: 226, 27: 230, 28: 234, 29: 236,
    30: 240, 31: 241, 32: 246, 33: 247, 34: 252, 35: 253,
    36: 266, 37: 259, 38: 267, 39: 261, 40: 270, 41: 271,
    42: 274, 43: 275,
}


class BusinessRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vocab_script = VOCAB.read_text(encoding="utf-8")
        cls.script = REGISTRY.read_text(encoding="utf-8")

    # ── Helpers ──

    def _resolve_value(self, raw):
        if raw == "null" or raw is None:
            return None
        if raw.startswith('"') and raw.endswith('"'):
            return raw[1:-1]
        value_map = {
            "NA.CANONICAL": "canonical",
            "NA.PROPOSED": "proposed-number",
            "NA.CANDIDATE": "candidate",
            "NA.EXISTING_PROJECT": "existing-project",
            "NA.RESERVED": "reserved",
            "NA.RECONCILIATION": "number-reconciliation-required",
            "UI.NOT_STARTED": "NOT_STARTED",
            "UI.IN_PROGRESS": "IN_PROGRESS",
            "UI.NOT_READY": "UI_NOT_READY",
            "UI.CONDITIONALLY_READY": "UI_CONDITIONALLY_READY",
            "UI.APPROVED": "UI_APPROVED",
            "UI.NOT_APPLICABLE": "NOT_APPLICABLE",
            "UX.BLOCKED_BY_UI": "BLOCKED_BY_UI",
            "UX.NOT_STARTED": "NOT_STARTED",
            "UX.IN_PROGRESS": "IN_PROGRESS",
            "UX.NOT_READY": "UX_NOT_READY",
            "UX.CONDITIONALLY_READY": "UX_CONDITIONALLY_READY",
            "UX.APPROVED": "UX_APPROVED",
            "UX.NOT_APPLICABLE": "NOT_APPLICABLE",
            "BE.FROZEN": "FROZEN",
            "BE.DECISION_PENDING": "DECISION_PENDING",
            "BE.DEFERRED": "DEFERRED",
            "BE.AUTHORIZED": "AUTHORIZED",
            "BE.IN_PROGRESS": "IN_PROGRESS",
            "BE.IMPLEMENTED": "IMPLEMENTED",
            "BE.NOT_APPLICABLE": "NOT_APPLICABLE",
        }
        return value_map.get(raw, raw)

    def _records(self):
        """Parse each rec({...}) block and extract ALL fields."""
        records = []
        # Match rec({...}) blocks
        blocks = re.findall(r"\brec\(\{(.*?)\}\)", self.script, re.DOTALL)
        for block in blocks:
            def get_short(k):
                m = re.search(
                    rf"\b{k}:\s*((\"[^\"]*\")|null|NA\.\w+|UI\.\w+|UX\.\w+|BE\.\w+|\d+)",
                    block,
                )
                if not m:
                    return None
                return self._resolve_value(m.group(1))

            def get_string(k):
                m = re.search(rf"\b{k}:\s*(\"[^\"]*\")", block)
                if not m:
                    return None
                return self._resolve_value(m.group(1))

            num_raw = get_short("n")
            if num_raw is None:
                continue
            # Apply factory defaults for missing fields (same as rec() factory)
            ui_val = get_short("ui")
            ux_val = get_short("ux")
            be_val = get_short("be")
            rs_val = get_short("rs")
            l_val = get_short("l")
            lv_val = get_string("lv")
            r = {
                "number": int(num_raw) if isinstance(num_raw, str) and num_raw.isdigit() else num_raw,
                "slug": get_string("s"),
                "title": get_string("t"),
                "koreanTitle": get_string("k"),
                "numberAuthority": get_short("a"),
                "lifecycle": l_val or "concept",
                "state": get_short("st") or "planned",
                "uiStatus": ui_val or "NOT_STARTED",
                "uxStatus": ux_val or "BLOCKED_BY_UI",
                "backendStatus": be_val or "FROZEN",
                "productDecisionIssue": get_short("pdi"),
                "currentIssue": get_short("ci"),
                "currentPr": get_short("pr"),
                "releaseState": rs_val or "not_released",
                "lastVerified": lv_val or "2026-07-29",
                "sources": get_string("src"),
            }
            records.append(r)
        return records

    def _get_by_number(self, n):
        records = self._records()
        for r in records:
            if r["number"] == n:
                return r
        return None

    # ── Existence & ordering ──

    def test_registry_has_exact_ordered_unique_numbers(self):
        """Exactly 55 records, numbers 1-55, ascending, no gaps."""
        records = self._records()
        numbers = [r["number"] for r in records]
        self.assertEqual(len(numbers), 55)
        self.assertEqual(numbers, list(range(1, 56)))
        self.assertEqual(len(numbers), len(set(numbers)))

    def test_all_records_have_required_fields(self):
        records = self._records()
        self.assertEqual(len(records), 55)
        required = ["number", "slug", "title", "koreanTitle",
                     "numberAuthority", "lifecycle", "uiStatus", "uxStatus",
                     "backendStatus", "releaseState", "lastVerified", "sources"]
        for r in records:
            for field in required:
                self.assertIsNotNone(
                    r.get(field),
                    f"B{r['number']}: missing required field '{field}'",
                )
            # Phase states should never be None
            self.assertIsNotNone(r["uiStatus"], f"B{r['number']}: uiStatus is None")
            self.assertIsNotNone(r["uxStatus"], f"B{r['number']}: uxStatus is None")
            self.assertIsNotNone(r["backendStatus"], f"B{r['number']}: backendStatus is None")

    # ── Vocabulary validation ──

    def test_valid_number_authority_vocabulary(self):
        records = self._records()
        bad = [f"B{r['number']}: invalid authority '{r['numberAuthority']}'"
               for r in records if r["numberAuthority"] not in VALID_AUTHORITY]
        self.assertEqual(bad, [])

    def test_valid_ui_vocabulary(self):
        records = self._records()
        bad = [f"B{r['number']}: invalid uiStatus '{r['uiStatus']}'"
               for r in records if r["uiStatus"] not in VALID_UI]
        self.assertEqual(bad, [])

    def test_valid_ux_vocabulary(self):
        records = self._records()
        bad = [f"B{r['number']}: invalid uxStatus '{r['uxStatus']}'"
               for r in records if r["uxStatus"] not in VALID_UX]
        self.assertEqual(bad, [])

    def test_valid_backend_vocabulary(self):
        records = self._records()
        bad = [f"B{r['number']}: invalid backendStatus '{r['backendStatus']}'"
               for r in records if r["backendStatus"] not in VALID_BACKEND]
        self.assertEqual(bad, [])

    # ── Invariant sums ──

    def test_authority_counts_sum_to_55(self):
        records = self._records()
        counts = {}
        for r in records:
            counts[r["numberAuthority"]] = counts.get(r["numberAuthority"], 0) + 1
        total = sum(counts.values())
        self.assertEqual(total, 55, f"Authority counts sum to {total}, not 55")

    def test_ui_counts_sum_to_55(self):
        records = self._records()
        counts = {}
        for r in records:
            counts[r["uiStatus"]] = counts.get(r["uiStatus"], 0) + 1
        total = sum(counts.values())
        self.assertEqual(total, 55, f"UI counts sum to {total}, not 55")

    def test_ux_counts_sum_to_55(self):
        records = self._records()
        counts = {}
        for r in records:
            counts[r["uxStatus"]] = counts.get(r["uxStatus"], 0) + 1
        total = sum(counts.values())
        self.assertEqual(total, 55, f"UX counts sum to {total}, not 55")

    def test_backend_counts_sum_to_55(self):
        records = self._records()
        counts = {}
        for r in records:
            counts[r["backendStatus"]] = counts.get(r["backendStatus"], 0) + 1
        total = sum(counts.values())
        self.assertEqual(total, 55, f"Backend counts sum to {total}, not 55")

    # ── Correct authority for specific businesses ──

    def test_canonical_entries(self):
        for n in [1, 2, 3, 4, 13, 14]:
            r = self._get_by_number(n)
            self.assertEqual(r["numberAuthority"], "canonical", f"B{n} should be canonical")

    def test_proposed_entries(self):
        proposed = [5, 7, 8, 9, 10, 11, 12, 15, 16, 17, 18, 19, 20, 21, 22,
                    26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43]
        for n in proposed:
            r = self._get_by_number(n)
            self.assertEqual(r["numberAuthority"], "proposed-number",
                             f"B{n} should be proposed-number, got {r['numberAuthority']}")

    def test_existing_project_entries(self):
        for n in [23, 24, 25, 44]:
            r = self._get_by_number(n)
            self.assertEqual(r["numberAuthority"], "existing-project",
                             f"B{n} should be existing-project, got {r['numberAuthority']}")

    def test_reserved_entries(self):
        n = 6
        # B06 is number-reconciliation-required, not reserved
        # No true reserved entries now
        pass

    def test_number_reconciliation(self):
        r = self._get_by_number(6)
        self.assertEqual(r["numberAuthority"], "number-reconciliation-required",
                         "B06 should be number-reconciliation-required")

    def test_candidate_entries(self):
        candidate = list(range(45, 56))  # 45-55
        for n in candidate:
            r = self._get_by_number(n)
            self.assertEqual(r["numberAuthority"], "candidate",
                             f"B{n} should be candidate, got {r['numberAuthority']}")

    # ── Product-decision Issue mapping ──

    def test_product_decision_issue_mappings(self):
        """Verify product-decision issues for all mapped Businesses."""
        records = self._records()
        for n, expected_issue in PRODUCT_DECISION_MAP.items():
            r = self._get_by_number(n)
            actual = r["productDecisionIssue"]
            self.assertIsNotNone(actual, f"B{n}: productDecisionIssue is None")
            self.assertEqual(
                actual, str(expected_issue),
                f"B{n}: expected productDecisionIssue #{expected_issue}, got #{actual}",
            )

    def test_businesses_with_product_decision_are_not_candidate_only(self):
        """Any Business with a product-decision issue must not be 'candidate' authority."""
        records = self._records()
        for r in records:
            if r["productDecisionIssue"] is not None:
                self.assertNotEqual(
                    r["numberAuthority"], "candidate",
                    f"B{r['number']}: has productDecisionIssue #{r['productDecisionIssue']} but is candidate",
                )

    def test_businesses_with_phase1_issue_have_ui_in_progress_or_approved(self):
        """Any Business with a Phase 1 UI Issue should not have UI NOT_STARTED."""
        # These have Phase 1 UI issues: check their UI status
        # B7-B22 and B26-B43 have Phase 1 UI issues
        businesses_with_ui_issue = list(range(7, 23)) + list(range(26, 44))
        for n in businesses_with_ui_issue:
            r = self._get_by_number(n)
            self.assertNotEqual(
                r["uiStatus"], "NOT_STARTED",
                f"B{n}: has Phase 1 UI Issue but uiStatus is NOT_STARTED",
            )

    # ── Phase constraint invariants ──

    def test_ui_approved_does_not_imply_ux_approved(self):
        """UI_APPROVED must not automatically set UX_APPROVED."""
        records = self._records()
        for r in records:
            if r["uiStatus"] == "UI_APPROVED" and r["uxStatus"] == "UX_APPROVED":
                # Only permitted for existing-projects with UX work
                self.assertEqual(
                    r["numberAuthority"], "existing-project",
                    f"B{r['number']}: UI_APPROVED and UX_APPROVED on non-existing-project",
                )

    def test_ux_approved_does_not_imply_backend_authorized(self):
        """UX_APPROVED must not automatically set backend AUTHORIZED."""
        records = self._records()
        for r in records:
            if r["uxStatus"] == "UX_APPROVED" and r["backendStatus"] == "AUTHORIZED":
                self.fail(f"B{r['number']}: UX_APPROVED implies backend AUTHORIZED")

    # ── Security / path invariants ──

    def test_no_secret_like_literals(self):
        text = self.script.lower()
        forbidden = ("api_key", "private_key", "password",
                     "database_url", "firebase_service_account",
                     "github_app_id", "github_app_installation_id",
                     "github_app_private_key")
        for token in forbidden:
            self.assertNotIn(token.lower(), text)

    def test_no_absolute_local_paths(self):
        forbidden = ("G:\\\\", "C:\\\\", "D:\\\\", "Users\\\\")
        for token in forbidden:
            self.assertNotIn(token, self.script)

    def test_verified_surfaces_use_https(self):
        urls = re.findall(r"\bsu:\s*\"([^\"]+)\"", self.script)
        for url in urls:
            self.assertTrue(url.startswith("https://"), f"Non-https URL: {url}")

    def test_no_progress_field(self):
        self.assertNotIn("progress:", self.script)

    # ── Vocabulary file validation ──

    def test_vocabulary_file_exists_and_valid(self):
        self.assertTrue(VOCAB.is_file())
        self.assertIn("NUMBER_AUTHORITY", self.vocab_script)
        self.assertIn("UI_STATUS", self.vocab_script)
        self.assertIn("UX_STATUS", self.vocab_script)
        self.assertIn("BACKEND_STATUS", self.vocab_script)
        self.assertIn("function rec", self.vocab_script)
        self.assertIn("generateSummary", self.vocab_script)


if __name__ == "__main__":
    unittest.main()
