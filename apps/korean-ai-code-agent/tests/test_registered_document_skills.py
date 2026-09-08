"""#2014: 견적서/발주서 registered-Skill definitions — focused contract tests."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from contextlib import redirect_stderr

from padiem_ai_core.skill_package import ApprovalHook, ReusableSkillPackage
from padiem_ai_core.skill_registry import (
    SkillInstallStatus,
    SkillRegistrySnapshot,
)

from kagent.cli import main
from kagent.contracts import ContractError
from kagent.draft_flow import DRAFT_DOC_TYPES
from kagent.registered_document_skills import (
    CUSTOMER_QUOTE_DOC_TYPE,
    CUSTOMER_QUOTE_SKILL,
    CUSTOMER_QUOTE_SKILL_ID,
    DOCUMENT_DRAFT_CAPABILITY,
    DOCUMENT_SKILL_PACKAGES,
    ENGINE_RUNTIME_DEPENDENCIES,
    ENGINE_RUNTIME_READY,
    FREE_FORM_REQUEST_INPUT_CONTRACT_REF,
    MAX_FREEFORM_REQUEST_CHARS,
    PURCHASE_ORDER_DOC_TYPE,
    PURCHASE_ORDER_SKILL,
    PURCHASE_ORDER_SKILL_ID,
    SKILL_PUBLISHER_ID,
    SkillRequestIntake,
    build_document_skill_installations,
    build_document_skill_registry,
    document_skill_catalogue,
    resolve_document_skill,
    resolve_request_doc_type,
    resolve_skill_for_request,
)

QUOTE_REQUEST = "(주)가나다에 알루미늄 프로파일 100개 단가 12,000원 견적서 뽑아줘"
ORDER_REQUEST = "협력업체 대성에 발주서 작성해줘 · 납기 다음주 금요일"


class RegisteredSkillDefinitionTests(unittest.TestCase):
    def test_both_document_skills_are_core_valid_packages(self):
        for package in DOCUMENT_SKILL_PACKAGES:
            self.assertIsInstance(package, ReusableSkillPackage)
            self.assertEqual(package.publisher_id, SKILL_PUBLISHER_ID)
            self.assertEqual(
                package.input_contract_ref, FREE_FORM_REQUEST_INPUT_CONTRACT_REF
            )

    def test_skill_ids_are_distinct_and_bind_to_expected_doc_types(self):
        self.assertEqual(CUSTOMER_QUOTE_SKILL.skill_id, CUSTOMER_QUOTE_SKILL_ID)
        self.assertEqual(PURCHASE_ORDER_SKILL.skill_id, PURCHASE_ORDER_SKILL_ID)
        self.assertNotEqual(CUSTOMER_QUOTE_SKILL_ID, PURCHASE_ORDER_SKILL_ID)
        self.assertIn(CUSTOMER_QUOTE_DOC_TYPE, DRAFT_DOC_TYPES)
        self.assertIn(PURCHASE_ORDER_DOC_TYPE, DRAFT_DOC_TYPES)

    def test_packages_declare_only_the_document_draft_capability(self):
        for package in DOCUMENT_SKILL_PACKAGES:
            self.assertEqual(
                package.required_capabilities, (DOCUMENT_DRAFT_CAPABILITY,)
            )
            self.assertEqual(package.allowed_tool_ids, ())
            self.assertEqual(package.connector_requirement_ids, ())

    def test_packages_narrow_permissions_and_gate_external_side_effects(self):
        for package in DOCUMENT_SKILL_PACKAGES:
            self.assertEqual(package.execution_budget.max_tool_calls, 0)
            self.assertIn(
                ApprovalHook.BEFORE_EXTERNAL_SIDE_EFFECT, package.approval_hooks
            )

    def test_instructions_carry_the_anti_hallucination_and_no_send_rules(self):
        for package in DOCUMENT_SKILL_PACKAGES:
            self.assertIn("입력 필요", package.instruction)
            self.assertIn("추측", package.instruction)
            self.assertIn("전송하지 않습니다", package.instruction)
            self.assertIn("DRAFT", package.instruction)


class SkillRegistryRegistrationTests(unittest.TestCase):
    def test_registry_snapshot_contains_both_skills_sorted(self):
        registry = build_document_skill_registry()
        self.assertIsInstance(registry, SkillRegistrySnapshot)
        self.assertEqual(
            registry.skill_ids, (CUSTOMER_QUOTE_SKILL_ID, PURCHASE_ORDER_SKILL_ID)
        )

    def test_registration_is_idempotent_by_fingerprint(self):
        registry = build_document_skill_registry()
        again = registry.with_package(CUSTOMER_QUOTE_SKILL)
        self.assertIs(again, registry)

    def test_both_skills_are_installed_enabled(self):
        installations = build_document_skill_installations()
        statuses = {
            item.skill_id: item.status for item in installations.installations
        }
        self.assertEqual(
            statuses,
            {
                CUSTOMER_QUOTE_SKILL_ID: SkillInstallStatus.ENABLED,
                PURCHASE_ORDER_SKILL_ID: SkillInstallStatus.ENABLED,
            },
        )

    def test_resolve_enabled_skill_returns_the_package(self):
        self.assertEqual(
            resolve_document_skill(CUSTOMER_QUOTE_SKILL_ID).skill_id,
            CUSTOMER_QUOTE_SKILL_ID,
        )
        self.assertEqual(
            resolve_document_skill(PURCHASE_ORDER_SKILL_ID).skill_id,
            PURCHASE_ORDER_SKILL_ID,
        )

    def test_unregistered_skill_id_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_document_skill("skill:kagent.b54:not-registered@1")

    def test_catalogue_exposes_registration_evidence_rows(self):
        catalogue = document_skill_catalogue()
        self.assertEqual(len(catalogue), 2)
        by_id = {row["skill_id"]: row for row in catalogue}
        self.assertEqual(
            set(by_id), {CUSTOMER_QUOTE_SKILL_ID, PURCHASE_ORDER_SKILL_ID}
        )
        quote_row = by_id[CUSTOMER_QUOTE_SKILL_ID]
        self.assertEqual(quote_row["doc_type"], CUSTOMER_QUOTE_DOC_TYPE)
        self.assertTrue(quote_row["enabled"])
        self.assertTrue(quote_row["installed"])
        self.assertEqual(
            quote_row["input_contract_ref"], FREE_FORM_REQUEST_INPUT_CONTRACT_REF
        )
        self.assertEqual(
            quote_row["required_capabilities"], [DOCUMENT_DRAFT_CAPABILITY]
        )
        self.assertEqual(quote_row["fingerprint"], quote_row["fingerprint"])
        self.assertTrue(quote_row["fingerprint"])


class FreeFormIntakeContractTests(unittest.TestCase):
    def test_freeform_text_resolves_the_quote_skill(self):
        intake = SkillRequestIntake(QUOTE_REQUEST)
        self.assertEqual(intake.resolved_doc_type, CUSTOMER_QUOTE_DOC_TYPE)
        self.assertEqual(
            resolve_skill_for_request(intake).skill_id, CUSTOMER_QUOTE_SKILL_ID
        )

    def test_freeform_text_resolves_the_order_skill(self):
        intake = SkillRequestIntake(ORDER_REQUEST)
        self.assertEqual(intake.resolved_doc_type, PURCHASE_ORDER_DOC_TYPE)
        self.assertEqual(
            resolve_skill_for_request(intake).skill_id, PURCHASE_ORDER_SKILL_ID
        )

    def test_explicit_doc_type_wins_over_keywords(self):
        intake = SkillRequestIntake(QUOTE_REQUEST, doc_type=PURCHASE_ORDER_DOC_TYPE)
        self.assertEqual(intake.resolved_doc_type, PURCHASE_ORDER_DOC_TYPE)
        self.assertEqual(
            resolve_skill_for_request(intake).skill_id, PURCHASE_ORDER_SKILL_ID
        )

    def test_input_payload_carries_request_text_not_a_file_path(self):
        intake = SkillRequestIntake(
            QUOTE_REQUEST, attachment_texts=("추출된 첨부 본문", "")
        )
        payload = intake.to_input_payload()
        self.assertEqual(payload["contract"], FREE_FORM_REQUEST_INPUT_CONTRACT_REF)
        self.assertEqual(payload["doc_type"], CUSTOMER_QUOTE_DOC_TYPE)
        self.assertEqual(payload["request_text"], QUOTE_REQUEST)
        self.assertEqual(len(payload["attachments"]), 1)
        self.assertEqual(payload["attachments"][0]["text"], "추출된 첨부 본문")
        for key in ("input_path", "file_path", "input_file"):
            self.assertNotIn(key, payload)

    def test_resolver_accepts_explicit_doc_type_without_keywords(self):
        self.assertEqual(
            resolve_request_doc_type("품목 3종 정리해줘", CUSTOMER_QUOTE_DOC_TYPE),
            CUSTOMER_QUOTE_DOC_TYPE,
        )

    def test_resolver_rejects_unknown_doc_type(self):
        with self.assertRaises(ContractError):
            resolve_request_doc_type(QUOTE_REQUEST, "세금계산서")

    def test_silent_request_text_fails_closed(self):
        with self.assertRaises(ContractError) as ctx:
            SkillRequestIntake("품목 3종 정리해줘").resolved_doc_type
        self.assertIn("freeform_doc_type_unresolved", str(ctx.exception))

    def test_ambiguous_request_text_fails_closed(self):
        with self.assertRaises(ContractError) as ctx:
            SkillRequestIntake("견적서랑 발주서 둘 다 만들어줘").resolved_doc_type
        self.assertIn("freeform_doc_type_ambiguous", str(ctx.exception))

    def test_empty_and_oversized_request_text_are_rejected(self):
        with self.assertRaises(ContractError):
            SkillRequestIntake("   ")
        with self.assertRaises(ContractError):
            SkillRequestIntake("가" * (MAX_FREEFORM_REQUEST_CHARS + 1) + " 견적서")

    def test_control_characters_and_non_string_are_rejected(self):
        with self.assertRaises(ContractError):
            SkillRequestIntake("견적서\x00포함")
        with self.assertRaises(ContractError):
            SkillRequestIntake(123)

    def test_credential_material_in_request_text_is_rejected(self):
        with self.assertRaises(ContractError):
            SkillRequestIntake("견적서 작성해줘 sk-" + "A" * 24)

    def test_invalid_doc_type_and_channel_are_rejected(self):
        with self.assertRaises(ContractError):
            SkillRequestIntake(QUOTE_REQUEST, doc_type="세금계산서")
        with self.assertRaises(ContractError):
            SkillRequestIntake(QUOTE_REQUEST, channel="bad channel!")

    def test_attachment_limit_is_enforced(self):
        with self.assertRaises(ContractError):
            SkillRequestIntake(QUOTE_REQUEST, attachment_texts=("a",) * 9)

    def test_intake_requires_a_skill_request_intake_instance(self):
        with self.assertRaises(ContractError):
            resolve_skill_for_request(QUOTE_REQUEST)  # type: ignore[arg-type]


class EngineDependencyDocumentationTests(unittest.TestCase):
    def test_engine_runtime_is_documented_as_not_ready(self):
        self.assertFalse(ENGINE_RUNTIME_READY)
        self.assertEqual(ENGINE_RUNTIME_DEPENDENCIES, ("#1969", "#1971"))

    def test_p01_public_wire_refuses_skill_authority_fields(self):
        from kagent import p01_orchestration_client as client

        for field in (
            "skill_id",
            "skill_registry",
            "skill_installations",
            "skill_runtime_policy",
        ):
            self.assertIn(field, client._NULLABLE_AUTHORITY_FIELDS)

    def test_catalogue_rows_report_the_engine_dependency(self):
        for row in document_skill_catalogue():
            self.assertFalse(row["engine_runtime_ready"])
            self.assertEqual(row["engine_runtime_dependencies"], ["#1969", "#1971"])


class SkillCliSurfaceTests(unittest.TestCase):
    def test_skill_list_prints_both_registered_skills(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([".", "skill", "list"])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn(CUSTOMER_QUOTE_SKILL_ID, text)
        self.assertIn(PURCHASE_ORDER_SKILL_ID, text)

    def test_skill_show_prints_one_definition(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([".", "skill", "show", CUSTOMER_QUOTE_SKILL_ID])
        self.assertEqual(code, 0)
        self.assertIn(CUSTOMER_QUOTE_SKILL_ID, out.getvalue())

    def test_skill_show_rejects_unknown_id(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = main([".", "skill", "show", "skill:kagent.b54:missing@1"])
        self.assertEqual(code, 2)
        self.assertTrue(err.getvalue().strip())

    def test_skill_intake_accepts_freeform_request_text(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([".", "skill", "intake", ORDER_REQUEST])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn(PURCHASE_ORDER_SKILL_ID, text)
        self.assertIn(PURCHASE_ORDER_DOC_TYPE, text)

    def test_skill_intake_fails_closed_on_ambiguous_text(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = main([".", "skill", "intake", "견적서랑 발주서"])
        self.assertEqual(code, 2)
        self.assertTrue(err.getvalue().strip())

    def test_skill_intake_honours_explicit_doc_type(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(
                [
                    ".",
                    "skill",
                    "intake",
                    QUOTE_REQUEST,
                    "--doc-type",
                    PURCHASE_ORDER_DOC_TYPE,
                ]
            )
        self.assertEqual(code, 0)
        self.assertIn(PURCHASE_ORDER_SKILL_ID, out.getvalue())

    def test_existing_cli_subcommands_are_preserved(self):
        from kagent.cli import parser

        modes = set()
        parsed = parser()
        for action in parsed._actions:
            if action.dest == "mode":
                modes = set(action.choices)
        self.assertTrue({"plan", "run", "p01-run", "review", "draft", "order"} <= modes)
        self.assertIn("skill", modes)


if __name__ == "__main__":
    unittest.main()
