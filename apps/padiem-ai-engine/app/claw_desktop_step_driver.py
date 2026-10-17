"""PADIEM Claw desktop structured-step adapter.

This driver has no native provider tool calls. A trusted Engine model selector
receives real JPEG bytes from an owner-scoped receipt loader and chooses the
next validated Core ToolInvocation. It never interprets a fixed action plan.
"""
from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, Mapping

from padiem_ai_core.agent_runtime import AgentStepContext, AgentStepDecision
from padiem_ai_core.tool_runtime import ToolInvocation


class DesktopStepContractError(ValueError):
    pass


class StructuredDesktopStepDriver:
    """Core AgentStepDriver backed by a trusted structured model response."""

    def __init__(
        self,
        *,
        select_step: Callable[..., Awaitable[Mapping[str, Any]]],
        read_capture: Callable[..., Awaitable[bytes | None]],
        allowed_tool_ids: frozenset[str],
    ) -> None:
        if not callable(select_step) or not callable(read_capture):
            raise DesktopStepContractError("step selector and capture reader are required")
        if not allowed_tool_ids:
            raise DesktopStepContractError("desktop tool allowlist is required")
        self._select_step = select_step
        self._read_capture = read_capture
        self._allowed_tool_ids = allowed_tool_ids

    async def next_step(self, context: AgentStepContext, compiled_profile: Any) -> AgentStepDecision:
        observations = []
        for index, result in enumerate(context.tool_results):
            output = result.output_copy()
            if not isinstance(output, dict):
                raise DesktopStepContractError("desktop result must be an object")
            receipt = output.get("capture_receipt")
            image = None
            if receipt is not None:
                if not isinstance(receipt, str) or not receipt:
                    raise DesktopStepContractError("invalid capture receipt")
                if index == len(context.tool_results) - 1:
                    # The latest capture is authoritative for the next decision.
                    # Earlier snapshots stay as audit metadata, not R2 re-reads.
                    image = await self._read_capture(
                        context=context, result=result, receipt=receipt
                    )
                    if not isinstance(image, bytes) or not image.startswith(b"\xff\xd8\xff"):
                        raise DesktopStepContractError("JPEG observation unavailable")
            observations.append({
                "tool_id": result.tool_id,
                "event": result.event.to_public_dict(),
                "output": {k: v for k, v in output.items() if k != "capture_receipt"},
                "image_jpeg": image,
            })
        decision = await self._select_step(
            context=context, compiled_profile=compiled_profile,
            observations=tuple(observations),
        )
        if not isinstance(decision, Mapping):
            raise DesktopStepContractError("model step must be an object")
        if decision.get("action") == "complete":
            answer = decision.get("answer")
            if not isinstance(answer, str):
                raise DesktopStepContractError("model completion requires text")
            return AgentStepDecision.complete(answer)
        if decision.get("action") != "tool":
            raise DesktopStepContractError("model step action is invalid")
        tool_id = decision.get("tool_id")
        arguments = decision.get("arguments")
        if tool_id not in self._allowed_tool_ids or not isinstance(arguments, Mapping):
            raise DesktopStepContractError("model tool selection is not authorized")
        return AgentStepDecision.use_tool(
            ToolInvocation(tool_id=tool_id, arguments=dict(arguments))
        )


# Existing Core ToolRuntime binding; no second tool execution framework.
from contextvars import ContextVar
from padiem_ai_core.agent_definition import AgentExecutionBudget, BoundedAgentDefinition
from padiem_ai_core.agent_profile_adapter import (
    ToolRuntimeBinding, TrustedAgentRuntimePolicy, compile_agent_profile,
)
from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect, ToolSpec
from padiem_ai_core.tool_runtime import (
    ToolAuthorizationContext, ToolRuntime, ToolHandlerError,
)
from padiem_ai_core.tool_registry import RegisteredTool, ToolRegistrySnapshot
from padiem_ai_core.tool_resource_policy import ToolResourcePolicy
from app.tool_projection import EngineToolBinding, TrustedToolAuthority
import hashlib
import hmac
import json
import time

CLAW_APP_ID = "b54-padiem-claw"
DESKTOP_AGENT_ID = "agent:padiem:claw-desktop@1"
DESKTOP_CANONICAL_CAPTURE = "tool:padiem:claw-desktop-capture@1"
DESKTOP_CAPTURE_ID = "claw.desktop.capture"
DESKTOP_CAPTURE_SCOPE = "claw.desktop.capture"
_ENGINE_DESKTOP_OWNER = ContextVar("claw_engine_desktop_owner", default=None)


async def _signed_desktop_capture(*, service, request_factory, secret, subject_id, run_id, device_id, desktop_op="desktop:capture"):
    if not isinstance(secret, str) or len(secret) < 32:
        raise ToolHandlerError("desktop_secret_missing", "Engine desktop authorization unavailable")
    body = json.dumps({
        "subject_id": subject_id, "run_id": run_id,
        "device_id": device_id, "desktop_op": desktop_op,
    }, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    proof = hmac.new(
        secret.encode("utf-8"), timestamp.encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    request = request_factory(
        "https://padiem-chat.internal/internal/claw/engine-desktop",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Claw-Engine-Time": timestamp,
            "X-Claw-Engine-Proof": proof,
        },
        body=body.decode("utf-8"),
    )
    try:
        response = await service.fetch(request.js_object)
        status = int(response.status)
        raw = await response.text()
        data = json.loads(raw)
    except Exception as exc:
        raise ToolHandlerError(
            "desktop_transport_unavailable",
            "Authenticated Chat desktop transport unavailable; no automatic replay",
        ) from exc
    if status != 200 or not isinstance(data, dict) or data.get("ok") is not True:
        raise ToolHandlerError(
            "desktop_chat_denied",
            "Chat desktop authority denied or failed; no automatic replay",
        )
    dispatch = data.get("dispatch")
    if (not isinstance(dispatch, dict)
        or dispatch.get("run_id") != run_id
        or dispatch.get("kind") != "desktop"
        or not isinstance(dispatch.get("dispatch_id"), str)):
        raise ToolHandlerError(
            "desktop_dispatch_mismatch",
            "Chat desktop dispatch correlation invalid; no automatic replay",
        )
    # Durable dispatch ack is NOT execution confirmation. Await the exact
    # owner-scoped first result without re-sending the PC operation.
    import asyncio
    dispatch_id = dispatch["dispatch_id"]
    while True:
        await asyncio.sleep(2)
        status_payload = json.dumps({
            "subject_id": subject_id, "run_id": run_id,
            "dispatch_id": dispatch_id, "mode": "status",
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")
        status_time = str(int(time.time()))
        status_proof = hmac.new(
            secret.encode("utf-8"),
            status_time.encode("ascii") + b"." + status_payload,
            hashlib.sha256,
        ).hexdigest()
        status_request = request_factory(
            "https://padiem-chat.internal/internal/claw/engine-desktop",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Claw-Engine-Time": status_time,
                "X-Claw-Engine-Proof": status_proof,
            },
            body=status_payload.decode("utf-8"),
        )
        try:
            status_response = await service.fetch(status_request.js_object)
            status_code = int(status_response.status)
            status_data = json.loads(await status_response.text())
        except Exception as exc:
            raise ToolHandlerError(
                "desktop_result_unavailable",
                "Desktop execution may have occurred; result unavailable, do not replay",
            ) from exc
        if (status_code != 200 or not isinstance(status_data, dict)
            or status_data.get("ok") is not True):
            raise ToolHandlerError(
                "desktop_result_unavailable",
                "Desktop result authority failed; do not replay the PC action",
            )
        observed = status_data.get("dispatch")
        if (not isinstance(observed, dict)
            or observed.get("dispatch_id") != dispatch_id
            or observed.get("run_id") != run_id
            or observed.get("kind") != "desktop"):
            raise ToolHandlerError(
                "desktop_result_mismatch",
                "Desktop result correlation failed; do not replay the PC action",
            )
        state = observed.get("state")
        if state == "done":
            digest = observed.get("result_sha256")
            if not isinstance(digest, str) or len(digest) != 64:
                raise ToolHandlerError(
                    "desktop_result_missing", "Desktop output fingerprint not verified",
                )
            return {
                "dispatch_id": dispatch_id, "run_id": run_id, "state": state,
                "capture_receipt": dispatch_id if desktop_op == "desktop:capture" else None,
                "result_sha256": digest, "execution_confirmed": True,
            }
        if state == "failed":
            raise ToolHandlerError(
                "desktop_execution_failed", "Desktop executor reported a failed capture",
            )
        if state not in ("pending", "received", "store_failed"):
            raise ToolHandlerError(
                "desktop_result_unknown",
                "Desktop result state is unknown; do not replay the PC action",
            )


def build_claw_desktop_tool_binding(*, service, request_factory, secret):
    """Bind capture only to an admitted Claw run and Chat-verified device owner."""
    spec = ToolSpec(
        id=DESKTOP_CAPTURE_ID, title="Observe owned desktop",
        description="Capture current screen of the verified user's pinned PC",
        owner="core", side_effect=ToolSideEffect.READ,
        approval_policy=ApprovalPolicy.NOT_REQUIRED,
        auth_scope=(DESKTOP_CAPTURE_SCOPE,),
        input_schema={"type": "object", "properties": {
            "device_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "use_pinned_device": {"type": "boolean", "enum": [True]},
        }, "additionalProperties": False},
        output_contract={"type": "object"}, timeout_seconds=300.0,
    )
    runtime = ToolRuntime()

    async def capture(arguments):
        owner = _ENGINE_DESKTOP_OWNER.get()
        if (not isinstance(owner, tuple) or len(owner) != 2
            or not all(isinstance(v, str) and v for v in owner)):
            raise ToolHandlerError(
                "desktop_admission_required",
                "Desktop requires a verified Claw run admission",
            )
        return await _signed_desktop_capture(
            service=service, request_factory=request_factory, secret=secret,
            subject_id=owner[0], run_id=owner[1],
            device_id=arguments.get("device_id"),
        )

    runtime.register(spec, capture)
    # All PC inputs pass through the same signed Chat owner/run authorization and
    # Oracle executor grammar. Never replay a dispatch on uncertain outcome.
    input_specs = {}
    for name, schema in (
        ("click", {"x": {"type": "integer", "minimum": 0, "maximum": 65535},
                   "y": {"type": "integer", "minimum": 0, "maximum": 65535}}),
        ("type", {"text": {"type": "string", "minLength": 1, "maxLength": 4096}}),
        ("keys", {"combo": {"type": "string", "enum": [
            "enter", "esc", "tab", "backspace", "delete",
            "ctrl+s", "ctrl+c", "ctrl+v", "ctrl+a", "alt+f4",
            "win+r", "win",
        ]}}),
    ):
        required = ["x", "y"] if name == "click" else ["text" if name == "type" else "combo"]
        input_specs[name] = ToolSpec(
            id="claw.desktop." + name, title="Owner PC " + name,
            description="Run one owner-authorized desktop " + name + " operation",
            owner="core", side_effect=ToolSideEffect.WRITE,
            approval_policy=ApprovalPolicy.EXTERNAL_AUTHORIZATION,
            auth_scope=(DESKTOP_CAPTURE_SCOPE,),
            input_schema={"type": "object", "properties": schema,
                          "required": required, "additionalProperties": False},
            output_contract={"type": "object"}, timeout_seconds=300.0,
        )
    for name, input_spec in input_specs.items():
        async def perform(arguments, _name=name):
            owner = _ENGINE_DESKTOP_OWNER.get()
            if (not isinstance(owner, tuple) or len(owner) != 2
                or not all(isinstance(v, str) and v for v in owner)):
                raise ToolHandlerError("desktop_admission_required", "Verified run required")
            if _name == "click":
                op = f"desktop:click\n{arguments['x']},{arguments['y']}"
            elif _name == "type":
                op = "desktop:type\n" + arguments["text"]
            else:
                op = "desktop:keys\n" + arguments["combo"]
            return await _signed_desktop_capture(
                service=service, request_factory=request_factory, secret=secret,
                subject_id=owner[0], run_id=owner[1], device_id=None,
                desktop_op=op,
            )
        runtime.register(input_spec, perform)
    canonical_input_ids = tuple(
        "tool:padiem:claw-desktop-" + name + "@1" for name in input_specs
    )
    definition = BoundedAgentDefinition(
        agent_id=DESKTOP_AGENT_ID, publisher_id="padiem",
        title="PADIEM Claw screen observation",
        description="Owner-bound desktop screen observation through Chat",
        instruction="Observe only the currently authorized desktop",
        output_contract_ref="output:text@1",
        allowed_tool_ids=(DESKTOP_CANONICAL_CAPTURE,) + canonical_input_ids,
        execution_budget=AgentExecutionBudget(),
    )
    policy = TrustedAgentRuntimePolicy(
        context_policy_ref="context:default", model_policy_ref="model:auto",
        output_contract_ref="output:text@1",
        task_type="general", optimize_for="balanced", max_tokens=None,
        max_steps_cap=definition.execution_budget.max_steps,
        context_policy={}, model_policy={}, output_contract={},
        tool_bindings=(ToolRuntimeBinding(
            canonical_tool_id=DESKTOP_CANONICAL_CAPTURE,
            runtime_tool_id=DESKTOP_CAPTURE_ID,
        ),) + tuple(
            ToolRuntimeBinding(canonical_tool_id=canonical,
                               runtime_tool_id="claw.desktop." + name)
            for name, canonical in zip(input_specs, canonical_input_ids)
        ),
    )
    compiled = compile_agent_profile(definition, policy)
    authorization = ToolAuthorizationContext(
        app_id=CLAW_APP_ID, agent_id=compiled.runtime_profile.id,
        granted_auth_scopes=(DESKTOP_CAPTURE_SCOPE,),
        # ToolRuntime's external authorization lane is this signed Chat
        # transport: each invocation is independently re-authorized against
        # the canonical subject, live session, device and command_exec grant
        # before Oracle creates a dispatch. No direct PC handler exists here.
        externally_authorized_tools=frozenset(
            "claw.desktop." + name for name in input_specs
        ),
    )
    return EngineToolBinding(
        app_id=CLAW_APP_ID, tool_runtime=runtime,
        registry=ToolRegistrySnapshot.from_entries((
            RegisteredTool.from_spec(
                canonical_tool_id=DESKTOP_CANONICAL_CAPTURE,
                runtime_spec=spec,
            ),
        ) + tuple(
            RegisteredTool.from_spec(canonical_tool_id=canonical,
                                     runtime_spec=input_specs[name])
            for name, canonical in zip(input_specs, canonical_input_ids)
        )),
        authorities={DESKTOP_AGENT_ID: TrustedToolAuthority(
            canonical_agent_id=DESKTOP_AGENT_ID, definition=definition,
            compiled=compiled, authorization=authorization,
        )},
        authorization_provider=None, resource_policy=ToolResourcePolicy(),
    )

def build_live_desktop_driver(*, b14_client, chat_service, request_factory,
                              secret, model_id, model_policy=None,
                              task_type=None, optimize_for=None):
    """Server-composed Core driver; model chooses GUI actions from JPEG."""
    import base64

    async def read_capture(*, context, result, receipt):
        owner = _ENGINE_DESKTOP_OWNER.get()
        output = result.output_copy()
        if (not isinstance(owner, tuple) or len(owner) != 2
            or receipt != output.get("dispatch_id")
            or output.get("run_id") != owner[1]
            or output.get("execution_confirmed") is not True):
            raise DesktopStepContractError("capture owner/run correlation failed")
        body = json.dumps({
            "subject_id": owner[0], "run_id": owner[1],
            "dispatch_id": receipt, "mode": "image",
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")
        now = str(int(time.time()))
        proof = hmac.new(secret.encode(), now.encode("ascii") + b"." + body,
                         hashlib.sha256).hexdigest()
        request = request_factory(
            "https://padiem-chat.internal/internal/claw/engine-desktop",
            method="POST", headers={
                "Content-Type": "application/json",
                "X-Claw-Engine-Time": now, "X-Claw-Engine-Proof": proof,
            }, body=body.decode("utf-8"),
        )
        response = await chat_service.fetch(request.js_object)
        if int(response.status) != 200:
            raise DesktopStepContractError("owned capture JPEG unavailable")
        image_buffer = await response.arrayBuffer()
        image = bytes(image_buffer.to_py())
        if (not image.startswith(b"\xff\xd8\xff")
            or hashlib.sha256(image).hexdigest() != output.get("result_sha256")):
            raise DesktopStepContractError("JPEG digest or format mismatch")
        return image

    async def select_step(*, context, compiled_profile, observations):
        if not observations or observations[-1]["tool_id"] != DESKTOP_CAPTURE_ID:
            # After a PC input, get a fresh independent screenshot before any
            # further model-selected input. Never reuse stale screenshot pixels.
            return {"action": "tool", "tool_id": DESKTOP_CAPTURE_ID,
                    "arguments": {"use_pinned_device": True}}
        from padiem_ai_core.b14_multimodal import B14MultimodalChatRequest
        from padiem_ai_core.b14_execution import B14RoutingOptions
        parts = [{
            "type": "text",
            "text": (
                "Return exactly one JSON object. Choose from "
                "claw.desktop.click (x,y), claw.desktop.type (text), "
                "claw.desktop.keys (combo), claw.desktop.capture "
                "(use_pinned_device=true), or complete (answer). "
                'Tool format: {"action":"tool","tool_id":"...","arguments":{}}. '
                'Completion format: {"action":"complete","answer":"..."}. '
                "Examine the screenshot and prior outcomes, do not guess coordinates. "
                "Task: " + context.input_text
                + "\nPrior verified results: " + json.dumps(
                    [{"tool_id": o["tool_id"], "output": o["output"]}
                     for o in observations], ensure_ascii=False)
            ),
        }]
        # B14 multimodal contract consumes the most recent screenshot image;
        # earlier action outcomes remain in text, never duplicate stale images.
        jpeg = observations[-1]["image_jpeg"]
        if jpeg is not None:
            parts.append({
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64,"
                              + base64.b64encode(jpeg).decode("ascii")},
            })
        if len(parts) == 1:
            raise DesktopStepContractError("No verified screenshot for GUI choice")
        request = B14MultimodalChatRequest(
            model=model_id, messages=({"role": "user", "content": parts},),
            max_tokens=None,
            routing=B14RoutingOptions(
                product_tier=model_policy.get("product_tier")
                if model_policy is not None else None,
                max_retries=model_policy.get("max_retries")
                if model_policy is not None else None,
                task_type=task_type, optimize_for=optimize_for,
            ),
        )
        response = await b14_client.execute(request)
        try:
            return json.loads(response.answer.strip())
        except (TypeError, ValueError) as exc:
            raise DesktopStepContractError("Model step is not valid JSON") from exc

    return StructuredDesktopStepDriver(
        select_step=select_step, read_capture=read_capture,
        allowed_tool_ids=frozenset({
            "claw.desktop.capture", "claw.desktop.click",
            "claw.desktop.type", "claw.desktop.keys",
        }),
    )
