"""#8035 ②: the members tab routes — administrator-only, reusing the same
`_central_admin` guard every other admin surface uses. Opening a member's
detail leaves an audit row (who·when·which member); normal members and
guests have neither the screen nor the API (the guest `/api/*` contract).
"""
from __future__ import annotations


from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .central_model_control_routes import _central_admin
from .ops_member_store import MemberMissing, OpsMemberUnavailable

_NO_STORE = {'Cache-Control': 'private, no-store, max-age=0', 'Pragma': 'no-cache',
             'X-Content-Type-Options': 'nosniff'}


def _response(payload, status=200):
    return JSONResponse(payload, status_code=status, headers=dict(_NO_STORE))


def _error(code, status):
    return _response({'ok': False, 'error': {'code': code}}, status)


def _store(request):
    return getattr(request.app.state, 'ops_member_store', None)


def _audit_store(request):
    return getattr(request.app.state, 'ops_audit_store', None)


def _actor(request):
    return current_user_id(request) if auth_ready(request) else None


async def admin_members(request):
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    store = _store(request)
    if store is None:
        return _error('ops_member_unavailable', 503)
    query = request.query_params.get('query', '')
    cursor = request.query_params.get('cursor') or None
    if len(request.query_params) - (1 if query else 0) - (1 if cursor else 0) > 0:
        return _error('ops_member_invalid_request', 400)
    try:
        members, next_cursor = await store.list_members(query=query, cursor=cursor)
    except MemberMissing:
        return _error('ops_member_invalid_request', 400)
    except OpsMemberUnavailable:
        return _error('ops_member_unavailable', 503)
    return _response({'ok': True, 'members': members, 'next_cursor': next_cursor})


async def admin_member_detail(request):
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    store = _store(request)
    if store is None:
        return _error('ops_member_unavailable', 503)
    user_id = request.path_params.get('member_id', '')
    try:
        member = await store.get_member(user_id)
    except MemberMissing:
        return _error('ops_member_not_found', 404)
    except OpsMemberUnavailable:
        return _error('ops_member_unavailable', 503)
    actor = _actor(request)
    audit = _audit_store(request)
    if audit is not None and actor:
        # Opening a member's detail is a read an audit row must remember.
        await audit.append(actor_user_id=actor, action='member_detail_view',
                           target_type='member', target_id=user_id)
    return _response({'ok': True, 'member': member})


async def admin_ops_audit(request):
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    audit = _audit_store(request)
    if audit is None:
        return _error('ops_audit_unavailable', 503)
    try:
        rows = await audit.list_recent(limit=20)
    except Exception:
        return _error('ops_audit_unavailable', 503)
    return _response({'ok': True, 'audit': rows})


def register_ops_member_routes(routes: list) -> None:
    from starlette.routing import Route
    routes.extend([
        Route('/api/admin/members', admin_members, methods=['GET']),
        Route('/api/admin/members/{member_id}', admin_member_detail, methods=['GET']),
        Route('/api/admin/ops-audit', admin_ops_audit, methods=['GET']),
    ])
