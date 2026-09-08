"""Google Drive READ capability contract tests for P01 Core (#2166, parent #2010).

Behavioural cases are transplanted from the reviewed B54 suite
(``apps/korean-ai-code-agent/tests/test_google_drive_connector.py`` surface)
with Core-side registry/runtime conformance checks for the
ToolSpec/ConnectorDescriptor/ToolRuntime contract, plus the promoted fail-closed
bounds: trashed fail-closed, shortcut no-escape, binary no-auto-ingest, Shared
Drive identity and version evidence preservation.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from padiem_ai_core import AgentProfile
from padiem_ai_core.connector_registry import validate_connector_tools
from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect
from padiem_ai_core.drive_capability import (
    DRIVE_BASE_URL,
    DRIVE_BINARY_AUTO_INGEST,
    DRIVE_CANONICAL_TOOL_IDS,
    DRIVE_CONNECTOR_ID,
    DRIVE_DESCRIPTOR,
    DRIVE_GET_FILE_METADATA_TOOL_ID,
    DRIVE_LIST_RECENT_FILES_TOOL_ID,
    DRIVE_RAW_CREDENTIAL_IN_CORE,
    DRIVE_READ_FILE_CONTENT_TOOL_ID,
    DRIVE_READONLY_AUTH_SCOPE,
    DRIVE_READONLY_SCOPE,
    DRIVE_READ_TOOL_IDS,
    DRIVE_SEARCH_FILES_TOOL_ID,
    DRIVE_SHORTCUT_AUTO_ESCAPE,
    DRIVE_TRASHED_RESOURCE_READABLE,
    DRIVE_WRITE_TOOLS_PRESENT,
    DriveCapability,
    DriveCapabilityClassification,
    DriveCapabilityGrant,
    DriveContractError,
    DriveResourceClassification,
    build_drive_read_handlers,
    capability_requires_p01_approval,
    classify_drive_resource,
    classify_drive_tool_id,
    core_auth_scopes_for_capability,
    drive_capability_snapshot,
    drive_read_tool_specs,
    drive_search_query,
    export_mime_for,
    is_textual_mime,
    project_drive_file,
    provider_scopes_for_capability,
    register_drive_read_tools,
)
from padiem_ai_core.tool_registry import RegisteredTool, ToolRegistrySnapshot
from padiem_ai_core.tool_runtime import (
    ToolAuthorizationContext,
    ToolInvocation,
    ToolRuntime,
    ToolRuntimeError,
)

BINDING_REF = "binding_drive_1"
ACTOR_REF = "actor_1"

GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
GOOGLE_SHEET_MIME = "application/vnd.google-apps.spreadsheet"
GOOGLE_SLIDES_MIME = "application/vnd.google-apps.presentation"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"


def run(coro):
    return asyncio.run(coro)


class FakeDrivePort:
    """In-memory trusted port double. No network, no credentials, no OAuth."""

    def __init__(
        self,
        *,
        json_responses: list[dict] | None = None,
        text_responses: list[str] | None = None,
    ) -> None:
        self.json_responses: list[dict] = list(json_responses or [])
        self.text_responses: list[str] = list(text_responses or [])
        self.calls: list[dict] = []

    def get_json(self, **kwargs):
        self.calls.append(kwargs)
        if not self.json_responses:
            raise AssertionError("unexpected provider JSON call")
        return self.json_responses.pop(0)

    def get_text(self, **kwargs):
        self.calls.append(kwargs)
        if not self.text_responses:
            raise AssertionError("unexpected provider text call")
        return self.text_responses.pop(0)


def drive_handlers(port: FakeDrivePort) -> dict:
    return build_drive_read_handlers(port, binding_ref=BINDING_REF, actor_ref=ACTOR_REF)


def drive_profile(*allowed_tools: str, agent_id: str = "agent-1") -> AgentProfile:
    return AgentProfile(
        id=agent_id,
        title="Agent",
        description="Google Drive connector test agent",
        system_instruction="Use only allowed tools.",
        task_type="general",
        optimize_for="balanced",
        max_tokens=500,
        allowed_tools=tuple(allowed_tools),
    )


def drive_auth(
    *,
    app_id: str = "padiem-chat",
    agent_id: str = "agent-1",
    scopes: tuple[str, ...] = (),
) -> ToolAuthorizationContext:
    return ToolAuthorizationContext(
        app_id=app_id,
        agent_id=agent_id,
        granted_auth_scopes=scopes,
        user_confirmed_tools=(),
        externally_authorized_tools=(),
    )


def file_metadata(
    file_id: str = "file_1",
    *,
    name: str = "Roadmap",
    mime: str = GOOGLE_DOC_MIME,
    trashed: bool = False,
    drive_id: str | None = None,
    shortcut: dict | None = None,
) -> dict:
    metadata: dict = {
        "id": file_id,
        "name": name,
        "mimeType": mime,
        "trashed": trashed,
        "modifiedTime": "2026-09-08T10:00:00.000Z",
        "version": "7",
        "md5Checksum": "0" * 32,
        "headRevisionId": f"rev_{file_id}",
        "webViewLink": f"https://drive.google.com/file/d/{file_id}/view",
        "size": "2048",
    }
    if drive_id is not None:
        metadata["driveId"] = drive_id
    if shortcut is not None:
        metadata["shortcutDetails"] = shortcut
    return metadata


# --- Core contract surface ---


def test_specs_mirror_reviewed_b54_readonly_surface() -> None:
    specs = drive_read_tool_specs()
    assert tuple(spec.id for spec in specs) == (
        DRIVE_SEARCH_FILES_TOOL_ID,
        DRIVE_LIST_RECENT_FILES_TOOL_ID,
        DRIVE_GET_FILE_METADATA_TOOL_ID,
        DRIVE_READ_FILE_CONTENT_TOOL_ID,
    )
    for spec in specs:
        assert spec.side_effect is ToolSideEffect.READ
        assert spec.approval_policy is ApprovalPolicy.NOT_REQUIRED
        assert spec.owner == "core"
        assert spec.auth_scope == (DRIVE_READONLY_AUTH_SCOPE,)
        assert spec.input_schema["additionalProperties"] is False
    handlers = drive_handlers(FakeDrivePort())
    assert set(handlers) == {
        DRIVE_SEARCH_FILES_TOOL_ID,
        DRIVE_LIST_RECENT_FILES_TOOL_ID,
        DRIVE_GET_FILE_METADATA_TOOL_ID,
        DRIVE_READ_FILE_CONTENT_TOOL_ID,
    }
    assert DRIVE_WRITE_TOOLS_PRESENT is False
    assert DRIVE_RAW_CREDENTIAL_IN_CORE is False


def test_canonical_tool_ids_and_descriptor_conform_to_core_registries() -> None:
    entries = tuple(
        RegisteredTool.from_spec(canonical_tool_id=canonical_id, runtime_spec=spec)
        for canonical_id, spec in zip(DRIVE_CANONICAL_TOOL_IDS, drive_read_tool_specs())
    )
    tool_registry = ToolRegistrySnapshot.from_entries(entries)
    validated = validate_connector_tools(DRIVE_DESCRIPTOR, tool_registry)
    assert validated.connector_id == DRIVE_CONNECTOR_ID
    assert validated.canonical_tool_ids == DRIVE_CANONICAL_TOOL_IDS


def test_descriptor_requires_authorization_and_never_carries_credentials() -> None:
    assert DRIVE_DESCRIPTOR.requires_authorization is True
    public = DRIVE_DESCRIPTOR.to_public_dict()
    assert public["connector_id"] == "connector:google:drive@1"
    assert "credential" not in public
    assert "token" not in public


def test_classify_drive_tool_id_is_fail_closed() -> None:
    for tool_id in DRIVE_READ_TOOL_IDS:
        assert classify_drive_tool_id(tool_id) is DriveCapabilityClassification.READ
    for canonical_id in DRIVE_CANONICAL_TOOL_IDS:
        assert classify_drive_tool_id(canonical_id) is DriveCapabilityClassification.READ
    assert (
        classify_drive_tool_id("drive.upload_file") is DriveCapabilityClassification.WRITE_OR_MATERIAL
    )
    assert (
        classify_drive_tool_id("drive.create_folder") is DriveCapabilityClassification.WRITE_OR_MATERIAL
    )
    assert (
        classify_drive_tool_id("drive.share_file") is DriveCapabilityClassification.WRITE_OR_MATERIAL
    )
    assert classify_drive_tool_id("drive.something_else") is DriveCapabilityClassification.UNKNOWN
    with pytest.raises(DriveContractError):
        classify_drive_tool_id("not a tool id")


def test_classify_drive_resource_covers_reviewed_bounds() -> None:
    assert classify_drive_resource(file_metadata()) is DriveResourceClassification.GOOGLE_NATIVE_EXPORT
    assert (
        classify_drive_resource(file_metadata(mime=GOOGLE_SHEET_MIME))
        is DriveResourceClassification.GOOGLE_NATIVE_EXPORT
    )
    assert (
        classify_drive_resource(file_metadata(mime=GOOGLE_SLIDES_MIME))
        is DriveResourceClassification.GOOGLE_NATIVE_EXPORT
    )
    assert classify_drive_resource(file_metadata(mime="text/plain")) is DriveResourceClassification.TEXT_READ
    assert (
        classify_drive_resource(file_metadata(mime="application/json"))
        is DriveResourceClassification.TEXT_READ
    )
    assert (
        classify_drive_resource(file_metadata(mime=SHORTCUT_MIME))
        is DriveResourceClassification.SHORTCUT_TARGET_REQUIRED
    )
    assert (
        classify_drive_resource(file_metadata(trashed=True))
        is DriveResourceClassification.TRASHED_FAIL_CLOSED
    )
    assert (
        classify_drive_resource(file_metadata(mime="application/pdf"))
        is DriveResourceClassification.BINARY_NOT_INGESTED
    )


def test_export_mime_and_textual_mime_ports() -> None:
    assert export_mime_for(GOOGLE_DOC_MIME) == "text/plain"
    assert export_mime_for(GOOGLE_SHEET_MIME) == "text/csv"
    assert export_mime_for(GOOGLE_SLIDES_MIME) == "text/plain"
    assert export_mime_for("text/plain") is None
    assert is_textual_mime("text/csv") is True
    assert is_textual_mime("application/x-yaml") is True
    assert is_textual_mime("application/pdf") is False
    assert is_textual_mime(None) is False


def test_search_query_escapes_reviewed_b54_form() -> None:
    assert drive_search_query("invoice") == "name contains 'invoice' or fullText contains 'invoice'"
    escaped = drive_search_query("O'Brien")
    assert "\\'" in escaped
    with pytest.raises(DriveContractError):
        drive_search_query("   ")
    with pytest.raises(DriveContractError):
        drive_search_query("x" * 1_001)


# --- promoted safety bounds ---


def test_projection_preserves_shared_drive_identity_and_version_evidence() -> None:
    projection = project_drive_file(file_metadata(drive_id="shared_drive_42"))
    payload = projection.safe_dict()
    assert projection.space_kind == "shared_drive"
    assert payload["shared_drive_id"] == "shared_drive_42"
    assert payload["version_evidence"]["version"] == 7
    assert payload["version_evidence"]["modified_time"] == "2026-09-08T10:00:00.000Z"
    assert payload["version_evidence"]["md5_checksum"] == "0" * 32
    assert payload["version_evidence"]["head_revision_id"] == "rev_file_1"
    assert payload["content_ingested"] is False
    assert payload["raw_credentials_present"] is False

    my_drive = project_drive_file(file_metadata())
    assert my_drive.space_kind == "my_drive"
    assert my_drive.safe_dict()["shared_drive_id"] is None


def test_trashed_resource_fails_closed() -> None:
    with pytest.raises(DriveContractError):
        project_drive_file(file_metadata(trashed=True))

    port = FakeDrivePort(json_responses=[file_metadata(trashed=True)])
    handlers = drive_handlers(port)
    with pytest.raises(DriveContractError):
        run(handlers[DRIVE_GET_FILE_METADATA_TOOL_ID]({"fileId": "file_1"}))

    port = FakeDrivePort(json_responses=[file_metadata(trashed=True)])
    handlers = drive_handlers(port)
    with pytest.raises(DriveContractError):
        run(handlers[DRIVE_READ_FILE_CONTENT_TOOL_ID]({"fileId": "file_1"}))
    assert all("export" not in call["path"] for call in port.calls)
    assert DRIVE_TRASHED_RESOURCE_READABLE is False


def test_shortcut_projection_never_escapes_to_target() -> None:
    projection = project_drive_file(
        file_metadata(
            mime=SHORTCUT_MIME,
            shortcut={"targetId": "target_9", "targetMimeType": GOOGLE_DOC_MIME},
        )
    )
    payload = projection.safe_dict()
    assert payload["shortcut_target_id"] == "target_9"
    assert payload["shortcut_target_mime_type"] == GOOGLE_DOC_MIME
    assert payload["shortcut_target_escape"] is False
    assert payload["content_ingested"] is False
    assert DRIVE_SHORTCUT_AUTO_ESCAPE is False

    port = FakeDrivePort(
        json_responses=[
            file_metadata(
                mime=SHORTCUT_MIME,
                shortcut={"targetId": "target_9", "targetMimeType": GOOGLE_DOC_MIME},
            )
        ]
    )
    handlers = drive_handlers(port)
    with pytest.raises(DriveContractError):
        run(handlers[DRIVE_READ_FILE_CONTENT_TOOL_ID]({"fileId": "file_1"}))
    assert all("export" not in call["path"] for call in port.calls)


def test_binary_content_is_never_ingested() -> None:
    port = FakeDrivePort(json_responses=[file_metadata(mime="application/pdf")])
    handlers = drive_handlers(port)
    with pytest.raises(DriveContractError):
        run(handlers[DRIVE_READ_FILE_CONTENT_TOOL_ID]({"fileId": "file_1"}))
    assert all("media" not in call.get("query", {}) for call in port.calls)
    assert DRIVE_BINARY_AUTO_INGEST is False


def test_binary_metadata_still_readable() -> None:
    port = FakeDrivePort(json_responses=[file_metadata(mime="application/pdf")])
    handlers = drive_handlers(port)
    result = run(handlers[DRIVE_GET_FILE_METADATA_TOOL_ID]({"fileId": "file_1"}))
    assert result["result_status"] == "OK"
    assert result["projection"]["mime_type"] == "application/pdf"
    assert result["content_ingested"] is False


# --- capability split ---


def test_capability_scopes_and_approval_semantics() -> None:
    assert provider_scopes_for_capability(DriveCapability.READ) == (DRIVE_READONLY_SCOPE,)
    assert core_auth_scopes_for_capability(DriveCapability.READ) == (DRIVE_READONLY_AUTH_SCOPE,)
    assert capability_requires_p01_approval(DriveCapability.READ) is False
    assert capability_requires_p01_approval(DriveCapability.MUTATION) is True
    with pytest.raises(DriveContractError):
        provider_scopes_for_capability("read")


def test_grant_never_mints_mutation_authority() -> None:
    grant = DriveCapabilityGrant(
        connector_id=DRIVE_CONNECTOR_ID,
        binding_ref=BINDING_REF,
        granted_capabilities=(DriveCapability.READ,),
    )
    assert grant.allows(DriveCapability.READ) is True
    assert grant.allows(DriveCapability.MUTATION) is False
    assert grant.mutation_authority() is False
    payload = grant.safe_dict()
    assert payload["raw_credentials_present"] is False
    assert payload["oauth_token_present"] is False
    assert payload["mints_approval_authority"] is False
    assert payload["shortcut_target_escape"] is False

    with pytest.raises(DriveContractError):
        DriveCapabilityGrant(
            connector_id=DRIVE_CONNECTOR_ID,
            binding_ref=BINDING_REF,
            granted_capabilities=(DriveCapability.READ, DriveCapability.READ),
        )


def test_snapshot_is_deterministic_and_fail_closed() -> None:
    first = drive_capability_snapshot()
    second = drive_capability_snapshot()
    assert first == second
    assert first["connector_id"] == DRIVE_CONNECTOR_ID
    assert first["read_tool_ids"] == list(DRIVE_READ_TOOL_IDS)
    assert first["registered_write_tools"] == []
    assert first["search_list_metadata_read"] is True
    assert first["shortcut_escape"] is False
    assert first["trashed_resource_failclosed"] is True
    assert first["binary_auto_ingest"] is False
    assert first["shared_drive_identity_preserved"] is True
    assert first["version_evidence_preserved"] is True
    assert first["provider_scope_grants_padiem_authority"] is False
    assert first["raw_credentials_present"] is False
    assert first["oauth_flow_implemented"] is False
    assert first["live_provider_calls"] == 0
    assert first["production_activation"] is False


# --- bounded handler projections ---


def test_search_files_projects_bounded_file_refs() -> None:
    port = FakeDrivePort(
        json_responses=[
            {
                "files": [
                    file_metadata("file_1", name="Roadmap", drive_id="shared_drive_42"),
                    file_metadata("file_2", name="Notes", mime="text/plain"),
                    file_metadata("file_3", name="Old", trashed=True),
                ]
            }
        ]
    )
    handlers = drive_handlers(port)
    result = run(handlers[DRIVE_SEARCH_FILES_TOOL_ID]({"query": "invoice"}))
    assert result["operation"] == "files.list.search"
    assert result["result_status"] == "OK"
    assert result["result_count"] == 2
    assert result["trashed_omitted_count"] == 1
    assert result["files"][0]["shared_drive_id"] == "shared_drive_42"
    assert result["files"][1]["shared_drive_id"] is None
    assert result["raw_credentials_present"] is False

    call = port.calls[0]
    assert call["base_url"] == DRIVE_BASE_URL
    assert call["required_scopes"] == (DRIVE_READONLY_SCOPE,)
    assert call["binding_ref"] == BINDING_REF
    assert call["actor_ref"] == ACTOR_REF
    assert call["query"]["q"] == "(name contains 'invoice' or fullText contains 'invoice') and trashed = false"
    assert call["query"]["supportsAllDrives"] == "true"
    assert call["query"]["includeItemsFromAllDrives"] == "true"


def test_search_requires_query_and_rejects_unknown_args_shape() -> None:
    port = FakeDrivePort()
    handlers = drive_handlers(port)
    with pytest.raises(DriveContractError):
        run(handlers[DRIVE_SEARCH_FILES_TOOL_ID]({}))
    with pytest.raises(DriveContractError):
        run(handlers[DRIVE_READ_FILE_CONTENT_TOOL_ID]({}))
    assert port.calls == []


def test_list_recent_files_orders_by_modified_time() -> None:
    port = FakeDrivePort(json_responses=[{"files": [file_metadata("file_1")]}])
    handlers = drive_handlers(port)
    result = run(handlers[DRIVE_LIST_RECENT_FILES_TOOL_ID]({}))
    assert result["operation"] == "files.list.recent"
    assert result["result_status"] == "OK"
    assert port.calls[0]["query"]["orderBy"] == "modifiedTime desc"
    assert port.calls[0]["query"]["q"] == "trashed = false"


def test_read_file_content_exports_google_native() -> None:
    port = FakeDrivePort(
        json_responses=[file_metadata(mime=GOOGLE_SHEET_MIME)],
        text_responses=["a,b\n1,2\n"],
    )
    handlers = drive_handlers(port)
    result = run(handlers[DRIVE_READ_FILE_CONTENT_TOOL_ID]({"fileId": "file_1"}))
    assert result["operation"] == "files.export"
    assert result["resource_classification"] == DriveResourceClassification.GOOGLE_NATIVE_EXPORT.value
    assert result["export_mime_type"] == "text/csv"
    assert result["content"] == "a,b\n1,2\n"
    assert result["content_truncated"] is False
    assert result["projection"]["version_evidence"]["version"] == 7
    assert result["drive_content_trusted"] is False
    assert port.calls[-1]["path"].endswith("/export")
    assert port.calls[-1]["query"]["mimeType"] == "text/csv"


def test_read_file_content_reads_text_media() -> None:
    port = FakeDrivePort(
        json_responses=[file_metadata(mime="text/plain")],
        text_responses=["plain body"],
    )
    handlers = drive_handlers(port)
    result = run(handlers[DRIVE_READ_FILE_CONTENT_TOOL_ID]({"fileId": "file_1"}))
    assert result["operation"] == "files.get.media"
    assert result["resource_classification"] == DriveResourceClassification.TEXT_READ.value
    assert result["export_mime_type"] is None
    assert result["content"] == "plain body"
    assert port.calls[-1]["query"]["alt"] == "media"


def test_oversized_content_is_bounded_and_marked_review_required() -> None:
    port = FakeDrivePort(
        json_responses=[file_metadata(mime="text/plain")],
        text_responses=["x" * 50_000],
    )
    handlers = drive_handlers(port)
    result = run(handlers[DRIVE_READ_FILE_CONTENT_TOOL_ID]({"fileId": "file_1"}))
    assert result["result_status"] == "REVIEW_REQUIRED"
    assert result["content_truncated"] is True
    assert result["content_chars"] == 20_000


# --- Core runtime conformance ---


def test_registered_tools_execute_under_core_runtime() -> None:
    port = FakeDrivePort(json_responses=[{"files": [file_metadata("file_1")]}])
    runtime = ToolRuntime()
    registered = register_drive_read_tools(
        runtime, port, binding_ref=BINDING_REF, actor_ref=ACTOR_REF
    )
    assert registered == (
        DRIVE_SEARCH_FILES_TOOL_ID,
        DRIVE_LIST_RECENT_FILES_TOOL_ID,
        DRIVE_GET_FILE_METADATA_TOOL_ID,
        DRIVE_READ_FILE_CONTENT_TOOL_ID,
    )
    agent = drive_profile(DRIVE_SEARCH_FILES_TOOL_ID)

    with pytest.raises(ToolRuntimeError) as info:
        run(
            runtime.execute(
                ToolInvocation(DRIVE_SEARCH_FILES_TOOL_ID, {"query": "invoice"}),
                agent,
                drive_auth(),
            )
        )
    assert info.value.code == "tool_auth_scope_missing"
    assert port.calls == []

    port.json_responses.append({"files": [file_metadata("file_1")]})
    result = run(
        runtime.execute(
            ToolInvocation(DRIVE_SEARCH_FILES_TOOL_ID, {"query": "invoice"}),
            agent,
            drive_auth(scopes=(DRIVE_READONLY_AUTH_SCOPE,)),
        )
    )
    output = result.output_copy()
    assert output["operation"] == "files.list.search"
    assert port.calls[-1]["required_scopes"] == (DRIVE_READONLY_SCOPE,)


def test_unknown_drive_tool_is_not_registered() -> None:
    port = FakeDrivePort()
    runtime = ToolRuntime()
    register_drive_read_tools(runtime, port, binding_ref=BINDING_REF, actor_ref=ACTOR_REF)
    with pytest.raises(ToolRuntimeError) as info:
        run(
            runtime.execute(
                ToolInvocation("drive.upload_file", {}),
                drive_profile("drive.upload_file"),
                drive_auth(scopes=(DRIVE_READONLY_AUTH_SCOPE,)),
            )
        )
    assert info.value.code == "tool_not_registered"
    assert port.calls == []


def test_port_failure_is_wrapped_and_never_leaks_refs() -> None:
    class LeakyPort(FakeDrivePort):
        def get_json(self, **kwargs):
            self.calls.append(kwargs)
            raise RuntimeError(
                f"boom bind:SECRET123 actor:XYZ required={kwargs.get('required_scopes')}"
            )

    port = LeakyPort()
    handlers = drive_handlers(port)
    with pytest.raises(DriveContractError) as info:
        run(handlers[DRIVE_GET_FILE_METADATA_TOOL_ID]({"fileId": "file_1"}))
    message = str(info.value)
    assert "SECRET123" not in message
    assert BINDING_REF not in message
    assert ACTOR_REF not in message


def test_module_owns_no_network_or_credential_surface() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "padiem_ai_core"
        / "drive_capability.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("import httpx", "import requests", "import socket", "urllib.request", "webbrowser"):
        assert forbidden not in source
    assert "raw_credentials_present" in source
    assert "oauth_token_present" in source


def test_b54_compatibility_source_is_not_mutated_by_core() -> None:
    snapshot = drive_capability_snapshot()
    assert snapshot["live_provider_calls"] == 0
    assert snapshot["production_activation"] is False
    assert DRIVE_RAW_CREDENTIAL_IN_CORE is False
