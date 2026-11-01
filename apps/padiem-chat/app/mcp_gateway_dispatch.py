"""Bind a bearer request to exact first-party consent and existing PC execution."""
from __future__ import annotations

import json
import logging
import re

from .mcp_gateway_store import mcp_request_digest
from .same_origin_guard import expected_browser_origin


APPROVAL_META_KEY = "net.padiem/approval_id"
_LOGGER = logging.getLogger("padiem_chat.request")


def _log_operation(audit, status, *, outcome=None):
    """Use the existing request event stream with a closed metadata projection."""
    event = {"event": "mcp_operation", "status": status,
             "request_digest": mcp_request_digest(audit["tool_name"], audit["arguments"])}
    for key, value in (("token_id", audit["identity"]["token_id"]),
                       ("tool", audit["tool_name"]), ("approval_id", audit.get("approval_id")),
                       ("run_id", (outcome or {}).get("run_id"))):
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", value):
            event[key] = value
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
        return {"status": "unavailable", "answer": "PC 작업 연결을 지금 사용할 수 없습니다."}
    identity = {"user_id": principal["owner_id"], "device_id": principal["device_id"],
                "token_id": principal["token_id"]}
    audit = {"identity": identity, "tool_name": tool_name, "arguments": arguments,
             "approval_id": approval_id}
    try:
        await store.audit(**audit, status="requested")
    except Exception:
        return {"status": "unavailable", "answer": "작업 기록을 준비하지 못해 실행하지 않았습니다. 잠시 뒤 다시 시도해 주세요."}
    _log_operation(audit, "requested")
    approval = None
    browser = tool_name in {"pc_browser_open", "pc_browser_read", "pc_browser_screenshot", "pc_browser_act"}
    if browser and approval_id is not None:
        outcome = {"status": "confirmation_required", "answer": "이 브라우저 작업은 PADIEM 대화에서 확인해 주세요.",
                   "confirmation_kind": "conversation"}
        await _record_outcome(store, audit, outcome)
        return outcome
    if browser:
        # Browser use is predelegated; sensitive actions ask in ordinary chat.
        # Never reinterpret an old approval button receipt as browser consent.
        pass
    elif approval_id is not None:
        try:
            approval = await store.consume_approval(identity=identity, approval_id=approval_id,
                                                    tool_name=tool_name, arguments=arguments)
        except Exception:
            return {"status": "unavailable", "answer": "승인 내용을 확인하지 못해 실행하지 않았습니다."}
        if approval is None:
            outcome = {"status": "confirmation_required", "answer": "승인을 아직 받지 못했거나 이미 사용한 확인입니다. PADIEM에서 확인해 주세요.",
                       "approval_id": approval_id, "approval_status": "unavailable"}
            await _record_outcome(store, audit, outcome)
            return outcome
    else:
        try:
            # Ordinary MCP clients can retry the same tool arguments without
            # supporting a PADIEM-specific metadata extension. The database
            # binds this lookup to the exact account, token, PC and request.
            approval = await store.consume_matching_approval(identity=identity, tool_name=tool_name,
                                                             arguments=arguments)
        except Exception:
            return {"status": "unavailable", "answer": "승인 내용을 확인하지 못해 실행하지 않았습니다."}
    if approval is not None:
        audit["approval_id"] = approval["approval_id"]
    try:
        outcome = await executor(request, principal, tool_name, arguments, approval=approval)
        if not isinstance(outcome, dict) or outcome.get("status") not in {"completed", "confirmation_required", "failed", "unavailable"}:
            raise ValueError("Invalid PC result")
    except Exception:
        outcome = {"status": "unavailable", "answer": "PC 작업의 실제 결과를 확인하지 못했습니다. PADIEM에서 작업 상태를 확인해 주세요."}
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
                outcome = {"status": "unavailable", "answer": "확인할 작업을 저장하지 못해 실행하지 않았습니다. 잠시 뒤 다시 시도해 주세요."}
    await _record_outcome(store, audit, outcome)
    return outcome


async def _record_outcome(store, audit, outcome):
    try:
        await store.audit(**audit, status=outcome["status"])
    except Exception:
        # An execution may already have happened: preserve its truthful result,
        # mark the missing final audit explicitly, and never retry the action.
        outcome["audit_status"] = "unavailable"
    _log_operation(audit, outcome["status"], outcome=outcome)
