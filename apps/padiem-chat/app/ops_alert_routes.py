"""#8105: 운영센터 알림 상태·다시 보내기 — 관리자 전용.

다른 관리자 화면과 같은 `_central_admin` 가드를 첫 줄에서 쓴다. 열람과 다시
보내기는 각각 감사 기록(ops_audit_log) 한 줄을 남긴다. 게스트·일반 회원에게는
API도 화면도 없다.
"""
from __future__ import annotations

from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .central_model_control_routes import _central_admin
from .ops_alert_delivery import retry_pending_alerts
from .ops_alert_store import OpsAlertUnavailable

_NO_STORE = {'Cache-Control': 'private, no-store, max-age=0', 'Pragma': 'no-cache',
             'X-Content-Type-Options': 'nosniff'}


def _response(payload, status=200):
    return JSONResponse(payload, status_code=status, headers=dict(_NO_STORE))


def _error(code, status):
    return _response({'ok': False, 'error': {'code': code}}, status)


def _store(request):
    return getattr(request.app.state, 'ops_alert_store', None)


async def _audit(request, *, action, detail=None):
    audit = getattr(request.app.state, 'ops_audit_store', None)
    actor = current_user_id(request) if auth_ready(request) else None
    if audit is None or not actor:
        return
    await audit.append(actor_user_id=actor, action=action,
                       target_type='ops_alert', target_id='outbox',
                       detail=detail)


async def admin_ops_alerts(request):
    """채널별 마지막 성공·실패와 대기 개수. 열람도 감사 기록을 남긴다."""
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    store = _store(request)
    if store is None:
        return _error('ops_alert_unavailable', 503)
    if set(request.query_params):
        return _error('ops_alert_invalid_request', 400)
    try:
        status = await store.status()
    except OpsAlertUnavailable:
        return _error('ops_alert_unavailable', 503)
    notifier = getattr(request.app.state, 'b66_signup_notifier', None)
    configured = sorted(getattr(notifier, 'channels', {}) or {})
    await _audit(request, action='ops_alert_view',
                 detail={'pending': status['pending']})
    return _response({'ok': True, 'configured': configured, **status})


async def admin_ops_alerts_dispatch(request):
    """대기함을 다시 보낸다 — 이미 보낸 채널로는 다시 가지 않는다."""
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    store = _store(request)
    if store is None:
        return _error('ops_alert_unavailable', 503)
    notifier = getattr(request.app.state, 'b66_signup_notifier', None)
    if not getattr(notifier, 'channels', None):
        return _error('ops_alert_not_configured', 503)
    try:
        result = await retry_pending_alerts(request, limit=5)
    except Exception:
        return _error('ops_alert_dispatch_failed', 503)
    await _audit(request, action='ops_alert_dispatch', detail=result)
    return _response({'ok': True, 'result': result})


def register_ops_alert_routes(routes: list) -> None:
    from starlette.routing import Route
    routes.extend([
        Route('/api/admin/ops-alerts', admin_ops_alerts, methods=['GET']),
        Route('/api/admin/ops-alerts/dispatch', admin_ops_alerts_dispatch,
              methods=['POST']),
    ])