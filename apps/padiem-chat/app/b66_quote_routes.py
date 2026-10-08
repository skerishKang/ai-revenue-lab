"""Authenticated B66 Saved Quote Skill + conversation routes (#3303).

Normal customer runtime:
signed-in Padiem owner -> assigned server-side Saved Quote Skill -> one bounded
conversation-to-variable extraction -> browser-side SavedQuoteSkill/QuoteCore/
approved renderer.

No source quotation parsing, server-side totals calculation, template mutation,
or arbitrary tenant selection occurs here.
"""

from __future__ import annotations

import inspect
import json
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .b14_client import ChatRuntimeError
from .b66_registered_model_boundary import B66ModelRouteError
from .b66_quote_conversation import (
    B66QuoteConversationError,
    MAX_CONVERSATION_CHARS,
)
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .claw_memory_routes import _resolve_memory_workspace

MAX_BODY_BYTES = 16 * 1024
MAX_LIST_LIMIT = 20
_FORBIDDEN_OWNER_KEYS = frozenset(
    {"user_id", "userId", "tenant_id", "tenantId", "workspace_id", "workspaceId", "owner"}
)
_NO_STORE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}

# Bounded rejection diagnostics (#3391): the 422 response may carry the
# structured reason / field path / JSON type name of the failed conversation
# validation. Header values are allowlist-checked so customer text or model
# output can never reach the response regardless of what a raise site attaches.
_REJECTION_REASON_RE = re.compile(r"^[a-z_]{1,64}$")
_REJECTION_PATH_RE = re.compile(r"^[A-Za-z0-9_.\[\]]{1,64}$")
_REJECTION_TYPE_RE = re.compile(r"^[a-z]{1,16}$")


# Bounded 502 upstream diagnostics (#3391): a provider/runtime failure may carry
# only a product-owned fixed upstream class. For broad errors this is the public
# ``ChatRuntimeError.code``; malformed-answer failures may additionally carry a
# narrower internal ``upstream_class``. Raw exception text, provider payloads,
# model output and customer values are never part of this header.
#
# Every value here is reachable on this lane today, which is what keeps "header
# present" meaningful. Broad Core/provider classes come from
# ``b14_client._chat_error``; the five ``upstream_*content/shape/json/empty*``
# values are bounded internal refinements of the existing malformed-answer
# public contract. ``upstream_binding_unavailable`` is raised by the
# Production-composed ``DispatchAwareB14Client.complete`` itself when the required B14 Service
# Binding is absent (``require_service_binding`` True with
# ``service_transport`` None, as composed in ``worker.py``).
#
# Deliberately outside the allowlist: request/policy classes such as
# ``model_profile_unassigned`` (unreachable here — the B66 lane never binds a
# request tier, so policy resolution always yields the executable Padiem Plus
# default), ``tier_unavailable`` / ``unknown_model_alias`` (only for a quote text
# that literally begins with a slash alias) and ``invalid_request`` (Core
# request-contract rejection, not an upstream class).
_UPSTREAM_CLASS_ALLOWLIST = frozenset(
    {
        "upstream_timeout",
        "upstream_busy",
        "upstream_response_too_large",
        "malformed_upstream",
        "upstream_malformed_json",
        "upstream_unexpected_shape",
        "upstream_missing_content",
        "upstream_non_text_content",
        "upstream_empty_answer",
        "upstream_unavailable",
        "provider_auth_error",
        "provider_route_error",
        "provider_server_error",
        "upstream_execution_failed",
        "upstream_error",
        "upstream_binding_unavailable",
    }
)


def _upstream_class_headers(exc: BaseException) -> dict[str, str]:
    if not isinstance(exc, ChatRuntimeError):
        return {}
    upstream_class = getattr(exc, "upstream_class", None)
    code = (
        upstream_class
        if isinstance(upstream_class, str)
        else getattr(exc, "code", None)
    )
    if not isinstance(code, str) or code not in _UPSTREAM_CLASS_ALLOWLIST:
        return {}
    return {"X-B66-Upstream-Class": code}


# Closed-vocabulary 502 provenance diagnostics for CGI freeform (#3751).
# Do not expose exceptions/messages/provider payloads/user input in headers.
_B66_INTERPRET_FAILURE_STAGES = frozenset({
    "interpreter_exception",
    "projection_missing_safe_dict",
})
_B66_INTERPRET_EXCEPTION_FAMILIES = frozenset({
    "chat_runtime_non_upstream",
    "type_error",
    "value_error",
    "runtime_error",
    "unexpected_exception",
})


def _bounded_interpret_exception_family(exc: BaseException) -> str:
    if isinstance(exc, ChatRuntimeError):
        return "chat_runtime_non_upstream"
    if isinstance(exc, TypeError):
        return "type_error"
    if isinstance(exc, ValueError):
        return "value_error"
    if isinstance(exc, RuntimeError):
        return "runtime_error"
    return "unexpected_exception"


def _rejection_diagnostic_headers(exc: BaseException) -> dict[str, str]:
    headers: dict[str, str] = {}
    reason = getattr(exc, "message", None)
    if isinstance(reason, str) and _REJECTION_REASON_RE.fullmatch(reason):
        headers["X-B66-Rejection-Reason"] = reason
    path = getattr(exc, "path", None)
    if isinstance(path, str) and _REJECTION_PATH_RE.fullmatch(path):
        headers["X-B66-Rejection-Path"] = path
    observed_type = getattr(exc, "observed_type", None)
    if isinstance(observed_type, str) and _REJECTION_TYPE_RE.fullmatch(observed_type):
        headers["X-B66-Rejection-Type"] = observed_type
    return headers


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status,
        headers=_NO_STORE,
    )


def _owner(request: Request) -> str | None:
    if not auth_ready(request):
        return None
    try:
        return current_user_id(request)
    except Exception:
        return None


def _store(request: Request) -> Any | None:
    return getattr(request.app.state, "b66_saved_quote_skill_store", None)


def _company_profile_store(request: Request) -> Any | None:
    return getattr(request.app.state, "b66_company_profile_store", None)


async def _json(request: Request) -> dict[str, Any] | JSONResponse:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "unsupported_media_type", "JSON 요청만 허용됩니다.")
    try:
        body = await read_bounded_request_body(request, max_bytes=MAX_BODY_BYTES)
    except RequestBodyTooLarge:
        return _error(413, "request_too_large", "요청 크기가 너무 큽니다.")
    if not body:
        return _error(400, "empty_request_body", "요청 본문이 비어 있습니다.")
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json", "유효한 JSON 형식이 아닙니다.")
    if not isinstance(data, dict):
        return _error(400, "invalid_payload", "요청 데이터는 객체여야 합니다.")
    if any(key in data for key in _FORBIDDEN_OWNER_KEYS):
        return _error(400, "forbidden_owner_field", "계정 범위는 서버가 결정합니다.")
    return data


async def b66_runtime_config(request: Request) -> JSONResponse:
    uid = _owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    base = getattr(request.app.state, "b66_quote_base_url", None)
    if not isinstance(base, str) or not base:
        return JSONResponse(
            {"ok": True, "enabled": False, "embed_url": None, "origin": None},
            headers=_NO_STORE,
        )
    return JSONResponse(
        {
            "ok": True,
            "enabled": True,
            "embed_url": base.rstrip("/") + "/embed.html",
            "origin": base.rstrip("/"),
        },
        headers=_NO_STORE,
    )


async def b66_saved_skills(request: Request) -> JSONResponse:
    uid = _owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    store = _store(request)
    list_fn = getattr(store, "list_skills", None) if store is not None else None
    if not callable(list_fn):
        return _error(503, "saved_quote_skill_unavailable", "내 견적서를 사용할 수 없습니다.")
    raw_limit = request.query_params.get("limit")
    try:
        limit = MAX_LIST_LIMIT if raw_limit is None else int(raw_limit)
    except (TypeError, ValueError):
        return _error(400, "invalid_limit", "limit 형식이 올바르지 않습니다.")
    if limit < 1:
        return _error(400, "invalid_limit", "limit 형식이 올바르지 않습니다.")
    workspace_id = await _resolve_memory_workspace(request, uid)
    try:
        value = list_fn(user_id=uid, workspace_id=workspace_id, limit=min(limit, MAX_LIST_LIMIT))
        skills = await value if inspect.isawaitable(value) else value
    except Exception:
        return _error(503, "saved_quote_skill_read_failed", "내 견적서를 불러오지 못했습니다.")
    if not isinstance(skills, list):
        return _error(503, "saved_quote_skill_read_failed", "내 견적서를 불러오지 못했습니다.")
    return JSONResponse({"ok": True, "skills": skills}, headers=_NO_STORE)


async def b66_saved_skill_detail(request: Request) -> JSONResponse:
    uid = _owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    saved_skill_id = request.path_params.get("saved_skill_id", "")
    store = _store(request)
    get_fn = getattr(store, "get_skill", None) if store is not None else None
    if not callable(get_fn):
        return _error(503, "saved_quote_skill_unavailable", "내 견적서를 사용할 수 없습니다.")
    workspace_id = await _resolve_memory_workspace(request, uid)
    try:
        value = get_fn(
            user_id=uid,
            workspace_id=workspace_id,
            saved_skill_id=saved_skill_id,
        )
        skill = await value if inspect.isawaitable(value) else value
    except Exception:
        return _error(400, "invalid_saved_skill_id", "내 견적서 ID 형식이 올바르지 않습니다.")
    if skill is None:
        return _error(404, "saved_quote_skill_not_found", "내 견적서를 찾을 수 없습니다.")
    return JSONResponse({"ok": True, "saved_skill": skill}, headers=_NO_STORE)


async def b66_quote_interpret(request: Request) -> JSONResponse:
    uid = _owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    data = await _json(request)
    if isinstance(data, JSONResponse):
        return data
    if set(data) - {"saved_skill_id", "message"}:
        return _error(400, "unsupported_field", "지원되지 않는 요청 필드가 있습니다.")
    saved_skill_id = data.get("saved_skill_id")
    message = data.get("message")
    if not isinstance(saved_skill_id, str) or not saved_skill_id:
        return _error(400, "invalid_saved_skill_id", "내 견적서 ID가 필요합니다.")
    if (
        not isinstance(message, str)
        or not message.strip()
        or len(message.strip()) > MAX_CONVERSATION_CHARS
    ):
        return _error(400, "invalid_message", "견적 요청 내용을 입력해 주세요.")

    store = _store(request)
    get_fn = getattr(store, "get_skill", None) if store is not None else None
    interpreter = getattr(request.app.state, "b66_quote_interpreter", None)
    interpret_fn = getattr(interpreter, "interpret", None) if interpreter is not None else None
    if not callable(get_fn) or not callable(interpret_fn):
        return _error(503, "quote_runtime_unavailable", "견적 대화 기능을 사용할 수 없습니다.")

    workspace_id = await _resolve_memory_workspace(request, uid)
    try:
        value = get_fn(
            user_id=uid,
            workspace_id=workspace_id,
            saved_skill_id=saved_skill_id,
        )
        saved = await value if inspect.isawaitable(value) else value
    except Exception:
        return _error(400, "invalid_saved_skill_id", "내 견적서 ID 형식이 올바르지 않습니다.")
    if saved is None:
        return _error(404, "saved_quote_skill_not_found", "내 견적서를 찾을 수 없습니다.")
    skill = saved.get("skill") if isinstance(saved, dict) else None
    if not isinstance(skill, dict):
        return _error(503, "saved_quote_skill_invalid", "내 견적서 데이터를 확인할 수 없습니다.")

    try:
        value = interpret_fn(message=message.strip(), skill=skill)
        projection = await value if inspect.isawaitable(value) else value
    except B66ModelRouteError as exc:
        # B14 model authority unavailable/ambiguous is not a provider 5xx.
        # Closed vocabulary only; never return messages, customer data or
        # provider catalog bodies.
        response = _error(
            503,
            "quote_model_unavailable",
            "?? ??? ? ?? ?? AI ??? ????. ?? ? ?? ??? ???.",
        )
        response.headers["X-B66-Model-Selection-Status"] = (
            "ambiguous" if exc.code == "selection_ambiguous" else "unavailable"
        )
        return response
    except B66QuoteConversationError as exc:
        response = _error(422, "quote_input_unrecognized", "견적 입력값을 확인해 주세요.")
        for header_name, header_value in _rejection_diagnostic_headers(exc).items():
            response.headers[header_name] = header_value
        return response
    except Exception as exc:
        response = _error(502, "quote_interpretation_failed", "견적 요청을 해석하지 못했습니다.")
        for header_name, header_value in _upstream_class_headers(exc).items():
            response.headers[header_name] = header_value
        response.headers["X-B66-Interpret-Failure-Stage"] = "interpreter_exception"
        # A recognized upstream class already identifies the failure; the
        # broader family is needed only when no upstream class is available.
        if "X-B66-Upstream-Class" not in response.headers:
            response.headers["X-B66-Interpret-Exception-Family"] = (
                _bounded_interpret_exception_family(exc)
            )
        return response

    safe_dict = getattr(projection, "safe_dict", None)
    if not callable(safe_dict):
        response = _error(502, "quote_interpretation_failed", "견적 요청을 해석하지 못했습니다.")
        response.headers["X-B66-Interpret-Failure-Stage"] = (
            "projection_missing_safe_dict"
        )
        return response
    candidate = safe_dict()

    company_profile = None
    profile_store = _company_profile_store(request)
    get_profile = getattr(profile_store, "get_profile", None) if profile_store is not None else None
    if callable(get_profile):
        try:
            value = get_profile(user_id=uid, workspace_id=workspace_id)
            company_profile = await value if inspect.isawaitable(value) else value
        except Exception:
            return _error(503, "company_profile_read_failed", "회사정보를 불러오지 못했습니다.")

    return JSONResponse(
        {
            "ok": True,
            "saved_skill": {
                "saved_skill_id": saved.get("saved_skill_id"),
                "skill_id": saved.get("skill_id"),
                "skill_name": saved.get("skill_name"),
                "skill_fingerprint": saved.get("skill_fingerprint"),
                "skill_version": saved.get("skill_version"),
            },
            "candidate": candidate,
            "company_profile": company_profile,
            "execution": {
                "source_document_parse_calls": 0,
                "server_total_calculation": False,
                "server_rendering": False,
                "browser_quote_core_required": True,
                "browser_approved_renderer_required": True,
            },
        },
        headers=_NO_STORE,
    )
