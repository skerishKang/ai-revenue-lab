"""Admin-only usage log summary for the operations center.

#8035 ③ (#7718 흡수): the counts already stored for AI honorary members are
read as before, and the return score / round history now come from the round
scores an administrator enters in the ops center (`ops_round_score`,
migration 129). Without that store the two stay null/empty exactly as before,
so an older deployment keeps its answer.
"""
from __future__ import annotations

from starlette.responses import JSONResponse

from .central_model_control_routes import _central_admin

_NO_STORE = {'Cache-Control': 'private, no-store, max-age=0', 'Pragma': 'no-cache',
             'X-Content-Type-Options': 'nosniff'}

METRICS = (
    ('active', '활동 고객(회원)'),
    ('left', '떠난 고객(회원)'),
    ('new', '새 의견'),
    ('resolved', '해결'),
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
    scores = getattr(request.app.state, 'ops_round_score_store', None)
    journal = None
    if scores is not None:
        try:
            journal = await scores.journal(days=30)
        except Exception:
            journal = None
    metrics = []
    for key, label in METRICS:
        if key == 'return':
            value = journal.get('return_avg') if journal else None
        else:
            value = counts.get(key)
        metrics.append({'key': key, 'label': label, 'value': value})
    rows = []
    if journal:
        for person in journal.get('personas', []):
            rows.append({
                'persona': person['persona'],
                'grade': 'AI 고객' if person['source'] == 'ai' else '실제 고객',
                'entries': [{'round': entry['round'], 'at': entry['at'],
                             'summary': '', 'score': entry['pretty']}
                            for entry in person['entries']],
            })
    return JSONResponse({'ok': True, 'rows': rows, 'metrics': metrics}, headers=_NO_STORE)