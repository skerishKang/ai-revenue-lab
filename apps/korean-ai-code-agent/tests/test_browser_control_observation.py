"""#3629 — bounded page-observation authority tests (owner decision #3609).

Hermetic: no browser, no network, no model call, no production surface. The
deny-list rules of D1=ENABLED_BOUNDED are exercised at the exact-key level so
an edit that widens the projection fails here rather than in review.
"""

from __future__ import annotations

import unittest

from kagent.browser_control_observation import (
    BROWSER_ACTION_EXECUTION_IMPLEMENTED,
    BROWSER_CONTROL_OBSERVATION_IMPLEMENTED,
    BROWSER_OBSERVATION_HOST_REF,
    COOKIE_STORAGE_EXPORT_SUPPORTED,
    CREDENTIAL_VALUE_EXPORT_SUPPORTED,
    GENERIC_IPC_SURFACE,
    JAVASCRIPT_EVALUATE_PERMITTED,
    MASKED_CREDENTIAL_NAME,
    MAX_ELEMENT_NAME_CHARS,
    MAX_OBSERVATION_ELEMENTS,
    MAX_SERIALIZED_OBSERVATION_BYTES,
    PDF_CAPTURE_SUPPORTED,
    RENDERER_OWNS_PROJECTION_AUTHORITY,
    SCREENSHOT_SUPPORTED,
    SECOND_BROWSER_AUTHORITY,
    TRUSTED_MAIN_HOST_OWNS_EXTRACTION,
    BrowserObservationRefusal,
    build_bounded_page_observation,
    observation_element_ref,
    truncate_observation_name,
    validate_trusted_page_observation,
)
from kagent.browser_open import (
    BROWSER_CONTROL_IMPLEMENTED as BROWSER_OPEN_CONTROL_IMPLEMENTED,
    BROWSER_OPEN_PAGE_DERIVED_BYTES,
    BROWSER_OPEN_RECEIPT_FIELDS,
)
from kagent.contracts import ContractError

PROJECTION_ID = "obs_" + "a" * 24


def source_element(**overrides: object) -> dict[str, object]:
    element: dict[str, object] = {
        "role": "button",
        "name": "제출",
        "bounds": {"x": 1, "y": 2, "width": 30, "height": 20},
        "state_flags": ["focusable"],
        "interaction_flags": ["clickable"],
        "credential_field": False,
    }
    element.update(overrides)
    return element


def built(elements: list[dict[str, object]], origin: str = "https://example.com"):
    payload = build_bounded_page_observation(PROJECTION_ID, origin, elements)
    return payload, validate_trusted_page_observation(payload)


class BoundedObservationAuthorityTest(unittest.TestCase):
    def test_authority_flags_pin_the_slice_boundary(self) -> None:
        self.assertTrue(BROWSER_CONTROL_OBSERVATION_IMPLEMENTED)
        self.assertFalse(BROWSER_ACTION_EXECUTION_IMPLEMENTED)
        self.assertTrue(TRUSTED_MAIN_HOST_OWNS_EXTRACTION)
        self.assertFalse(RENDERER_OWNS_PROJECTION_AUTHORITY)
        self.assertFalse(SECOND_BROWSER_AUTHORITY)
        self.assertFalse(GENERIC_IPC_SURFACE)
        self.assertFalse(JAVASCRIPT_EVALUATE_PERMITTED)
        self.assertFalse(SCREENSHOT_SUPPORTED)
        self.assertFalse(PDF_CAPTURE_SUPPORTED)
        self.assertFalse(COOKIE_STORAGE_EXPORT_SUPPORTED)
        self.assertFalse(CREDENTIAL_VALUE_EXPORT_SUPPORTED)

    def test_ordinary_button_textbox_and_link_project_bounded_metadata(self) -> None:
        payload, observation = built(
            [
                source_element(role="button", name="저장"),
                source_element(role="textbox", name="이름", interaction_flags=["typeable", "editable"]),
                source_element(role="link", name="Docs"),
            ]
        )
        self.assertEqual(observation.origin_ref, "https://example.com")
        self.assertEqual(payload["host_ref"], BROWSER_OBSERVATION_HOST_REF)
        self.assertEqual(payload["element_count"], 3)
        self.assertFalse(payload["truncated"])
        self.assertEqual(
            [element["element_ref"] for element in payload["elements"]],
            ["el-0001", "el-0002", "el-0003"],
        )
        self.assertEqual(payload["elements"][0]["name"], "저장")
        self.assertEqual(payload["elements"][0]["bounds"], {"x": 1, "y": 2, "width": 30, "height": 20})
        self.assertFalse(payload["page_content_included"])
        self.assertFalse(payload["cookie_included"])
        self.assertFalse(payload["credential_value_included"])
        self.assertFalse(payload["dom_api_exposed"])

    def test_more_than_400_elements_truncate_deterministically(self) -> None:
        elements = [
            source_element(name=f"버튼 {index}") for index in range(MAX_OBSERVATION_ELEMENTS + 40)
        ]
        payload, observation = built(elements)
        self.assertTrue(payload["truncated"])
        self.assertLessEqual(payload["element_count"], MAX_OBSERVATION_ELEMENTS)
        self.assertGreaterEqual(payload["element_count"], 1)
        self.assertEqual(
            payload["elements"][-1]["element_ref"],
            f"el-{payload['element_count']:04d}",
        )
        self.assertLessEqual(observation.serialized_bytes(), MAX_SERIALIZED_OBSERVATION_BYTES)

    def test_byte_budget_truncates_whole_elements_never_bytes(self) -> None:
        elements = [source_element(name="x" * MAX_ELEMENT_NAME_CHARS) for _ in range(100)]
        payload, observation = built(elements)
        self.assertTrue(payload["truncated"])
        self.assertLess(payload["element_count"], 100)
        self.assertLessEqual(observation.serialized_bytes(), MAX_SERIALIZED_OBSERVATION_BYTES)

    def test_names_truncate_to_64_characters(self) -> None:
        self.assertEqual(len(truncate_observation_name("a" * 100)), MAX_ELEMENT_NAME_CHARS)
        self.assertEqual(truncate_observation_name("가" * 40), "가" * 40)
        payload, _ = built([source_element(name="a" * 100)])
        self.assertEqual(len(payload["elements"][0]["name"]), MAX_ELEMENT_NAME_CHARS)

    def test_password_values_are_never_projected_marker_only(self) -> None:
        payload, _ = built([source_element(role="textbox", name="hunter2", credential_field=True)])
        element = payload["elements"][0]
        self.assertTrue(element["credential_field"])
        self.assertEqual(element["name"], MASKED_CREDENTIAL_NAME)
        self.assertNotIn("value", element)
        self.assertFalse(payload["credential_value_included"])

    def test_a_masked_credential_name_is_required_for_credential_fields(self) -> None:
        # The builder masks credential names; a payload that carries real
        # credential material in the name cannot pass the validator.
        payload = build_bounded_page_observation(PROJECTION_ID, "https://example.com", [])
        payload["elements"] = [
            {
                "element_ref": "el-0001",
                "role": "textbox",
                "name": "hunter2",
                "bounds": {"x": 0, "y": 0, "width": 10, "height": 10},
                "state_flags": [],
                "interaction_flags": ["typeable"],
                "credential_field": True,
            }
        ]
        with self.assertRaises(BrowserObservationRefusal):
            validate_trusted_page_observation(payload)

    def test_form_values_and_textarea_contents_are_structurally_refused(self) -> None:
        for forbidden in ("value", "values", "form_values", "text", "content"):
            with self.assertRaises((BrowserObservationRefusal, ContractError)):
                built([source_element(**{forbidden: "typed-secret"})]),  # type: ignore[arg-type]

    def test_cookie_and_storage_material_is_structurally_refused(self) -> None:
        for forbidden in ("cookies", "local_storage", "session_storage", "localStorage"):
            with self.assertRaises((BrowserObservationRefusal, ContractError)):
                built([source_element(**{forbidden: {"session": "token"}})]),  # type: ignore[arg-type]

    def test_raw_dom_html_and_page_source_are_structurally_refused(self) -> None:
        for forbidden in ("dom", "html", "source"):
            with self.assertRaises((BrowserObservationRefusal, ContractError)):
                built([source_element(**{forbidden: "<html></html>"})]),  # type: ignore[arg-type]

    def test_arbitrary_attributes_are_refused_by_the_exact_key_schema(self) -> None:
        for extra in ("data_foo", "aria_label", "style", "class_name", "id", "placeholder"):
            with self.assertRaises((BrowserObservationRefusal, ContractError)):
                built([source_element(**{extra: "anything"})]),  # type: ignore[arg-type]

    def test_screenshot_image_and_pdf_keys_are_structurally_refused(self) -> None:
        for forbidden in ("screenshot", "image", "pdf"):
            with self.assertRaises((BrowserObservationRefusal, ContractError)):
                built([source_element(**{forbidden: "bytes"})]),  # type: ignore[arg-type]

    def test_renderer_minted_observations_are_refused(self) -> None:
        payload = build_bounded_page_observation(PROJECTION_ID, "https://example.com", [])
        payload["host_ref"] = "renderer-supplied-authority"
        with self.assertRaises(BrowserObservationRefusal) as caught:
            validate_trusted_page_observation(payload)
        self.assertEqual(caught.exception.code, "trusted_host_required")

    def test_element_refs_are_stable_and_derived_from_order_only(self) -> None:
        self.assertEqual(observation_element_ref(1), "el-0001")
        self.assertEqual(observation_element_ref(MAX_OBSERVATION_ELEMENTS), "el-0400")
        with self.assertRaises(BrowserObservationRefusal):
            observation_element_ref(0)
        with self.assertRaises(BrowserObservationRefusal):
            observation_element_ref(MAX_OBSERVATION_ELEMENTS + 1)
        first_payload, _ = built([source_element(), source_element(role="link", name="A")])
        second_payload, _ = built([source_element(), source_element(role="link", name="A")])
        self.assertEqual(first_payload["elements"], second_payload["elements"])

    def test_origin_ref_is_a_bare_http_s_origin(self) -> None:
        for bad_origin in (
            "https://example.com/path?token=secret",
            "https://user:pass@example.com",
            "file:///etc/passwd",
            "javascript:alert(1)",
            f"https://{'a' * 400}.com",
        ):
            with self.assertRaises((BrowserObservationRefusal, ContractError)):
                built([source_element()], origin=bad_origin)

    def test_element_count_omitted_and_flags_cannot_drift(self) -> None:
        payload = build_bounded_page_observation(
            PROJECTION_ID, "https://example.com", [source_element()], omitted_elements=2
        )
        payload["element_count"] = 99
        with self.assertRaises(BrowserObservationRefusal):
            validate_trusted_page_observation(payload)
        payload = build_bounded_page_observation(
            PROJECTION_ID, "https://example.com", [source_element()]
        )
        payload["dom_api_exposed"] = True
        with self.assertRaises(BrowserObservationRefusal):
            validate_trusted_page_observation(payload)

    def test_browser_open_byte_zero_contract_is_unchanged(self) -> None:
        self.assertEqual(BROWSER_OPEN_PAGE_DERIVED_BYTES, 0)
        self.assertFalse(BROWSER_OPEN_CONTROL_IMPLEMENTED)
        self.assertNotIn("observation", BROWSER_OPEN_RECEIPT_FIELDS)
        self.assertNotIn("elements", BROWSER_OPEN_RECEIPT_FIELDS)


if __name__ == "__main__":
    unittest.main()
