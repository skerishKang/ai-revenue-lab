from __future__ import annotations

import unittest

from kagent.connector_platform import ConnectorAuthKind, ConnectorEffect
from kagent.verified_mcp_catalogue import (
    GMAIL_ENTRY,
    GOOGLE_CALENDAR_ENTRY,
    GOOGLE_WORKSPACE_MCP_DEVELOPER_PREVIEW,
    RAW_MCP_OAUTH_CREDENTIAL_IN_B54,
    REAL_GMAIL_MCP_CONFIGURED,
    REAL_GOOGLE_CALENDAR_MCP_CONFIGURED,
    REAL_SLACK_MCP_CONFIGURED,
    SLACK_ENTRY,
    VERIFIED_MCP_SOURCE_CONTRACTS,
)


class VerifiedMcpCatalogueTests(unittest.TestCase):
    def test_gmail_current_source_contract_is_user_oauth_and_fail_closed(self):
        self.assertEqual(GMAIL_ENTRY.host, "https://gmailmcp.googleapis.com")
        self.assertEqual(GMAIL_ENTRY.path, "/mcp/v1")
        self.assertEqual(GMAIL_ENTRY.auth_kind, ConnectorAuthKind.USER_OAUTH)
        self.assertEqual(GMAIL_ENTRY.classify("search_threads"), ConnectorEffect.READ)
        self.assertEqual(GMAIL_ENTRY.classify("create_draft"), ConnectorEffect.WRITE)
        self.assertEqual(GMAIL_ENTRY.classify("future_gmail_tool"), ConnectorEffect.WRITE)

    def test_calendar_current_source_contract_separates_read_and_write(self):
        self.assertEqual(
            GOOGLE_CALENDAR_ENTRY.host,
            "https://calendarmcp.googleapis.com",
        )
        self.assertEqual(GOOGLE_CALENDAR_ENTRY.path, "/mcp/v1")
        self.assertEqual(
            GOOGLE_CALENDAR_ENTRY.auth_kind,
            ConnectorAuthKind.USER_OAUTH,
        )
        self.assertEqual(
            GOOGLE_CALENDAR_ENTRY.classify("list_events"),
            ConnectorEffect.READ,
        )
        self.assertEqual(
            GOOGLE_CALENDAR_ENTRY.classify("respond_to_event"),
            ConnectorEffect.WRITE,
        )
        self.assertEqual(
            GOOGLE_CALENDAR_ENTRY.classify("future_calendar_tool"),
            ConnectorEffect.WRITE,
        )

    def test_slack_reuses_endpoint_but_not_historical_shared_bearer_assumption(self):
        self.assertEqual(SLACK_ENTRY.host, "https://mcp.slack.com")
        self.assertEqual(SLACK_ENTRY.path, "/mcp")
        self.assertEqual(SLACK_ENTRY.auth_kind, ConnectorAuthKind.USER_OAUTH)
        self.assertEqual(
            SLACK_ENTRY.classify("slack_send_message"),
            ConnectorEffect.WRITE,
        )
        # No Slack read tool is trusted until a live/reviewed tool-list reconciliation.
        self.assertEqual(
            SLACK_ENTRY.classify("slack_search_messages"),
            ConnectorEffect.WRITE,
        )

    def test_source_contracts_are_preparation_not_live_execution(self):
        self.assertTrue(GOOGLE_WORKSPACE_MCP_DEVELOPER_PREVIEW)
        self.assertFalse(REAL_GMAIL_MCP_CONFIGURED)
        self.assertFalse(REAL_GOOGLE_CALENDAR_MCP_CONFIGURED)
        self.assertFalse(REAL_SLACK_MCP_CONFIGURED)
        self.assertFalse(RAW_MCP_OAUTH_CREDENTIAL_IN_B54)
        for contract in VERIFIED_MCP_SOURCE_CONTRACTS.values():
            rendered = contract.safe_dict()
            self.assertEqual(rendered["verified_on"], "2026-09-03")
            self.assertFalse(rendered["live_execution_configured"])
            self.assertFalse(rendered["raw_oauth_credential"])
            self.assertFalse(rendered["entry"]["credential_fields"])

    def test_exact_current_connector_set_is_deterministic(self):
        self.assertEqual(
            set(VERIFIED_MCP_SOURCE_CONTRACTS),
            {"gmail", "google-calendar", "slack"},
        )


if __name__ == "__main__":
    unittest.main()
