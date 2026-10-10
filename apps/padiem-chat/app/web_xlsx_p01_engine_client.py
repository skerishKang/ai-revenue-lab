"""#3580: dedicated B62 -> Engine trusted XLSX ToolRuntime request transport.

No generic P01 Engine client widening, no arbitrary URL, no browser-selected
tool/args/credential, no direct content/Drive/PC action and no retries.
"""
from __future__ import annotations

import json
import re
from typing import Any

from padiem_ai_engine_client import ENGINE_INTERNAL_ORIGIN

from .claw_web_xlsx_p01_request import (
    TrustedWebXlsxP01Request, WebXlsxP01RequestError,
)
from .service_binding_response import (
    ServiceBindingResponseError, ServiceBindingResponseTooLarge,
    read_bounded_service_binding_body,
)

_ENDPOINT = "/internal/v1/tools/execute"
_APP = "padiem-web-xlsx-p01"
_AGENT = "agent:padiem:web-xlsx-confirm@1"
_TOOL = "tool:padiem:web-xlsx-confirm@1"
_ORIGINAL_TOOL = "workspace.xlsx.confirm_original_read"
_MAX_RESPONSE_BYTES = 12_288
_MAX_BODY_BYTES = 2048
_CREDENTIAL_CHARS = re.compile(r"^[^\x00-\x1f\x7f]{1,512}$")
_CALLER_CHARS = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:@+-]{0,127}$")


def web_xlsx_engine_tool_payload(request: TrustedWebXlsxP01Request) -> dict[str, Any]:
    """Build a closed Engine ToolInvocation from an authenticated B62 source."""
    if not isinstance(request, TrustedWebXlsxP01Request):
        raise WebXlsxP01RequestError("trusted B62 owner-run XLSX request required")
    return {
        "app_id": _APP,
        "agent_id": _AGENT,
        "tool_id": _TOOL,
        "arguments": {
            "owner_id": request.owner_id,
            "workspace_id": request.workspace_id,
            "run_id": request.run_id,
            "selection_ref": request.selection_ref,
            "document_id": request.document_id,
            "source_sha256": request.source_sha256,
            "operation": "read_for_workcopy",
            "source_kind": "browser_upload",
            "original_immutable": True,
            "read_content": False,
            "drive_write": False,
            "local_pc_access": False,
        },
    }


class CloudflareWebXlsxP01EngineClient:
    """Fixed HTTPS internal ToolRuntime path through the EXISTING P01 binding."""

    def __init__(
        self, service_binding: Any, *,
        caller_id: str, credential: str, request_factory: Any,
    ) -> None:
        if service_binding is None or not callable(getattr(service_binding, "fetch", None)):
            raise ValueError("existing P01 Engine Service Binding required")
        if not callable(request_factory):
            raise ValueError("Worker-native Request constructor required")
        if not isinstance(caller_id, str) or not _CALLER_CHARS.fullmatch(caller_id):
            raise ValueError("existing Engine caller identity required")
        if not isinstance(credential, str) or not _CREDENTIAL_CHARS.fullmatch(credential):
            raise ValueError("existing Engine credential required")
        self._binding = service_binding
        self._caller_id = caller_id
        self._credential = credential
        self._request_factory = request_factory

    async def start_pause(self, request: TrustedWebXlsxP01Request) -> dict[str, Any]:
        data = web_xlsx_engine_tool_payload(request)
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > _MAX_BODY_BYTES:
            raise WebXlsxP01RequestError("Engine web XLSX request exceeds bound")
        # The target is CONSTANT. It is never supplied by a browser or by a
        # request field and cannot reach generic orchestrate/model endpoints.
        req = self._request_factory(
            f"{ENGINE_INTERNAL_ORIGIN}{_ENDPOINT}",
            method="POST",
            headers={
                "content-type": "application/json",
                "accept": "application/json",
                "x-padiem-engine-caller": self._caller_id,
                "x-padiem-engine-credential": self._credential,
            },
            body=encoded,
        )
        try:
            response = await self._binding.fetch(req.js_object)
            raw = await read_bounded_service_binding_body(
                response, max_bytes=_MAX_RESPONSE_BYTES,
            )
        except (ServiceBindingResponseError, ServiceBindingResponseTooLarge,
                TypeError, ValueError) as exc:
            raise WebXlsxP01RequestError("bounded private Engine response unavailable") from exc
        # No retries on any outcome, including an uncertain transport result.
        try:
            status = int(response.status)
            body = json.loads(raw.decode("utf-8"))
        except (TypeError, ValueError, UnicodeDecodeError, AttributeError) as exc:
            raise WebXlsxP01RequestError("invalid private Engine response") from exc
        if (status != 202 or not isinstance(body, dict)
                or set(body) != {"ok", "tool"} or body.get("ok") is not True
                or not isinstance(body.get("tool"), dict)
                or body["tool"].get("status") != "paused"):
            raise WebXlsxP01RequestError("Engine did not issue a P01 pause")
        return body

    async def resume_owner_decision(
        self, *, continuation_ref: str, submission: dict[str, Any],
    ) -> dict[str, Any]:
        """One private Engine continuation; no tool or arguments in resume.

        The owner session and continuation are independently looked up in B62
        private D1 by the caller. The Engine still has to verify the decision
        and issue a server-only ToolRuntime confirmation grant.
        """
        from .claw_web_xlsx_p01_request import _CONT
        if (not isinstance(continuation_ref, str)
                or not _CONT.fullmatch(continuation_ref)
                or not isinstance(submission, dict)
                or set(submission) != {
                    "decision_id", "pause_id", "outcome", "authority_ref",
                    "evidence_ref", "decided_at",
                }
                or submission.get("outcome") not in ("approved", "denied")):
            raise WebXlsxP01RequestError("invalid trusted owner decision")
        encoded = json.dumps(
            {"app_id": _APP, "continuation_ref": continuation_ref,
             "decision": submission},
            separators=(",", ":"), ensure_ascii=False,
        )
        if len(encoded.encode("utf-8")) > _MAX_BODY_BYTES:
            raise WebXlsxP01RequestError("owner decision exceeds internal bound")
        req = self._request_factory(
            f"{ENGINE_INTERNAL_ORIGIN}/internal/v1/tools/resume",
            method="POST",
            headers={
                "content-type": "application/json", "accept": "application/json",
                "x-padiem-engine-caller": self._caller_id,
                "x-padiem-engine-credential": self._credential,
            },
            body=encoded,
        )
        try:
            resp = await self._binding.fetch(req.js_object)
            raw = await read_bounded_service_binding_body(
                resp, max_bytes=_MAX_RESPONSE_BYTES,
            )
            status = int(resp.status)
            response = json.loads(raw.decode("utf-8"))
        except (ServiceBindingResponseError, ServiceBindingResponseTooLarge,
                TypeError, ValueError, UnicodeDecodeError, AttributeError) as exc:
            raise WebXlsxP01RequestError("private Engine decision response unavailable") from exc
        # Engine rejects approval without its own first-party tool grant.
        # Denial is a genuine consumed Core continuation (409), not a 200.
        if (submission["outcome"] == "denied"
                and status == 409 and isinstance(response, dict)
                and response.get("ok") is False
                and isinstance(response.get("error"), dict)
                and response["error"].get("code") == "approval_denied"):
            return {"ok": True, "status": "denied"}
        if (submission["outcome"] == "approved"
                and status == 200 and isinstance(response, dict)
                and response.get("ok") is True
                and isinstance(response.get("tool"), dict)
                and response["tool"].get("canonical_tool_id") == _TOOL
                and response["tool"].get("status") == "completed"
                and response["tool"].get("continuation_ref") == continuation_ref
                and isinstance(response["tool"].get("output"), dict)
                and response["tool"]["output"].get("p01_intent_confirmed") is True
                and response["tool"]["output"].get("read_executed") is False
                and response["tool"]["output"].get("workcopy_created") is False):
            return {"ok": True, "status": "confirmed"}
        raise WebXlsxP01RequestError("Engine did not verify owner P01 outcome")


WEB_XLSX_P01_TOOL_DISPATCH_FLAG = "PADIEM_WEB_XLSX_P01_TOOL_DISPATCH_ENABLED"


def build_web_xlsx_p01_engine_client(
    env: Any, *, request_factory: Any, runtime_mode: str,
) -> CloudflareWebXlsxP01EngineClient | None:
    """Operator-only composition using the existing P01 Engine caller.

    No new Secrets, credential, remote URL, public token or generic tool
    executor. The Engine must *separately* enable its trusted selection scope
    resolver; this function cannot grant Engine-side permissions.
    """
    from .worker_config import binding_value, p01_engine_config_from_worker_bindings

    if (runtime_mode != "b14"
            or binding_value(env, WEB_XLSX_P01_TOOL_DISPATCH_FLAG) != "true"):
        return None
    try:
        config = p01_engine_config_from_worker_bindings(env)
        if config is None:
            return None
        return CloudflareWebXlsxP01EngineClient(
            config.service_binding,
            caller_id=config.caller_id,
            credential=config.credential,
            request_factory=request_factory,
        )
    except Exception:
        return None
