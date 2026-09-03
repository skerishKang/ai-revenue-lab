from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import unittest

from kagent.connector_platform import ConnectorEffect
from kagent.connector_trust import ConnectorWriteIntent, ConnectorWriteReceipt
from kagent.contracts import ContractError
from kagent.notion_contracts import (
    CURRENT_NOTION_MCP_ENTRY,
    NOTION_CURRENT_TRASH_FIELD,
    NOTION_DATABASE_DATA_SOURCE_DISTINCT,
    NOTION_DEPRECATED_REQUEST_TRASH_FIELD,
    NOTION_HOSTED_MCP_FILE_UPLOAD_SUPPORTED,
    NOTION_HOSTED_MCP_PKCE_SUPPORTED,
    NOTION_HOSTED_MCP_USER_OAUTH_REQUIRED,
    NOTION_LINKED_RESOURCE_SCOPE_EXPANSION,
    NOTION_PERMANENT_DELETE_SUPPORTED,
    NOTION_RAW_OAUTH_TOKEN_IN_B54,
    NOTION_WHOLE_WORKSPACE_MODEL_VISIBILITY_IMPLIED,
    NotionContentProjection,
    NotionMutationApproval,
    NotionMutationCapability,
    NotionMutationMaterial,
    NotionMutationPreflightDecision,
    NotionMutationReceipt,
    NotionResourceKind,
    NotionResourceRef,
    NotionScopeProjection,
    NotionSearchHit,
    filter_notion_search_hits,
    notion_mutation_preflight,
)

NOW = datetime(2026, 9, 3, 5, 30, tzinfo=timezone.utc)
CONTENT_HASH = hashlib.sha256(b"content").hexdigest()
PROPS_HASH = hashlib.sha256(b"props").hexdigest()


class NotionContractTests(unittest.TestCase):
    def page(self, ref: str = "page_1") -> NotionResourceRef:
        return NotionResourceRef(NotionResourceKind.PAGE, ref)

    def database(self, ref: str = "database_1") -> NotionResourceRef:
        return NotionResourceRef(NotionResourceKind.DATABASE, ref)

    def data_source(self, ref: str = "data_source_1") -> NotionResourceRef:
        return NotionResourceRef(NotionResourceKind.DATA_SOURCE, ref)

    def scope(self) -> NotionScopeProjection:
        return NotionScopeProjection(
            binding_ref="binding_notion_1",
            workspace_ref="workspace_1",
            allowed_resources=(
                self.page(),
                self.database(),
                self.data_source(),
            ),
        )

    def state(self, content_hash: str = CONTENT_HASH) -> NotionContentProjection:
        return NotionContentProjection(
            binding_ref="binding_notion_1",
            workspace_ref="workspace_1",
            resource=self.page(),
            content_text="trusted adapter output but untrusted Notion content",
            last_edited_at=NOW,
            content_sha256=content_hash,
            linked_resources=(
                self.database(),
                NotionResourceRef(NotionResourceKind.PAGE, "page_outside"),
            ),
            in_trash=False,
        )

    def test_current_hosted_mcp_tools_have_reviewed_effects_and_unknown_fails_closed(self):
        self.assertEqual(CURRENT_NOTION_MCP_ENTRY.host, "https://mcp.notion.com")
        self.assertEqual(CURRENT_NOTION_MCP_ENTRY.path, "/mcp")
        self.assertEqual(CURRENT_NOTION_MCP_ENTRY.classify("notion-search"), ConnectorEffect.READ)
        self.assertEqual(CURRENT_NOTION_MCP_ENTRY.classify("notion-fetch"), ConnectorEffect.READ)
        self.assertEqual(CURRENT_NOTION_MCP_ENTRY.classify("notion-create-pages"), ConnectorEffect.WRITE)
        self.assertEqual(CURRENT_NOTION_MCP_ENTRY.classify("future-notion-tool"), ConnectorEffect.WRITE)

    def test_search_results_are_filtered_to_padiem_allowlist(self):
        hits = (
            NotionSearchHit(self.page(), "Allowed page", NOW),
            NotionSearchHit(
                NotionResourceRef(NotionResourceKind.PAGE, "page_outside"),
                "Outside page",
                NOW,
            ),
        )
        filtered = filter_notion_search_hits(self.scope(), hits)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].resource.resource_ref, "page_1")

    def test_linked_resources_do_not_expand_model_scope(self):
        projection = self.state().model_projection(self.scope())
        self.assertEqual(projection["linked_resources"], ["database:database_1"])
        self.assertTrue(projection["out_of_scope_links_hidden"])
        self.assertFalse(projection["content_trusted"])

    def test_database_and_data_source_identities_remain_distinct(self):
        self.assertNotEqual(self.database().key, self.data_source().key)
        self.assertTrue(NOTION_DATABASE_DATA_SOURCE_DISTINCT)

    def test_update_page_requires_exact_scope_approval_and_current_state(self):
        current = self.state()
        material = NotionMutationMaterial(
            binding_ref="binding_notion_1",
            workspace_ref="workspace_1",
            capability=NotionMutationCapability.UPDATE_PAGE,
            target=self.page(),
            parent=None,
            title="Updated page",
            content_sha256=hashlib.sha256(b"new-content").hexdigest(),
            properties_sha256=PROPS_HASH,
            expected_state_ref=current.state_ref,
        )
        approval = NotionMutationApproval(
            approval_ref="approval_1",
            evidence_ref="evidence_1",
            material_fingerprint=material.material_fingerprint,
            approved_at=NOW,
        )
        intent = ConnectorWriteIntent(
            connector_id="notion",
            binding_ref="binding_notion_1",
            actor_ref="actor_1",
            tool_name="notion.update_page",
            target_ref=material.target_ref,
            payload_fingerprint=material.material_fingerprint,
            idempotency_key="notion_update_1",
            approval_ref="approval_1",
            evidence_ref="evidence_1",
            requested_at=NOW,
            expected_version_ref=material.version_ref,
        )
        self.assertEqual(
            notion_mutation_preflight(
                scope=self.scope(),
                material=material,
                approval=approval,
                intent=intent,
                current_state=current,
            ),
            NotionMutationPreflightDecision.ALLOW,
        )

        stale = self.state(hashlib.sha256(b"changed-current-state").hexdigest())
        self.assertEqual(
            notion_mutation_preflight(
                scope=self.scope(),
                material=material,
                approval=approval,
                intent=intent,
                current_state=stale,
            ),
            NotionMutationPreflightDecision.STALE_STATE,
        )

    def test_create_page_requires_exact_allowed_parent(self):
        material = NotionMutationMaterial(
            binding_ref="binding_notion_1",
            workspace_ref="workspace_1",
            capability=NotionMutationCapability.CREATE_PAGE,
            target=None,
            parent=self.database(),
            title="New page",
            content_sha256=CONTENT_HASH,
            properties_sha256=PROPS_HASH,
        )
        approval = NotionMutationApproval(
            approval_ref="approval_create_1",
            evidence_ref="evidence_create_1",
            material_fingerprint=material.material_fingerprint,
            approved_at=NOW,
        )
        intent = ConnectorWriteIntent(
            connector_id="notion",
            binding_ref="binding_notion_1",
            actor_ref="actor_1",
            tool_name="notion.create_page",
            target_ref=material.target_ref,
            payload_fingerprint=material.material_fingerprint,
            idempotency_key="notion_create_1",
            approval_ref="approval_create_1",
            evidence_ref="evidence_create_1",
            requested_at=NOW,
            expected_version_ref=material.version_ref,
        )
        self.assertEqual(
            notion_mutation_preflight(
                scope=self.scope(), material=material, approval=approval, intent=intent
            ),
            NotionMutationPreflightDecision.ALLOW,
        )

        outside_parent = NotionMutationMaterial(
            binding_ref="binding_notion_1",
            workspace_ref="workspace_1",
            capability=NotionMutationCapability.CREATE_PAGE,
            target=None,
            parent=NotionResourceRef(NotionResourceKind.PAGE, "outside_parent"),
            title="New page",
            content_sha256=CONTENT_HASH,
            properties_sha256=PROPS_HASH,
        )
        outside_approval = NotionMutationApproval(
            approval_ref="approval_create_2",
            evidence_ref="evidence_create_2",
            material_fingerprint=outside_parent.material_fingerprint,
            approved_at=NOW,
        )
        outside_intent = ConnectorWriteIntent(
            connector_id="notion",
            binding_ref="binding_notion_1",
            actor_ref="actor_1",
            tool_name="notion.create_page",
            target_ref=outside_parent.target_ref,
            payload_fingerprint=outside_parent.material_fingerprint,
            idempotency_key="notion_create_2",
            approval_ref="approval_create_2",
            evidence_ref="evidence_create_2",
            requested_at=NOW,
            expected_version_ref=outside_parent.version_ref,
        )
        self.assertEqual(
            notion_mutation_preflight(
                scope=self.scope(),
                material=outside_parent,
                approval=outside_approval,
                intent=outside_intent,
            ),
            NotionMutationPreflightDecision.OUT_OF_SCOPE,
        )

    def test_trash_and_restore_use_current_in_trash_semantics(self):
        current = self.state()
        trash = NotionMutationMaterial(
            binding_ref="binding_notion_1",
            workspace_ref="workspace_1",
            capability=NotionMutationCapability.TRASH_PAGE,
            target=self.page(),
            parent=None,
            title="",
            content_sha256=CONTENT_HASH,
            properties_sha256=PROPS_HASH,
            expected_state_ref=current.state_ref,
            in_trash=True,
        )
        restore = NotionMutationMaterial(
            binding_ref="binding_notion_1",
            workspace_ref="workspace_1",
            capability=NotionMutationCapability.RESTORE_PAGE,
            target=self.page(),
            parent=None,
            title="",
            content_sha256=CONTENT_HASH,
            properties_sha256=PROPS_HASH,
            expected_state_ref=current.state_ref,
            in_trash=False,
        )
        self.assertNotEqual(trash.material_fingerprint, restore.material_fingerprint)
        self.assertEqual(NOTION_CURRENT_TRASH_FIELD, "in_trash")
        self.assertEqual(NOTION_DEPRECATED_REQUEST_TRASH_FIELD, "archived")
        self.assertFalse(NOTION_PERMANENT_DELETE_SUPPORTED)

    def test_receipt_must_correlate_exact_target(self):
        receipt = ConnectorWriteReceipt(
            receipt_ref="receipt_1",
            connector_id="notion",
            binding_ref="binding_notion_1",
            idempotency_key="notion_update_1",
            provider_operation_ref="notion_op_1",
            target_ref="notion:workspace_1:page:page_1",
            committed_at=NOW,
            evidence_ref="provider_evidence_1",
        )
        wrapped = NotionMutationReceipt(
            connector_receipt=receipt,
            capability=NotionMutationCapability.UPDATE_PAGE,
            approved_target_ref="notion:workspace_1:page:page_1",
            result_resource=self.page(),
            result_last_edited_at=NOW,
        )
        self.assertEqual(wrapped.result_resource.key, "page:page_1")
        with self.assertRaises(ContractError):
            NotionMutationReceipt(
                connector_receipt=receipt,
                capability=NotionMutationCapability.UPDATE_PAGE,
                approved_target_ref="notion:workspace_1:page:other",
                result_resource=self.page(),
                result_last_edited_at=NOW,
            )

    def test_hosted_mcp_nonclaims_and_oauth_boundary(self):
        self.assertTrue(NOTION_HOSTED_MCP_USER_OAUTH_REQUIRED)
        self.assertTrue(NOTION_HOSTED_MCP_PKCE_SUPPORTED)
        self.assertFalse(NOTION_HOSTED_MCP_FILE_UPLOAD_SUPPORTED)
        self.assertFalse(NOTION_WHOLE_WORKSPACE_MODEL_VISIBILITY_IMPLIED)
        self.assertFalse(NOTION_LINKED_RESOURCE_SCOPE_EXPANSION)
        self.assertFalse(NOTION_RAW_OAUTH_TOKEN_IN_B54)


if __name__ == "__main__":
    unittest.main()
