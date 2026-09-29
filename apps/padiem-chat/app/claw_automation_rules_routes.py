"""#3237 — read-only Web projection of the canonical Claw automation rules.

Endpoint:
- GET /api/claw/automation/rules — signed-in owner only (401 otherwise), and
  only when a canonical tenant resolves (403/503 otherwise).

What this is
------------
A **read-only** listing surface. The rows come from the existing canonical
authority ``claw_automation_store.list_rules(workspace_id)`` (the B54
``ClawAutomationStore`` protocol, D1-backed by ``D1ClawAutomationStore``,
schema owned by migration 018/019). This module registers no rule, installs no
registry, mints no second store and never enumerates across tenants: exactly
one caller-supplied-free, server-resolved ``workspace_id`` is read.

Identity (the strict contract, #3237)
-------------------------------------
    signed-in user
    -> identity shadow
    -> refreshed canonical session
    -> AuthSessionSnapshot.tenant_id
    -> list_rules(tenant_id)

There is deliberately **no owner-derived fallback**. The Claw memory resolver
(``claw_memory_routes._resolve_memory_workspace``) falls back to
``f"owner:{user_id}"`` when no canonical tenant exists; that compatibility
branch is NOT reused here, because a synthetic per-owner workspace would be a
second, non-canonical authority and could read rules that no tenant ever
scoped. When the canonical tenant cannot be resolved this route fails closed
and discloses nothing.

The caller can never supply or influence the tenant: no query parameter, no
path value, no body field and no header feeds it. Every rule returned was
stored under this resolved tenant, so cross-tenant disclosure is structurally
impossible rather than filtered after the fact.

Projection
----------
Deliberately smaller than the stored rule. Display and status only:
``rule_id``, ``name``, ``enabled``, schedule kind/expression/timezone, target
source, output type and notification channels.

Never projected: ``workspace_id`` (tenant identity), ``owner_ref`` (opaque
delivery provenance), ``canonical_subject_id`` (authority provenance) and
``execution_intent`` (``task`` / ``repository_ref`` / ``exact_revision`` —
internal execution material that must not reach the browser).

This module does not create/update/delete rules, toggle enablement, run a rule
now, activate cron or a Production scheduler, call a provider, or send
anything outbound.
"""

from __future__ import annotations

import inspect
from typing import Any, Mapping

from starlette.requests import Request
from starlette.responses import JSONResponse

from kagent.claw_automation import ClawAutomationRule

# The read-only surface of this slice. Kept as constants so no code path can
# drift into claiming a write, schedule or execution capability.
RULE_CREATE = False
RULE_UPDATE = False
RULE_DELETE = False
RULE_ENABLE_DISABLE = False
RUN_NOW = False
CRON_ACTIVATION = False
PRODUCTION_SCHEDULER_ACTIVATION = False
CALLER_TENANT_AUTHORITY = False
OWNER_FALLBACK_WORKSPACE = False
CALLER_LIST_ALL_TENANTS = False
SECOND_AUTOMATION_STORE_AUTHORITY = False

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

# Hard ceiling on one response. The store is the authority on what exists; this
# only bounds what a single browser call can pull.
MAX_RULES_PER_RESPONSE = 200

# The exact set of keys a browser may ever receive from this endpoint.
WEB_RULE_KEYS = frozenset({
    "rule_id",
    "name",
    "enabled",
    "schedule_kind",
    "schedule_expression",
    "schedule_timezone",
    "target_source",
    "output_type",
    "notification_channels",
})


class AutomationRuleProjectionError(Exception):
    """Raised when a stored rule cannot be projected to the minimal Web shape."""


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status_code,
        headers=_NO_STORE_HEADERS,
    )


def _require_owner(request: Request) -> str | None:
    """The signed-in product user, or None. Never a caller-supplied value."""

    from .auth_routes import auth_ready, current_user_id

    if not auth_ready(request):
        return None
    try:
        uid = current_user_id(request)
    except Exception:
        return None
    return uid if uid else None


async def _resolve_canonical_tenant(request: Request) -> str | None:
    """Canonical tenant for the signed-in user, or None to fail closed.

    This reuses the EXISTING strict canonical tenant resolver
    (``claw_routes._resolve_canonical_tenant``) — signed-in user -> identity
    shadow -> refreshed canonical session -> ``AuthSessionSnapshot.tenant_id``,
    with every contract check required to pass. It is reused rather than
    reimplemented so #3237 cannot introduce a second tenant authority.

    The Claw memory resolver is intentionally NOT used: its
    ``f"owner:{user_id}"`` fallback is exactly the non-canonical authority this
    endpoint must not have.
    """

    from .claw_routes import _resolve_canonical_tenant

    return await _resolve_canonical_tenant(request)


def _bounded_text(value: Any, limit: int = 256) -> str:
    if not isinstance(value, str):
        raise AutomationRuleProjectionError("expected string value")
    text = value.strip()
    if not text or len(text) > limit:
        raise AutomationRuleProjectionError("text value out of bounds")
    return text


def _bounded_enum(value: Any, enum_cls) -> str:
    try:
        return enum_cls(value).value
    except (TypeError, ValueError) as exc:
        raise AutomationRuleProjectionError("enum value out of bounds") from exc


def project_web_rule_row(rule: ClawAutomationRule) -> dict[str, Any]:
    """Project one stored rule to the minimal, browser-safe shape.

    Only display/status fields survive. The tenant id, the delivery owner
    provenance, the canonical subject provenance and the execution intent
    (task / repository ref / exact revision) are dropped here and never leave
    the server.
    """

    if not isinstance(rule, ClawAutomationRule):
        raise AutomationRuleProjectionError("rule must be a ClawAutomationRule")
    schedule = rule.schedule
    kind = _bounded_enum(getattr(schedule, "kind", None), _schedule_kind_enum())
    expression = _bounded_text(getattr(schedule, "expression", None), 128)
    timezone = _bounded_text(getattr(schedule, "timezone", None), 64)
    channels = []
    for preference in rule.notification_channels or ():
        channels.append(
            _bounded_enum(getattr(preference, "channel", None), _notification_channel_enum())
        )
    row = {
        "rule_id": _bounded_text(rule.rule_id, 128),
        "name": _bounded_text(rule.name, 256),
        "enabled": rule.enabled is True,
        "schedule_kind": kind,
        "schedule_expression": expression,
        "schedule_timezone": timezone,
        "target_source": _bounded_enum(rule.target_source, _target_enum()),
        "output_type": _bounded_enum(rule.output_type, _output_enum()),
        "notification_channels": channels,
    }
    # Defence in depth: a future field added above cannot silently ship.
    if set(row) != set(WEB_RULE_KEYS):
        raise AutomationRuleProjectionError("projected rule keys drifted")
    return row


def _schedule_kind_enum():
    from kagent.claw_automation import ClawScheduleKind

    return ClawScheduleKind


def _notification_channel_enum():
    from kagent.claw_automation import ClawNotificationChannel

    return ClawNotificationChannel


def _target_enum():
    from kagent.claw_automation import ClawAutomationTarget

    return ClawAutomationTarget


def _output_enum():
    from kagent.claw_automation import ClawAutomationOutputType

    return ClawAutomationOutputType


def _automation_store(request: Request) -> Any | None:
    """The existing canonical store, or None. Never constructed here."""

    store = getattr(request.app.state, "claw_automation_store", None)
    if store is None:
        return None
    if not callable(getattr(store, "list_rules", None)):
        return None
    return store


async def claw_automation_rules(request: Request) -> JSONResponse:
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "인증이 필요합니다.")
    tenant_id = await _resolve_canonical_tenant(request)
    if tenant_id is None:
        # No canonical tenant -> no catalogue. Fails closed and discloses
        # nothing; there is intentionally no owner-derived workspace here.
        return _error(403, "canonical_tenant_unavailable", "워크스페이스 권한을 확인할 수 없습니다.")
    store = _automation_store(request)
    if store is None:
        return _error(503, "automation_store_unavailable", "자동화 규칙을 사용할 수 없습니다.")
    try:
        rules = store.list_rules(tenant_id)
        if inspect.isawaitable(rules):
            rules = await rules
    except Exception:
        return _error(503, "automation_rules_read_failed", "자동화 규칙을 불러오지 못했습니다.")
    if not isinstance(rules, list):
        return _error(503, "automation_rules_read_failed", "자동화 규칙을 불러오지 못했습니다.")
    projected: list[dict[str, Any]] = []
    for rule in rules[:MAX_RULES_PER_RESPONSE]:
        try:
            projected.append(project_web_rule_row(rule))
        except AutomationRuleProjectionError:
            # One unprojectable row must not disclose or misreport the rest.
            continue
    projected.sort(key=lambda item: item["rule_id"])
    return JSONResponse(
        {"ok": True, "rules": projected, "truncated": len(rules) > MAX_RULES_PER_RESPONSE},
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


__all__ = [
    "MAX_RULES_PER_RESPONSE",
    "WEB_RULE_KEYS",
    "AutomationRuleProjectionError",
    "claw_automation_rules",
    "project_web_rule_row",
]
