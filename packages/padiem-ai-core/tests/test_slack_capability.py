"""Core Slack capability contract tests (#2356).

Network-free. Stubs the trusted ``SlackReadPort`` boundary with a recording
fake; zero provider calls, zero tokens, zero sends.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from padiem_ai_core.connector_registry import validate_connector_tools
from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect
from padiem_ai_core.slack_capability import (
    MAX_SLACK_CHANNELS,
    MAX_SLACK_FILE_BYTES,
    MAX_SLACK_FILES_PER_ACTION,
    MAX_SLACK_MESSAGE_CHARS,
    MAX_SLACK_PROJECTION_ITEMS,
    SLACK_API_HOST,
    SLACK_BASE_URL,
    SLACK_CANONICAL_TOOL_IDS,
    SLACK_CONNECTOR_ID,
    SLACK_DESCRIPTOR,
    SLACK_GET_CHANNEL_HISTORY_TOOL_ID,
    SLACK_GET_FILE_INFO_TOOL_ID,
    SLACK_GET_THREAD_REPLIES_TOOL_ID,
    SLACK_GET_USER_INFO_TOOL_ID,
    SLACK_GET_WORKSPACE_INFO_TOOL_ID,
    SLACK_LIST_CHANNELS_TOOL_ID,
    SLACK_RAW_OAUTH_TOKEN_IN_CORE,
    SLACK_READONLY_AUTH_SCOPE,
    SLACK_READ_TOOL_IDS,
    SLACK_SEND_AUTH_SCOPE,
    SLACK_SIGNATURE_MAX_AGE_SECONDS,
    SlackCapability,
    SlackCapabilityClassification,
    SlackCapabilityGrant,
    SlackChannelInfo,
    SlackContractError,
    SlackFileManifest,
    SlackMessageInfo,
    SlackUserInfo,
    SlackWorkspaceInfo,
    SlackWorkspaceScope,
    build_slack_read_handlers,
    capability_requires_send_approval,
    classify_slack_tool_id,
    core_auth_scopes_for_capability,
    register_slack_read_tools,
    slack_capability_snapshot,
    slack_read_tool_specs,
)
from padiem_ai_core.tool_registry import RegisteredTool, ToolRegistrySnapshot
from padiem_ai_core.tool_runtime import ToolRuntime

BINDING_REF = "binding_slack_1"
ACTOR_REF = "actor_1"
CHANNEL_ID = "C012AB3CD4E"
PRIVATE_CHANNEL_ID = "G098ZYXWVU7"
USER_ID = "U012AB3CD4E"
FILE_ID = "F012AB3CD4E"
TEAM_ID = "T012AB3CD4E"
MESSAGE_TS = "1712345678.123456"


def run(coro):
    return asyncio.run(coro)


class FakeSlackPort:
    """In-memory trusted port double. No network, no token."""

    def __init__(self, *, json_responses: list[dict] | None = None) -> None:
        self.json_responses: list[dict] = list(json_responses or [])
        self.calls: list[dict] = []

    def get_json(self, **kwargs):
        self.calls.append(kwargs)
        if not self.json_responses:
            raise AssertionError("unexpected provider JSON call")
        return self.json_responses.pop(0)


def slack_handlers(port: FakeSlackPort, **kwargs) -> dict:
    return build_slack_read_handlers(
        port, binding_ref=BINDING_REF, actor_ref=ACTOR_REF, **kwargs
    )


def auth_test() -> dict:
    return {
        "ok": True,
        "url": "https://acme.slack.com/",
        "team": "Acme",
        "user": "padiem-bot",
        "team_id": TEAM_ID,
        "user_id": USER_ID,
        "bot_id": "B012AB3CD4E",
    }


def channels_list(*channels: dict) -> dict:
    return {"ok": True, "channels": list(channels)}


def channel_entry(channel_id: str = CHANNEL_ID, *, private: bool = False, name: str = "ops") -> dict:
    return {"id": channel_id, "name": name, "is_private": private, "is_archived": False}


def history(*messages: dict) -> dict:
    return {"ok": True, "messages": list(messages)}


def message_entry(**overrides) -> dict:
    base = {"type": "message", "ts": MESSAGE_TS, "user": USER_ID, "text": "hello"}
    base.update(overrides)
    return base


def user_info(user_id: str = USER_ID) -> dict:
    return {
        "ok": True,
        "user": {
            "id": user_id,
            "name": "jane",
            "real_name": "Jane Doe",
            "is_bot": False,
            "profile": {"email": "jane@acme.example", "image_original": "https://x/y.png"},
        },
    }


def file_info(file_id: str = FILE_ID, size: int = 1024) -> dict:
    return {
        "ok": True,
        "file": {
            "id": file_id,
            "name": "report.pdf",
            "mimetype": "application/pdf",
            "size": size,
            "url_private": "https://files.slack.com/private-secret-link",
            "url_private_download": "https://files.slack.com/download-secret-link",
        },
    }


# --- Core contract surface ---


def test_specs_are_read_only_and_bounded() -> None:
    specs = slack_read_tool_specs()
    assert tuple(spec.id for spec in specs) == SLACK_READ_TOOL_IDS
    for spec in specs:
        assert spec.side_effect is ToolSideEffect.READ
        assert spec.approval_policy is ApprovalPolicy.NOT_REQUIRED
        assert spec.auth_scope == (SLACK_READONLY_AUTH_SCOPE,)
    assert all("post" not in spec.id and "send" not in spec.id for spec in specs)


def test_canonical_tool_ids_and_descriptor_conform_to_core_registries() -> None:
    entries = tuple(
        RegisteredTool.from_spec(canonical_tool_id=canonical_id, runtime_spec=spec)
        for canonical_id, spec in zip(SLACK_CANONICAL_TOOL_IDS, slack_read_tool_specs())
    )
    tool_registry = ToolRegistrySnapshot.from_entries(entries)
    validated = validate_connector_tools(SLACK_DESCRIPTOR, tool_registry)
    assert validated.connector_id == SLACK_CONNECTOR_ID
    assert validated.canonical_tool_ids == SLACK_CANONICAL_TOOL_IDS


def test_bounds_mirror_reviewed_b54_contract() -> None:
    assert MAX_SLACK_CHANNELS == 128
    assert MAX_SLACK_MESSAGE_CHARS == 20_000
    assert MAX_SLACK_FILE_BYTES == 10 * 1024 * 1024
    assert MAX_SLACK_FILES_PER_ACTION == 8
    assert SLACK_SIGNATURE_MAX_AGE_SECONDS == 300
    assert MAX_SLACK_PROJECTION_ITEMS == 100


def test_classify_slack_tool_id_is_fail_closed() -> None:
    for tool_id in SLACK_READ_TOOL_IDS + SLACK_CANONICAL_TOOL_IDS:
        assert classify_slack_tool_id(tool_id) is SlackCapabilityClassification.READ
    for tool_id in (
        "slack.post_message",
        "chat.postMessage",
        "conversations.mark",
        "files.upload",
        "conversations.join",
        "users.setPresence",
        "tool:slack:channel.post_message@1",
    ):
        assert classify_slack_tool_id(tool_id) is SlackCapabilityClassification.WRITE_OR_MATERIAL
    for tool_id in ("slack.unknown_read", "tool:slack:channel.mystery@1"):
        assert classify_slack_tool_id(tool_id) is SlackCapabilityClassification.UNKNOWN
    with pytest.raises(SlackContractError):
        classify_slack_tool_id("")
    with pytest.raises(SlackContractError):
        classify_slack_tool_id("bad id with spaces")


def test_capability_scopes_and_approval_semantics() -> None:
    assert core_auth_scopes_for_capability(SlackCapability.READ) == (SLACK_READONLY_AUTH_SCOPE,)
    assert core_auth_scopes_for_capability(SlackCapability.POST_MESSAGE) == (SLACK_SEND_AUTH_SCOPE,)
    assert capability_requires_send_approval(SlackCapability.READ) is False
    assert capability_requires_send_approval(SlackCapability.POST_MESSAGE) is True
    assert capability_requires_send_approval(SlackCapability.UPLOAD_FILE) is True


def test_grant_never_mints_write_or_token_authority() -> None:
    grant = SlackCapabilityGrant(
        connector_id=SLACK_CONNECTOR_ID,
        binding_ref=BINDING_REF,
        granted_capabilities=(SlackCapability.READ,),
    )
    snapshot = grant.safe_dict()
    assert snapshot["write_authority"] is False
    assert snapshot["bot_token_present"] is False
    assert snapshot["mints_approval_authority"] is False
    with pytest.raises(SlackContractError):
        SlackCapabilityGrant(
            connector_id=SLACK_CONNECTOR_ID,
            binding_ref=BINDING_REF,
            granted_capabilities=(SlackCapability.READ, SlackCapability.READ),
        )
    with pytest.raises(SlackContractError):
        SlackCapabilityGrant(
            connector_id=SLACK_CONNECTOR_ID,
            binding_ref=BINDING_REF,
            granted_capabilities=("slack.send",),  # type: ignore[arg-type]
        )


def test_snapshot_is_deterministic_and_fail_closed() -> None:
    first = slack_capability_snapshot()
    assert first == slack_capability_snapshot()
    assert json.dumps(first, sort_keys=True)
    assert first["write_tools_present"] is False
    assert first["registered_write_tools"] == []
    assert first["events_ingress_in_scope"] is False
    assert first["private_channel_access_implicit"] is False
    assert first["whole_workspace_dump_supported"] is False
    assert first["raw_bot_token_in_core"] is False
    assert first["production_send_authority_minted"] is False
    assert first["live_provider_calls"] == 0
    assert first["production_activation"] is False
    assert SLACK_RAW_OAUTH_TOKEN_IN_CORE is False


# --- workspace scope (B54 promotion) ---


def test_workspace_scope_requires_explicit_channel_allowlist() -> None:
    scope = SlackWorkspaceScope(
        binding_ref=BINDING_REF,
        workspace_ref="workspace_acme",
        slack_team_id=TEAM_ID,
        slack_app_id="A012AB3CD4E",
        allowed_channel_ids=(CHANNEL_ID, PRIVATE_CHANNEL_ID),
        explicitly_private_channel_ids=(PRIVATE_CHANNEL_ID,),
    )
    assert scope.authorizes(channel_id=CHANNEL_ID) is True
    assert scope.authorizes(channel_id=PRIVATE_CHANNEL_ID, private_channel=True) is True
    assert scope.authorizes(channel_id="C9999999999", private_channel=False) is False
    assert scope.authorizes(channel_id=CHANNEL_ID, private_channel=True) is False
    snapshot = scope.safe_dict()
    assert snapshot["contract_version"] == "padiem-slack-workspace-scope.v1"
    assert snapshot["workspace_connection_implies_all_channels"] is False
    assert snapshot["private_channel_access_implicit"] is False
    assert snapshot["bot_token_present"] is False


def test_workspace_scope_rejects_malformed_bounds() -> None:
    with pytest.raises(SlackContractError):
        SlackWorkspaceScope(
            binding_ref=BINDING_REF,
            workspace_ref="workspace_acme",
            slack_team_id=TEAM_ID,
            slack_app_id="A012AB3CD4E",
            allowed_channel_ids=(),
        )
    with pytest.raises(SlackContractError):
        SlackWorkspaceScope(
            binding_ref=BINDING_REF,
            workspace_ref="workspace_acme",
            slack_team_id=TEAM_ID,
            slack_app_id="A012AB3CD4E",
            allowed_channel_ids=(CHANNEL_ID, CHANNEL_ID),
        )
    with pytest.raises(SlackContractError):
        SlackWorkspaceScope(
            binding_ref=BINDING_REF,
            workspace_ref="workspace_acme",
            slack_team_id=TEAM_ID,
            slack_app_id="A012AB3CD4E",
            allowed_channel_ids=(CHANNEL_ID,),
            explicitly_private_channel_ids=(PRIVATE_CHANNEL_ID,),
        )
    with pytest.raises(SlackContractError):
        SlackWorkspaceScope(
            binding_ref=BINDING_REF,
            workspace_ref="workspace acme!",
            slack_team_id=TEAM_ID,
            slack_app_id="A012AB3CD4E",
            allowed_channel_ids=(CHANNEL_ID,),
        )


# --- projections ---


def test_workspace_info_projection_has_no_url_or_token() -> None:
    info = SlackWorkspaceInfo(team_id=TEAM_ID, team_name="Acme", bot_user_id=USER_ID)
    snapshot = info.safe_dict()
    assert snapshot["user_impersonation"] is False
    assert snapshot["bot_token_present"] is False
    with pytest.raises(SlackContractError):
        SlackWorkspaceInfo(team_id=TEAM_ID, team_name="Acme", bot_user_id="not an id")


def test_channel_and_message_projections_are_bounded_and_untrusted() -> None:
    channel = SlackChannelInfo(channel_id=CHANNEL_ID, name="ops")
    assert channel.safe_dict()["message_content_present"] is False
    with pytest.raises(SlackContractError):
        SlackChannelInfo(channel_id="lowercase-id", name="ops")
    message = SlackMessageInfo(
        channel_id=CHANNEL_ID,
        message_ts=MESSAGE_TS,
        user_ref=USER_ID,
        text="hello",
    )
    snapshot = message.safe_dict()
    assert snapshot["message_content_trusted"] is False
    assert snapshot["mention_grants_tool_authority"] is False
    with pytest.raises(SlackContractError):
        SlackMessageInfo(
            channel_id=CHANNEL_ID,
            message_ts="nope",
            user_ref=None,
            text="hello",
        )
    with pytest.raises(SlackContractError):
        SlackMessageInfo(
            channel_id=CHANNEL_ID,
            message_ts=MESSAGE_TS,
            user_ref=None,
            text="x" * (MAX_SLACK_MESSAGE_CHARS + 1),
        )


def test_file_manifest_never_carries_bytes_or_urls() -> None:
    manifest = SlackFileManifest(
        file_ref=FILE_ID, filename="report.pdf", mime_type="application/pdf", size_bytes=1024
    )
    snapshot = manifest.safe_dict()
    assert snapshot["raw_bytes_present"] is False
    assert snapshot["download_url_present"] is False
    assert snapshot["model_usable"] is False
    with pytest.raises(SlackContractError):
        SlackFileManifest(
            file_ref=FILE_ID,
            filename="big.bin",
            mime_type="application/octet-stream",
            size_bytes=MAX_SLACK_FILE_BYTES + 1,
        )


def test_user_info_projection_drops_profile_material() -> None:
    user = SlackUserInfo(user_id=USER_ID, display_name="Jane Doe")
    snapshot = user.safe_dict()
    assert snapshot["email_present"] is False
    assert snapshot["profile_url_present"] is False


# --- handlers ---


def test_get_workspace_info_projects_bounded_identity() -> None:
    port = FakeSlackPort(json_responses=[auth_test()])
    handlers = slack_handlers(port)
    result = run(handlers[SLACK_GET_WORKSPACE_INFO_TOOL_ID]({}))
    assert result["provider"] == "slack"
    assert result["result_status"] == "OK"
    assert result["workspace"]["team_id"] == TEAM_ID
    assert "url" not in json.dumps(result)
    assert result["bot_token_present"] is False
    assert result["write_capability_granted"] is False
    call = port.calls[0]
    assert call["base_url"] == SLACK_BASE_URL
    assert call["path"] == "/api/auth.test"
    assert call["required_scopes"] == (SLACK_READONLY_AUTH_SCOPE,)
    assert call["binding_ref"] == BINDING_REF
    assert call["actor_ref"] == ACTOR_REF


def test_get_workspace_info_rejects_provider_error_without_echo() -> None:
    port = FakeSlackPort(json_responses=[{"ok": False, "error": "invalid_auth for token xoxb-secret"}])
    handlers = slack_handlers(port)
    with pytest.raises(SlackContractError) as exc_info:
        run(handlers[SLACK_GET_WORKSPACE_INFO_TOOL_ID]({}))
    assert "secret" not in str(exc_info.value)
    assert "xoxb" not in str(exc_info.value)


def test_list_channels_filters_to_allowlist_and_drops_implicit_private() -> None:
    port = FakeSlackPort(
        json_responses=[
            channels_list(
                channel_entry(CHANNEL_ID),
                channel_entry(PRIVATE_CHANNEL_ID, private=True),
                channel_entry("C9999999999", name="not-allowed"),
            )
        ]
    )
    handlers = slack_handlers(
        port,
        allowed_channel_ids=(CHANNEL_ID, PRIVATE_CHANNEL_ID),
        explicitly_private_channel_ids=(PRIVATE_CHANNEL_ID,),
    )
    result = run(handlers[SLACK_LIST_CHANNELS_TOOL_ID]({}))
    ids = [channel["channel_id"] for channel in result["channels"]]
    assert ids == [CHANNEL_ID, PRIVATE_CHANNEL_ID]
    assert result["whole_workspace_dump"] is False
    assert result["private_channel_access_implicit"] is False


def test_list_channels_drops_private_without_explicit_grant() -> None:
    port = FakeSlackPort(
        json_responses=[channels_list(channel_entry(CHANNEL_ID), channel_entry(PRIVATE_CHANNEL_ID, private=True))]
    )
    handlers = slack_handlers(port, allowed_channel_ids=(CHANNEL_ID, PRIVATE_CHANNEL_ID))
    result = run(handlers[SLACK_LIST_CHANNELS_TOOL_ID]({}))
    ids = [channel["channel_id"] for channel in result["channels"]]
    assert ids == [CHANNEL_ID]


def test_get_channel_history_enforces_server_allowlist() -> None:
    port = FakeSlackPort(json_responses=[history(message_entry())])
    handlers = slack_handlers(port, allowed_channel_ids=(CHANNEL_ID,))
    result = run(
        handlers[SLACK_GET_CHANNEL_HISTORY_TOOL_ID]({"channelId": CHANNEL_ID, "limit": 10})
    )
    assert result["messages"][0]["message_ts"] == MESSAGE_TS
    assert result["messages"][0]["message_content_trusted"] is False
    assert port.calls[0]["path"] == "/api/conversations.history"
    assert port.calls[0]["query"] == {"channel": CHANNEL_ID, "limit": "10"}

    handlers_other = slack_handlers(FakeSlackPort(), allowed_channel_ids=(CHANNEL_ID,))
    with pytest.raises(SlackContractError):
        run(handlers_other[SLACK_GET_CHANNEL_HISTORY_TOOL_ID]({"channelId": "C9999999999"}))


def test_get_channel_history_rejects_malformed_arguments() -> None:
    port = FakeSlackPort()
    handlers = slack_handlers(port)
    for arguments in (
        {},
        {"channelId": "bad id"},
        {"channelId": CHANNEL_ID, "limit": 0},
        {"channelId": CHANNEL_ID, "limit": 101},
        {"channelId": CHANNEL_ID, "extra": True},
    ):
        with pytest.raises(SlackContractError):
            run(handlers[SLACK_GET_CHANNEL_HISTORY_TOOL_ID](arguments))
    assert port.calls == []


def test_get_thread_replies_requires_channel_and_thread_ts() -> None:
    port = FakeSlackPort(json_responses=[history(message_entry(thread_ts=MESSAGE_TS))])
    handlers = slack_handlers(port, allowed_channel_ids=(CHANNEL_ID,))
    result = run(
        handlers[SLACK_GET_THREAD_REPLIES_TOOL_ID](
            {"channelId": CHANNEL_ID, "threadTs": MESSAGE_TS}
        )
    )
    assert result["thread_ts"] == MESSAGE_TS
    assert result["reply_count"] == 1
    assert port.calls[0]["path"] == "/api/conversations.replies"
    assert port.calls[0]["query"] == {
        "channel": CHANNEL_ID,
        "ts": MESSAGE_TS,
        "limit": str(MAX_SLACK_PROJECTION_ITEMS),
    }
    with pytest.raises(SlackContractError):
        run(handlers[SLACK_GET_THREAD_REPLIES_TOOL_ID]({"channelId": CHANNEL_ID}))


def test_get_user_info_rejects_identity_mismatch_and_drops_profile() -> None:
    port = FakeSlackPort(json_responses=[user_info()])
    handlers = slack_handlers(port)
    result = run(handlers[SLACK_GET_USER_INFO_TOOL_ID]({"userId": USER_ID}))
    assert result["user"]["user_id"] == USER_ID
    assert result["user"]["email_present"] is False
    encoded = json.dumps(result)
    assert "jane@acme.example" not in encoded

    mismatch = FakeSlackPort(json_responses=[user_info(user_id="U99999999999")])
    handlers_mismatch = slack_handlers(mismatch)
    with pytest.raises(SlackContractError):
        run(handlers_mismatch[SLACK_GET_USER_INFO_TOOL_ID]({"userId": USER_ID}))


def test_get_file_info_never_projects_signed_urls() -> None:
    port = FakeSlackPort(json_responses=[file_info()])
    handlers = slack_handlers(port)
    result = run(handlers[SLACK_GET_FILE_INFO_TOOL_ID]({"fileId": FILE_ID}))
    assert result["file"]["file_ref"] == FILE_ID
    encoded = json.dumps(result)
    assert "private-secret-link" not in encoded
    assert "download-secret-link" not in encoded
    assert result["file"]["raw_bytes_present"] is False


def test_port_exception_is_sanitized_never_leaks_token() -> None:
    class ExplodingPort:
        def get_json(self, **kwargs):
            raise RuntimeError(
                "POST https://slack.com/api/auth.test failed with "
                "Authorization: Bearer xoxb-SECRET-TOKEN-VALUE"
            )

    handlers = slack_handlers(ExplodingPort())
    with pytest.raises(SlackContractError) as exc_info:
        run(handlers[SLACK_GET_WORKSPACE_INFO_TOOL_ID]({}))
    message = str(exc_info.value)
    assert "SECRET-TOKEN" not in message
    assert "xoxb" not in message
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_registration_is_read_only_on_shared_runtime() -> None:
    runtime = ToolRuntime()
    port = FakeSlackPort()
    registered = register_slack_read_tools(
        runtime, port, binding_ref=BINDING_REF, actor_ref=ACTOR_REF
    )
    assert registered == SLACK_READ_TOOL_IDS
    assert set(runtime.registered_tool_ids) == set(SLACK_READ_TOOL_IDS)
    assert len(runtime.registered_tool_ids) == len(SLACK_READ_TOOL_IDS)
    assert all(not spec.id.startswith("slack.post") for spec in slack_read_tool_specs())


def test_host_constant_is_official_api_only() -> None:
    assert SLACK_API_HOST == "slack.com"
    assert SLACK_BASE_URL == "https://slack.com"
    assert SLACK_CONNECTOR_ID == "connector:slack:workspace@1"
