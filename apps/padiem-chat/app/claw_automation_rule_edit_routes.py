"""#3270 — OWNER-gated bounded edit of a canonical automation rule.

The first Edit surface, right after Create (#3257) and enable/disable (#3262).
Exactly four caller fields are editable:

```text
name
schedule_kind
schedule_expression
schedule_timezone
```

Everything else on the stored rule is carried through unchanged — notably the
#2908 immutable ``execution_intent`` (task / repository_ref / exact_revision),
``owner_ref``, ``canonical_subject_id``, ``workspace_id``, ``rule_id``,
``enabled``, ``target_source``, ``output_type`` and ``notification_channels``.
The existing store enforces that immutability too (``save_rule`` fails closed
on a changed owner_ref / canonical subject / execution intent), so this route
constructs the updated rule from the persisted row rather than from caller
input.

```text
signed-in browser
  -> PATCH /api/claw/automation/rules/{rule_id}  {"name", "schedule_*"} (exact 4 keys)
  -> shared OWNER mutation authority (#3262 helper, shared with Create/Toggle)
  -> server-derived canonical tenant; get_rule(rule_id, tenant) ONLY
  -> canonical authority classification + execution-readiness
  -> existing ClawScheduleExpression + Calendar timezone contract
  -> new ClawAutomationRule carrying every non-edited field from the row
  -> existing store.update_rule(updated)          (exactly one write)
  -> existing store.get_rule(...) re-read         (response = durable truth)
  -> existing safe projection (project_web_rule_row) -> 200
```

Boundaries:

* ``rule_id`` is a path value, never authority (existing canonical ``_safe_id``
  contract); missing and foreign-tenant rules share one bounded 404 and no
  cross-tenant probe exists;
* legacy/quarantined rows and canonical-but-incomplete rows are refused with
  bounded 409s and zero writes; nothing is minted, repaired or reconstructed;
* no Edit is optimistic: the response is the re-read persisted row, and a
  post-write read failure is a bounded 503 with no second write;
* a schedule edit changes the STORED rule schedule only — it is not a cron
  registration, a scheduler activation, or a claim that automatic execution is
  live (#2833 HOLD).

Out of scope: task/execution-intent edit, target/output/notification/enabled
edit, rule delete, run-now, cron or scheduler activation, live binding
mutation, deploy.
"""

from __future__ import annotations

import inspect
import json
from typing import Any

from kagent.claw_automation import (
    ClawAutomationRule,
    ClawAutomationRuleAuthority,
    ClawScheduleExpression,
    _safe_id,
    classify_rule_background_authority,
)
from kagent.contracts import ContractError
from starlette.requests import Request
from starlette.responses import JSONResponse

from .claw_automation_mutation_authority import resolve_automation_owner_mutation_context
from .claw_automation_rules_routes import (
    _NO_STORE_HEADERS,
    _error,
    project_web_rule_row,
)

RULE_NAME_SCHEDULE_EDIT = True
TASK_EDIT = False
EXECUTION_INTENT_EDIT = False
OWNER_REF_EDIT = False
TARGET_SOURCE_EDIT = False
OUTPUT_TYPE_EDIT = False
NOTIFICATION_EDIT = False
ENABLED_EDIT = False
RULE_DELETE = False
RUN_NOW = False
CRON_ACTIVATION = False
PRODUCTION_SCHEDULER_ACTIVATION = False
CALLER_RULE_ID_AUTHORITY = False
CALLER_TENANT_AUTHORITY = False
CALLER_SUBJECT_AUTHORITY = False
CALLER_ROLE_AUTHORITY = False
CROSS_TENANT_RULE_LOOKUP = False
IN_PLACE_RULE_MUTATION = False
SECOND_UPDATE_IMPLEMENTATION = False

# Four bounded string fields; the same generous-but-finite bound Create uses.
MAX_BODY_BYTES = 8 * 1024
EXPECTED_BODY_KEYS = frozenset({
    "name",
    "schedule_kind",
    "schedule_expression",
    "schedule_timezone",
})


async def read_edit_fields(request: Request) -> tuple[dict[str, str] | None, JSONResponse | None]:
    """Read exactly the four editable string fields, or a bounded error."""

    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > MAX_BODY_BYTES:
                return None, _error(413, "request_body_too_large", "요청 본문이 너무 큽니다.")
        except ValueError:
            return None, _error(400, "invalid_request", "요청을 해석할 수 없습니다.")
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        return None, _error(413, "request_body_too_large", "요청 본문이 너무 큽니다.")
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None, _error(400, "invalid_json", "요청 형식이 올바르지 않습니다.")
    if not isinstance(body, dict) or set(body) != EXPECTED_BODY_KEYS:
        # Missing, extra and every authority/immutable key (task,
        # execution_intent, owner_ref, enabled, target_source, output_type,
        # notification_channels, tenant, subject, role, product, member, ...)
        # are refused by one closed set; raw input is never echoed.
        return None, _error(400, "unexpected_field", "수정할 수 없는 필드가 포함되어 있습니다.")
    if not all(isinstance(body[key], str) and body[key].strip() for key in EXPECTED_BODY_KEYS):
        return None, _error(400, "invalid_field", "요청 값을 확인해 주세요.")
    return {key: body[key] for key in EXPECTED_BODY_KEYS}, None


def _automation_store(request: Request) -> Any | None:
    store = getattr(request.app.state, "claw_automation_store", None)
    if store is None:
        return None
    if not callable(getattr(store, "get_rule", None)) or not callable(
        getattr(store, "update_rule", None)
    ):
        return None
    return store


async def _call(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _is_mutable(rule: ClawAutomationRule) -> bool:
    try:
        return (
            classify_rule_background_authority(rule)
            is ClawAutomationRuleAuthority.CANONICAL_BACKGROUND_ELIGIBLE
        )
    except Exception:
        return False


def _is_execution_ready(rule: ClawAutomationRule) -> bool:
    return rule.owner_ref is not None and rule.execution_intent is not None


async def claw_automation_rule_edit(request: Request) -> JSONResponse:
    rule_id = request.path_params.get("rule_id", "")
    try:
        _safe_id(rule_id, "rule_id")
    except ContractError:
        return _error(404, "automation_rule_not_found", "해당 자동화 규칙을 사용할 수 없습니다.")

    context, authority_error = await resolve_automation_owner_mutation_context(
        request, denied_message="워크스페이스 소유자만 변경할 수 있습니다."
    )
    if authority_error is not None:
        return authority_error
    assert context is not None  # narrowed by the guard above

    fields, body_error = await read_edit_fields(request)
    if body_error is not None:
        return body_error

    store = _automation_store(request)
    if store is None:
        return _error(503, "automation_store_unavailable", "규칙을 수정하지 못했습니다.")

    # Tenant-scoped lookup only; missing and foreign rules are one bounded 404.
    try:
        existing = await _call(store.get_rule(rule_id, context.tenant_id))
    except Exception:
        return _error(503, "automation_rule_read_failed", "규칙을 수정하지 못했습니다.")
    if not isinstance(existing, ClawAutomationRule):
        return _error(404, "automation_rule_not_found", "해당 자동화 규칙을 사용할 수 없습니다.")

    if not _is_mutable(existing):
        return _error(409, "automation_rule_not_mutable", "이 규칙은 변경할 수 없습니다.")
    if not _is_execution_ready(existing):
        return _error(
            409,
            "automation_rule_not_execution_ready",
            "이 규칙은 실행 준비가 되지 않아 수정할 수 없습니다.",
        )

    from .calendar_contracts import CalendarContractError, validate_timezone

    try:
        # Existing contracts only: the schedule grammar and the reviewed
        # Calendar timezone contract. No second parser is introduced here.
        schedule = ClawScheduleExpression(
            kind=fields["schedule_kind"],
            expression=fields["schedule_expression"],
            timezone=fields["schedule_timezone"],
        )
        try:
            validate_timezone(fields["schedule_timezone"])
        except CalendarContractError:
            return _error(
                400, "invalid_timezone", "시간대를 확인해 주세요. IANA 시간대가 필요합니다."
            )
    except (ContractError, TypeError, ValueError):
        return _error(400, "invalid_schedule", "주기와 시간대를 확인해 주세요.")

    try:
        # Only name and schedule come from the caller; every other field is the
        # persisted row's value, so the #2908 execution intent is carried over
        # unchanged rather than reconstructed.
        updated = ClawAutomationRule(
            rule_id=existing.rule_id,
            workspace_id=existing.workspace_id,
            name=fields["name"],
            schedule=schedule,
            target_source=existing.target_source,
            output_type=existing.output_type,
            enabled=existing.enabled,
            notification_channels=existing.notification_channels,
            owner_ref=existing.owner_ref,
            execution_intent=existing.execution_intent,
            canonical_subject_id=existing.canonical_subject_id,
        )
    except ContractError:
        # Existing rule-name contract (bound, credential material) applies.
        return _error(400, "invalid_name", "규칙 이름을 확인해 주세요.")

    try:
        await _call(store.update_rule(updated))
    except ContractError:
        # The store's own immutability guard refused; nothing is written twice.
        return _error(409, "automation_rule_not_mutable", "이 규칙은 변경할 수 없습니다.")
    except Exception:
        return _error(503, "automation_rule_save_failed", "규칙을 수정하지 못했습니다.")

    # The response is the durable truth re-read after the write, never the
    # locally constructed object. A failed read is a bounded 503 with no second
    # write.
    try:
        persisted = await _call(store.get_rule(rule_id, context.tenant_id))
    except Exception:
        return _error(503, "automation_rule_read_failed", "규칙을 수정하지 못했습니다.")
    if not isinstance(persisted, ClawAutomationRule):
        return _error(503, "automation_rule_read_failed", "규칙을 수정하지 못했습니다.")

    return JSONResponse(
        {"ok": True, "rule": project_web_rule_row(persisted)},
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


__all__ = [
    "EXPECTED_BODY_KEYS",
    "MAX_BODY_BYTES",
    "RULE_NAME_SCHEDULE_EDIT",
    "claw_automation_rule_edit",
    "read_edit_fields",
]