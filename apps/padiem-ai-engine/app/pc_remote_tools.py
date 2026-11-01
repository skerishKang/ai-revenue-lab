"""Execution adapters for the existing owner-bound PC callback and batch runner."""
from __future__ import annotations

import asyncio
from contextvars import copy_context
from collections.abc import Mapping
import hashlib
import json
import threading

from kagent.pc_query_adapter import PC_QUERY_OWNER, PC_QUERY_RUN_SCOPE, PC_REQUEST_SCOPE_TOOLS
from kagent.pc_remote_tools import (
    REMOTE_TOOL_IDS, OP_TO_TOOL, operation_actions, remote_tool_allowed, validate_remote_arguments,
)
from padiem_ai_core.tool_runtime import ToolHandlerError

_MODES = {
    "claw.pc.read_output": "read_output", "claw.pc.search_output": "search_output",
    "claw.pc.start_job": "job_start", "claw.pc.job_status": "job_status",
    "claw.pc.job_output": "job_output",
}


def _plain(value):
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _digest(tool_id, arguments):
    return hashlib.sha256(json.dumps([tool_id, _plain(arguments)], sort_keys=True,
        separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def record_remote_admission(driver, tool_id, arguments):
    """Request-local receipt after the shared evidence/delegation preflight."""
    state = driver.scope_state
    state["_remote_driver"] = driver
    if tool_id in {"claw.pc.batch", "claw.pc.start_job"}:
        receipts = state.setdefault("_remote_admissions", {})
        receipts[_digest(tool_id, arguments)] = PC_QUERY_OWNER.get()


def _owner_state():
    owner, state = PC_QUERY_OWNER.get(), PC_QUERY_RUN_SCOPE.get()
    if (not isinstance(owner, tuple) or len(owner) != 4
            or not all(isinstance(value, str) and value for value in owner)
            or not isinstance(state, dict)):
        raise ToolHandlerError("pc_remote_admission_required", "Verified PC owner and scope are required")
    return owner, state


def _stored(value):
    if isinstance(value, dict) and isinstance(value.get("handle"), str):
        from app.pc_work_metrics import current_pc_work_metrics
        metrics = current_pc_work_metrics()
        if metrics is not None:
            metrics.mark_stored_output(value["handle"])


async def _job_action_result(result, *, owner, service, request_factory, secret, signed_call):
    operation = result.get("operation")
    if not isinstance(operation, dict) or operation.get("op") not in {"write", "move", "delete"}:
        return result
    op, path = operation["op"], operation.get("path")
    if not isinstance(path, str) or not path:
        return result
    result["source_tool_id"] = OP_TO_TOOL[op]
    if result.get("state") not in {"done", "failed"}:
        return result
    from app.pc_action_verification import unavailable_action, verify_pc_action
    from app.claw_pc_query_step_driver import _pc_write_result
    verification = unavailable_action(op, path, destination=operation.get("destination"))
    try:
        response = await signed_call(service=service, request_factory=request_factory,
            secret=secret, owner=owner, mode="result", payload={"dispatch_id": result["job_id"]})
        final = response.get("dispatch")
        if (not isinstance(final, dict) or final.get("dispatch_id") != result["job_id"]
                or final.get("run_id") != owner[1] or final.get("kind") != "command"
                or not isinstance(final.get("output"), str) or final.get("output_ref") is not None):
            result["action_verification"] = verification
            return result
        account = _pc_write_result(final["output"])
        verification = verify_pc_action(operation=op, path=path,
            extra={"destination": operation["destination"]} if op == "move" else {},
            expected_content=operation if op == "write" else None,
            account=account, state=result["state"], termination=final.get("termination"),
            exit_code=final.get("exit_code"))
    except (ToolHandlerError, ValueError, KeyError, TypeError):
        pass
    result["action_verification"] = verification
    return result


def make_remote_handler(tool_id, *, service, request_factory, secret, signed_call, file_handlers):
    async def handler(arguments):
        try:
            arguments = validate_remote_arguments(tool_id, arguments)
        except (TypeError, ValueError):
            raise ToolHandlerError("pc_remote_arguments_invalid", "Invalid PC remote request") from None
        owner, state = _owner_state()
        claim = state.get("claim", {})
        base_tools = PC_REQUEST_SCOPE_TOOLS.get(claim.get("admitted"), frozenset())
        if not remote_tool_allowed(tool_id, arguments, base_tools):
            raise ToolHandlerError("pc_remote_scope_denied", "PC wrapper exceeds this run's scope")
        if tool_id in {"claw.pc.batch", "claw.pc.start_job"}:
            receipt = state.get("_remote_admissions", {}).pop(_digest(tool_id, arguments), None)
            if receipt != owner:
                raise ToolHandlerError("pc_remote_preflight_required", "PC action evidence is required")

        async def call(mode, payload):
            response = await signed_call(service=service, request_factory=request_factory,
                secret=secret, owner=owner, mode=mode, payload=payload)
            result = response.get("result")
            if not isinstance(result, dict):
                raise ToolHandlerError("pc_remote_result_invalid", "Verified PC result is unavailable")
            _stored(result)
            _stored(result.get("output_ref"))
            return result

        if tool_id == "claw.pc.recall_context":
            driver = state.get("_remote_driver")
            recall = getattr(driver, "recall_context", None)
            if not callable(recall):
                raise ToolHandlerError("context_source_unavailable", "Original context is unavailable")
            import inspect
            from app.pc_context_compaction import PCContextCompactionError
            try:
                result = recall(arguments)
                if inspect.isawaitable(result):
                    result = await result
                return result
            except PCContextCompactionError as error:
                raise ToolHandlerError(error.code, "Original context is unavailable") from None

        if tool_id != "claw.pc.batch":
            payload = dict(arguments)
            if tool_id == "claw.pc.start_job":
                payload["tool_call_ref"] = _digest(tool_id, [owner[1], arguments])
            result = await call(_MODES[tool_id], payload)
            if tool_id == "claw.pc.start_job":
                job_id = result.get("job_id")
                if not isinstance(job_id, str) or not job_id:
                    raise ToolHandlerError("pc_job_receipt_missing", "PC job receipt is unavailable")
                from app.pc_work_metrics import current_pc_work_metrics
                metrics = current_pc_work_metrics()
                if metrics is not None:
                    metrics.mark_background_job(job_id)
            if tool_id == "claw.pc.start_job":
                operation = arguments["operation"]
                if operation["op"] in {"write", "move", "delete"}:
                    result["source_tool_id"] = OP_TO_TOOL[operation["op"]]
            if tool_id in {"claw.pc.job_status", "claw.pc.job_output"}:
                result = await _job_action_result(result, owner=owner, service=service,
                    request_factory=request_factory, secret=secret, signed_call=signed_call)
            return result

        from padiem_ai_core.pc_batch import bind_batch_services, run_batch
        actions = operation_actions(arguments, batch=True)
        reverse = {value: key for key, value in OP_TO_TOOL.items()}
        steps = [{"op": reverse[action], "args": data} for action, data in actions]
        owner_key = json.dumps(owner, separators=(",", ":"))
        loop, context = asyncio.get_running_loop(), copy_context()
        attempted, action_verifications = [], []
        cancelled, pending_lock, pending = threading.Event(), threading.Lock(), set()

        def submit(coro):
            if cancelled.is_set():
                coro.close()
                raise RuntimeError("PC batch was cancelled")
            future = context.copy().run(asyncio.run_coroutine_threadsafe, coro, loop)
            with pending_lock:
                pending.add(future)
                if cancelled.is_set():
                    future.cancel()
            try:
                return future.result()
            finally:
                with pending_lock:
                    pending.discard(future)

        class Executor:
            def confirm_batch(self, candidate, *, owner):
                return not cancelled.is_set() and owner == owner_key and candidate == steps

            def execute_authorized(self, op, args, *, owner):
                if cancelled.is_set():
                    raise RuntimeError("PC batch was cancelled")
                if owner != owner_key:
                    raise ValueError("PC owner mismatch")
                child = OP_TO_TOOL.get(op)
                if child not in base_tools or child not in file_handlers:
                    raise ValueError("PC operation exceeds the admitted scope")
                operation_actions({"operation": {"op": op, **args}})
                attempted.append(child)
                result = submit(file_handlers[child](args))
                if op in {"write", "move", "delete"}:
                    from app.pc_action_verification import unavailable_action
                    verification = result.get("action_verification")
                    if not isinstance(verification, dict):
                        verification = unavailable_action(op, args["path"], destination=args.get("destination"))
                    action_verifications.append({"tool_id": child, "action_verification": verification})
                return {"ok": result.get("ok", True), **result}

        class Store:
            def store(self, output, *, owner, source):
                if owner != owner_key or source != "pc_batch":
                    raise ValueError("PC output owner mismatch")
                return submit(call("store_output", {
                    "output": output, "source": "pc_batch",
                    "tool_call_ref": _digest("pc_batch", [steps, output]),
                }))

        def execute():
            with bind_batch_services(Executor(), Store()):
                return run_batch(steps, owner=owner_key,
                    stop_on_error=arguments["stop_on_error"], total_timeout=None)

        try:
            result = await asyncio.to_thread(execute)
        except asyncio.CancelledError:
            cancelled.set()
            with pending_lock:
                for future in tuple(pending):
                    future.cancel()
            raise
        result["source_tool_ids"] = attempted
        result["action_verifications"] = action_verifications
        return result

    return handler
