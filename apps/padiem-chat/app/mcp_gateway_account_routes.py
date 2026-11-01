"""Existing authenticated PADIEM account UI manages MCP credentials/decisions."""
from __future__ import annotations

import json

from starlette.responses import JSONResponse

from .auth_routes import current_user_id
from .mcp_gateway_store import McpGatewayStoreError
from .same_origin_guard import expected_browser_origin


MCP_TOKENS_PATH = "/api/account/mcp/tokens"
MCP_TOKEN_PATH = MCP_TOKENS_PATH + "/{token_id}"
MCP_APPROVALS_PATH = "/api/account/mcp/approvals"
MCP_APPROVAL_PATH = MCP_APPROVALS_PATH + "/{approval_id}"
_NO_STORE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}


class McpGatewayUnavailable(RuntimeError):
    """Public transport maps this to 503 without logging credential material."""


def _response(body, status=200):
    return JSONResponse(body, status_code=status, headers=_NO_STORE)


def _error(status, code, message):
    return _response({"error": {"code": code, "message": message}}, status)


def _unavailable():
    return _error(503, "mcp_settings_unavailable", "외부 AI 연결 설정을 지금 불러오지 못했습니다. 잠시 뒤 다시 시도해 주세요.")


def _mutation_origin(request):
    # Reuse the central origin authority for both legacy and shared-login
    # sessions, including a shared-login request without padiem_session cookie.
    expected = expected_browser_origin(request.app.state.settings)
    if expected is None:
        return _error(503, "origin_guard_unavailable", "요청 출처 확인을 사용할 수 없습니다.")
    if request.headers.get("origin", "").strip() != expected:
        return _error(403, "origin_rejected", "요청 출처를 확인할 수 없습니다.")
    return None


def _store(request):
    store = getattr(request.app.state, "mcp_gateway_store", None)
    if store is None:
        raise McpGatewayUnavailable("MCP settings unavailable")
    return store


async def _paired_device(request, owner_id, device_id):
    pairing = getattr(request.app.state, "pc_device_pairing_store", None)
    if pairing is None:
        raise McpGatewayUnavailable("PC pairing unavailable")
    # Existing authority excludes revoked/paused links and supplies only active
    # roots. This is re-read on every bearer request, not cached at issuance.
    return await pairing.link_for(user_id=owner_id, mesh_node_id=device_id)


async def authenticate_mcp_request(request) -> dict | None:
    """Bearer credentials never inherit an ambient browser cookie's owner."""
    header = request.headers.get("authorization", "")
    parts = header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    try:
        identity = await _store(request).authenticate(parts[1])
        if identity is None or not await _paired_device(request, identity["user_id"], identity["device_id"]):
            return None
    except Exception as exc:
        raise McpGatewayUnavailable("MCP authentication unavailable") from exc
    return {"owner_id": identity["user_id"], "device_id": identity["device_id"],
            "token_id": identity["token_id"], "name": identity["name"]}


async def _json(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise McpGatewayStoreError("JSON request required")
    try:
        value = json.loads((await request.body()).decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise McpGatewayStoreError("Invalid JSON") from exc
    if not isinstance(value, dict):
        raise McpGatewayStoreError("JSON object required")
    return value


async def mcp_tokens_get(request):
    owner = current_user_id(request)
    if not owner:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    try:
        return _response({"ok": True, "tokens": await _store(request).list_tokens(user_id=owner)})
    except Exception:
        return _unavailable()


async def mcp_tokens_post(request):
    owner = current_user_id(request)
    if not owner:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    denied = _mutation_origin(request)
    if denied is not None:
        return denied
    try:
        body = await _json(request)
        if set(body) != {"name", "device_id"}:
            raise McpGatewayStoreError("Unexpected credential fields")
        if not isinstance(body["device_id"], str):
            raise McpGatewayStoreError("Invalid device")
        if not await _paired_device(request, owner, body["device_id"]):
            return _error(403, "pc_device_unavailable", "현재 연결된 내 PC를 선택해 주세요.")
        issued = await _store(request).issue_token(user_id=owner, device_id=body["device_id"], name=body["name"])
    except (McpGatewayStoreError, ValueError):
        return _error(422, "invalid_mcp_token", "연결 이름과 내 PC를 확인해 주세요.")
    except Exception:
        return _unavailable()
    return _response({"ok": True, **issued}, 201)


async def mcp_token_delete(request):
    owner = current_user_id(request)
    if not owner:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    denied = _mutation_origin(request)
    if denied is not None:
        return denied
    try:
        revoked = await _store(request).revoke_token(user_id=owner, token_id=request.path_params["token_id"])
    except Exception:
        return _unavailable()
    if not revoked:
        return _error(404, "mcp_token_not_found", "연결을 찾을 수 없습니다.")
    return _response({"ok": True})


async def mcp_approvals_get(request):
    owner = current_user_id(request)
    if not owner:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    try:
        return _response({"ok": True, "approvals": await _store(request).list_approvals(user_id=owner)})
    except Exception:
        return _unavailable()


async def mcp_approval_post(request):
    owner = current_user_id(request)
    if not owner:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    denied = _mutation_origin(request)
    if denied is not None:
        return denied
    try:
        body = await _json(request)
        if set(body) != {"decision", "request_digest"}:
            raise McpGatewayStoreError("Unexpected decision fields")
        store = _store(request)
        pending = await store.get_approval(user_id=owner, approval_id=request.path_params["approval_id"])
        if pending is None or not await _paired_device(request, owner, pending["device_id"]):
            return _error(404, "mcp_approval_not_found", "확인할 작업을 찾을 수 없습니다.")
        approved = await store.decide_approval(user_id=owner, approval_id=pending["id"],
                                              request_digest=body["request_digest"], decision=body["decision"])
    except (McpGatewayStoreError, ValueError):
        return _error(422, "invalid_mcp_decision", "확인할 작업과 선택을 다시 확인해 주세요.")
    except Exception:
        return _unavailable()
    if approved is None:
        return _error(409, "mcp_approval_unavailable", "이미 처리했거나 시간이 지난 작업입니다. 외부 AI에서 다시 요청해 주세요.")
    return _response({"ok": True, "approval": approved})
