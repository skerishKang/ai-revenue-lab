"""Fixed internal Cloudflare ToolRuntime transport for independent XLSX WRITE P01.

No user URL, arguments, token, pause or continuation are accepted from web.
Reuses existing private P01 Engine caller identity; never retries failures.
"""
from __future__ import annotations
import json
import re
from typing import Any
from padiem_ai_engine_client import ENGINE_INTERNAL_ORIGIN
from .web_xlsx_p01_engine_client import CloudflareWebXlsxP01EngineClient
from .claw_web_xlsx_p01_request import WebXlsxP01RequestError, _CONT
from .service_binding_response import (
    ServiceBindingResponseError, ServiceBindingResponseTooLarge,
    read_bounded_service_binding_body,
)
from .claw_web_xlsx_quote_write_store import D1WebQuoteWriteReceiptStore

_APP="padiem-web-xlsx-write-p01"
_AGENT="agent:padiem:web-xlsx-quote-write@1"
_TOOL="tool:padiem:web-xlsx-quote-write@1"
_RUNTIME="workspace.xlsx.quote.revise_workcopy"
_MAX=12288
_P=re.compile(r"pause:[0-9a-f]{24,64}")

class CloudflareWebQuoteWriteP01Client(CloudflareWebXlsxP01EngineClient):
    async def _send(self,route,payload):
        encoded=json.dumps(payload,ensure_ascii=False,separators=(",",":"))
        if len(encoded.encode("utf-8"))>3072:
            raise WebXlsxP01RequestError("bounded WRITE ToolRuntime payload exceeded")
        request=self._request_factory(
            ENGINE_INTERNAL_ORIGIN+route,method="POST",headers={
                "content-type":"application/json","accept":"application/json",
                "x-padiem-engine-caller":self._caller_id,
                "x-padiem-engine-credential":self._credential,
            },body=encoded,
        )
        try:
            response=await self._binding.fetch(request.js_object)
            raw=await read_bounded_service_binding_body(response,max_bytes=_MAX)
            status=int(response.status)
            body=json.loads(raw.decode("utf-8"))
            if not isinstance(body,dict):
                raise ValueError("Engine object required")
        except (ServiceBindingResponseError,ServiceBindingResponseTooLarge,
                TypeError,ValueError,UnicodeDecodeError,AttributeError) as exc:
            raise WebXlsxP01RequestError("private Core WRITE response unknown") from exc
        return status,body

    async def start_pause(self,row:dict[str,Any])->dict[str,Any]:
        D1WebQuoteWriteReceiptStore.validate(row)
        if row.get("owner_id")!=row["user_id"]:
            raise WebXlsxP01RequestError("trusted owner WRITE scope required")
        data={
            "app_id":_APP,"agent_id":_AGENT,"tool_id":_TOOL,
            "arguments":{
                **{k:row[k] for k in (
                    "owner_id","workspace_id","run_id","selection_ref",
                    "source_document_id","source_sha256","workcopy_document_id",
                    "edit_sha256","school_name","supply_amount")},
                "workcopy_sha256":row["source_sha256"],
                "operation":"xlsx.quote.revise_workcopy",
                "source_kind":"browser_upload",
                "original_immutable":True,"overwrite_original":False,
                "write_intent_only":True,"drive_write":False,
                "local_pc_access":False,"pdf_exported":False,
            },
        }
        status,body=await self._send("/internal/v1/tools/execute",data)
        tool=body.get("tool")
        if (status!=202 or body.get("ok") is not True
                or type(tool) is not dict
                or tool.get("canonical_tool_id")!=_TOOL
                or tool.get("status")!="paused"
                or type(tool.get("approval_pause")) is not dict):
            raise WebXlsxP01RequestError("independent Core WRITE pause unavailable")
        p=tool["approval_pause"]
        pause_id=p.get("continuation_id")
        ref=tool.get("continuation_ref")
        expiry=p.get("expires_at")
        if (type(pause_id) is not str or not _P.fullmatch(pause_id)
                or type(ref) is not str or not _CONT.fullmatch(ref)
                or type(expiry) is not str):
            raise WebXlsxP01RequestError("invalid paused Core WRITE identity")
        return {
            "status":"paused","pause_id":pause_id,
            "continuation_ref":ref,"expires_at":expiry,
        }

    async def resume_owner_decision(self,*,continuation_ref,submission):
        if (type(continuation_ref) is not str
                or not _CONT.fullmatch(continuation_ref)
                or type(submission) is not dict
                or set(submission)!={
                    "decision_id","pause_id","outcome","authority_ref",
                    "evidence_ref","decided_at"}
                or submission["outcome"] not in ("approved","denied")
                or type(submission["pause_id"]) is not str
                or not _P.fullmatch(submission["pause_id"])):
            raise WebXlsxP01RequestError("trusted WRITE decision required")
        status,body=await self._send("/internal/v1/tools/resume",{
            "app_id":_APP,"continuation_ref":continuation_ref,
            "decision":submission,
        })
        if (submission["outcome"]=="denied"
                and status==409 and body.get("ok") is False
                and type(body.get("error")) is dict
                and body["error"].get("code")=="approval_denied"):
            return {"ok":True,"status":"denied"}
        tool=body.get("tool")
        if (status!=200 or body.get("ok") is not True
                or type(tool) is not dict
                or tool.get("canonical_tool_id")!=_TOOL
                or tool.get("status")!="completed"
                or tool.get("continuation_ref")!=continuation_ref
                or type(tool.get("output")) is not dict):
            raise WebXlsxP01RequestError("Core did not confirm exact WRITE")
        output=tool["output"]
        if set(output)!={
                "ok","core_tool_completed","operation","owner_id",
                "workspace_id","run_id","source_document_id","source_sha256",
                "workcopy_document_id","workcopy_sha256","edit_sha256",
                "pdf_exported"} or output.get("ok") is not True or output.get("core_tool_completed") is not True:
            raise WebXlsxP01RequestError("Core WRITE proof incomplete")
        return {"ok":True,"status":"confirmed","proof":output}


WRITE_FLAG="PADIEM_WEB_XLSX_QUOTE_WRITE_ENABLED"

def build_web_quote_write_engine_client(env:Any,*,request_factory:Any,
                                        runtime_mode:str):
    """Explicit operator-controlled B62 configuration; independent Engine gate."""
    from .worker_config import binding_value,p01_engine_config_from_worker_bindings
    if (runtime_mode!="b14" or binding_value(env,WRITE_FLAG)!="true"
            or binding_value(env,"PADIEM_WEB_XLSX_P01_OWNER_DECISION_ENABLED")!="true"
            or binding_value(env,"PADIEM_WEB_XLSX_WORKCOPY_AFTER_P01_ENABLED")!="true"):
        return None
    try:
        config=p01_engine_config_from_worker_bindings(env)
        if config is None:return None
        return CloudflareWebQuoteWriteP01Client(
            config.service_binding,caller_id=config.caller_id,
            credential=config.credential,request_factory=request_factory,
        )
    except Exception:
        return None
