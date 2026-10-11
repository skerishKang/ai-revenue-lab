"""#3933 independent Core ToolRuntime P01 WRITE-intent tool.

This registers neither a B62 Worker feature flag nor a Production route.
Its handler only confirms authority; B62 performs a separate copy-on-write
after independently checking Engine completion and exact D1 receipt scope.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from padiem_ai_core.agent_definition import AgentExecutionBudget, BoundedAgentDefinition
from padiem_ai_core.agent_profile_adapter import (
    ToolRuntimeBinding, TrustedAgentRuntimePolicy, compile_agent_profile,
)
from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect, ToolSpec
from padiem_ai_core.tool_registry import RegisteredTool, ToolRegistrySnapshot
from padiem_ai_core.tool_resource_policy import ToolResourcePolicy
from padiem_ai_core.tool_runtime import ToolAuthorizationContext, ToolRuntime

from .tool_projection import EngineToolBinding, TrustedToolAuthority

APP_ID = "padiem-web-xlsx-write-p01"
AGENT_ID = "agent:padiem:web-xlsx-quote-write@1"
RUNTIME_TOOL = "workspace.xlsx.quote.revise_workcopy"
CANONICAL_TOOL = "tool:padiem:web-xlsx-quote-write@1"
SCOPE = "workspace.xlsx.quote.write.confirmed"
OPERATION = "xlsx.quote.revise_workcopy"
_FIELDS = (
    "owner_id", "workspace_id", "run_id", "selection_ref",
    "source_document_id", "source_sha256", "workcopy_document_id",
    "workcopy_sha256", "edit_sha256", "school_name", "supply_amount",
)
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}")
_DOC = re.compile(r"doc_[0-9a-f]{32}")
_SEL = re.compile(r"sel_[0-9a-f]{32}")
_SHA = re.compile(r"[0-9a-f]{64}")


def quote_edit_sha256(school_name: str, supply_amount: int) -> str:
    """Must match B62's immutable quote edit canonical payload."""
    if (type(school_name) is not str or not 1 <= len(school_name) <= 120
            or school_name != school_name.strip()
            or school_name[0] in "=+@-"
            or any(ord(c) < 32 or ord(c) == 127 for c in school_name)
            or type(supply_amount) is not int
            or not 1 <= supply_amount <= 999999999999
            or supply_amount % 10):
        raise ValueError("invalid quote edit values")
    encoded = json.dumps({
        "school_name": school_name, "supply_amount": supply_amount,
        "output_formats": ["xlsx"], "overwrite_original": False,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class TrustedQuoteWriteScope:
    owner_id: str
    workspace_id: str
    run_id: str
    selection_ref: str
    source_document_id: str
    source_sha256: str
    workcopy_document_id: str
    workcopy_sha256: str
    edit_sha256: str
    school_name: str
    supply_amount: int
    write_reserved: bool
    source_immutable: bool
    workcopy_private: bool
    run_active: bool

    def __post_init__(self):
        checks = (
            *(type(getattr(self, k)) is str and _ID.fullmatch(getattr(self, k))
              for k in ("owner_id", "workspace_id", "run_id")),
            type(self.selection_ref) is str and _SEL.fullmatch(self.selection_ref),
            *(type(getattr(self, k)) is str and _DOC.fullmatch(getattr(self, k))
              for k in ("source_document_id", "workcopy_document_id")),
            *(type(getattr(self, k)) is str and _SHA.fullmatch(getattr(self, k))
              for k in ("source_sha256", "workcopy_sha256", "edit_sha256")),
            self.source_sha256 == self.workcopy_sha256,
            all(getattr(self, k) is True for k in (
                "write_reserved", "source_immutable", "workcopy_private", "run_active")),
        )
        if not all(checks):
            raise ValueError("invalid trusted write scope")
        if quote_edit_sha256(self.school_name, self.supply_amount) != self.edit_sha256:
            raise ValueError("write digest does not match exact edit")


def quote_write_arguments(scope: TrustedQuoteWriteScope) -> dict:
    if not isinstance(scope, TrustedQuoteWriteScope):
        raise ValueError("trusted D1 write scope required")
    return {
        **{k: getattr(scope, k) for k in _FIELDS},
        "operation": OPERATION,
        "source_kind": "browser_upload",
        "original_immutable": True,
        "overwrite_original": False,
        "write_intent_only": True,
        "drive_write": False,
        "local_pc_access": False,
        "pdf_exported": False,
    }


def quote_write_spec() -> ToolSpec:
    props = {
        **{k: {"type": "string", "minLength": 1, "maxLength": 128}
           for k in ("owner_id", "workspace_id", "run_id", "school_name")},
        **{k: {"type": "string", "pattern": "^doc_[0-9a-f]{32}$"}
           for k in ("source_document_id", "workcopy_document_id")},
        "selection_ref": {"type": "string", "pattern": "^sel_[0-9a-f]{32}$"},
        **{k: {"type": "string", "pattern": "^[0-9a-f]{64}$"}
           for k in ("source_sha256", "workcopy_sha256", "edit_sha256")},
        "supply_amount": {"type": "integer", "minimum": 1, "maximum": 999999999999},
        "operation": {"type": "string", "enum": [OPERATION]},
        "source_kind": {"type": "string", "enum": ["browser_upload"]},
        **{k: {"type": "boolean", "enum": [True]}
           for k in ("original_immutable", "write_intent_only")},
        **{k: {"type": "boolean", "enum": [False]}
           for k in ("overwrite_original", "drive_write", "local_pc_access", "pdf_exported")},
    }
    return ToolSpec(
        id=RUNTIME_TOOL, title="Confirm exact Hark XLSX quote revision",
        description="Independent user confirmation of one immutable edit plan",
        owner="core", side_effect=ToolSideEffect.WRITE,
        approval_policy=ApprovalPolicy.USER_CONFIRMATION,
        auth_scope=(SCOPE,),
        input_schema={"type": "object", "additionalProperties": False,
                      "properties": props, "required": list(props)},
        output_contract={"type": "object", "fields": [
            "ok", "core_tool_completed", "operation", "owner_id",
            "workspace_id", "run_id", "source_document_id",
            "source_sha256", "workcopy_document_id", "workcopy_sha256",
            "edit_sha256", "pdf_exported",
        ]},
        timeout_seconds=5.0, user_visible=False,
    )


def build_web_quote_write_tool_binding(
    scope_resolver: Callable[[str], TrustedQuoteWriteScope | None],
) -> EngineToolBinding:
    if not callable(scope_resolver):
        raise ValueError("independent D1 write receipt resolver required")

    async def verify_exact(arguments: dict) -> bool:
        if not isinstance(arguments, Mapping):
            return False
        ref = arguments.get("selection_ref")
        if type(ref) is not str or not _SEL.fullmatch(ref):
            return False
        try:
            expected = scope_resolver(ref)
            if inspect.isawaitable(expected):
                expected = await expected
            return isinstance(expected, TrustedQuoteWriteScope) and dict(arguments) == quote_write_arguments(expected)
        except (TypeError, ValueError, KeyError):
            return False

    async def confirm_intent_only(arguments: dict) -> dict:
        # Check after user approval again. No R2 read, overwrite, PDF, or
        # mutation. The trusted B62 host carries out exact separately gated IO.
        if not await verify_exact(arguments):
            raise ValueError("original owner or reserved edit changed")
        return {
            "ok": True, "core_tool_completed": True,
            "operation": OPERATION,
            **{k: arguments[k] for k in (
                "owner_id", "workspace_id", "run_id", "source_document_id",
                "source_sha256", "workcopy_document_id", "workcopy_sha256",
                "edit_sha256",
            )}, "pdf_exported": False,
        }

    spec = quote_write_spec()
    runtime = ToolRuntime()
    runtime.register(spec, confirm_intent_only)
    registry = ToolRegistrySnapshot.from_entries((
        RegisteredTool.from_spec(canonical_tool_id=CANONICAL_TOOL, runtime_spec=spec),
    ))
    definition = BoundedAgentDefinition(
        agent_id=AGENT_ID, publisher_id="padiem",
        title="Hark exact XLSX quote write approval",
        description="Confirm owner approved exactly one quote edit digest",
        instruction="Confirm only, do not read or change workbook content.",
        output_contract_ref="output:text@1", allowed_tool_ids=(CANONICAL_TOOL,),
        execution_budget=AgentExecutionBudget(),
    )
    policy = TrustedAgentRuntimePolicy(
        context_policy_ref="context:default", model_policy_ref="model:auto",
        output_contract_ref="output:text@1", task_type="general",
        optimize_for="balanced", max_tokens=128, max_steps_cap=2,
        context_policy={}, model_policy={}, output_contract={},
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
        invocation_preflight=verify_exact,
    )


def with_web_quote_write_tool_binding(
    base_resolver: Callable[[str], EngineToolBinding | None] | None,
    *, enabled: bool = False,
    scope_resolver: Callable[[str], TrustedQuoteWriteScope | None] | None = None,
):
    # Explicit private trusted composition only; Production remains OFF.
    if enabled is not True or not callable(scope_resolver):
        return base_resolver
    binding = build_web_quote_write_tool_binding(scope_resolver)

    def resolve(app_id: str):
        if app_id == APP_ID:
            return binding
        return base_resolver(app_id) if base_resolver is not None else None

    subject = getattr(base_resolver, "subject_for_app", None)
    if callable(subject):
        setattr(resolve, "subject_for_app", subject)
    return resolve


PRODUCTION_HARK_WEB_QUOTE_WRITE_COMPOSED = False
WRITE_TOOL_NEVER_MUTATES_FILE = True
