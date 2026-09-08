"""S5 attachment input presentation contract tests (network-free)."""

from __future__ import annotations

import unittest

from padiem_embedded_runtime.attachment_input import (
    HINT_OVER_SHARED_BOUND,
    HINT_SUPPORTED_MEDIA_TYPE,
    HINT_UNSUPPORTED_MEDIA_TYPE,
    MAX_SELECTIONS,
    REJECT_REASON_INVALID_GRAMMAR,
    REJECT_REASON_MALFORMED_ITEM,
    REJECT_REASON_URL_SHAPED,
    STATUS_DEGRADED,
    STATUS_EMPTY,
    STATUS_PRESENTED,
    STATUS_READY,
    STATUS_REJECTED,
    normalize_selection,
    present_attachment_ref,
    present_selections,
    present_upload_lifecycle,
)

VALID_REF = "att_Zm9vYmFyMTIzNDU2Nzg5MDEy"


class NormalizeSelectionTests(unittest.TestCase):
    def test_valid_descriptor_round_trips(self) -> None:
        descriptor = normalize_selection(
            {"name": "photo.png", "media_type": "image/png", "byte_size": 204800}
        )
        self.assertEqual(descriptor.name, "photo.png")
        self.assertEqual(descriptor.to_public_dict()["byte_size"], 204800)

    def test_unknown_field_fails_closed(self) -> None:
        with self.assertRaises(Exception):
            normalize_selection(
                {"name": "a.png", "media_type": "image/png", "byte_size": 1, "url": "x"}
            )

    def test_path_shaped_name_is_rejected(self) -> None:
        for name in ("C:\\dir\\a.png", "/tmp/a.png", "https://x.test/a.png", "../a.png"):
            with self.subTest(name=name):
                with self.assertRaises(Exception):
                    normalize_selection(
                        {"name": name, "media_type": "image/png", "byte_size": 1}
                    )

    def test_guarded_name_is_rejected(self) -> None:
        with self.assertRaises(Exception):
            normalize_selection(
                {"name": "api_key leak.png", "media_type": "image/png", "byte_size": 1}
            )

    def test_non_token_media_type_is_rejected(self) -> None:
        with self.assertRaises(Exception):
            normalize_selection(
                {"name": "a.png", "media_type": "https://evil/x", "byte_size": 1}
            )

    def test_non_integer_or_oversize_byte_size_is_rejected(self) -> None:
        for size in ("100", 1.5, True, -1, 256 * 1024 * 1024 + 1):
            with self.subTest(size=size):
                with self.assertRaises(Exception):
                    normalize_selection(
                        {"name": "a.png", "media_type": "image/png", "byte_size": size}
                    )


class PresentSelectionsTests(unittest.TestCase):
    def test_order_preserved_dedup_and_labels(self) -> None:
        presentation = present_selections(
            [
                {"name": "photo.png", "media_type": "image/png", "byte_size": 204800},
                {"name": "notes.pdf", "media_type": "application/pdf", "byte_size": 4096},
                {"name": "photo.png", "media_type": "image/png", "byte_size": 204800},
            ]
        )
        self.assertEqual(presentation.status, STATUS_READY)
        self.assertEqual([s.label for s in presentation.selections], ["[1]", "[2]"])
        self.assertEqual(presentation.selections[0].selection.name, "photo.png")

    def test_shared_bounds_are_hints_not_authority(self) -> None:
        presentation = present_selections(
            [
                {"name": "big.png", "media_type": "image/png", "byte_size": 5 * 1024 * 1024},
                {"name": "notes.txt", "media_type": "text/plain", "byte_size": 10},
            ]
        )
        self.assertEqual(presentation.status, STATUS_READY)
        big, notes = presentation.selections
        self.assertIn(HINT_SUPPORTED_MEDIA_TYPE, big.hints)
        self.assertIn(HINT_OVER_SHARED_BOUND, big.hints)
        self.assertEqual(notes.hints, (HINT_UNSUPPORTED_MEDIA_TYPE,))

    def test_selection_bound_is_enforced(self) -> None:
        items = [
            {"name": f"p{i}.png", "media_type": "image/png", "byte_size": i + 1}
            for i in range(MAX_SELECTIONS + 3)
        ]
        presentation = present_selections(items)
        self.assertEqual(len(presentation.selections), MAX_SELECTIONS)
        self.assertEqual(presentation.dropped_count, 3)
        self.assertEqual(presentation.status, STATUS_DEGRADED)

    def test_empty_input_is_empty_status(self) -> None:
        presentation = present_selections([])
        self.assertEqual(presentation.status, STATUS_EMPTY)
        self.assertEqual(presentation.selections, ())

    def test_malformed_items_drop_without_raising_or_retention(self) -> None:
        presentation = present_selections(
            [
                {"name": "ok.png", "media_type": "image/png", "byte_size": 100},
                "not-a-mapping",
                {"name": "C:\\x\\bad.png", "media_type": "image/png", "byte_size": 1},
            ]
        )
        self.assertEqual(presentation.status, STATUS_DEGRADED)
        self.assertEqual(presentation.dropped_count, 2)
        self.assertEqual(
            set(presentation.drop_reasons), {"MALFORMED_ITEM", "INVALID_FIELD"}
        )
        self.assertEqual(len(presentation.selections), 1)
        self.assertNotIn("bad", str(presentation.to_public_dict()))

    def test_non_sequence_input_degrades(self) -> None:
        presentation = present_selections("not-a-list")
        self.assertEqual(presentation.status, STATUS_DEGRADED)
        self.assertEqual(presentation.dropped_count, 1)


class LifecycleTests(unittest.TestCase):
    def test_valid_flow_states_pass(self) -> None:
        for state in ("idle", "selecting", "validating", "ready", "uploaded"):
            with self.subTest(state=state):
                view = present_upload_lifecycle({"state": state})
                self.assertEqual(view.state, state)
                self.assertFalse(view.degraded)

    def test_failed_requires_allowlisted_reason_only(self) -> None:
        view = present_upload_lifecycle({"state": "failed", "reason_code": "USER_CANCELLED"})
        self.assertEqual(view.state, "failed")
        self.assertEqual(view.reason_code, "USER_CANCELLED")
        self.assertFalse(view.degraded)

    def test_reason_on_non_failed_state_degrades(self) -> None:
        view = present_upload_lifecycle({"state": "ready", "reason_code": "USER_CANCELLED"})
        self.assertTrue(view.degraded)
        self.assertEqual(view.state, "idle")
        self.assertEqual(view.reason_code, "INVALID_HOST_INPUT")

    def test_malformed_input_never_raises_and_degrades_safely(self) -> None:
        for raw in (
            {"state": "exploded"},
            {"state": 7},
            "not-a-mapping",
            {"state": "idle", "url": "https://x"},
            {"state": "ready", "selection_count": 999},
        ):
            with self.subTest(raw=str(raw)):
                view = present_upload_lifecycle(raw)
                self.assertTrue(view.degraded)
                self.assertEqual(view.state, "idle")

    def test_selection_count_bound(self) -> None:
        view = present_upload_lifecycle({"state": "ready", "selection_count": MAX_SELECTIONS})
        self.assertEqual(view.selection_count, MAX_SELECTIONS)
        self.assertFalse(view.degraded)


class AttachmentRefTests(unittest.TestCase):
    def test_canonical_ref_presents(self) -> None:
        view = present_attachment_ref(VALID_REF)
        self.assertEqual(view.status, STATUS_PRESENTED)
        self.assertEqual(view.label, VALID_REF)

    def test_url_shaped_ref_rejected_without_retention(self) -> None:
        view = present_attachment_ref("https://storage.example.com/bucket/key")
        self.assertEqual(view.status, STATUS_REJECTED)
        self.assertEqual(view.reason_code, REJECT_REASON_URL_SHAPED)
        self.assertEqual(view.label, "")
        self.assertNotIn("storage.example.com", str(view.to_public_dict()))

    def test_bad_grammar_rejected(self) -> None:
        for value in ("att_short", "bogus_Zm9vYmFyMTIzNDU2Nzg5", "att_a/b", "file_att_1234567890123"):
            with self.subTest(value=value):
                view = present_attachment_ref(value)
                self.assertEqual(view.status, STATUS_REJECTED)
                self.assertIn(
                    view.reason_code, (REJECT_REASON_INVALID_GRAMMAR, REJECT_REASON_URL_SHAPED)
                )

    def test_non_string_rejected_as_malformed(self) -> None:
        for value in (None, 7, ["att_Zm9vYmFyMTIzNDU2Nzg5MDEy"]):
            with self.subTest(value=str(value)):
                view = present_attachment_ref(value)
                self.assertEqual(view.status, STATUS_REJECTED)
                self.assertEqual(view.reason_code, REJECT_REASON_MALFORMED_ITEM)


if __name__ == "__main__":
    unittest.main()
