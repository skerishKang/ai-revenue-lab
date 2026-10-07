"""#3647 — bounded browser.control action slice 1 tests (agent-side authority).

Hermetic: no browser, no network, no model call, no production surface. The
action taxonomy, request bounds, lease shape and receipt pinning of the
#3607/#3609 authority family are exercised at the exact-key level.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from kagent.browser_control_actions import (
    ACTION_RECEIPT_KEYS,
    BROWSER_ACTION_EXECUTION_IMPLEMENTED,
    DURABLE_ADMISSION_WIRED,
    GENERIC_IPC_SURFACE,
    JAVASCRIPT_EVALUATE_PERMITTED,
    LEASE_ELIGIBLE_ACTIONS,
    MAX_ACTIONS_PER_LEASE,
    MAX_ACTION_TEXT_CHARS,
    MAX_LEASE_TTL_SECONDS,
    MAX_SCROLL_DELTA,
    MAX_SELECT_INDEX,
    NEW_APPROVAL_STORE,
    PROHIBITED_ACTIONS,
    SECOND_BROWSER_AUTHORITY,
    STEP_UP_EXECUTION_IMPLEMENTED,
    STEP_UP_REQUIRED_ACTIONS,
    BrowserControlActionLease,
    BrowserControlActionRefusal,
    BrowserControlActionRequest,
    classify_browser_control_action,
    validate_bounded_action_receipt,
)
from kagent.browser_control_observation import BROWSER_CONTROL_OBSERVATION_IMPLEMENTED
from kagent.browser_open import BROWSER_OPEN_PAGE_DERIVED_BYTES

NOW = datetime(2026, 10, 8, 9, 0, 0, tzinfo=timezone.utc)


def action_request(**overrides: object) -> BrowserControlActionRequest:
    values: dict[str, object] = {
        "action": "click",
        "session_ref": "run/session-1",
        "origin_ref": "https://example.com",
        "element_ref": "el-0002",
        "params": None,
    }
    values.update(overrides)
    return BrowserControlActionRequest(**values)  # type: ignore[arg-type]


def lease(**overrides: object) -> BrowserControlActionLease:
    values: dict[str, object] = {
        "lease_id": "lease/session-1",
        "session_ref": "run/session-1",
        "origin_ref": "https://example.com",
        "allowed_actions": ("click", "type", "scroll", "focus", "select"),
        "max_actions": 8,
        "issued_at": NOW,
        "expires_at": NOW + timedelta(seconds=300),
    }
    values.update(overrides)
    return BrowserControlActionLease(**values)  # type: ignore[arg-type]


class ActionTaxonomyTest(unittest.TestCase):
    def test_slice_1_implements_exactly_the_lease_eligible_set(self) -> None:
        self.assertEqual(
            LEASE_ELIGIBLE_ACTIONS, ("scroll", "focus", "click", "type", "select")
        )
        self.assertTrue(BROWSER_ACTION_EXECUTION_IMPLEMENTED)
        self.assertFalse(STEP_UP_EXECUTION_IMPLEMENTED)

    def test_step_up_classes_are_refused_by_construction(self) -> None:
        for action in STEP_UP_REQUIRED_ACTIONS:
            with self.assertRaises(BrowserControlActionRefusal) as caught:
                classify_browser_control_action(action)
                BrowserControlActionRequest(  # type: ignore[arg-type]
                    action=action,  # type: ignore[dict-item]
                    session_ref="run/session-1",
                    origin_ref="https://example.com",
                )
            self.assertIn(
                caught.exception.code, {"step_up_required", "unknown_action"}, action
            )

    def test_submit_download_and_credential_interaction_are_step_up(self) -> None:
        self.assertEqual(classify_browser_control_action("submit"), "step_up_required")
        self.assertEqual(classify_browser_control_action("download"), "step_up_required")
        self.assertEqual(
            classify_browser_control_action("credential_field_interaction"), "step_up_required"
        )
        self.assertEqual(
            classify_browser_control_action("cross_origin_navigation"), "step_up_required"
        )

    def test_prohibited_actions_stay_prohibited(self) -> None:
        self.assertEqual(
            PROHIBITED_ACTIONS, ("javascript_evaluate", "observe_dom_read")
        )
        for action in PROHIBITED_ACTIONS:
            with self.assertRaises(BrowserControlActionRefusal) as caught:
                BrowserControlActionRequest(  # type: ignore[arg-type]
                    action=action,  # type: ignore[dict-item]
                    session_ref="run/session-1",
                    origin_ref="https://example.com",
                )
            self.assertEqual(caught.exception.code, "action_prohibited")

    def test_unknown_actions_are_refused(self) -> None:
        with self.assertRaises(BrowserControlActionRefusal) as caught:
            classify_browser_control_action("format_the_disk")  # type: ignore[arg-type]
        self.assertEqual(caught.exception.code, "unknown_action")


class ActionRequestBoundsTest(unittest.TestCase):
    def test_click_and_focus_require_a_bounded_element_ref_and_no_params(self) -> None:
        for action in ("click", "focus"):
            request = action_request(action=action)
            self.assertEqual(request.element_ref, "el-0002")
            with self.assertRaises(BrowserControlActionRefusal):
                action_request(action=action, element_ref="not-bounded")
            with self.assertRaises(BrowserControlActionRefusal):
                action_request(action=action, params={"force": True})

    def test_scroll_takes_bounded_deltas_and_no_element(self) -> None:
        request = action_request(
            action="scroll", element_ref=None, params={"dx": 0, "dy": -MAX_SCROLL_DELTA}
        )
        self.assertEqual(request.params, {"dx": 0, "dy": -MAX_SCROLL_DELTA})
        with self.assertRaises(BrowserControlActionRefusal):
            action_request(action="scroll", element_ref=None, params={"dx": MAX_SCROLL_DELTA + 1, "dy": 0})
        with self.assertRaises(BrowserControlActionRefusal):
            action_request(action="scroll", element_ref="el-0001", params={"dx": 1, "dy": 0})
        with self.assertRaises(BrowserControlActionRefusal):
            action_request(action="scroll", element_ref=None, params={"dx": 1})

    def test_type_is_single_line_bounded_non_credential_text(self) -> None:
        request = action_request(action="type", params={"text": "안녕하세요"})
        self.assertEqual(request.params, {"text": "안녕하세요"})
        self.assertLessEqual(
            len(request.params["text"]), MAX_ACTION_TEXT_CHARS  # type: ignore[index]
        )
        with self.assertRaises(BrowserControlActionRefusal):
            action_request(action="type", params={"text": "line1\nline2"})
        with self.assertRaises(BrowserControlActionRefusal):
            action_request(action="type", params={"text": "tab\there"})
        with self.assertRaises(BrowserControlActionRefusal):
            action_request(action="type", params={"text": "x" * (MAX_ACTION_TEXT_CHARS + 1)})
        with self.assertRaises(BrowserControlActionRefusal):
            action_request(action="type", params={})

    def test_select_takes_a_bounded_option_index(self) -> None:
        request = action_request(action="select", params={"option_index": 3})
        self.assertEqual(request.params, {"option_index": 3})
        with self.assertRaises(BrowserControlActionRefusal):
            action_request(action="select", params={"option_index": MAX_SELECT_INDEX + 1})
        with self.assertRaises(BrowserControlActionRefusal):
            action_request(action="select", params={"option_value": "three"})

    def test_requests_are_serialization_bounded(self) -> None:
        payload = action_request().safe_dict()
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self.assertLessEqual(len(encoded.encode("utf-8")), 2048)


class ActionLeaseTest(unittest.TestCase):
    def test_lease_binds_origin_session_actions_count_and_ttl(self) -> None:
        bounded = lease()
        self.assertTrue(bounded.allows(action_request()))
        self.assertFalse(
            bounded.allows(action_request(origin_ref="https://other.example"))
        )
        self.assertFalse(
            lease(allowed_actions=("click",)).allows(
                action_request(action="type", params={"text": "hi"})
            )
        )
        self.assertFalse(bounded.allows(action_request(session_ref="run/session-2")))

    def test_lease_refuses_out_of_family_shapes(self) -> None:
        with self.assertRaises(BrowserControlActionRefusal):
            lease(allowed_actions=())
        with self.assertRaises(BrowserControlActionRefusal):
            lease(allowed_actions=("submit",))
        with self.assertRaises(BrowserControlActionRefusal):
            lease(max_actions=MAX_ACTIONS_PER_LEASE + 1)
        with self.assertRaises(BrowserControlActionRefusal):
            lease(expires_at=NOW + timedelta(seconds=MAX_LEASE_TTL_SECONDS + 1))
        with self.assertRaises(BrowserControlActionRefusal):
            lease(expires_at=NOW + timedelta(seconds=30))
        with self.assertRaises(BrowserControlActionRefusal):
            lease(origin_ref="https://example.com/path?token=secret")

    def test_slice_does_not_create_a_second_approval_authority(self) -> None:
        self.assertFalse(NEW_APPROVAL_STORE)
        self.assertFalse(DURABLE_ADMISSION_WIRED)
        self.assertFalse(SECOND_BROWSER_AUTHORITY)
        self.assertFalse(GENERIC_IPC_SURFACE)
        self.assertFalse(JAVASCRIPT_EVALUATE_PERMITTED)
        self.assertTrue(BROWSER_CONTROL_OBSERVATION_IMPLEMENTED)
        self.assertEqual(BROWSER_OPEN_PAGE_DERIVED_BYTES, 0)


class ActionReceiptTest(unittest.TestCase):
    def test_receipts_are_exact_and_pin_zero_page_derived_bytes(self) -> None:
        receipt = {
            "action_id": "act_" + "a" * 24,
            "action": "click",
            "element_ref": "el-0002",
            "origin_ref": "https://example.com",
            "outcome": "dispatched",
            "page_content_included": False,
            "cookie_included": False,
            "credential_value_included": False,
            "dom_api_exposed": False,
        }
        self.assertEqual(validate_bounded_action_receipt(receipt), receipt)

    def test_receipt_drift_is_refused(self) -> None:
        base = {
            "action_id": "act_" + "a" * 24,
            "action": "click",
            "element_ref": None,
            "origin_ref": "https://example.com",
            "outcome": "dispatched",
            "page_content_included": False,
            "cookie_included": False,
            "credential_value_included": False,
            "dom_api_exposed": False,
        }
        for mutation in (
            {"page_content_included": True},
            {"outcome": "submitted"},
            {"action_id": "renderer-minted"},
            {"element_ref": "el-12"},
            {"extra": True},
        ):
            payload = dict(base)
            payload.update(mutation)
            with self.assertRaises(BrowserControlActionRefusal):
                validate_bounded_action_receipt(payload)
        self.assertTrue(ACTION_RECEIPT_KEYS)


if __name__ == "__main__":
    unittest.main()
