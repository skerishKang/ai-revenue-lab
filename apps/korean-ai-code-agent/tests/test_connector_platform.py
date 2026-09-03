from __future__ import annotations

import unittest

from kagent.connector_platform import (
    AllowReadsConnectorPolicy,
    ConnectorAuthKind,
    ConnectorCatalogueEntry,
    ConnectorConnection,
    ConnectorEffect,
    ConnectorGrant,
    ConnectorRuntime,
    ConnectorSkill,
    ConnectorTool,
    DeterministicFakeConnectorTransport,
    GOOGLE_DRIVE_ENTRY,
    NOTION_ENTRY,
    bounded_connector_result,
)
from kagent.contracts import ContractError


class ConnectorPlatformTests(unittest.TestCase):
    def connection(self):
        return ConnectorConnection(
            binding_ref="binding_drive_1",
            actor_ref="actor_1",
            connector_id="google-drive",
        )

    def test_google_drive_catalogue_is_pinned_and_secret_free(self):
        rendered = GOOGLE_DRIVE_ENTRY.safe_dict()
        self.assertEqual(rendered["host"], "https://www.googleapis.com")
        self.assertEqual(rendered["auth_kind"], ConnectorAuthKind.USER_OAUTH.value)
        self.assertFalse(rendered["credential_fields"])

    def test_unknown_tool_fails_closed_as_write(self):
        self.assertEqual(GOOGLE_DRIVE_ENTRY.classify("future_tool"), ConnectorEffect.WRITE)
        self.assertEqual(NOTION_ENTRY.classify("future_notion_tool"), ConnectorEffect.WRITE)

    def test_custom_connector_tools_are_never_implicitly_reads(self):
        entry = ConnectorCatalogueEntry(
            connector_id="custom",
            title="Custom",
            vendor="Custom",
            host="https://example.com",
            path="/mcp",
            auth_kind=ConnectorAuthKind.DEPLOYMENT_BEARER,
            transport_kind="mcp",
            read_tools=("search",),
            first_party=False,
        )
        self.assertEqual(entry.classify("search"), ConnectorEffect.WRITE)

    def test_bounded_result_states_empty_content_instead_of_returning_empty_string(self):
        result = bounded_connector_result("   ")
        self.assertIn("Nothing was found", result.text)
        self.assertFalse(result.is_error)
        self.assertFalse(result.truncated)

    def test_bounded_result_truncates_visibly(self):
        result = bounded_connector_result("x" * 25_000)
        self.assertTrue(result.truncated)
        self.assertIn("[truncated:", result.text)

    def test_skill_declaration_never_grants_tool(self):
        tool = ConnectorTool("search_files", "search", {"type": "object"})
        transport = DeterministicFakeConnectorTransport((tool,))
        runtime = ConnectorRuntime(
            catalogue={"google-drive": GOOGLE_DRIVE_ENTRY},
            transports={"google-drive-rest": transport},
            policy=AllowReadsConnectorPolicy(),
            grants=(),
            skills=(
                ConnectorSkill(
                    slug="drive-search",
                    title="Drive Search",
                    instructions="Search Drive.",
                    tool_refs=("google-drive/search_files",),
                ),
            ),
        )
        self.assertEqual(runtime.offered_refs("agent_1", ("drive-search",)), set())
        with self.assertRaises(ContractError):
            runtime.call(
                connection=self.connection(),
                agent_ref="agent_1",
                tool_name="search_files",
                args={"query": "report"},
            )

    def test_grant_and_policy_are_independent_gates(self):
        read = ConnectorTool("search_files", "search", {"type": "object"})
        write = ConnectorTool("create_file", "create", {"type": "object"})
        transport = DeterministicFakeConnectorTransport((read, write))
        grants = (
            ConnectorGrant("agent_1", "google-drive/search_files", "admin_1"),
            ConnectorGrant("agent_1", "google-drive/create_file", "admin_1"),
        )
        runtime = ConnectorRuntime(
            catalogue={"google-drive": GOOGLE_DRIVE_ENTRY},
            transports={"google-drive-rest": transport},
            policy=AllowReadsConnectorPolicy(),
            grants=grants,
        )
        result = runtime.call(
            connection=self.connection(),
            agent_ref="agent_1",
            tool_name="search_files",
            args={"query": "report"},
        )
        self.assertEqual(result.text, "fake:search_files")
        with self.assertRaises(ContractError):
            runtime.call(
                connection=self.connection(),
                agent_ref="agent_1",
                tool_name="create_file",
                args={"name": "x"},
            )
        self.assertEqual(len(transport.calls), 1)

    def test_selected_skill_narrows_claimed_tools_but_keeps_unclaimed_grants(self):
        tools = (
            ConnectorTool("search_files", "search", {"type": "object"}),
            ConnectorTool("get_file_metadata", "metadata", {"type": "object"}),
        )
        runtime = ConnectorRuntime(
            catalogue={"google-drive": GOOGLE_DRIVE_ENTRY},
            transports={"google-drive-rest": DeterministicFakeConnectorTransport(tools)},
            policy=AllowReadsConnectorPolicy(),
            grants=(
                ConnectorGrant("agent_1", "google-drive/search_files", "admin_1"),
                ConnectorGrant("agent_1", "google-drive/get_file_metadata", "admin_1"),
            ),
            skills=(
                ConnectorSkill(
                    slug="drive-search",
                    title="Drive Search",
                    instructions="Search Drive.",
                    tool_refs=("google-drive/search_files",),
                ),
            ),
        )
        offered = runtime.offered_refs("agent_1", ("drive-search",))
        self.assertEqual(
            offered,
            {"google-drive/search_files", "google-drive/get_file_metadata"},
        )

    def test_connection_projection_never_contains_raw_credentials(self):
        rendered = self.connection().safe_dict()
        self.assertFalse(rendered["raw_access_token"])
        self.assertFalse(rendered["raw_refresh_token"])
        self.assertFalse(rendered["raw_api_key"])


if __name__ == "__main__":
    unittest.main()
