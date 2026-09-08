from __future__ import annotations

import pytest

from padiem_ai_core.connectors import (
    GMAIL_CANONICAL_TOOL_IDS,
    GMAIL_READONLY_AUTH_SCOPE,
    GMAIL_READONLY_SCOPE,
    GmailContractError,
)
from padiem_ai_core.gmail_capability import (
    GMAIL_COMPOSE_AUTH_SCOPE,
    GMAIL_COMPOSE_SCOPE,
    GMAIL_MCP_SEND_TOOL_SUPPORTED,
    GMAIL_MODIFY_AUTH_SCOPE,
    GMAIL_MODIFY_SCOPE,
    GMAIL_PROVIDER_SCOPE_ALONE_GRANTS_PADIEM_SEND_AUTHORITY,
    GMAIL_READ_TOOL_IDS,
    GMAIL_RAW_CREDENTIAL_IN_CORE,
    GMAIL_SEND_REQUIRES_P01_APPROVAL,
    GMAIL_WRITE_TOOLS_PRESENT,
    GmailCapability,
    GmailCapabilityClassification,
    GmailCapabilityGrant,
    capability_requires_p01_approval,
    classify_gmail_tool_id,
    core_auth_scopes_for_capability,
    gmail_capability_snapshot,
    provider_scopes_for_capability,
)


def test_capability_values_match_reviewed_b54_contract():
    assert {item.value for item in GmailCapability} == {
        "read",
        "create_draft",
        "send_existing_approved_draft",
        "label_mutation",
    }


def test_provider_scope_mapping_matches_reviewed_contract():
    assert provider_scopes_for_capability(GmailCapability.READ) == (GMAIL_READONLY_SCOPE,)
    assert provider_scopes_for_capability(GmailCapability.CREATE_DRAFT) == (GMAIL_COMPOSE_SCOPE,)
    assert provider_scopes_for_capability(GmailCapability.SEND_EXISTING_APPROVED_DRAFT) == (GMAIL_COMPOSE_SCOPE,)
    assert provider_scopes_for_capability(GmailCapability.LABEL_MUTATION) == (GMAIL_MODIFY_SCOPE,)


def test_core_auth_scope_tokens_are_bounded_and_never_provider_urls():
    assert core_auth_scopes_for_capability(GmailCapability.READ) == (GMAIL_READONLY_AUTH_SCOPE,)
    assert core_auth_scopes_for_capability(GmailCapability.CREATE_DRAFT) == (GMAIL_COMPOSE_AUTH_SCOPE,)
    assert core_auth_scopes_for_capability(GmailCapability.SEND_EXISTING_APPROVED_DRAFT) == (
        GMAIL_COMPOSE_AUTH_SCOPE,
    )
    assert core_auth_scopes_for_capability(GmailCapability.LABEL_MUTATION) == (GMAIL_MODIFY_AUTH_SCOPE,)
    for capability in GmailCapability:
        for token in core_auth_scopes_for_capability(capability):
            assert "/" not in token


def test_only_promoted_read_tools_classify_as_read():
    assert GMAIL_READ_TOOL_IDS == ("gmail.search_messages", "gmail.get_message", "gmail.get_thread")
    for tool_id in GMAIL_READ_TOOL_IDS:
        assert classify_gmail_tool_id(tool_id) is GmailCapabilityClassification.READ
    for canonical in GMAIL_CANONICAL_TOOL_IDS:
        assert classify_gmail_tool_id(canonical) is GmailCapabilityClassification.READ


def test_unknown_and_future_gmail_tools_fail_closed():
    assert classify_gmail_tool_id("gmail.create_draft") is GmailCapabilityClassification.WRITE_OR_MATERIAL
    assert classify_gmail_tool_id("gmail.send_message") is GmailCapabilityClassification.WRITE_OR_MATERIAL
    assert classify_gmail_tool_id("gmail.labels.modify") is GmailCapabilityClassification.WRITE_OR_MATERIAL
    assert classify_gmail_tool_id("gmail.future_tool") is GmailCapabilityClassification.UNKNOWN
    with pytest.raises(GmailContractError):
        classify_gmail_tool_id("")
    with pytest.raises(GmailContractError):
        classify_gmail_tool_id("bad id!")
    with pytest.raises(GmailContractError):
        classify_gmail_tool_id("x" * 200)


def test_send_and_label_require_p01_approval_but_read_and_draft_do_not():
    assert capability_requires_p01_approval(GmailCapability.READ) is False
    assert capability_requires_p01_approval(GmailCapability.CREATE_DRAFT) is False
    assert capability_requires_p01_approval(GmailCapability.SEND_EXISTING_APPROVED_DRAFT) is True
    assert capability_requires_p01_approval(GmailCapability.LABEL_MUTATION) is True
    assert GMAIL_SEND_REQUIRES_P01_APPROVAL is True


def test_grant_allows_only_explicit_capabilities():
    grant = GmailCapabilityGrant(
        connector_id="connector:google:gmail@1",
        binding_ref="bind:gmail_engine",
        granted_capabilities=(GmailCapability.READ, GmailCapability.CREATE_DRAFT),
    )
    assert grant.allows(GmailCapability.READ) is True
    assert grant.allows(GmailCapability.CREATE_DRAFT) is True
    assert grant.allows(GmailCapability.SEND_EXISTING_APPROVED_DRAFT) is False
    assert grant.allows(GmailCapability.LABEL_MUTATION) is False


def test_draft_capability_never_implies_send_authority():
    draft_only = GmailCapabilityGrant(
        connector_id="connector:google:gmail@1",
        binding_ref="bind:gmail_engine",
        granted_capabilities=(GmailCapability.CREATE_DRAFT,),
    )
    read_and_draft = GmailCapabilityGrant(
        connector_id="connector:google:gmail@1",
        binding_ref="bind:gmail_engine",
        granted_capabilities=(GmailCapability.READ, GmailCapability.CREATE_DRAFT),
    )
    send = GmailCapabilityGrant(
        connector_id="connector:google:gmail@1",
        binding_ref="bind:gmail_engine",
        granted_capabilities=(GmailCapability.SEND_EXISTING_APPROVED_DRAFT,),
    )
    assert draft_only.send_authority() is False
    assert read_and_draft.send_authority() is False
    assert send.send_authority() is True


def test_grant_safe_projection_carries_no_credentials_or_second_authority():
    grant = GmailCapabilityGrant(
        connector_id="connector:google:gmail@1",
        binding_ref="bind:gmail_engine",
        granted_capabilities=(GmailCapability.READ,),
    )
    projection = grant.safe_dict()
    assert projection["granted_capabilities"] == ["read"]
    assert projection["send_authority"] is False
    assert projection["raw_credentials_present"] is False
    assert projection["oauth_token_present"] is False
    assert projection["mints_approval_authority"] is False
    assert projection["draft_implies_send"] is False


def test_grant_rejects_duplicate_capabilities_and_bad_refs():
    with pytest.raises(GmailContractError):
        GmailCapabilityGrant(
            connector_id="connector:google:gmail@1",
            binding_ref="bind:gmail_engine",
            granted_capabilities=(GmailCapability.READ, GmailCapability.READ),
        )
    with pytest.raises(GmailContractError):
        GmailCapabilityGrant(
            connector_id="connector:google:gmail@1",
            binding_ref="bad ref!",
            granted_capabilities=(GmailCapability.READ,),
        )
    with pytest.raises(GmailContractError):
        GmailCapabilityGrant(
            connector_id="",
            binding_ref="bind:gmail_engine",
            granted_capabilities=(GmailCapability.READ,),
        )


def test_snapshot_records_fail_closed_review_state():
    snapshot = gmail_capability_snapshot()
    assert snapshot["contract_version"] == "padiem-gmail-capability.v1"
    assert snapshot["registered_write_tools"] == []
    assert snapshot["draft_implies_send"] is False
    assert snapshot["provider_scope_grants_padiem_authority"] is False
    assert snapshot["mints_second_approval_authority"] is False
    assert snapshot["raw_credentials_present"] is False
    assert snapshot["live_provider_calls"] == 0
    assert snapshot["production_activation"] is False
    assert GMAIL_WRITE_TOOLS_PRESENT is False
    assert GMAIL_RAW_CREDENTIAL_IN_CORE is False
    assert GMAIL_MCP_SEND_TOOL_SUPPORTED is False
    assert GMAIL_PROVIDER_SCOPE_ALONE_GRANTS_PADIEM_SEND_AUTHORITY is False
