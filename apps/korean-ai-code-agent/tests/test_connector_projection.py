"""#1999 — catalogue -> Core projection contract tests.

Covers the acceptance matrix: five entries projected, validate_connector_tools
loop closed, fingerprint stability + drift detection, unreviewed-tool
fail-closed, and DEFERRED exclusion. Execution stays dormant: nothing here
constructs a ConnectorRuntime or registers a handler.
"""

from __future__ import annotations

import unittest

from kagent.connector_platform import (
    ConnectorAuthKind,
    ConnectorCatalogueEntry,
)
from kagent.connector_projection import (
    DEFERRED_CONNECTORS,
    PROJECTED_CATALOGUE_ENTRIES,
    ConnectorProjectionError,
    project_catalogue_entries,
    project_reviewed_entries,
)
from padiem_ai_core.connector_registry import (
    ConnectorDescriptor,
    validate_connector_tools,
)
from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect
from padiem_ai_core.tool_registry import ToolRegistrySnapshot


class FiveEntriesProjectedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.projection = project_reviewed_entries()

    def test_projection_shapes(self) -> None:
        self.assertEqual(len(self.projection.descriptors), 5)
        for descriptor in self.projection.descriptors:
            self.assertIsInstance(descriptor, ConnectorDescriptor)

    def test_connector_id_grammar(self) -> None:
        ids = {d.connector_id for d in self.projection.descriptors}
        self.assertEqual(
            ids,
            {
                "connector:b54:gmail@1",
                "connector:b54:google-drive@1",
                "connector:b54:google-calendar@1",
                "connector:b54:slack@1",
                "connector:b54:notion@1",
            },
        )

    def test_tool_ids_canonical(self) -> None:
        for descriptor in self.projection.descriptors:
            connector_local = descriptor.connector_id.split(":")[2].split("@")[0]
            for tool_id in descriptor.canonical_tool_ids:
                self.assertTrue(tool_id.startswith("tool:b54:"), tool_id)
                self.assertTrue(tool_id.endswith("@1"), tool_id)
                local = tool_id.split(":")[2].split("@")[0]
                self.assertTrue(local.startswith(f"{connector_local}_"), tool_id)

    def test_write_tools_carry_user_confirmation(self) -> None:
        entry_by_local = {
            entry.connector_id: entry for entry in PROJECTED_CATALOGUE_ENTRIES
        }
        for descriptor in self.projection.descriptors:
            local = descriptor.connector_id.split(":")[2].split("@")[0]
            entry = entry_by_local[local]
            for tool_id in descriptor.canonical_tool_ids:
                registered = self.projection.tool_registry.get(tool_id)
                spec = registered.runtime_spec
                local_tool = tool_id.split(":")[2].split("@")[0]
                tool_name = local_tool.removeprefix(f"{local}_")
                if tool_name in entry.write_tools:
                    self.assertIs(spec.side_effect, ToolSideEffect.WRITE, tool_id)
                    self.assertIs(
                        spec.approval_policy, ApprovalPolicy.USER_CONFIRMATION, tool_id
                    )
                else:
                    self.assertIs(spec.side_effect, ToolSideEffect.READ, tool_id)

    def test_requires_authorization_from_auth_kind(self) -> None:
        # All five reviewed entries are USER_OAUTH -> authorization required.
        for descriptor in self.projection.descriptors:
            self.assertTrue(descriptor.requires_authorization, descriptor.connector_id)

    def test_gmail_reviewed_schemas_carried(self) -> None:
        tool_id = "tool:b54:gmail_search_messages@1"
        spec = self.projection.tool_registry.get(tool_id).runtime_spec
        self.assertIn("query", dict(spec.input_schema)["properties"])


class ValidateLoopClosedTests(unittest.TestCase):
    def test_every_descriptor_validates_against_snapshot(self) -> None:
        projection = project_reviewed_entries()
        for descriptor in projection.descriptors:
            # raises ConnectorRegistryError if any tool ref is unresolvable
            validate_connector_tools(descriptor, projection.tool_registry)

    def test_snapshot_is_wellformed(self) -> None:
        from padiem_ai_core.connector_registry import ConnectorRegistrySnapshot

        projection = project_reviewed_entries()
        self.assertIsInstance(projection.connector_registry, ConnectorRegistrySnapshot)
        self.assertIsInstance(projection.tool_registry, ToolRegistrySnapshot)
        # duplicate canonical ids are structurally impossible here but the
        # snapshot post-init proves sortedness/uniqueness.
        ids = projection.tool_registry.canonical_tool_ids
        self.assertEqual(len(ids), len(set(ids)))


class FingerprintDriftTests(unittest.TestCase):
    def test_fingerprint_stable_across_projections(self) -> None:
        first = project_reviewed_entries()
        second = project_reviewed_entries()
        self.assertEqual(first.fingerprints, second.fingerprints)
        self.assertTrue(first.fingerprints)
        for value in first.fingerprints.values():
            self.assertEqual(len(value), 64)

    def test_fingerprint_changes_when_tool_definition_changes(self) -> None:
        base = project_reviewed_entries()
        # Same title/description shape as gmail/search_messages but WITHOUT
        # the reviewed parameter schema (gmailx is not in
        # REVIEWED_TOOL_SCHEMAS), so the ToolSpec content differs ->
        # different fingerprint.
        mutated_entry = ConnectorCatalogueEntry(
            connector_id="gmailx",
            title="Gmail",
            vendor="Google",
            host="https://gmail.googleapis.com",
            path="/gmail/v1",
            auth_kind=ConnectorAuthKind.USER_OAUTH,
            transport_kind="gmail-rest",
            read_tools=("search_messages",),
            write_tools=(),
        )
        mutated = project_catalogue_entries([mutated_entry])
        original = base.tool_registry.get("tool:b54:gmail_search_messages@1")
        changed = mutated.tool_registry.get("tool:b54:gmailx_search_messages@1")
        self.assertNotEqual(original.fingerprint, changed.fingerprint)


class UnreviewedFailClosedTests(unittest.TestCase):
    def test_advertised_unreviewed_tool_raises(self) -> None:
        entry = ConnectorCatalogueEntry(
            connector_id="acme",
            title="Acme",
            vendor="Acme",
            host="https://api.acme.example",
            path="/v1",
            auth_kind=ConnectorAuthKind.DEPLOYMENT_BEARER,
            transport_kind="acme-rest",
            read_tools=("known_read",),
            write_tools=(),
        )
        with self.assertRaises(ConnectorProjectionError) as ctx:
            project_catalogue_entries(
                [entry],
                advertised_tools={"acme": ("known_read", "mystery_tool")},
            )
        self.assertEqual(ctx.exception.code, "unreviewed_tool")

    def test_write_without_policy_never_projected(self) -> None:
        # Structural guard: every projected WRITE carries USER_CONFIRMATION,
        # so a silent downgrade is impossible. Assert on the real projection.
        projection = project_reviewed_entries()
        for entry in PROJECTED_CATALOGUE_ENTRIES:
            local = entry.connector_id
            for tool_name in entry.write_tools:
                spec = projection.tool_registry.get(
                    f"tool:b54:{local}_{tool_name}@1"
                ).runtime_spec
                self.assertIs(spec.side_effect, ToolSideEffect.WRITE)
                self.assertIsNot(spec.approval_policy, ApprovalPolicy.NOT_REQUIRED)


class DeferredExclusionTests(unittest.TestCase):
    def test_deferred_list_documented(self) -> None:
        self.assertEqual(
            set(DEFERRED_CONNECTORS),
            {"kakao", "neon-postgres", "cloudflare"},
        )
        for reason in DEFERRED_CONNECTORS.values():
            self.assertTrue(reason.strip())

    def test_deferred_entry_projection_raises(self) -> None:
        entry = ConnectorCatalogueEntry(
            connector_id="cloudflare",
            title="Cloudflare",
            vendor="Cloudflare",
            host="https://api.cloudflare.com",
            path="/client/v4",
            auth_kind=ConnectorAuthKind.DEPLOYMENT_BEARER,
            transport_kind="cf-rest",
            read_tools=("list_zones",),
            write_tools=("deploy_worker",),
        )
        with self.assertRaises(ConnectorProjectionError) as ctx:
            project_catalogue_entries([entry])
        self.assertEqual(ctx.exception.code, "deferred_connector_projection")

    def test_reviewed_five_exclude_deferred(self) -> None:
        ids = {entry.connector_id for entry in PROJECTED_CATALOGUE_ENTRIES}
        self.assertEqual(
            ids, {"gmail", "google-drive", "google-calendar", "slack", "notion"}
        )
        self.assertFalse(ids & set(DEFERRED_CONNECTORS))


class ExecutionDormancyTests(unittest.TestCase):
    def test_projection_module_does_not_touch_runtime(self) -> None:
        import kagent.connector_projection as module
        from pathlib import Path

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("ConnectorRuntime(", source)
        self.assertNotIn("ToolRuntime(", source)
        self.assertNotIn(".register(", source)


if __name__ == "__main__":
    unittest.main()
