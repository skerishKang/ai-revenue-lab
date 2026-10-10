"""Core ToolRuntime web XLSX user confirmation contract."""
from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass

from padiem_ai_core.agent_definition import AgentExecutionBudget, BoundedAgentDefinition
from padiem_ai_core.agent_profile_adapter import (
    ToolRuntimeBinding, TrustedAgentRuntimePolicy, compile_agent_profile,
)
from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect, ToolSpec
from padiem_ai_core.tool_registry import RegisteredTool, ToolRegistrySnapshot
from padiem_ai_core.tool_resource_policy import ToolResourcePolicy
from padiem_ai_core.tool_runtime import ToolAuthorizationContext, ToolRuntime
from app.tool_projection import EngineToolBinding, TrustedToolAuthority

APP_ID = "padiem-web-xlsx-p01"
AGENT_ID = "agent:padiem:web-xlsx-confirm@1"
RUNTIME_TOOL = "workspace.xlsx.confirm_original_read"
CANONICAL_TOOL = "tool:padiem:web-xlsx-confirm@1"
SCOPE = "workspace.xlsx.original.read.intent"
_FIELDS = ("owner_id", "workspace_id", "run_id",
           "selection_ref", "document_id", "source_sha256")


@dataclass(frozen=True, slots=True)
class TrustedWebXlsxSelectionScope:
    owner_id: str
    workspace_id: str
    run_id: str
    selection_ref: str
    document_id: str
    source_sha256: str
    original_immutable: bool
    source_active: bool

    def __post_init__(self):
        if not all(isinstance(getattr(self, k), str) and
                   re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:@+-]{0,127}",
                                getattr(self, k)) for k in _FIELDS[:3]):
            raise ValueError("invalid trusted identity")
        if not re.fullmatch(r"sel_[0-9a-f]{32}", self.selection_ref):
            raise ValueError("invalid selection ref")
        if not re.fullmatch(r"doc_[0-9a-f]{32}", self.document_id):
            raise ValueError("invalid document ref")
        if not re.fullmatch(r"[0-9a-f]{64}", self.source_sha256):
            raise ValueError("invalid source fingerprint")
        if type(self.original_immutable) is not bool or type(self.source_active) is not bool:
            raise ValueError("invalid source flags")


def web_xlsx_p01_arguments(scope: TrustedWebXlsxSelectionScope) -> dict:
    """Build exact invocation arguments from trusted server scope only."""
    if not isinstance(scope, TrustedWebXlsxSelectionScope):
        raise ValueError("trusted selection scope required")
    if not scope.source_active or not scope.original_immutable:
        raise ValueError("selected original must be active and immutable")
    return {
        **{name: getattr(scope, name) for name in _FIELDS},
        "operation": "read_for_workcopy",
        "source_kind": "browser_upload",
        "original_immutable": True,
        "read_content": False,
        "drive_write": False,
        "local_pc_access": False,
    }


def web_xlsx_confirmation_spec() -> ToolSpec:
    short = {"type": "string", "minLength": 1, "maxLength": 128}
    props = {
        "owner_id": short, "workspace_id": short, "run_id": short,
        "selection_ref": {"type": "string", "pattern": "^sel_[0-9a-f]{32}$"},
        "document_id": {"type": "string", "pattern": "^doc_[0-9a-f]{32}$"},
        "source_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "operation": {"type": "string", "enum": ["read_for_workcopy"]},
        "source_kind": {"type": "string", "enum": ["browser_upload"]},
        "original_immutable": {"type": "boolean", "enum": [True]},
        "read_content": {"type": "boolean", "enum": [False]},
        "drive_write": {"type": "boolean", "enum": [False]},
        "local_pc_access": {"type": "boolean", "enum": [False]},
    }
    return ToolSpec(
        id=RUNTIME_TOOL, title="Confirm web XLSX original selection",
        description="Explicit user confirmation before server-side read",
        owner="core", side_effect=ToolSideEffect.NONE,
        approval_policy=ApprovalPolicy.USER_CONFIRMATION,
        auth_scope=(SCOPE,),
        input_schema={"type": "object", "additionalProperties": False,
                      "properties": props, "required": list(props)},
        output_contract={"type": "object", "fields": [
            "p01_intent_confirmed", "source_sha256", "read_executed",
            "workcopy_created", "drive_write",
        ]},
        timeout_seconds=5.0, user_visible=False,
    )

def build_web_xlsx_p01_tool_binding(
    selection_resolver: Callable[[str], TrustedWebXlsxSelectionScope | None],
) -> EngineToolBinding:
    if not callable(selection_resolver):
        raise ValueError("trusted selection source is required")

    async def confirm_only(arguments: dict) -> dict:
        selected = selection_resolver(arguments["selection_ref"])
        if inspect.isawaitable(selected):
            selected = await selected
        if not isinstance(selected, TrustedWebXlsxSelectionScope):
            raise ValueError("selected source unavailable")
        if any(getattr(selected, key) != arguments[key] for key in _FIELDS):
            raise ValueError("selected source does not match")
        if not selected.original_immutable or not selected.source_active:
            raise ValueError("selected source expired")
        return {
            "p01_intent_confirmed": True,
            "source_sha256": arguments["source_sha256"],
            "read_executed": False,
            "workcopy_created": False,
            "drive_write": False,
            "local_pc_access": False,
        }

    spec = web_xlsx_confirmation_spec()
    runtime = ToolRuntime()
    runtime.register(spec, confirm_only)
    registry = ToolRegistrySnapshot.from_entries((
        RegisteredTool.from_spec(canonical_tool_id=CANONICAL_TOOL, runtime_spec=spec),
    ))
    definition = BoundedAgentDefinition(
        agent_id=AGENT_ID, publisher_id="padiem",
        title="Web XLSX selection confirmation",
        description="Approve the original XLSX identity",
        instruction="Confirm this original's identity without reading file bytes.",
        output_contract_ref="output:text@1", allowed_tool_ids=(CANONICAL_TOOL,),
        execution_budget=AgentExecutionBudget(),
    )
    policy = TrustedAgentRuntimePolicy(
        context_policy_ref="context:default", model_policy_ref="model:auto",
        output_contract_ref="output:text@1",
        task_type="general", optimize_for="balanced", max_tokens=128,
        max_steps_cap=2, context_policy={}, model_policy={}, output_contract={},
        tool_bindings=(ToolRuntimeBinding(
            canonical_tool_id=CANONICAL_TOOL, runtime_tool_id=RUNTIME_TOOL,
        ),),
    )
    compiled = compile_agent_profile(definition, policy)
    auth = ToolAuthorizationContext(
        app_id=APP_ID, agent_id=compiled.runtime_profile.id,
        granted_auth_scopes=(SCOPE,),
    )
    return EngineToolBinding(
        app_id=APP_ID, tool_runtime=runtime, registry=registry,
        authorities={AGENT_ID: TrustedToolAuthority(
            canonical_agent_id=AGENT_ID, definition=definition,
            compiled=compiled, authorization=auth,
        )},
        authorization_provider=None, resource_policy=ToolResourcePolicy(),
    )


def with_web_xlsx_p01_tool_binding(
    base_resolver: Callable[[str], EngineToolBinding | None] | None,
    *,
    enabled: bool = False,
    selection_resolver: Callable[[str], TrustedWebXlsxSelectionScope | None] | None = None,
) -> Callable[[str], EngineToolBinding | None] | None:
    # No authenticated host resolver: no runtime feature registration.
    if enabled is not True or not callable(selection_resolver):
        return base_resolver
    binding = build_web_xlsx_p01_tool_binding(selection_resolver)

    def resolve(app_id: str) -> EngineToolBinding | None:
        if app_id == APP_ID:
            return binding
        return base_resolver(app_id) if base_resolver is not None else None

    subject = getattr(base_resolver, "subject_for_app", None)
    if callable(subject):
        setattr(resolve, "subject_for_app", subject)
    return resolve


PRODUCTION_WEB_XLSX_P01_COMPOSED = False
CONFIRMATION_NEVER_READS_OR_WRITES_FILE = True
