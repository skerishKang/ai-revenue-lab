"""#3580 real Core/Engine P01 confirmation tools for selected-root Office.

Only the existing Engine first-party verifier can resolve the ToolRuntime
USER_CONFIRMATION pause. A confirmed tool emits no file bytes, authority grants,
Resident command or cloud write. Production is disabled by default.
"""
from __future__ import annotations

from collections.abc import Callable

from padiem_ai_core import (
    AgentExecutionBudget, ApprovalPolicy, BoundedAgentDefinition,
    ToolAuthorizationContext, ToolRegistrySnapshot, ToolResourcePolicy,
    ToolRuntime, ToolRuntimeBinding, ToolSideEffect, ToolSpec,
    TrustedAgentRuntimePolicy, compile_agent_profile,
)
from padiem_ai_core.tool_registry import RegisteredTool
from app.tool_projection import EngineToolBinding, TrustedToolAuthority

ENABLE_ENV = "PADIEM_ENGINE_HARK_OFFICE_P01_ENABLED"
APP_ID = "hark-office-local-p01"
AGENT_ID = "agent:padiem:hark-office-p01@1"
LIST_TOOL_ID = "local.filesystem.list.quote-candidates"
READ_TOOL_ID = "local.filesystem.read"
LIST_CANONICAL_ID = "tool:padiem:hark-office-list@1"
READ_CANONICAL_ID = "tool:padiem:hark-office-read@1"
FILE_SCOPE = "filesystem.read"

_REF = {"type": "string", "minLength": 1, "maxLength": 128}
_DIGEST = {"type": "string", "pattern": "^[a-f0-9]{64}$"}


def _schema(*, listing: bool) -> dict:
    common = {
        "action_id": _REF, "run_id": _REF, "device_id": _REF,
        "root_ref": _REF, "request_fingerprint": _DIGEST,
    }
    if listing:
        fields = {
            **common,
            "max_candidates": {"type": "integer", "minimum": 1, "maximum": 40},
            "metadata_only": {"type": "boolean", "enum": [True]},
            "recursive": {"type": "boolean", "enum": [False]},
            "read_content": {"type": "boolean", "enum": [False]},
            "file_extensions": {"type": "array", "items": {
                "type": "string", "enum": ["xls", "xlsx"],
            }, "minItems": 2, "maxItems": 2, "uniqueItems": True},
            "whole_pc_scan": {"type": "boolean", "enum": [False]},
            "name_contains": {"type": "string", "maxLength": 40,
                              "pattern": r"^[^/\\:*?\"<>|\x00-\x1f]{0,40}$"},
        }
    else:
        fields = {
            **common,
            "operation": {"type": "string", "enum": ["read"]},
            "path_relative": {"type": "string", "minLength": 5, "maxLength": 160,
                              "pattern": r"^[^<>:/\\|?*\x00-\x1f]{1,155}\.[xX][lL][sS][xX]?$"},
            "requested_at": {"type": "string", "minLength": 19, "maxLength": 64},
            "content_bytes": {"type": "integer", "enum": [0]},
            "content_sha256": {"enum": [None]},
            "directory_enumeration": {"type": "boolean", "enum": [False]},
            "recursive_delete": {"type": "boolean", "enum": [False]},
            "admin_elevation": {"type": "boolean", "enum": [False]},
        }
    return {"type": "object", "additionalProperties": False,
            "properties": fields, "required": list(fields)}


async def _acknowledge_only(arguments: dict) -> dict:
    return {
        "intent_confirmed": True,
        "request_fingerprint": arguments["request_fingerprint"],
        "file_read_executed": False, "local_file_content": False,
        "drive_write": False, "resident_dispatched": False,
    }


def _spec(*, listing: bool) -> ToolSpec:
    return ToolSpec(
        id=LIST_TOOL_ID if listing else READ_TOOL_ID,
        title="Hark Office selected-root candidates" if listing
              else "Hark Office selected local file read",
        description="User confirmation of canonical Office intent only, not file access",
        owner="core", side_effect=ToolSideEffect.NONE,
        approval_policy=ApprovalPolicy.USER_CONFIRMATION,
        auth_scope=(FILE_SCOPE,), input_schema=_schema(listing=listing),
        output_contract={"type": "object", "fields": [
            "intent_confirmed", "request_fingerprint",
            "file_read_executed", "local_file_content",
        ]},
        timeout_seconds=5.0, user_visible=False,
    )


def build_hark_office_p01_tool_binding() -> EngineToolBinding:
    listing = _spec(listing=True)
    read = _spec(listing=False)
    runtime = ToolRuntime()
    runtime.register(listing, _acknowledge_only)
    runtime.register(read, _acknowledge_only)
    registry = ToolRegistrySnapshot.from_entries((
        RegisteredTool.from_spec(canonical_tool_id=LIST_CANONICAL_ID,
                                 runtime_spec=listing),
        RegisteredTool.from_spec(canonical_tool_id=READ_CANONICAL_ID,
                                 runtime_spec=read),
    ))
    definition = BoundedAgentDefinition(
        agent_id=AGENT_ID, publisher_id="padiem",
        title="Hark Office selected-file confirmation",
        description="Approve only a server-correlated selected-root LIST or READ",
        instruction="Confirm the exact registered Office intent; never open local bytes",
        output_contract_ref="output:text@1",
        allowed_tool_ids=(LIST_CANONICAL_ID, READ_CANONICAL_ID),
        execution_budget=AgentExecutionBudget(),
    )
    policy = TrustedAgentRuntimePolicy(
        context_policy_ref="context:default",
        model_policy_ref="model:auto",
        output_contract_ref="output:text@1",
        task_type="general", optimize_for="balanced",
        max_tokens=128, max_steps_cap=2,
        context_policy={}, model_policy={}, output_contract={},
        tool_bindings=(
            ToolRuntimeBinding(canonical_tool_id=LIST_CANONICAL_ID,
                               runtime_tool_id=LIST_TOOL_ID),
            ToolRuntimeBinding(canonical_tool_id=READ_CANONICAL_ID,
                               runtime_tool_id=READ_TOOL_ID),
        ),
    )
    compiled = compile_agent_profile(definition, policy)
    authority = ToolAuthorizationContext(
        app_id=APP_ID, agent_id=compiled.runtime_profile.id,
        granted_auth_scopes=(FILE_SCOPE,),
    )
    return EngineToolBinding(
        app_id=APP_ID, tool_runtime=runtime, registry=registry,
        authorities={AGENT_ID: TrustedToolAuthority(
            canonical_agent_id=AGENT_ID, definition=definition,
            compiled=compiled, authorization=authority,
        )},
        authorization_provider=None, resource_policy=ToolResourcePolicy(),
    )


def with_hark_office_p01_tool_binding(
    env: object,
    base_resolver: Callable[[str], EngineToolBinding | None] | None,
) -> Callable[[str], EngineToolBinding | None] | None:
    if getattr(env, ENABLE_ENV, None) != "1":
        return base_resolver
    registered = build_hark_office_p01_tool_binding()

    def resolve(app_id: str) -> EngineToolBinding | None:
        if app_id == APP_ID:
            return registered
        return base_resolver(app_id) if base_resolver is not None else None

    subject_for_app = getattr(base_resolver, "subject_for_app", None)
    if callable(subject_for_app):
        setattr(resolve, "subject_for_app", subject_for_app)
    return resolve


PRODUCTION_HARK_OFFICE_P01_ENABLED = False
OFFICE_CONFIRMATION_PRODUCES_LOCAL_FILE_GRANT = False
