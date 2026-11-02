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


#: #6460 step 3 — the owner's 그만 is a first-class end of the loop, stated in
#: the conversation rather than raised as an error.
DESKTOP_STOP_ANSWER = (
    "그만하기로 하셔서 PC에서 다음 동작을 더 보내지 않고 멈췄습니다. "
    "멈춘 시간은 실행 기록에 남겼습니다."
)
#: The same screen after the same action is not progress, so the loop stops
#: instead of repeating an input with no observed effect.
DESKTOP_NO_PROGRESS_ANSWER = (
    "화면이 바뀌지 않아 같은 동작을 반복하지 않고 멈췄습니다. "
    "다른 방법으로 다시 요청해 주세요."
)
#: The three input tools one step may choose. ``capture`` observes only.
DESKTOP_INPUT_TOOL_IDS = frozenset({
    "claw.desktop.click", "claw.desktop.type", "claw.desktop.keys",
})


class StructuredDesktopStepDriver:
    """Core AgentStepDriver backed by a trusted structured model response."""

    def __init__(
        self,
        *,
        select_step: Callable[..., Awaitable[Mapping[str, Any]]],
        read_capture: Callable[..., Awaitable[bytes | None]],
        allowed_tool_ids: frozenset[str],
        is_stopped: Callable[..., Awaitable[Mapping[str, Any] | None]] | None = None,
    ) -> None:
        if not callable(select_step) or not callable(read_capture):
            raise DesktopStepContractError("step selector and capture reader are required")
        if not allowed_tool_ids:
            raise DesktopStepContractError("desktop tool allowlist is required")
        self._select_step = select_step
        self._read_capture = read_capture
        self._allowed_tool_ids = allowed_tool_ids
        self._is_stopped = is_stopped
        # The last input this run chose. A repeated input on an unchanged
        # screen is the no-progress stop, so the memory is the full action,
        # not just its tool id.
        self._last_input: tuple[str, str] | None = None

    async def next_step(self, context: AgentStepContext, compiled_profile: Any) -> AgentStepDecision:
        observations = []
        # #4379: the driver resolves the results it needs through their
        # authorized references, so the runtime never retains every payload.
        for index, ref in enumerate(context.tool_result_refs):
            result = await context.resolve_tool_result(ref)
            output = result.output_copy()
            if not isinstance(output, dict):
                raise DesktopStepContractError("desktop result must be an object")
            receipt = output.get("capture_receipt")
            image = None
            if receipt is not None:
                if not isinstance(receipt, str) or not receipt:
                    raise DesktopStepContractError("invalid capture receipt")
                if index == len(context.tool_result_refs) - 1:
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
        # The owner's stop can also arrive as the answer to an input that was
        # already sent: the executor reports the row as cancelled, and the loop
        # ends without sending anything else.
        if observations and observations[-1]["output"].get("stopped_by_owner") is True:
            return AgentStepDecision.complete(DESKTOP_STOP_ANSWER)
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
        # Checked right before the dispatch, so a stop that arrived while the
        # model was choosing is still honoured; the dispatch route re-checks.
        if self._is_stopped is not None:
            stopped = await self._is_stopped(context=context)
            if stopped:
                return AgentStepDecision.complete(DESKTOP_STOP_ANSWER)
        if tool_id in DESKTOP_INPUT_TOOL_IDS:
            signature = (str(tool_id), _action_signature(arguments))
            capture_digests = [
                observation["output"].get("result_sha256")
                for observation in observations
                if observation["tool_id"] == "claw.desktop.capture"
                and isinstance(observation["output"].get("result_sha256"), str)
            ]
            screen_unchanged = (
                len(capture_digests) >= 2
                and capture_digests[-1] == capture_digests[-2]
            )
            if screen_unchanged and signature == self._last_input:
                return AgentStepDecision.complete(DESKTOP_NO_PROGRESS_ANSWER)
            self._last_input = signature
        return AgentStepDecision.use_tool(
            ToolInvocation(tool_id=tool_id, arguments=dict(arguments))
        )


def _action_signature(arguments: Mapping[str, Any]) -> str:
    """The action itself, without the per-step dispatch reference."""
    return json.dumps(
        {key: value for key, value in arguments.items() if key != "call_ref"},
        sort_keys=True, ensure_ascii=True, default=str,
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

#: The wait between two status reads of one signed dispatch. Short enough that
#: a step follows the PC closely; tests replace it so the loop suite stays fast.
DESKTOP_RESULT_POLL_SECONDS = 2.0

CLAW_APP_ID = "b54-padiem-claw"
DESKTOP_AGENT_ID = "agent:padiem:claw-desktop@1"
DESKTOP_CANONICAL_CAPTURE = "tool:padiem:claw-desktop-capture@1"
DESKTOP_CAPTURE_ID = "claw.desktop.capture"
DESKTOP_CAPTURE_SCOPE = "claw.desktop.capture"
_ENGINE_DESKTOP_OWNER = ContextVar("claw_engine_desktop_owner", default=None)


async def _signed_desktop_capture(*, service, request_factory, secret, subject_id, run_id, device_id,
                                  desktop_op="desktop:capture", call_ref=None, desktop_text=None):
    if not isinstance(secret, str) or len(secret) < 32:
        raise ToolHandlerError("desktop_secret_missing", "Engine desktop authorization unavailable")
    fields = {
        "subject_id": subject_id, "run_id": run_id,
        "device_id": device_id, "desktop_op": desktop_op,
    }
    # The loop's own per-step dispatch scope, and a typed value that travels
    # beside the op so it is never written into the dispatch row.
    if call_ref is not None:
        fields["call_ref"] = call_ref
    if desktop_text is not None:
        fields["desktop_text"] = desktop_text
    body = json.dumps(
        fields, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
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
    if status == 409 and isinstance(data, dict) and (
        (data.get("error") or {}).get("code") == "oracle_mesh_run_stopped"
    ):
        # The owner's stop won the race: nothing was dispatched for this step.
        return _stopped_desktop_result(run_id=run_id)
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
        await asyncio.sleep(DESKTOP_RESULT_POLL_SECONDS)
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
        if observed.get("termination") == "cancelled":
            # The owner pressed 그만 while this action was in flight. The row
            # keeps its claim so the executor lands what actually happened,
            # and the loop ends now without sending anything else.
            return _stopped_desktop_result(run_id=run_id, dispatch_id=dispatch_id)
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


def _stopped_desktop_result(*, run_id, dispatch_id=None):
    """The owner's stop, as a normal step outcome the loop can end on."""
    return {
        "dispatch_id": dispatch_id, "run_id": run_id, "state": "cancelled",
        "capture_receipt": None, "result_sha256": None,
        "execution_confirmed": False, "stopped_by_owner": True,
    }


async def _signed_run_status(*, service, request_factory, secret, subject_id, run_id):
    """One owner-scoped read of the run: did the owner stop it?

    A failed read is reported as ``None`` (unknown), never as a stop: an
    unreachable Chat store must not make the loop claim the owner stopped it.
    """
    if not isinstance(secret, str) or len(secret) < 32:
        return None
    body = json.dumps(
        {"subject_id": subject_id, "run_id": run_id, "mode": "run_status"},
        ensure_ascii=True, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
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
        if int(response.status) != 200:
            return None
        data = json.loads(await response.text())
    except Exception:
        return None
    run = data.get("run") if isinstance(data, dict) else None
    if (not isinstance(run, dict) or run.get("run_id") != run_id
            or not isinstance(run.get("state"), str)):
        return None
    return run


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
            "call_ref": {"type": "string", "minLength": 1, "maxLength": 120},
        }, "required": ["call_ref"], "additionalProperties": False},
        output_contract={"type": "object"}, timeout_seconds=None,
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
            call_ref=arguments.get("call_ref"),
        )

    runtime.register(spec, capture)
    # All PC inputs pass through the same signed Chat owner/run authorization and
    # Oracle executor grammar. Never replay a dispatch on uncertain outcome.
    input_specs = {}
    for name, schema in (
        ("click", {"x": {"type": "integer", "minimum": 0, "maximum": 65535},
                   "y": {"type": "integer", "minimum": 0, "maximum": 65535}}),
        # Free text and any reviewed key combo: the executor checks the value
        # and the key-name grammar before the PC is asked. A typed value rides
        # the one-shot channel, never this row.
        ("type", {"text": {"type": "string", "minLength": 1, "maxLength": 20000}}),
        ("keys", {"combo": {"type": "string", "minLength": 1, "maxLength": 64}}),
    ):
        required = ["x", "y"] if name == "click" else ["text" if name == "type" else "combo"]
        properties = dict(schema)
        properties["call_ref"] = {"type": "string", "minLength": 1, "maxLength": 120}
        input_specs[name] = ToolSpec(
            id="claw.desktop." + name, title="Owner PC " + name,
            description="Run one owner-authorized desktop " + name + " operation",
            owner="core", side_effect=ToolSideEffect.WRITE,
            approval_policy=ApprovalPolicy.EXTERNAL_AUTHORIZATION,
            auth_scope=(DESKTOP_CAPTURE_SCOPE,),
            input_schema={"type": "object", "properties": properties,
                          "required": required + ["call_ref"],
                          "additionalProperties": False},
            output_contract={"type": "object"}, timeout_seconds=None,
        )
    for name, input_spec in input_specs.items():
        async def perform(arguments, _name=name):
            owner = _ENGINE_DESKTOP_OWNER.get()
            if (not isinstance(owner, tuple) or len(owner) != 2
                or not all(isinstance(v, str) and v for v in owner)):
                raise ToolHandlerError("desktop_admission_required", "Verified run required")
            typed_text = None
            if _name == "click":
                op = f"desktop:click\n{arguments['x']},{arguments['y']}"
            elif _name == "type":
                op = "desktop:type"
                typed_text = arguments["text"]
            else:
                op = "desktop:keys\n" + arguments["combo"]
            return await _signed_desktop_capture(
                service=service, request_factory=request_factory, secret=secret,
                subject_id=owner[0], run_id=owner[1], device_id=None,
                desktop_op=op, call_ref=arguments.get("call_ref"),
                desktop_text=typed_text,
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
                              task_type=None, optimize_for=None,
                              capture_device_id=None):
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

    def with_dispatch_ref(decision, step_index):
        """Stamp the step's own dispatch scope on the tool decision.

        Chat stages one dispatch per step so the loop is not one dispatch per
        run; the reference is server-derived here and a repeated step still
        correlates to its own row instead of executing twice.
        """
        if (isinstance(decision, dict) and decision.get("action") == "tool"
                and isinstance(decision.get("arguments"), dict)):
            arguments = dict(decision["arguments"])
            arguments["call_ref"] = "desktop-step-%d" % step_index
            return {**decision, "arguments": arguments}
        return decision

    async def run_stopped(*, context):
        owner = _ENGINE_DESKTOP_OWNER.get()
        if (not isinstance(owner, tuple) or len(owner) != 2
                or not all(isinstance(v, str) and v for v in owner)):
            return None
        run = await _signed_run_status(
            service=chat_service, request_factory=request_factory, secret=secret,
            subject_id=owner[0], run_id=owner[1],
        )
        if run is None or run.get("state") != "cancelled":
            return None
        return run

    async def select_step(*, context, compiled_profile, observations):
        if not observations or observations[-1]["tool_id"] != DESKTOP_CAPTURE_ID:
            # After a PC input, get a fresh independent screenshot before any
            # further model-selected input. Never reuse stale screenshot pixels.
            capture_arguments = (
                {"device_id": capture_device_id}
                if isinstance(capture_device_id, str) and capture_device_id
                else {"use_pinned_device": True}
            )
            return with_dispatch_ref({
                "action": "tool", "tool_id": DESKTOP_CAPTURE_ID,
                "arguments": capture_arguments,
            }, context.step_index)
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
                "Never enter credentials, change an account or permission, delete "
                "something irreversibly, or send anything outside the PC; if the task "
                "would need one, complete with a question instead of acting. "
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
            ),
        )
        response = await b14_client.execute(request)
        try:
            decision = json.loads(response.answer.strip())
        except (TypeError, ValueError) as exc:
            raise DesktopStepContractError("Model step is not valid JSON") from exc
        return with_dispatch_ref(decision, context.step_index)

    return StructuredDesktopStepDriver(
        select_step=select_step, read_capture=read_capture,
        allowed_tool_ids=frozenset({
            "claw.desktop.capture", "claw.desktop.click",
            "claw.desktop.type", "claw.desktop.keys",
        }),
        is_stopped=run_stopped,
    )
