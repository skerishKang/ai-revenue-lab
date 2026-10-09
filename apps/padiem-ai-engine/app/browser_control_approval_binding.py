"""#3782: CLOSED, uncomposed Core browser.control approval-only tool binding.

NOT an action provider. This source-only binding proves canonical Core Tool
Runtime USER_CONFIRMATION can pause one browser.control invocation with the
same digest the Windows KAgent validates. Even if an unrelated authority were
to set user_confirmed_tools, the handler ALWAYS refuses: actual browser
execution belongs exclusively to approved Windows Broker/Resident/Desktop.

No Worker resolver includes this binding. No env flag, route, or model exposure.
A future authenticated product composition must supply immutable owner/subject,
admission and an identity-bound D1 issue adapter before activation.
"""
from __future__ import annotations

from padiem_ai_core import (
    AgentExecutionBudget,
    ApprovalPolicy,
    BoundedAgentDefinition,
    ToolAuthorizationContext,
    ToolRegistrySnapshot,
    ToolResourcePolicy,
    ToolRuntime,
    ToolRuntimeBinding,
    ToolSideEffect,
    ToolSpec,
    TrustedAgentRuntimePolicy,
    compile_agent_profile,
)
from padiem_ai_core.tool_registry import RegisteredTool

from app.tool_projection import EngineToolBinding, TrustedToolAuthority

BROWSER_P01_APP_ID = "b54-engine-browser-approval"
BROWSER_P01_AGENT_ID = "agent:padiem:browser_approval@1"
BROWSER_P01_CANONICAL_TOOL_ID = "tool:padiem:browser_control@1"
BROWSER_P01_RUNTIME_TOOL_ID = "browser.control"
BROWSER_P01_AUTH_SCOPE = "browser.control"

# Deliberate fail closed. Future product composition is NOT connected.
BROWSER_CONTROL_TOOL_BINDING_WIRED = False
BROWSER_CONTROL_BROWSER_ACTION_PROVIDER_WIRED = False

_REF = {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$", "minLength": 1, "maxLength": 256}

async def _inert_action_handler(arguments: dict) -> dict:
    """NOT a browser executor. No Input.*, network, or OS side effects."""
    raise RuntimeError("browser.control never executes via Engine ToolRuntime")


def browser_control_approval_tool_spec() -> ToolSpec:
    """Match exactly BrowserControlLeaseRequest.tool_invocation() arguments."""
    return ToolSpec(
        id=BROWSER_P01_RUNTIME_TOOL_ID,
        title="Browser control requires verified per-command approval",
        description="Approval-only tool; execution is unavailable in Engine.",
        owner="core",
        side_effect=ToolSideEffect.WRITE,
        approval_policy=ApprovalPolicy.USER_CONFIRMATION,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "browser_session_ref": _REF,
                "run_ref": _REF,
                "workspace_ref": _REF,
                "owner_ref": _REF,
                "device_id": _REF,
                "origin_scope": {
                    "type": "string", "minLength": 9, "maxLength": 255,
                    "pattern": r"^https://[a-z0-9.-]+(?::[0-9]{1,5})?$",
                },
                "allowed_action_classes": {
                    "type": "array", "minItems": 1, "maxItems": 5,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "enum": ["scroll", "focus", "click", "type", "select"],
                    },
                },
                "ttl_seconds": {"type": "integer", "minimum": 1, "maximum": 900},
                "max_actions": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": [
                "browser_session_ref", "run_ref", "workspace_ref", "owner_ref",
                "device_id", "origin_scope", "allowed_action_classes",
                "ttl_seconds", "max_actions",
            ],
        },
        auth_scope=(BROWSER_P01_AUTH_SCOPE,),
        timeout_seconds=1.0,
        user_visible=False,
    )


def build_inert_browser_control_approval_binding() -> EngineToolBinding:
    """Build solely canonical Core objects; never install in Worker by default."""
    spec = browser_control_approval_tool_spec()
    runtime = ToolRuntime()
    runtime.register(spec, _inert_action_handler)
    registry = ToolRegistrySnapshot.from_entries((
        RegisteredTool.from_spec(
            canonical_tool_id=BROWSER_P01_CANONICAL_TOOL_ID, runtime_spec=spec,
        ),
    ))
    definition = BoundedAgentDefinition(
        agent_id=BROWSER_P01_AGENT_ID,
        publisher_id="padiem",
        title="Browser P01 approval",
        description="Per-command browser approval-only authority",
        instruction="Require user confirmation. Never execute browser actions.",
        output_contract_ref="output:text@1",
        allowed_tool_ids=(BROWSER_P01_CANONICAL_TOOL_ID,),
        execution_budget=AgentExecutionBudget(),
    )
    policy = TrustedAgentRuntimePolicy(
        context_policy_ref="context:default",
        model_policy_ref="model:auto",
        output_contract_ref="output:text@1",
        task_type="general",
        optimize_for="balanced",
        max_tokens=128,
        max_steps_cap=2,
        context_policy={},
        model_policy={},
        output_contract={},
        tool_bindings=(ToolRuntimeBinding(
            canonical_tool_id=BROWSER_P01_CANONICAL_TOOL_ID,
            runtime_tool_id=BROWSER_P01_RUNTIME_TOOL_ID,
        ),),
    )
    compiled = compile_agent_profile(definition, policy)
    authorization = ToolAuthorizationContext(
        app_id=BROWSER_P01_APP_ID,
        agent_id=compiled.runtime_profile.id,
        granted_auth_scopes=(BROWSER_P01_AUTH_SCOPE,),
    )
    authority = TrustedToolAuthority(
        canonical_agent_id=BROWSER_P01_AGENT_ID,
        definition=definition,
        compiled=compiled,
        authorization=authorization,
    )
    return EngineToolBinding(
        app_id=BROWSER_P01_APP_ID,
        tool_runtime=runtime,
        registry=registry,
        authorities={BROWSER_P01_AGENT_ID: authority},
        authorization_provider=None,
        resource_policy=ToolResourcePolicy(),
    )
