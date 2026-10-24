"""Optional native PC tool exposure inside one existing Engine run.

The catalog only decides whether tool definitions may be sent. Actual execution
still requires the product's server-provisioned tool authority and declared-plan
admission. No keyword selection, classifier call, retry, or model policy lives here.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from contextvars import ContextVar
from typing import Any
import json
import uuid

from padiem_ai_core import AgentPlanExecutor, ExecutionResult, OrchestrationError, RunStatus
from padiem_ai_core.tool_channel import ToolDefinition
from padiem_ai_core.pc_device_identity import is_pc_device_id
from app.service import ServiceContractError

SCOPES = ("query_drives", "files_list", "files")


def parse_pc_tools(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    if "pc_tools" not in payload:
        return None
    data = payload["pc_tools"]
    if (
        payload.get("app_id") not in {"padiem-chat", "b54-padiem-claw"}
        or not payload.get("subject_id") or not payload.get("session_id")
        or payload.get("agent_plan") is not None
        or "tool_arguments" in payload or "declared_plan" in payload
        or not isinstance(data, Mapping)
        or set(data) != {"device_id", "allowed_scopes"}
        or not is_pc_device_id(data.get("device_id"))
    ):
        raise ServiceContractError("invalid_pc_tools", "PC tools context is invalid.", status_code=422)
    scopes = data["allowed_scopes"]
    if (
        not isinstance(scopes, list) or not scopes or len(scopes) > 3
        or any(not isinstance(s, str) or s not in SCOPES for s in scopes)
        or len(set(scopes)) != len(scopes)
    ):
        raise ServiceContractError("invalid_pc_tools", "PC tools scopes are invalid.", status_code=422)
    return {"device_id": data["device_id"], "allowed_scopes": list(scopes)}


def tool_names(context):
    allowed = set(context["allowed_scopes"])
    if "files" in allowed:
        allowed.add("files_list")
    return tuple(s for s in SCOPES if s in allowed)


def definitions(context):
    descriptions = {
        "query_drives": "Inspect the user's PC drives when the user requests drive inventory.",
        "files_list": "List PC file names only. Choose this for a listing request; never read file contents.",
        "files": "Read the requested PC file contents only when the user's turn asks for contents.",
    }
    return tuple(ToolDefinition(
        name=name, description=descriptions[name],
        parameters={"type": "object", "properties": (
            {} if name == "query_drives" else {"path": {"type": "string"}}
        ), "required": ([] if name == "query_drives" else ["path"]), "additionalProperties": False},
    ) for name in tool_names(context))


class CatalogToolCapabilities:
    """Read the existing B14 catalog; no provider/model policy is copied here."""
    def __init__(self, binding, request_factory):
        self.binding, self.request_factory = binding, request_factory

    async def __call__(self, model_id):
        try:
            request = self.request_factory("https://b14.internal/api/pilot/models", method="GET")
            response = await self.binding.fetch(request.js_object)
            if int(response.status) != 200:
                return False
            body = getattr(response, "body", None)
            if body is not None:
                from app.cloudflare_transport import CloudflareReadableByteStream
                stream = CloudflareReadableByteStream(body)
                encoded = bytearray()
                try:
                    async for chunk in stream:
                        if len(encoded) + len(chunk) > 2 * 1024 * 1024:
                            return False
                        encoded.extend(chunk)
                finally:
                    await stream.aclose()
                text = encoded.decode("utf-8")
            else:
                text = await response.text()
                if not isinstance(text, str) or len(text.encode("utf-8")) > 2 * 1024 * 1024:
                    return False
            data = json.loads(text)
            rows = data.get("catalog") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                return False
            # B14 /api/pilot/models: enabled catalog rows expose capability
            # names in tags, not in the provider-configured models list.
            return any(
                isinstance(row, dict) and row.get("id") == model_id
                and row.get("pilot_available") is True
                and isinstance(row.get("tags"), list) and "tools" in row["tags"]
                for row in rows
            )
        except Exception:
            # Unverified capability never exposes tools; preserve the text lane.
            return False


class PcToolsTurnRuntime:
    """Run the same first model stream inside the existing Core run/reservation."""
    def __init__(self, service, payload, fallback):
        self.service, self.payload, self.fallback = service, dict(payload), fallback
        self.context = parse_pc_tools(payload)

    async def run(self, request):
        service = self.service
        model_id = request.agent.model_policy.get("model")
        if (
            self.context is None or service._pc_streaming_runtime_factory is None
            or service._pc_tools_capability is None
            or not await service._pc_tools_capability(model_id)
        ):
            return await self.fallback.run(request)
        native = replace(request, tools=definitions(self.context), tool_choice="auto")
        runtime = service._pc_streaming_runtime_factory(self.payload["app_id"])
        iterator = runtime.stream(native)
        calls = []
        terminal = None
        try:
            async for event in iterator:
                if event.tool_call is not None:
                    calls.append(event.tool_call)
                if event.delta_content:
                    sink = _PC_TURN_STREAM_SINK.get()
                    if sink is not None:
                        sink({"text_delta": {"delta": event.delta_content}})
                if event.done:
                    terminal = event
        finally:
            close = getattr(iterator, "aclose", None)
            if callable(close):
                await close()
        if terminal is None:
            raise OrchestrationError("pc_tool_stream_incomplete", "The first model stream did not complete.")
        if not calls:
            if terminal.finish_reason == "tool_calls":
                raise OrchestrationError("pc_tool_call_missing", "The model did not provide a complete tool call.")
            return ExecutionResult(answer=terminal.answer, route=terminal.route, metadata=terminal.metadata)
        # Never execute a partial call or dispatch before a successful terminal.
        if len(calls) != 1 or terminal.finish_reason != "tool_calls":
            raise OrchestrationError("pc_tool_call_invalid", "A single complete PC tool call is required.")
        call = calls[0]
        if call.name not in tool_names(self.context):
            raise OrchestrationError("pc_tool_scope_denied", "The requested PC scope was not offered.")
        args = dict(call.arguments)
        expected = set() if call.name == "query_drives" else {"path"}
        if set(args) != expected or (
            expected and (not isinstance(args["path"], str) or not args["path"].strip())
        ):
            raise OrchestrationError("pc_tool_arguments_invalid", "The PC tool call arguments are invalid.")
        scope = call.name
        steps = (
            [{"step_id": "query_drives", "tool_id": "claw.pc.query_drives", "objective": "Query PC drives"}]
            if scope == "query_drives" else
            [{"step_id": "list_files", "tool_id": "claw.pc.list_files", "objective": "List PC files"}]
        )
        if scope == "files":
            steps.append({"step_id": "read_file", "tool_id": "claw.pc.read_file", "objective": "Read requested file"})
        tool_id = {
            "query_drives": "claw.pc.query_drives", "files_list": "claw.pc.list_files", "files": "claw.pc.read_file",
        }[scope]
        initial = {"action": "tool", "tool_id": tool_id, "arguments": args}
        child = dict(self.payload)
        child.pop("pc_tools")
        child.update(
            agent_plan={"agent_id": (
                "agent:padiem:chat-pc-query@1" if child["app_id"] == "padiem-chat"
                else "agent:padiem:claw-pc-query@1"
            ), "steps": steps},
            declared_plan=scope, tool_arguments={scope: {"device_id": self.context["device_id"]}},
        )
        built = service._orchestrate_request_from_payload(child)
        from app.service import ServiceResponse
        if isinstance(built, ServiceResponse):
            raise OrchestrationError("pc_tool_admission_failed", "PC plan admission failed.")
        app_id, orch, execution, _ = built
        attached = service._attach_pc_query_step_driver(
            app_id=app_id, orch_req=orch, exec_req=execution,
            declared_plan=scope, initial_decision=initial,
        )
        if isinstance(attached, ServiceResponse):
            raise OrchestrationError("pc_tool_admission_failed", "PC driver admission failed.")
        orch = attached
        if any(getattr(orch, field) is None for field in (
            "agent_definition", "compiled_agent_profile", "tool_authorization", "tool_runtime",
        )):
            raise OrchestrationError("pc_tool_admission_failed", "PC tool authority is unavailable.")
        from app.claw_pc_query_step_driver import _PC_QUERY_OWNER
        from kagent.pc_query_adapter import PC_QUERY_RUN_SCOPE
        # The model never supplies owner/device; they come from admitted context.
        from app.orchestration_service import _pc_query_stream_owner
        owner_token = _PC_QUERY_OWNER.set(_pc_query_stream_owner(app_id, orch))
        scope_token = PC_QUERY_RUN_SCOPE.set(getattr(orch.agent_step_driver, "scope_state", None))
        try:
            result = await AgentPlanExecutor().execute(
                plan=orch.agent_plan, definition=orch.agent_definition,
                compiled_profile=orch.compiled_agent_profile, authorization=orch.tool_authorization,
                tool_runtime=orch.tool_runtime, input_text=request.messages[-1].get("content", ""),
                run_id=f"bridge_run_{uuid.uuid4().hex[:12]}", trace_id=request.trace_id,
                tool_arguments=orch.tool_arguments, step_driver=orch.agent_step_driver,
                result_ledger=service._tool_result_ledger(app_id, orch.subject_id),
            )
        finally:
            PC_QUERY_RUN_SCOPE.reset(scope_token)
            _PC_QUERY_OWNER.reset(owner_token)
        if result.terminal_reason.value != "completed" or not result.answer:
            raise OrchestrationError("pc_tool_execution_failed", "The PC run did not complete.")
        return ExecutionResult(
            answer=result.answer, route=terminal.route,
            metadata=replace(terminal.metadata, status=RunStatus.COMPLETED, tool_events=tuple(result.tool_events)),
        )


_PC_TURN_STREAM_SINK: ContextVar[Any] = ContextVar("pc_turn_stream_sink", default=None)
