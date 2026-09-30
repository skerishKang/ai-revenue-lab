"""#3262 — OWNER-gated enable/disable for a canonical automation rule.

The first Automation *management* mutation, right after Create (#3257):

```text
signed-in browser
  -> PATCH /api/claw/automation/rules/{rule_id}/enabled   {"enabled": true|false}
  -> shared OWNER mutation authority (#3262 helper, shared with Create)
  -> server-derived canonical tenant, exact rule lookup in THAT tenant only
  -> canonical authority classification (classify_rule_background_authority)
  -> enabling additionally requires existing owner_ref + execution_intent
  -> existing store.set_rule_enabled(workspace_id, rule_id, enabled)
  -> existing safe projection (project_web_rule_row) -> 200
  -> Web list refresh
```

Boundaries this slice holds:

* ``rule_id`` is a path value, never authority: it is validated through the
  existing canonical ``_safe_id`` contract and the lookup is scoped to the
  session's tenant. A missing rule and a foreign-tenant rule are the same
  bounded 404 — the route never probes another tenant to tell them apart.
* legacy/quarantined rows (missing canonical subject, non-canonical workspace)
  stay immutable: 409 ``automation_rule_not_mutable``, zero writes.
* enabling requires the rule to already carry ``owner_ref`` **and**
  ``execution_intent``; otherwise 409
  ``automation_rule_not_execution_ready`` and zero writes. Nothing is minted or
  reconstructed during a toggle — a rule that lost its provenance stays that
  way until Create makes a new one.
* disabling an otherwise-incomplete canonical rule is allowed: reducing
  exposure is a safety increase, and the row stays quarantined-classified
  either way.
* ``enabled`` is the STORED RULE SETTING only. It never means the Production
  scheduler is live (#2833 HOLD), and the Web UI keeps that note visible.

Nothing else is in scope: no Edit, Delete, Run-now, notification/schedule/
target/output edit, cron registration or live binding mutation.
"""

from __future__ import annotations

import inspect
import json
from typing import Any

from kagent.claw_automation import (
    ClawAutomationRule,
    ClawAutomationRuleAuthority,
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

# This slice's write surface: the stored rule setting only.
RULE_ENABLED_TOGGLE = True
RULE_EDIT_FIELDS = False
RULE_DELETE = False
RUN_NOW = False
OWNER_REF_EDIT = False
EXECUTION_INTENT_EDIT = False
SCHEDULE_EDIT = False
TARGET_EDIT = False
OUTPUT_EDIT = False
NOTIFICATION_EDIT = False
CRON_ACTIVATION = False
PRODUCTION_SCHEDULER_ACTIVATION = False
CALLER_RULE_ID_AUTHORITY = False
CALLER_TENANT_AUTHORITY = False
CALLER_SUBJECT_AUTHORITY = False
CALLER_ROLE_AUTHORITY = False
CALLER_ENABLED_AUTHORITY_BEYOND_BOOLEAN = False
CROSS_TENANT_RULE_LOOKUP = False
LEGACY_RULE_MUTATION = False
SECOND_UPDATE_IMPLEMENTATION = False

# Bounded body: one boolean does not need more.
MAX_BODY_BYTES = 4 * 1024
EXPECTED_BODY_KEYS = frozenset({"enabled"})


async def read_enabled_flag(request: Request) -> tuple[bool | None, JSONResponse | None]:
    """Read exactly ``{"enabled": <JSON boolean>}``, or a bounded error."""
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
        # Missing key, unknown key and every authority-shaped key are refused
        # by the same closed set; raw input is never echoed.
        return None, _error(400, "unexpected_field", "요청 필드가 올바르지 않습니다.")
    # A JSON boolean only: "true", 1, 0 and null are not booleans.
    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        return None, _error(400, "invalid_enabled", "enabled는 true 또는 false여야 합니다.")
    return enabled, None


def _automation_store(request: Request) -> Any | None:
    store = getattr(request.app.state, "claw_automation_store", None)
    if store is None:
        return None
    if not callable(getattr(store, "get_rule", None)) or not callable(
        getattr(store, "set_rule_enabled", None)
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


async def claw_automation_rule_set_enabled(request: Request) -> JSONResponse:
    rule_id = request.path_params.get("rule_id", "")
    # The path value grants no authority: shape-checked through the existing
    # canonical _safe_id contract only (no second rule-id grammar).
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

    enabled, body_error = await read_enabled_flag(request)
    if body_error is not None:
        return body_error

    store = _automation_store(request)
    if store is None:
        return _error(503, "automation_store_unavailable", "규칙 상태를 변경하지 못했습니다.")

    # Lookup is scoped to the session's tenant only; a foreign-tenant rule and
    # a nonexistent rule are indistinguishable (both 404).
    try:
        rule = await _call(store.get_rule(rule_id, context.tenant_id))
    except Exception:
        return _error(503, "automation_rule_read_failed", "규칙 상태를 변경하지 못했습니다.")
    if not isinstance(rule, ClawAutomationRule):
        return _error(404, "automation_rule_not_found", "해당 자동화 규칙을 사용할 수 없습니다.")

    if not _is_mutable(rule):
        # Legacy/quarantined rows stay immutable in this slice. No provenance
        # or identity detail is disclosed.
        return _error(409, "automation_rule_not_mutable", "이 규칙은 변경할 수 없습니다.")

    if enabled and not _is_execution_ready(rule):
        # Enabling a canonical-shaped but incomplete rule would present it as
        # enabled while background execution could never resolve its owner or
        # execution material. Nothing is minted or repaired here.
        return _error(
            409,
            "automation_rule_not_execution_ready",
            "이 규칙은 실행 준비가 되지 않아 켤 수 없습니다.",
        )

    try:
        updated = await _call(store.set_rule_enabled(context.tenant_id, rule_id, enabled))
    except Exception:
        # No retry: an ambiguous write failure must not mint a second write.
        return _error(503, "automation_rule_save_failed", "규칙 상태를 변경하지 못했습니다.")
    if not isinstance(updated, ClawAutomationRule):
        return _error(503, "automation_rule_save_failed", "규칙 상태를 변경하지 못했습니다.")

    return JSONResponse(
        {"ok": True, "rule": project_web_rule_row(updated)},
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


__all__ = [
    "EXPECTED_BODY_KEYS",
    "MAX_BODY_BYTES",
    "RULE_ENABLED_TOGGLE",
    "claw_automation_rule_set_enabled",
    "read_enabled_flag",
]