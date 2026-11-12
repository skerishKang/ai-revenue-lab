"""Process-local identity cache and RPC counters, without cache keys or identities."""
import asyncio
from collections import defaultdict

_counts = defaultdict(lambda: [0, 0])
_rpc_counts = defaultdict(int)
_timer = None

#: #7542: every label an ``identity_rpc_minute`` line can carry is one of these
#: fixed names. A value outside them is counted as ``other``, so no payload,
#: response or error text can reach the journal through the RPC counter.
#:
#: ``call`` is a product request; ``keepwarm`` is the synthetic wake-up ping,
#: counted apart so it can be subtracted from the authority's own totals.
RPC_SOURCES = frozenset({'call', 'keepwarm'})
#: The identity RPCs this product calls (see ``control_plane_identity_worker``).
RPC_METHODS = frozenset({
    'assign_tenant_membership',
    'authorize_connector_enrollment_redeem',
    'bind_connector_enrollment_challenge',
    'create_tenant',
    'ensure_personal_tenant_membership',
    'establish_auth_session',
    'grant_connector_enrollment_consent',
    'install_connector_enrollment_schema',
    'issue_google_connect_ticket',
    'list_active_product_links_for_subject',
    'remove_product_link',
    'resolve_active_memberships',
    'resolve_active_tenant_membership',
    'resolve_auth_session',
    'resolve_connector_context',
    'resolve_connector_enrollment_consent_for_device',
    'resolve_connector_owner_scope',
    'resolve_connector_workspace',
    'resolve_current_auth_session',
    'resolve_or_create_product_link',
    'resolve_product_user_for_subject',
    'revoke_all_auth_sessions',
    'revoke_auth_session',
    'revoke_connector_enrollment_consent',
})
#: Result kinds. A ``call`` ends as ``ok``, as one of three refusals the
#: authority answered (``unauthorized``, ``forbidden``, ``rejected``), as
#: ``unavailable`` (no usable answer), ``invalid`` (malformed answer) or
#: ``interrupted`` (the caller went away first). A ``keepwarm`` ping only knows
#: its transport result: ``answered`` (HTTP 200), ``bad_status`` (any other
#: status) or ``unavailable`` (no response). No kind uses a word the journal
#: error patrol (scripts/ops/com2_error_patrol.sh) counts by keyword.
RPC_OUTCOME_KINDS = frozenset({
    'ok', 'unauthorized', 'forbidden', 'rejected', 'unavailable', 'invalid',
    'interrupted', 'answered', 'bad_status',
})


def record(layer, method, hit):
    _counts[(layer, method)][0 if hit else 1] += 1


def _label(value, allowed):
    return value if isinstance(value, str) and value in allowed else 'other'


def record_rpc(source, method, kind):
    """Count one identity RPC by name and result kind; nothing else is kept."""
    _rpc_counts[(_label(source, RPC_SOURCES), _label(method, RPC_METHODS),
                 _label(kind, RPC_OUTCOME_KINDS))] += 1


def _rpc_detail():
    rows = sorted(_rpc_counts.items())
    _rpc_counts.clear()
    grouped = {}
    for (source, method, kind), count in rows:
        grouped.setdefault(f'{source}.{method}', []).append(f'{kind}={count}')
    return ' '.join(f'{name}:{",".join(kinds)}' for name, kinds in grouped.items())


def flush():
    global _timer
    _timer = None
    rows = sorted(_counts.items())
    _counts.clear()
    detail = ' '.join(f'{layer}.{method}:hit={counts[0]},miss={counts[1]}'
                      for (layer, method), counts in rows)
    print('identity_cache_minute ' + (detail or 'empty'), flush=True)
    # #7542: the same minute, counted at the authority client itself. One line
    # per minute even when idle, so a quiet minute and a missing log differ.
    print('identity_rpc_minute ' + (_rpc_detail() or 'empty'), flush=True)


def _tick():
    flush()
    arm()


def arm():
    global _timer
    if _timer is None:
        _timer = asyncio.get_running_loop().call_later(60, _tick)


def stop():
    global _timer
    if _timer is not None:
        _timer.cancel()
        _timer = None
