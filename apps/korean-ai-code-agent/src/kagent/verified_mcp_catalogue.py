from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .connector_platform import (
    ConnectorAuthKind,
    ConnectorCatalogueEntry,
)

# Fresh first-party verification date for this source-contract slice.
VERIFIED_ON = "2026-09-03"

# Google Workspace MCP is currently a Developer Preview surface. These source
# contracts describe reviewed endpoints/tool effects only; they do not claim
# provider enrolment, OAuth authority or live execution readiness.
GOOGLE_WORKSPACE_MCP_DEVELOPER_PREVIEW = True

GMAIL_ENTRY = ConnectorCatalogueEntry(
    connector_id="gmail",
    title="Gmail",
    vendor="Google",
    host="https://gmailmcp.googleapis.com",
    path="/mcp/v1",
    auth_kind=ConnectorAuthKind.USER_OAUTH,
    transport_kind="mcp",
    read_tools=(
        "get_message",
        "get_thread",
        "list_drafts",
        "list_labels",
        "search_threads",
    ),
    write_tools=(
        "create_draft",
        "label_message",
        "label_thread",
        "unlabel_message",
        "unlabel_thread",
    ),
)

GOOGLE_CALENDAR_ENTRY = ConnectorCatalogueEntry(
    connector_id="google-calendar",
    title="Google Calendar",
    vendor="Google",
    host="https://calendarmcp.googleapis.com",
    path="/mcp/v1",
    auth_kind=ConnectorAuthKind.USER_OAUTH,
    transport_kind="mcp",
    read_tools=(
        "get_event",
        "list_calendars",
        "list_events",
        "search_events",
        "suggest_time",
    ),
    write_tools=(
        "create_event",
        "delete_event",
        "respond_to_event",
        "update_event",
    ),
)

# The endpoint is reusable from OpenBot's historical catalogue and still
# matches Slack's current first-party documentation. The historical generic
# bearer assumption is NOT reused: Slack's current MCP surface is backed by a
# registered Slack app and confidential per-user OAuth.
#
# No read tool is whitelisted here yet. Slack's current surface is broad and
# evolving (search, files, channels, canvases, lists, users). A live tool-list
# reconciliation must explicitly approve exact read names before B54 can treat
# any Slack tool as read-only. ConnectorCatalogueEntry.classify therefore makes
# every Slack tool material/write by default in this preparation slice.
SLACK_ENTRY = ConnectorCatalogueEntry(
    connector_id="slack",
    title="Slack",
    vendor="Slack",
    host="https://mcp.slack.com",
    path="/mcp",
    auth_kind=ConnectorAuthKind.USER_OAUTH,
    transport_kind="mcp",
    read_tools=(),
    write_tools=(
        "slack_send_message",
        "slack_send_message_draft",
        "slack_schedule_message",
        "slack_add_reaction",
        "slack_create_conversation",
        "slack_create_canvas",
        "slack_update_canvas",
    ),
)


@dataclass(frozen=True, slots=True)
class VerifiedConnectorSourceContract:
    entry: ConnectorCatalogueEntry
    vendor_documentation_ref: str
    source_provenance: str
    verified_on: str = VERIFIED_ON
    live_execution_configured: bool = False

    def safe_dict(self) -> dict[str, Any]:
        return {
            "entry": self.entry.safe_dict(),
            "vendor_documentation_ref": self.vendor_documentation_ref,
            "source_provenance": self.source_provenance,
            "verified_on": self.verified_on,
            "live_execution_configured": self.live_execution_configured,
            "raw_oauth_credential": False,
        }


VERIFIED_MCP_SOURCE_CONTRACTS: dict[str, VerifiedConnectorSourceContract] = {
    "gmail": VerifiedConnectorSourceContract(
        entry=GMAIL_ENTRY,
        vendor_documentation_ref="google-workspace-mcp/gmail",
        source_provenance="google-first-party-current",
    ),
    "google-calendar": VerifiedConnectorSourceContract(
        entry=GOOGLE_CALENDAR_ENTRY,
        vendor_documentation_ref="google-workspace-mcp/calendar",
        source_provenance="google-first-party-current",
    ),
    "slack": VerifiedConnectorSourceContract(
        entry=SLACK_ENTRY,
        vendor_documentation_ref="slack-developer-docs/mcp",
        source_provenance=(
            "openbot-history:e30465914ad3beeaf2de0b48812c0f9b7a532adc"
            "+slack-first-party-current"
        ),
    ),
}

REAL_GMAIL_MCP_CONFIGURED = False
REAL_GOOGLE_CALENDAR_MCP_CONFIGURED = False
REAL_SLACK_MCP_CONFIGURED = False
RAW_MCP_OAUTH_CREDENTIAL_IN_B54 = False
