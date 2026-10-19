"""#3257 — Web Automation Create: ``POST /api/claw/automation/rules``.

The first real mutation surface of Web Automation, one slice after #3252 made
the execution target server-owned. The caller authors exactly seven product
fields — name, task, schedule kind/expression/timezone, target, output — and
everything that constitutes authority is minted or derived on the server:

```text
signed-in browser
  -> current active B54 canonical session          (#3243 resolver, reused)
  -> exact ACTIVE role-bearing tenant membership   (existing authority)
  -> role == OWNER                                 (bounded first write policy)
  -> server-minted rule_id  (rule_<32 hex>)        (never caller-supplied)
  -> server-minted opaque owner_ref                (never an identity value)
  -> server-owned execution intent                 (#3252 composer, reused)
  -> create_canonical_automation_rule(...)         (#3043 helper, reused)
  -> existing D1ClawAutomationStore.save_rule()    (no new store/migration)
  -> existing project_web_rule_row(rule)           (safe projection only)
```

Fail-closed boundaries:

* signed-out -> 401; no current B54 session (including a foreign-product one)
  -> 403 without disclosure; membership that is not exactly this tenant+subject
  ACTIVE OWNER -> 403. VIEWER/OPERATOR/APPROVER cannot create: the repository
  has no reviewed write policy for those roles, so the first mutation slice is
  deliberately owner-only and widening it is a separate policy change.
* request body must be JSON with EXACTLY the seven keys; any missing, extra,
  unknown or authority-shaped key (rule_id, owner_ref, tenant, subject, role,
  repository_ref, exact_revision, ...) is a bounded 400/413 and the raw input
  is never echoed.
* the execution target authority is the server-injected Worker env. When the
  ``CF_VERSION_METADATA`` binding is absent or malformed (live activation is
  still a separately authorized gate) the response is
  ``503 automation_execution_target_unavailable`` and ``save_rule`` is never
  called: a rule with a fabricated revision or a null intent is worse than no
  rule.
* store unavailable or write failure -> bounded 503; there is no retry that
  could mint a second rule id after an ambiguous storage failure.
* notification is server-fixed to ``web_alert_inbox``; enabled=True is only the
  stored rule setting and never means the Production scheduler is live
  (#2833 HOLD).
"""

from __future__ import annotations

import inspect
import json
import secrets
from datetime import datetime, timezone
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from kagent.claw_automation import (
    ClawAutomationOutputType,
    ClawAutomationTarget,
    ClawNotificationChannel,
    ClawNotificationPreference,
    ClawScheduleExpression,
)
from kagent.contracts import ContractError
from padiem_control_plane.tenants import (
    TenantMembership,
    TenantMembershipRole,
    TenantMembershipState,
)

from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .claw_automation_execution_target import (
    compose_canonical_automation_execution_intent,
    resolve_automation_execution_revision,
)
from .claw_automation_mutation_authority import (
    resolve_automation_owner_mutation_context,
)
from .claw_automation_rules_routes import (
    _NO_STORE_HEADERS,
    _error,
    _require_owner,
    project_web_rule_row,
)

# This slice's write surface. Everything else stays closed exactly as in the
# read-only slice; production scheduler truth is unchanged (#2833 HOLD).
RULE_CREATE = True
RULE_UPDATE = False
RULE_DELETE = False
RULE_ENABLE_DISABLE = False
RUN_NOW = False
CRON_ACTIVATION = False
PRODUCTION_SCHEDULER_ACTIVATION = False
CREATE_ROLE_OWNER_ONLY = True
VIEWER_CREATE = False
OPERATOR_CREATE = False
APPROVER_CREATE = False
CALLER_RULE_ID_AUTHORITY = False
CALLER_OWNER_REF_AUTHORITY = False
CALLER_TENANT_AUTHORITY = False
CALLER_SUBJECT_AUTHORITY = False
CALLER_ROLE_AUTHORITY = False
CALLER_REPOSITORY_AUTHORITY = False
CALLER_REVISION_AUTHORITY = False
CALLER_NOTIFICATION_AUTHORITY = False
OWNER_REF_AS_IDENTITY = False
NEW_AUTOMATION_STORE = False
NEW_SCHEMA = False
NEW_MIGRATION = False

# The request body is bounded BEFORE parsing. A declared or actual body larger
# than this is rejected without being interpreted.
MAX_BODY_BYTES = 32 * 1024

# The exact keys a browser may submit. Anything else — including every
# authority-shaped field — is rejected by this closed set; the raw input is
# never echoed back.
EXPECTED_BODY_KEYS = frozenset({
    "name",
    "task",
    "schedule_kind",
    "schedule_expression",
    "schedule_timezone",
    "target_source",
    "output_type",
})

# Phase-1 notification is server-fixed: the Web alert inbox only.
NOTIFICATION_CHANNELS = (
    ClawNotificationPreference(channel=ClawNotificationChannel.WEB_ALERT_INBOX),
)


def _server_utc() -> datetime:
    return datetime.now(timezone.utc)


def _mint_rule_id() -> str:
    """Server-minted rule id: ``rule_`` + 32 random hex (``_safe_id``-shaped)."""

    return f"rule_{secrets.token_hex(16)}"


def _mint_owner_ref() -> str:
    """Server-minted opaque provenance: never derived from any identity value.

    The signed-in user id, product user id, canonical subject id, tenant id and
    member id are all deliberately unused here; the token carries no meaning.
    """

    return f"automation_owner_{secrets.token_hex(16)}"


async def _current_b54_session(request: Request) -> Any | None:
    """The #3243 current B54 session for the signed-in user, or None."""

    from .b54_canonical_session import resolve_current_b54_canonical_session

    try:
        return await resolve_current_b54_canonical_session(request)
    except Exception:
        return None


async def _read_bounded_json(request: Request) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    """Read a bounded JSON object, or return a bounded error response."""

    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > MAX_BODY_BYTES:
                return None, _error(
                    413, "request_body_too_large", "요청 본문이 너무 큽니다."
                )
        except ValueError:
            return None, _error(400, "invalid_request", "요청을 해석할 수 없습니다.")
    try:
        raw = await read_bounded_request_body(request, max_bytes=MAX_BODY_BYTES)
    except RequestBodyTooLarge:
        return None, _error(413, "request_body_too_large", "요청 본문이 너무 큽니다.")
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None, _error(400, "invalid_json", "요청 형식이 올바르지 않습니다.")
    if not isinstance(body, dict):
        return None, _error(400, "invalid_json", "요청 형식이 올바르지 않습니다.")
    if set(body) != EXPECTED_BODY_KEYS:
        # Covers missing keys, unknown keys and every authority-shaped key in
        # one closed-set check; the offending values are never echoed.
        return None, _error(400, "unexpected_field", "요청 필드가 올바르지 않습니다.")
    if not all(isinstance(body[key], str) and body[key].strip() for key in EXPECTED_BODY_KEYS):
        return None, _error(400, "invalid_field", "요청 값을 확인해 주세요.")
    return body, None


def _require_owner_membership(
    membership: Any, *, tenant_id: str, canonical_subject_id: str
) -> bool:
    """Delegated to the shared OWNER mutation authority (#3262)."""

    from .claw_automation_mutation_authority import require_owner_membership

    return require_owner_membership(
        membership, tenant_id=tenant_id, canonical_subject_id=canonical_subject_id
    )


async def claw_automation_rule_create(request: Request) -> JSONResponse:
    # #3262: Create and Toggle share ONE owner mutation authority
    # (``resolve_automation_owner_mutation_context``); only the denial copy is
    # action-specific here.
    context, authority_error = await resolve_automation_owner_mutation_context(
        request, denied_message="자동화 생성은 워크스페이스 소유자만 할 수 있습니다."
    )
    if authority_error is not None:
        return authority_error
    assert context is not None  # narrowed by the guard above
    tenant_id = context.tenant_id
    canonical_subject_id = context.canonical_subject_id
    auth_session = context.auth_session

    body, body_error = await _read_bounded_json(request)
    if body_error is not None:
        return body_error

    target_authority = getattr(
        request.app.state, "claw_automation_execution_target_authority", None
    )
    if target_authority is None:
        return _error(
            503,
            "automation_execution_target_unavailable",
            "자동화 생성 준비가 아직 완료되지 않았습니다.",
        )
    try:
        # Runtime availability is a server condition, not input validation: it
        # is judged first so a missing/malformed binding maps to 503 while
        # caller input errors map to 400. The composer itself remains the only
        # intent constructor; this pre-check resolves the same read-only
        # server facts and saves nothing.
        resolve_automation_execution_revision(target_authority)
    except ContractError:
        return _error(
            503,
            "automation_execution_target_unavailable",
            "자동화 생성 준비가 아직 완료되지 않았습니다.",
        )
    except Exception:
        return _error(
            503,
            "automation_execution_target_unavailable",
            "자동화 생성 준비가 아직 완료되지 않았습니다.",
        )
    try:
        intent = compose_canonical_automation_execution_intent(
            task=body["task"], execution_target_authority=target_authority
        )
    except ContractError:
        # The caller-authored task failed the existing #2908 bounds
        # (credential material, length, control characters).
        return _error(400, "invalid_task", "할 일 내용을 확인해 주세요.")

    try:
        # The existing domain contract is the authority for schedule validity:
        # kind vocabulary and the per-kind expression grammar. No second parser
        # exists here.
        schedule = ClawScheduleExpression(
            kind=body["schedule_kind"],
            expression=body["schedule_expression"],
            timezone=body["schedule_timezone"],
        )
        # The reviewed Calendar timezone contract is the resolvability
        # authority (#3260 review): an identifier the timezone database does
        # not know (e.g. Mars/Olympus) must be refused at create time, not
        # stored as a rule that fails on every future run. Reused, not
        # reimplemented.
        from .calendar_contracts import CalendarContractError, validate_timezone

        try:
            validate_timezone(body["schedule_timezone"])
        except CalendarContractError:
            return _error(
                400, "invalid_timezone", "시간대를 확인해 주세요. IANA 시간대가 필요합니다."
            )
        target_source = ClawAutomationTarget(body["target_source"])
        output_type = ClawAutomationOutputType(body["output_type"])
    except (ContractError, TypeError, ValueError):
        return _error(400, "invalid_schedule_or_target", "주기, 시간대, 대상 또는 결과를 확인해 주세요.")

    from .claw_automation_rule_authority import create_canonical_automation_rule

    try:
        rule = create_canonical_automation_rule(
            auth_session=auth_session,
            now=_server_utc(),
            rule_id=_mint_rule_id(),
            name=body["name"],
            schedule=schedule,
            target_source=target_source,
            output_type=output_type,
            enabled=True,
            notification_channels=NOTIFICATION_CHANNELS,
            owner_ref=_mint_owner_ref(),
            execution_intent=intent,
        )
    except ContractError:
        # Bounded caller input failed the canonical rule contract (name
        # bounds/credential material). Server-derived fields cannot fail here
        # because the session was already validated above.
        return _error(400, "invalid_rule_input", "자동화 내용을 확인해 주세요.")

    store = getattr(request.app.state, "claw_automation_store", None)
    if store is None or not callable(getattr(store, "save_rule", None)):
        return _error(503, "automation_store_unavailable", "자동화 규칙을 저장할 수 없습니다.")
    try:
        saved = store.save_rule(rule)
        if inspect.isawaitable(saved):
            await saved
    except Exception:
        # No retry: minting a new rule_id after an ambiguous storage failure
        # could create a second rule.
        return _error(503, "automation_rule_save_failed", "자동화 규칙을 저장하지 못했습니다.")

    return JSONResponse(
        {"ok": True, "rule": project_web_rule_row(rule)},
        status_code=201,
        headers=_NO_STORE_HEADERS,
    )


__all__ = [
    "CREATE_ROLE_OWNER_ONLY",
    "EXPECTED_BODY_KEYS",
    "MAX_BODY_BYTES",
    "NOTIFICATION_CHANNELS",
    "RULE_CREATE",
    "claw_automation_rule_create",
]
