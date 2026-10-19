"""#3647 — bounded browser.control action slice 1 tests (agent-side authority).

Hermetic: no browser, no network, no model call, no production surface. The
taxonomy (#3607 effect classes), the authoritative lease policy values, the
full lease correlation set and the receipt pinning are exercised at the
exact-key level.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from kagent.browser_control_actions import (
    ACTION_RECEIPT_KEYS,
    BROWSER_ACTION_EXECUTION_IMPLEMENTED,
    CLICK_ALLOWED_ROLE_ALLOWLIST,
    DURABLE_ADMISSION_WIRED,
    DOWNLOAD_EXECUTION_BLOCKED_UNTIL_ARTIFACT_AUTHORITY,
    GENERIC_IPC_SURFACE,
    JAVASCRIPT_EVALUATE_PERMITTED,
    LEASE_CROSS_ORIGIN_POLICY,
    LEASE_ELIGIBLE_ACTIONS,
    LEASE_IDLE_SECONDS,
    LEASE_MAX_ACTIONS,
    LEASE_MAX_ACTIONS_HARD_CAP,
    LEASE_REVOCATION,
    LEASE_RUN_TRANSFER,
    LEASE_SITE_SCOPE_POLICY,
    LEASE_TTL_MAX_SECONDS,
    LEASE_TTL_SECONDS,
    MAX_ACTION_TEXT_CHARS,
    MAX_SCROLL_DELTA,
    MAX_SELECT_INDEX,
    NEW_APPROVAL_STORE,
    OUT_OF_SCOPE_ACTIONS,
    OUT_OF_SCOPE_SURFACES,
    PROHIBITED_ACTIONS,
    SECOND_BROWSER_AUTHORITY,
    SLICE1_ORIGIN_SCOPE,
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
        "browser_session_ref": "run/session-1",
        "origin_ref": "https://example.com",
        "element_ref": "el-0002",
        "params": None,
    }
    values.update(overrides)
    return BrowserControlActionRequest(**values)  # type: ignore[arg-type]


def lease(**overrides: object) -> BrowserControlActionLease:
    values: dict[str, object] = {
        "lease_id": "lease/session-1",
        "request_fingerprint": "fingerprint/session-1",
        "browser_session_ref": "run/session-1",
        "run_ref": "run_3647",
        "workspace_ref": "workspace_3647",
        "owner_ref": "owner_3647",
        "allowed_action_classes": ("click", "type", "scroll", "focus", "select"),
        "origin_scope": "https://example.com",
        "max_actions": LEASE_MAX_ACTIONS,
        "issued_at": NOW,
        "expires_at": NOW + timedelta(seconds=LEASE_TTL_SECONDS),
        "approval_ref": "decision_3647",
        "evidence_ref": "evidence_3647",
    }
    values.update(overrides)
    return BrowserControlActionLease(**values)  # type: ignore[arg-type]


class LeasePolicyValuesTest(unittest.TestCase):
    def test_authoritative_3607_lease_values_are_declared_exactly(self) -> None:
        self.assertEqual(LEASE_TTL_SECONDS, 300)
        self.assertEqual(LEASE_TTL_MAX_SECONDS, 900)
        self.assertEqual(LEASE_MAX_ACTIONS, 25)
        self.assertEqual(LEASE_MAX_ACTIONS_HARD_CAP, 100)
        self.assertEqual(LEASE_IDLE_SECONDS, 120)
        self.assertEqual(LEASE_SITE_SCOPE_POLICY, "EXACT_ORIGIN_MAX_3_NO_WILDCARD")
        self.assertEqual(SLICE1_ORIGIN_SCOPE, "EXACT_ONE_ORIGIN")
        self.assertEqual(LEASE_CROSS_ORIGIN_POLICY, "INVALIDATE_AND_REQUIRE_STEP_UP")
        self.assertEqual(LEASE_RUN_TRANSFER, "PROHIBITED")
        self.assertEqual(LEASE_REVOCATION, "IMMEDIATE_USER_VISIBLE")
        self.assertTrue(DOWNLOAD_EXECUTION_BLOCKED_UNTIL_ARTIFACT_AUTHORITY)


class ActionTaxonomyTest(unittest.TestCase):
    def test_slice_1_implements_exactly_the_lease_eligible_set(self) -> None:
        self.assertEqual(
            LEASE_ELIGIBLE_ACTIONS, ("scroll", "focus", "click", "type", "select")
        )
        self.assertTrue(BROWSER_ACTION_EXECUTION_IMPLEMENTED)
        self.assertFalse(STEP_UP_EXECUTION_IMPLEMENTED)

    def test_step_up_classes_match_the_3607_effect_classes(self) -> None:
        self.assertEqual(
            STEP_UP_REQUIRED_ACTIONS,
            (
                "submit",
                "credential_field_interaction",
                "upload",
                "download",
                "clipboard_read",
                "clipboard_write",
                "cross_origin_navigation",
            ),
        )
        for action in STEP_UP_REQUIRED_ACTIONS:
            self.assertEqual(classify_browser_control_action(action), "step_up_required")
            with self.assertRaises(BrowserControlActionRefusal) as caught:
                BrowserControlActionRequest(  # type: ignore[arg-type]
                    action=action,  # type: ignore[dict-item]
                    browser_session_ref="run/session-1",
                    origin_ref="https://example.com",
                )
            self.assertEqual(caught.exception.code, "step_up_required")

    def test_prohibited_classes_are_never_step_up_able(self) -> None:
        self.assertEqual(
            PROHIBITED_ACTIONS,
            (
                "javascript_evaluate",
                "payment_or_purchase",
                "account_or_security_change",
                "destructive_action",
                "permission_prompt",
            ),
        )
        for action in PROHIBITED_ACTIONS:
            self.assertEqual(classify_browser_control_action(action), "prohibited")
            with self.assertRaises(BrowserControlActionRefusal) as caught:
                BrowserControlActionRequest(  # type: ignore[arg-type]
                    action=action,  # type: ignore[dict-item]
                    browser_session_ref="run/session-1",
                    origin_ref="https://example.com",
                )
            self.assertEqual(caught.exception.code, "action_prohibited")

    def test_out_of_scope_surfaces_are_never_classified_as_actions(self) -> None:
        self.assertEqual(OUT_OF_SCOPE_ACTIONS, ("external_protocol_launch",))
        self.assertEqual(
            OUT_OF_SCOPE_SURFACES,
            ("os_computer_use", "generic_cdp_devtools_surface", "file_navigation"),
        )
        self.assertEqual(classify_browser_control_action("external_protocol_launch"), "out_of_scope")
        with self.assertRaises(BrowserControlActionRefusal) as caught:
            BrowserControlActionRequest(  # type: ignore[arg-type]
                action="external_protocol_launch",
                browser_session_ref="run/session-1",
                origin_ref="https://example.com",
            )
        self.assertEqual(caught.exception.code, "out_of_scope")

    def test_unknown_actions_are_refused(self) -> None:
        with self.assertRaises(BrowserControlActionRefusal) as caught:
            classify_browser_control_action("format_the_disk")  # type: ignore[arg-type]
        self.assertEqual(caught.exception.code, "unknown_action")

    def test_click_roles_provable_non_committing_only(self) -> None:
        # The #3629 projection cannot prove link/button/menuitem/checkbox/
        # radio/switch/option clicks non-committing; only tab/treeitem remain.
        self.assertEqual(CLICK_ALLOWED_ROLE_ALLOWLIST, frozenset({"tab", "treeitem"}))


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
        for bad_text in ("line1\nline2", "tab\there", "x" * (MAX_ACTION_TEXT_CHARS + 1), ""):
            with self.assertRaises(BrowserControlActionRefusal):
                action_request(action="type", params={"text": bad_text})
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
    def test_lease_carries_the_full_correlation_set(self) -> None:
        bounded = lease()
        self.assertEqual(bounded.request_fingerprint, "fingerprint/session-1")
        self.assertEqual(bounded.browser_session_ref, "run/session-1")
        self.assertEqual(bounded.run_ref, "run_3647")
        self.assertEqual(bounded.workspace_ref, "workspace_3647")
        self.assertEqual(bounded.owner_ref, "owner_3647")
        self.assertEqual(bounded.approval_ref, "decision_3647")
        self.assertEqual(bounded.evidence_ref, "evidence_3647")
        self.assertEqual(bounded.origin_scope, "https://example.com")

    def test_lease_binds_origin_session_actions_count_and_ttl(self) -> None:
        bounded = lease()
        self.assertTrue(bounded.allows(action_request()))
        self.assertFalse(
            bounded.allows(action_request(origin_ref="https://other.example"))
        )
        self.assertFalse(
            lease(allowed_action_classes=("click",)).allows(
                action_request(action="type", params={"text": "hi"})
            )
        )
        self.assertFalse(
            bounded.allows(action_request(browser_session_ref="run/session-2"))
        )

    def test_lease_refuses_out_of_family_shapes(self) -> None:
        with self.assertRaises(BrowserControlActionRefusal):
            lease(allowed_action_classes=())
        with self.assertRaises(BrowserControlActionRefusal):
            lease(allowed_action_classes=("submit",))
        with self.assertRaises(BrowserControlActionRefusal):
            lease(max_actions=LEASE_MAX_ACTIONS_HARD_CAP + 1)
        with self.assertRaises(BrowserControlActionRefusal):
            lease(expires_at=NOW + timedelta(seconds=LEASE_TTL_MAX_SECONDS + 1))
        with self.assertRaises(BrowserControlActionRefusal):
            lease(expires_at=NOW)  # non-positive lifetime
        with self.assertRaises(BrowserControlActionRefusal):
            lease(origin_scope="https://example.com/path?token=secret")
        with self.assertRaises(BrowserControlActionRefusal):
            lease(request_fingerprint="")

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
