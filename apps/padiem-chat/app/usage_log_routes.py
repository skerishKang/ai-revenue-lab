"""Admin-only usage log summary for the operations center.

Only counts already stored for AI honorary members are read. Round history,
'예쁜가' and the return score have no stored source yet and stay null/empty;
new data collection needs a separate decision and is not done here.
"""
from __future__ import annotations

from starlette.responses import JSONResponse

from .central_model_control_routes import _central_admin

_NO_STORE = {'Cache-Control': 'private, no-store, max-age=0', 'Pragma': 'no-cache',
             'X-Content-Type-Options': 'nosniff'}

METRICS = (
    ('active', '활동 명예회원'),
    ('left', '떠난 명예회원'),
    ('new', '새 의견'),
    ('resolved', '고침'),
    ('return', '평균 다시 올 점수'),
)


def _error(code: str, status: int) -> JSONResponse:
    return JSONResponse({'ok': False, 'error': {'code': code}}, status_code=status, headers=_NO_STORE)


async def admin_usage_log(request):
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    store = getattr(request.app.state, 'feedback_store', None)
    if store is None:
        return _error('feedback_unavailable', 503)
    try:
        counts = await store.usage_log_counts()
    except Exception:
        return _error('feedback_unavailable', 503)
    metrics = []
    for key, label in METRICS:
        metrics.append({'key': key, 'label': label, 'value': counts.get(key) if key != 'return' else None})
    return JSONResponse({'ok': True, 'rows': [], 'metrics': metrics}, headers=_NO_STORE)
