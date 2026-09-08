from __future__ import annotations

import pytest

from padiem_ai_core.connectors import GMAIL_CONNECTOR_ID
from padiem_ai_core.gmail_capability import (
    GMAIL_READ_TOOL_IDS,
    GmailCapability,
    GmailCapabilityClassification,
    GmailCapabilityGrant,
)

from app.gmail_capability_projection import (
    GMAIL_ENGINE_CAPABILITY_PROJECTION_VERSION,
    classify_gmail_tool_for_binding,
    project_gmail_capability_facts,
)


def _grant(*capabilities: GmailCapability) -> GmailCapabilityGrant:
    return GmailCapabilityGrant(
        connector_id=GMAIL_CONNECTOR_ID,
        binding_ref="bind:gmail_engine",
        granted_capabilities=capabilities or (GmailCapability.READ,),
    )


def test_only_promoted_read_tools_are_bindable():
    for tool_id in GMAIL_READ_TOOL_IDS:
        assert classify_gmail_tool_for_binding(tool_id) is GmailCapabilityClassification.READ
    with pytest.raises(ValueError, match="write_or_material"):
        classify_gmail_tool_for_binding("gmail.create_draft")
    with pytest.raises(ValueError, match="unknown"):
        classify_gmail_tool_for_binding("gmail.future_tool")
    with pytest.raises(ValueError):
        classify_gmail_tool_for_binding("not-a-tool-id!")


def test_capability_facts_projection_is_bounded_and_credential_free():
    projection = project_gmail_capability_facts(_grant(GmailCapability.READ, GmailCapability.CREATE_DRAFT))
    assert projection["projection_version"] == GMAIL_ENGINE_CAPABILITY_PROJECTION_VERSION
    assert projection["granted_capabilities"] == ["create_draft", "read"]
    assert projection["send_authority"] is False
    assert projection["bindable_tool_ids"] == sorted(GMAIL_READ_TOOL_IDS)
    assert projection["draft_implies_send"] is False
    assert projection["mints_approval_authority"] is False
    assert projection["raw_credentials_present"] is False
    assert projection["oauth_token_present"] is False
    assert projection["live_provider_calls"] == 0
    assert projection["production_activation"] is False
    # Bounded Core auth-scope *tokens* only — never provider URLs in the
    # Engine projection (provider URL scopes stay at the trusted port boundary).
    for scopes in projection["capability_core_auth_scopes"].values():
        for scope in scopes:
            assert "https://" not in scope
    assert projection["capability_core_auth_scopes"]["read"] == ["gmail.readonly"]


def test_projection_requires_read_classification_for_every_tool():
    with pytest.raises(ValueError):
        project_gmail_capability_facts(_grant(GmailCapability.READ), tool_ids=("gmail.create_draft",))
    with pytest.raises(ValueError):
        project_gmail_capability_facts(_grant(GmailCapability.READ), tool_ids=())


def test_projection_rejects_non_core_grant():
    with pytest.raises(ValueError):
        project_gmail_capability_facts({"granted_capabilities": ["read"]})  # type: ignore[arg-type]


def test_send_authority_flag_tracks_explicit_capability_only():
    read_only = project_gmail_capability_facts(_grant(GmailCapability.READ))
    assert read_only["send_authority"] is False
    send_grant = project_gmail_capability_facts(_grant(GmailCapability.SEND_EXISTING_APPROVED_DRAFT))
    assert send_grant["send_authority"] is True
    assert send_grant["p01_approval_required"]["send_existing_approved_draft"] is True
    assert send_grant["p01_approval_required"]["create_draft"] is False
