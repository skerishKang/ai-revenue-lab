"""Bind a bearer request to exact first-party consent and existing PC execution."""
from __future__ import annotations

import json
import logging
import re

from .chat_pc_errors import ChatPCDriveError
from .mcp_device_selection import McpDeviceRefusal, device_id6, resolve_target_device
from .mcp_gateway_store import mcp_request_digest
from .mcp_gateway_shell import PC_SHELL_TOOL_NAMES
from .same_origin_guard import expected_browser_origin


APPROVAL_META_KEY = "net.padiem/approval_id"
PC_DEVICES_TOOL_NAME = "pc_devices"
_LOGGER = logging.getLogger("padiem_chat.request")


_SHORT_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")


def refusal_code(exc) -> str | None:
    """The engine's own bounded refusal code, when the refusal names one.

    ``ChatPCDriveError.cause`` is a diagnostic string at the HTTP boundary
    (``"<Class>: <code>: <text>"``). Only a token from the closed code grammar
    is read back out, so a provider blob can never become a status code.
    """
    for part in str(getattr(exc, "cause", None) or "").split(": "):
        token = part.strip()
        if _SHORT_CODE.fullmatch(token):
            return token
    return None


def _exception_name(exc) -> str:
    """One closed token naming the exception class, never its message."""
    name = exc.__class__.__name__
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name) else "Exception"


def _log_operation(audit, status, *, outcome=None):
    """Use the existing request event stream with a closed metadata projection."""
    event = {"event": "mcp_operation", "status": status,
             "request_digest": mcp_request_digest(audit["tool_name"], audit["arguments"])}
    for key, value in (("tool", audit["tool_name"]), ("approval_id", audit.get("approval_id")),
                       ("run_id", (outcome or {}).get("run_id")),
                       ("code", (outcome or {}).get("code")),
                       ("deny_reason", (outcome or {}).get("deny_reason"))):
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", value):
            event[key] = value
    # 대상 PC는 끝 6자만 남긴다. 전체 기기 ID·메시 노드 ID는 로그에도 쓰지 않는다.
    device6 = device_id6((audit.get("identity") or {}).get("device_id"))
    if device6:
        event["device"] = device6
    metadata = (outcome or {}).get("audit")
    if isinstance(metadata, dict):
        exit_code = metadata.get("exit_code")
        if isinstance(exit_code, int) and not isinstance(exit_code, bool):
            event["exit_code"] = exit_code
        for key in ("duration_ms", "output_bytes"):
            value = metadata.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                event[key] = value
        if isinstance(metadata.get("output_truncated"), bool):
            event["output_truncated"] = metadata["output_truncated"]
    if (outcome or {}).get("audit_status") == "unavailable":
        event["audit_status"] = "unavailable"
    _LOGGER.info(json.dumps(event, separators=(",", ":")))


async def dispatch_mcp_tool(request, principal, tool_name, arguments, *, approval_id=None):
    """Only a consumed DB receipt reaches Engine, never the client's claim.

    Audit records contain token identifiers and an argument digest, not bearer
    credentials or file contents. Record the attempt before any execution so
    even a subsequent disconnect retains evidence of the attempted action.
    """
    store = getattr(request.app.state, "mcp_gateway_store", None)
    executor = getattr(request.app.state, "mcp_gateway_executor", None)
    if store is None or executor is None:
        return {"status": "unavailable", "code": "mcp_gateway_unavailable",
                    "answer": "PC 작업 연결을 지금 사용할 수 없습니다."}
    principal = dict(principal) if isinstance(principal, dict) else principal
    # 2026-11-04: the caller may choose the target PC with the `device`
    # argument (the identifier pc_devices returns, or the PC's display name).
    # Resolution runs before the first audit write so both records carry the
    # PC the work was actually aimed at; a refusal is audited and answered
    # without reaching any PC.
    device_refusal = None
    if tool_name != PC_DEVICES_TOOL_NAME and isinstance(arguments, dict):
        device_arg = arguments.get("device")
        if isinstance(device_arg, str) and device_arg.strip():
            try:
                target = await resolve_target_device(
                    request, owner_id=principal["owner_id"], principal=principal,
                    device_arg=device_arg)
                principal = {**principal, "device_id": target["device_id"]}
            except McpDeviceRefusal as refusal:
                device_refusal = refusal
    identity = {"user_id": principal["owner_id"], "device_id": principal["device_id"],
                "token_id": principal["token_id"]}
    shell_tool = tool_name in PC_SHELL_TOOL_NAMES
    # PC shell is predelegated by the selected PC, token binding and the one
    # deployment switch. Ignore approval metadata for this family entirely.
    audit = {"identity": identity, "tool_name": tool_name, "arguments": arguments,
             "approval_id": None if shell_tool else approval_id}
    try:
        await store.audit(**audit, status="requested")
    except Exception:
        return {"status": "unavailable", "code": "mcp_audit_unavailable",
                    "answer": "작업 기록을 준비하지 못해 실행하지 않았습니다. 잠시 뒤 다시 시도해 주세요."}
    _log_operation(audit, "requested")
    if device_refusal is not None:
        outcome = {"status": "denied", "code": device_refusal.code,
                   "answer": device_refusal.message}
        await _record_outcome(request, store, audit, outcome)
        return outcome
    approval = None
    browser = tool_name in {"pc_browser_open", "pc_browser_read", "pc_browser_screenshot", "pc_browser_act"}
    if browser and approval_id is not None:
        outcome = {"status": "confirmation_required", "answer": "이 브라우저 작업은 PADIEM 대화에서 확인해 주세요.",
                   "confirmation_kind": "conversation"}
        await _record_outcome(request, store, audit, outcome)
        return outcome
    if browser:
        # Browser use is predelegated; sensitive actions ask in ordinary chat.
        # Never reinterpret an old approval button receipt as browser consent.
        pass
    elif shell_tool:
        # No per-command approval receipt is part of the MCP shell contract.
        pass
    elif approval_id is not None:
        try:
            approval = await store.consume_approval(identity=identity, approval_id=approval_id,
                                                    tool_name=tool_name, arguments=arguments)
        except Exception:
            return {"status": "unavailable", "code": "mcp_approval_lookup_failed",
                    "answer": "승인 내용을 확인하지 못해 실행하지 않았습니다."}
        if approval is None:
            outcome = {"status": "confirmation_required", "answer": "승인을 아직 받지 못했거나 이미 사용한 확인입니다. PADIEM에서 확인해 주세요.",
                       "approval_id": approval_id, "approval_status": "unavailable"}
            await _record_outcome(request, store, audit, outcome)
            return outcome
    else:
        try:
            # Ordinary MCP clients can retry the same tool arguments without
            # supporting a PADIEM-specific metadata extension. The database
            # binds this lookup to the exact account, token, PC and request.
            approval = await store.consume_matching_approval(identity=identity, tool_name=tool_name,
                                                             arguments=arguments)
        except Exception:
            return {"status": "unavailable", "code": "mcp_approval_lookup_failed",
                    "answer": "승인 내용을 확인하지 못해 실행하지 않았습니다."}
    if approval is not None:
        audit["approval_id"] = approval["approval_id"]
    try:
        outcome = await executor(request, principal, tool_name, arguments, approval=approval)
        if not isinstance(outcome, dict) or outcome.get("status") not in {
            "completed", "confirmation_required", "failed", "unavailable",
            "running", "queued", "cancelled", "denied", "tool_not_enabled",
        }:
            raise ValueError("Invalid PC result")
    except ChatPCDriveError as exc:
        # A refusal that names its branch keeps the owner's generic wording and
        # reports that branch as a code. "The engine refused admission" is a
        # known outcome, not "we could not learn the result".
        reason = refusal_code(exc)
        # An engine refusal means nothing reached a PC: that is a known
        # failure, not an unknown result. Other refusals keep their status.
        refused_by_engine = exc.code == "chat_pc_engine_unavailable" and bool(reason)
        outcome = {"status": "failed" if refused_by_engine else "unavailable",
                   "answer": exc.user_message,
                   "code": reason or exc.code,
                   "deny_reason": reason or exc.code}
    except Exception as exc:
        # 값·경로 원문은 남기지 않고, 어느 단계에서 어떤 종류의 예외로 끝났는지만
        # 한 줄 남긴다. 지금까지는 pc_dispatch_failed 하나로만 끝나 원인을 알 수 없었다.
        _LOGGER.warning(json.dumps(
            {"event": "mcp_operation", "status": "pc_dispatch_failed",
             "stage": "mcp_gateway_dispatch", "exception": _exception_name(exc)},
            separators=(",", ":")))
        outcome = {"status": "unavailable", "code": "pc_dispatch_failed",
                   "answer": "PC 작업의 실제 결과를 확인하지 못했습니다. PADIEM에서 작업 상태를 확인해 주세요."}
    if outcome["status"] == "confirmation_required":
        if browser:
            outcome = {**outcome, "confirmation_kind": "conversation",
                       "confirmation_instructions": "PADIEM의 해당 대화에서 질문에 답해 주세요. 답변은 새 요청으로 처리됩니다."}
        else:
            try:
                pending = await store.create_approval(identity=identity, tool_name=tool_name, arguments=arguments)
                outcome = {**outcome, "approval_id": pending["id"], "approval_status": "pending",
                           "expires_at": pending["expires_at"],
                           "confirmation_instructions": "PADIEM 설정의 외부 AI 연결에서 이 작업을 승인한 뒤, 같은 도구와 인자로 다시 요청해 주세요. 승인 한 번으로 한 번만 실행합니다."}
                origin = expected_browser_origin(getattr(request.app.state, "settings", None))
                if origin:
                    outcome["approval_url"] = origin + "/"
                audit["approval_id"] = pending["id"]
            except Exception:
                outcome = {"status": "unavailable", "code": "mcp_approval_store_failed",
                       "answer": "확인할 작업을 저장하지 못해 실행하지 않았습니다. 잠시 뒤 다시 시도해 주세요."}
    await _record_outcome(request, store, audit, outcome)
    return outcome


async def _record_outcome(request, store, audit, outcome):
    metadata = outcome.get("audit") if isinstance(outcome.get("audit"), dict) else {}
    job_receipt = outcome.pop("_job_receipt", None)
    try:
        await store.audit(**audit, status=outcome["status"],
                          exit_code=metadata.get("exit_code"),
                          duration_ms=metadata.get("duration_ms"),
                          output_bytes=metadata.get("output_bytes"),
                          output_truncated=metadata.get("output_truncated"),
                          job_receipt_id=job_receipt)
    except Exception:
        # An execution may already have happened: preserve its truthful result,
        # mark the missing final audit explicitly, and never retry the action.
        outcome["audit_status"] = "unavailable"
        if isinstance(job_receipt, str) and isinstance(outcome.get("run_id"), str):
            history = getattr(request.app.state, "history_store", None)
            cancel = getattr(history, "cancel_oracle_mesh_dispatches_for_run", None)
            if callable(cancel):
                try:
                    await cancel(user_id=audit["identity"]["user_id"],
                                 run_id=outcome["run_id"])
                except Exception:
                    pass
            outcome.update({"status": "unavailable", "code": "mcp_audit_final_failed",
                            "answer": "작업 기록을 저장하지 못해 PC 작업 중지를 요청했습니다."})
            for key in ("job_id", "output", "output_ref", "next_offset"):
                outcome.pop(key, None)
    _log_operation(audit, outcome["status"], outcome=outcome)
