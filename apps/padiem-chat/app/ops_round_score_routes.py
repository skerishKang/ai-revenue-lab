"""#8035 ③ (#7718 흡수): 회차 점수 입력·수정·숨김 라우트 — 관리자 전용.

모든 핸들러가 다른 관리자 화면과 같은 `_central_admin` 가드를 첫 줄에서 쓴다.
열람·입력·수정·숨김은 각각 감사 기록(ops_audit_log, 128) 한 줄을 남긴다.
게스트·일반 회원에게는 API도 화면도 없다(게스트 `/api/*` 0건 계약).
"""
from __future__ import annotations

import json

from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .central_model_control_routes import _central_admin
from .ops_round_score_store import (
    RoundScoreConflict,
    RoundScoreInvalid,
    RoundScoreMissing,
    RoundScoreUnavailable,
)

_NO_STORE = {'Cache-Control': 'private, no-store, max-age=0', 'Pragma': 'no-cache',
             'X-Content-Type-Options': 'nosniff'}
_CREATE_KEYS = frozenset({'persona_name', 'round_no', 'round_on', 'source',
                          'return_score', 'pretty_score', 'memo'})
_UPDATE_KEYS = _CREATE_KEYS
_BODY_MAX = 4096


def _response(payload, status=200):
    return JSONResponse(payload, status_code=status, headers=dict(_NO_STORE))


def _error(code, status):
    return _response({'ok': False, 'error': {'code': code}}, status)


def _store(request):
    return getattr(request.app.state, 'ops_round_score_store', None)


def _audit_store(request):
    return getattr(request.app.state, 'ops_audit_store', None)


def _actor(request):
    return current_user_id(request) if auth_ready(request) else None


async def _audit(request, *, action, target_id, detail=None):
    audit = _audit_store(request)
    actor = _actor(request)
    if audit is None or not actor:
        return
    await audit.append(actor_user_id=actor, action=action,
                       target_type='round_score', target_id=target_id,
                       detail=detail)


async def _body(request):
    raw = await request.body()
    if len(raw) > _BODY_MAX:
        raise RoundScoreInvalid()
    try:
        data = json.loads(raw or b'{}')
    except (TypeError, ValueError):
        raise RoundScoreInvalid() from None
    if not isinstance(data, dict):
        raise RoundScoreInvalid()
    return data


def _days(request):
    raw = request.query_params.get('days')
    if raw is None:
        return 30
    if not raw.isdigit():
        raise RoundScoreInvalid()
    value = int(raw)
    if not 1 <= value <= 365:
        raise RoundScoreInvalid()
    return value


async def admin_round_scores(request):
    """목록(열람). 기간·고객 이름으로 좁힐 수 있고, 열람도 감사 기록을 남긴다."""
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    store = _store(request)
    if store is None:
        return _error('ops_round_score_unavailable', 503)
    params = request.query_params
    if set(params) - {'days', 'persona'}:
        return _error('ops_round_score_invalid_request', 400)
    persona = params.get('persona') or None
    try:
        days = _days(request)
        scores = await store.list_scores(persona=persona, limit=100)
        journal = await store.journal(days=days)
    except RoundScoreInvalid:
        return _error('ops_round_score_invalid_request', 400)
    except RoundScoreUnavailable:
        return _error('ops_round_score_unavailable', 503)
    await _audit(request, action='round_score_view', target_id='list',
                 detail={'days': days, 'persona': bool(persona)})
    return _response({'ok': True, 'scores': scores, 'journal': journal})


async def admin_round_score_create(request):
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    store = _store(request)
    if store is None:
        return _error('ops_round_score_unavailable', 503)
    actor = _actor(request)
    if not actor:
        return _error('authentication_required', 401)
    try:
        data = await _body(request)
        if set(data) - _CREATE_KEYS or not _CREATE_KEYS - {'memo'} <= set(data):
            return _error('ops_round_score_invalid_request', 400)
        row = await store.create(actor=actor, **data)
    except RoundScoreInvalid:
        return _error('ops_round_score_invalid_request', 400)
    except RoundScoreConflict:
        return _error('ops_round_score_conflict', 409)
    except RoundScoreUnavailable:
        return _error('ops_round_score_unavailable', 503)
    await _audit(request, action='round_score_create', target_id=row['id'],
                 detail={'persona': row['persona_name'], 'round': row['round_no'],
                         'source': row['source'], 'return': row['return_score'],
                         'pretty': row['pretty_score']})
    # #8105: 알림은 저장 성공 뒤. 문구에는 고정 분류만 싣고 고객 이름·출처
    # 값은 싣지 않는다(분류 칸은 서버가 정하는 낱말만 받는다).
    from .ops_alert_delivery import enqueue_and_deliver
    await enqueue_and_deliver(request, kind='round_score',
                              target_id=row['id'], label='round_score')
    return _response({'ok': True, 'score': row})


async def admin_round_score_update(request):
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    store = _store(request)
    if store is None:
        return _error('ops_round_score_unavailable', 503)
    actor = _actor(request)
    if not actor:
        return _error('authentication_required', 401)
    score_id = request.path_params.get('score_id', '')
    try:
        data = await _body(request)
        if set(data) - _UPDATE_KEYS:
            return _error('ops_round_score_invalid_request', 400)
        row = await store.update(score_id, actor=actor, changes=data)
    except RoundScoreInvalid:
        return _error('ops_round_score_invalid_request', 400)
    except RoundScoreMissing:
        return _error('ops_round_score_not_found', 404)
    except RoundScoreConflict:
        return _error('ops_round_score_conflict', 409)
    except RoundScoreUnavailable:
        return _error('ops_round_score_unavailable', 503)
    await _audit(request, action='round_score_update', target_id=score_id,
                 detail={'fields': sorted(data)})
    return _response({'ok': True, 'score': row})


async def admin_round_score_hide(request):
    """지우기 = 숨김. 행은 남고 감사 기록이 무엇을 숨겼는지 기억한다."""
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    store = _store(request)
    if store is None:
        return _error('ops_round_score_unavailable', 503)
    actor = _actor(request)
    if not actor:
        return _error('authentication_required', 401)
    score_id = request.path_params.get('score_id', '')
    try:
        row = await store.hide(score_id, actor=actor)
    except RoundScoreMissing:
        return _error('ops_round_score_not_found', 404)
    except RoundScoreInvalid:
        return _error('ops_round_score_invalid_request', 400)
    except RoundScoreUnavailable:
        return _error('ops_round_score_unavailable', 503)
    await _audit(request, action='round_score_hide', target_id=score_id,
                 detail={'persona': row['persona_name'], 'round': row['round_no']})
    return _response({'ok': True, 'score': row})


def register_ops_round_score_routes(routes: list) -> None:
    from starlette.routing import Route
    routes.extend([
        Route('/api/admin/round-scores', admin_round_scores, methods=['GET']),
        Route('/api/admin/round-scores', admin_round_score_create, methods=['POST']),
        Route('/api/admin/round-scores/{score_id}', admin_round_score_update,
              methods=['PATCH']),
        Route('/api/admin/round-scores/{score_id}', admin_round_score_hide,
              methods=['DELETE']),
    ])