"""Focused contract tests: evidence/citation presentation (S4)."""

import json
import unittest

from padiem_embedded_runtime import SidecarContractError
from padiem_embedded_runtime.evidence import (
    DROP_REASON_INVALID_FIELD,
    DROP_REASON_MALFORMED_ITEM,
    STATUS_DEGRADED,
    STATUS_EMPTY,
    STATUS_READY,
    normalize_citation,
    present_citations,
)


def citation(source_id="doc-a", title="Alpha", locator=""):
    raw = {"source_id": source_id, "title": title}
    if locator:
        raw["locator"] = locator
    return raw


class CitationNormalizeTests(unittest.TestCase):
    def test_valid_citation_normalizes(self):
        ref = normalize_citation(citation("doc-a", "Alpha", "s1.2"))
        self.assertEqual(ref.source_id, "doc-a")
        self.assertEqual(ref.locator, "s1.2")
        json.dumps(ref.to_public_dict())

    def test_rejects_unknown_fields_and_missing_source(self):
        with self.assertRaises(SidecarContractError):
            normalize_citation({"source_id": "a", "url": "javascript:alert(1)"})
        with self.assertRaises(SidecarContractError):
            normalize_citation({"title": "no source"})
        with self.assertRaises(SidecarContractError):
            normalize_citation("not-a-mapping")

    def test_rejects_non_public_material(self):
        for bad_title in [
            "my api_key is abc",
            "Bearer tok123",
            "<script>alert(1)</script>",
            "tool_args: {...}",
            "Traceback (most recent call last)",
        ]:
            with self.assertRaises(SidecarContractError):
                normalize_citation(citation("doc-a", bad_title))

    def test_rejects_oversize_and_bad_ids(self):
        with self.assertRaises(SidecarContractError):
            normalize_citation(citation("doc-a", "x" * 121))
        with self.assertRaises(SidecarContractError):
            normalize_citation(citation("bad id with spaces"))
        with self.assertRaises(SidecarContractError):
            normalize_citation(citation("doc-a", "ok", "y" * 81))


class PresentationTests(unittest.TestCase):
    def test_ready_path_orders_and_labels_deterministically(self):
        presentation = present_citations(
            [
                citation("doc-beta", "Beta", "p1"),
                citation("doc-alpha", "Alpha", "s2"),
                citation("doc-alpha", "Alpha", "s1"),
            ]
        )
        self.assertEqual(presentation.status, STATUS_READY)
        self.assertEqual(
            [(c.label, c.citation.source_id, c.citation.locator) for c in presentation.citations],
            [("[1]", "doc-alpha", "s1"), ("[2]", "doc-alpha", "s2"), ("[3]", "doc-beta", "p1")],
        )
        first = present_citations([citation("z"), citation("a")]).to_public_dict()
        second = present_citations([citation("z"), citation("a")]).to_public_dict()
        self.assertEqual(first, second)

    def test_dedup_on_source_and_locator_keeps_first_seen(self):
        presentation = present_citations(
            [citation("doc-a", "First", "x"), citation("doc-a", "Second", "x")]
        )
        self.assertEqual(len(presentation.citations), 1)
        self.assertEqual(presentation.citations[0].citation.title, "First")

    def test_empty_input_is_empty_not_error(self):
        presentation = present_citations([])
        self.assertEqual(presentation.status, STATUS_EMPTY)
        self.assertEqual(presentation.citations, ())
        self.assertEqual(presentation.dropped_count, 0)

    def test_malformed_items_degrade_without_raising(self):
        presentation = present_citations(
            [citation("doc-ok"), "not-a-mapping", citation("doc-bad", "api_key leak")]
        )
        self.assertEqual(presentation.status, STATUS_DEGRADED)
        self.assertEqual(presentation.dropped_count, 2)
        self.assertEqual(
            set(presentation.drop_reasons), {DROP_REASON_MALFORMED_ITEM, DROP_REASON_INVALID_FIELD}
        )
        self.assertEqual(len(presentation.citations), 1)
        public = json.dumps(presentation.to_public_dict())
        self.assertNotIn("api_key", public)
        self.assertNotIn("leak", public)

    def test_all_items_bad_degrades_with_no_citations(self):
        presentation = present_citations(["x", 7])
        self.assertEqual(presentation.status, STATUS_DEGRADED)
        self.assertEqual(presentation.citations, ())

    def test_non_sequence_input_degrades(self):
        presentation = present_citations("not-a-list")
        self.assertEqual(presentation.status, STATUS_DEGRADED)
        self.assertEqual(presentation.dropped_count, 1)

    def test_citation_bound_is_enforced(self):
        items = [citation(f"doc-{i}", "t", f"L{i}") for i in range(20)]
        presentation = present_citations(items)
        self.assertLessEqual(len(presentation.citations), 12)
        self.assertGreater(presentation.dropped_count, 0)

    def test_presentation_status_allowlist(self):
        from padiem_embedded_runtime.evidence import CitationPresentation

        with self.assertRaises(SidecarContractError):
            CitationPresentation(status="raw_html", citations=())


if __name__ == "__main__":
    unittest.main()
