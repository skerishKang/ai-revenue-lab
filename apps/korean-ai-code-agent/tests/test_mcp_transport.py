from __future__ import annotations

import unittest

from kagent.connector_platform import (
    ConnectorAuthKind,
    ConnectorCatalogueEntry,
    ConnectorConnection,
    NOTION_ENTRY,
)
from kagent.contracts import ContractError
from kagent.mcp_transport import (
    DeterministicTrustedMcpAuthority,
    TrustedMcpCallResponse,
    TrustedMcpTransport,
)


class TrustedMcpTransportTests(unittest.TestCase):
    def connection(self, connector_id: str = "notion") -> ConnectorConnection:
        return ConnectorConnection(
            binding_ref="binding_1",
            actor_ref="actor_1",
            connector_id=connector_id,
        )

    def test_list_tools_uses_only_pinned_endpoint_and_opaque_refs(self):
        authority = DeterministicTrustedMcpAuthority(
            tools=(
                {
                    "name": "notion-search",
                    "description": "Search Notion.",
                    "inputSchema": {"type": "object"},
                },
            )
        )
        transport = TrustedMcpTransport(
            catalogue={"notion": NOTION_ENTRY},
            authority=authority,
        )
        tools = transport.list_tools(self.connection())
        self.assertEqual(tuple(tool.name for tool in tools), ("notion-search",))
        call = authority.list_calls[0]
        self.assertEqual(call["binding_ref"], "binding_1")
        self.assertEqual(call["actor_ref"], "actor_1")
        self.assertEqual(call["connector_id"], "notion")
        self.assertEqual(call["endpoint"], "https://mcp.notion.com/mcp")
        self.assertEqual(call["timeout_seconds"], 30)
        self.assertNotIn("token", call)
        self.assertNotIn("access_token", call)
        self.assertNotIn("refresh_token", call)
        self.assertNotIn("client_secret", call)

    def test_call_tool_is_bounded_redacted_and_preserves_error_flag(self):
        authority = DeterministicTrustedMcpAuthority(
            replies={
                "notion-search": TrustedMcpCallResponse(
                    text="token=supersecretvalue\n" + ("x" * 25_000),
                    is_error=True,
                )
            }
        )
        transport = TrustedMcpTransport(
            catalogue={"notion": NOTION_ENTRY},
            authority=authority,
        )
        result = transport.call_tool(
            self.connection(),
            "notion-search",
            {"query": "roadmap"},
        )
        self.assertTrue(result.is_error)
        self.assertTrue(result.truncated)
        self.assertNotIn("supersecretvalue", result.text)
        self.assertIn("[truncated:", result.text)
        call = authority.tool_calls[0]
        self.assertEqual(call["endpoint"], "https://mcp.notion.com/mcp")
        self.assertEqual(call["tool_name"], "notion-search")
        self.assertEqual(call["args"], {"query": "roadmap"})

    def test_duplicate_live_tool_names_are_rejected(self):
        authority = DeterministicTrustedMcpAuthority(
            tools=(
                {"name": "same", "description": "a", "inputSchema": {"type": "object"}},
                {"name": "same", "description": "b", "inputSchema": {"type": "object"}},
            )
        )
        transport = TrustedMcpTransport(
            catalogue={"notion": NOTION_ENTRY},
            authority=authority,
        )
        with self.assertRaises(ContractError):
            transport.list_tools(self.connection())

    def test_malformed_tool_record_is_rejected(self):
        authority = DeterministicTrustedMcpAuthority(
            tools=({"description": "missing name", "inputSchema": {"type": "object"}},)
        )
        transport = TrustedMcpTransport(
            catalogue={"notion": NOTION_ENTRY},
            authority=authority,
        )
        with self.assertRaises(ContractError):
            transport.list_tools(self.connection())

    def test_non_mcp_connector_cannot_use_mcp_transport(self):
        rest_entry = ConnectorCatalogueEntry(
            connector_id="rest-only",
            title="REST Only",
            vendor="Test",
            host="https://example.com",
            path="/v1",
            auth_kind=ConnectorAuthKind.USER_OAUTH,
            transport_kind="rest",
        )
        transport = TrustedMcpTransport(
            catalogue={"rest-only": rest_entry},
            authority=DeterministicTrustedMcpAuthority(),
        )
        with self.assertRaises(ContractError):
            transport.list_tools(self.connection("rest-only"))

    def test_unpinned_per_instance_host_is_rejected_in_m0(self):
        dynamic = ConnectorCatalogueEntry(
            connector_id="dynamic",
            title="Dynamic",
            vendor="Test",
            host=None,
            path="/mcp",
            auth_kind=ConnectorAuthKind.USER_OAUTH,
            transport_kind="mcp",
        )
        transport = TrustedMcpTransport(
            catalogue={"dynamic": dynamic},
            authority=DeterministicTrustedMcpAuthority(),
        )
        with self.assertRaises(ContractError):
            transport.list_tools(self.connection("dynamic"))

    def test_authority_must_return_exact_response_type(self):
        class BadAuthority:
            def list_tools(self, **kwargs):
                return ()

            def call_tool(self, **kwargs):
                return "not-a-trusted-envelope"

        transport = TrustedMcpTransport(
            catalogue={"notion": NOTION_ENTRY},
            authority=BadAuthority(),
        )
        with self.assertRaises(ContractError):
            transport.call_tool(self.connection(), "notion-search", {})


if __name__ == "__main__":
    unittest.main()
