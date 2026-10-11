"""D1-backed connector grant store for the Engine Worker (WO-10 PR-C2, D28).

Stores only grant references (app/agent/binding/actor/scopes/active).
OAuth credential material (client id, client secret, refresh token) is
injected via Worker secrets and never persisted here.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from padiem_ai_core.calendar_capability import (
    CALENDAR_CONNECTOR_ID,
    CalendarCapability,
)
from padiem_ai_core.drive_capability import DRIVE_CONNECTOR_ID, DriveCapability
from padiem_ai_core.slack_capability import (
    SLACK_CONNECTOR_ID,
    SlackCapability,
)
from padiem_ai_core.telegram_capability import (
    TELEGRAM_CONNECTOR_ID,
    TelegramCapability,
)
from app.connector_bindings import (
    GMAIL_CONNECTOR_ID,
    CALENDAR_AGENT_ID,
    CALENDAR_REFERENCE_APP_ID,
    CalendarGrant,
    GmailGrant,
    DriveGrant,
    SlackGrant,
    TelegramGrant,
)
from app.continuation_d1 import _maybe_await
from app.service import ServiceContractError

_TABLE_NAME = "padiem_engine_connector_grants"

# #2010: the Calendar READ slot is one canonical row for the whole store, so an
# activation must only ever rewrite a row that already belongs to the same trusted
# identity. A refusal is a normal outcome for another workspace, never a storage fault,
# and it must not disclose whose row it hit.
_ACTIVATION_REFUSED_CODE = "calendar_grant_slot_occupied"


def _activation_refused() -> ServiceContractError:
    return ServiceContractError(
        _ACTIVATION_REFUSED_CODE,
        "Calendar grant activation is not available for this workspace.",
        status_code=409,
    )


def _activation_unavailable(message: str) -> ServiceContractError:
    return ServiceContractError(
        "calendar_grant_activation_unavailable",
        message,
        status_code=503,
    )


def _d1_meta(result: Any) -> Mapping[str, Any] | None:
    """Read D1 ``run()`` meta from any of its shapes, or say it is unknown."""

    if isinstance(result, Mapping):
        meta: Any = result.get("meta")
    else:
        meta = getattr(result, "meta", None)
    to_py = getattr(meta, "to_py", None)
    if callable(to_py):
        meta = to_py()
    if isinstance(meta, Mapping):
        return {str(key): value for key, value in meta.items()}
    if meta is None:
        return None
    values = {}
    for key in ("changes", "rows_changed", "rowsUpdated", "rows_updated"):
        value = getattr(meta, key, None)
        if value is not None:
            values[key] = value
    return values or None


def _reported_changes(result: Any) -> int | None:
    """Rows the single guarded statement actually changed, or None when unknown.

    ``changes`` is D1's own answer for INSERT ... ON CONFLICT ... DO UPDATE: 0 means the
    conflict clause's WHERE rejected the write, which is decided inside the statement.
    A bool is never a row count, and an unrecognisable answer stays None so the caller
    must fall back to the canonical read-back instead of guessing.
    """

    meta = _d1_meta(result)
    if meta is None:
        return None
    for key in ("changes", "rows_changed", "rowsUpdated", "rows_updated"):
        value = meta.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        return value if value >= 0 else None
    return None


def _reported_success(result: Any) -> bool | None:
    """Whether D1 says the statement itself ran, or None when it does not say.

    Only an explicit ``success: false`` counts as a failure. The flag is absent in some
    D1Result shapes and in most doubles, and a missing answer must stay a read-back
    classification rather than becoming a fabricated storage fault.
    """

    for key in ("success", "ok", "succeeded"):
        value = result.get(key) if isinstance(result, Mapping) else getattr(result, key, None)
        if isinstance(value, bool):
            return value
    return None


class CloudflareD1ConnectorGrantStore:
    """Durable connector grant store backed by a trusted D1-like binding."""

    def __init__(self, binding: Any) -> None:
        if binding is None or not callable(getattr(binding, "prepare", None)):
            raise ValueError("connector grant binding must provide prepare(sql)")
        self._binding = binding

    async def _all(self, sql: str, *params: Any) -> list[Mapping[str, Any]]:
        result = await _maybe_await(self._binding.prepare(sql).bind(*params).all())

        # Cloudflare D1 all()/run() returns a D1Result object whose query rows
        # live under ``results``. Python Workers may expose that collection as
        # a JS proxy, in which case ``to_py()`` materializes the row list.
        # Keep list/tuple compatibility for existing isolated test doubles.
        if isinstance(result, Mapping):
            rows: Any = result.get("results")
        elif isinstance(result, (list, tuple)):
            rows = result
        else:
            rows = getattr(result, "results", None)

        to_py = getattr(rows, "to_py", None)
        if callable(to_py):
            rows = to_py()

        if rows is None:
            raise TypeError("D1 result is missing results")
        if not isinstance(rows, (list, tuple)):
            raise TypeError("D1 results must be a row sequence")

        normalized: list[Mapping[str, Any]] = []
        for row in rows:
            row_to_py = getattr(row, "to_py", None)
            if callable(row_to_py):
                row = row_to_py()
            if not isinstance(row, Mapping):
                raise TypeError("D1 result row must be a mapping")
            normalized.append(dict(row))
        return normalized

    async def load_gmail_grants(self) -> dict[str, GmailGrant]:
        sql = (
            f"SELECT app_id, canonical_agent_id, connector_id, binding_ref, "
            f"actor_ref, granted_scopes_json FROM {_TABLE_NAME} "
            f"WHERE connector_id = ? AND active = 1"
        )
        try:
            rows = await self._all(sql, GMAIL_CONNECTOR_ID)
        except Exception:
            raise ServiceContractError(
                "connector_grants_unavailable",
                "Connector grant storage returned an invalid record.",
                status_code=503,
            ) from None

        grants: dict[str, GmailGrant] = {}
        for data in rows:
            try:
                scopes = tuple(json.loads(data["granted_scopes_json"]))
                grants[data["app_id"]] = GmailGrant(
                    app_id=str(data["app_id"]),
                    canonical_agent_id=str(data["canonical_agent_id"]),
                    binding_ref=str(data["binding_ref"]),
                    actor_ref=str(data["actor_ref"]),
                    granted_scopes=scopes,
                )
            except (ValueError, KeyError, TypeError):
                raise ServiceContractError(
                    "connector_grants_unavailable",
                    "Connector grant storage returned an invalid record.",
                    status_code=503,
                ) from None

        return grants

    async def load_drive_grants(self) -> dict[str, DriveGrant]:
        sql = (
            f"SELECT app_id, canonical_agent_id, connector_id, binding_ref, "
            f"actor_ref, granted_capabilities_json FROM {_TABLE_NAME} "
            f"WHERE connector_id = ? AND active = 1"
        )
        try:
            rows = await self._all(sql, DRIVE_CONNECTOR_ID)
        except Exception:
            raise ServiceContractError(
                "connector_grants_unavailable",
                "Connector grant storage returned an invalid record.",
                status_code=503,
            ) from None

        grants: dict[str, DriveGrant] = {}
        for data in rows:
            try:
                raw_capabilities = json.loads(data["granted_capabilities_json"])
                if raw_capabilities != [DriveCapability.READ.value]:
                    raise ValueError("Drive grants must contain exactly the reviewed READ capability")
                capabilities = (DriveCapability.READ,)
                grants[data["app_id"]] = DriveGrant(
                    app_id=str(data["app_id"]),
                    canonical_agent_id=str(data["canonical_agent_id"]),
                    binding_ref=str(data["binding_ref"]),
                    actor_ref=str(data["actor_ref"]),
                    granted_capabilities=capabilities,
                )
            except (ValueError, KeyError, TypeError):
                raise ServiceContractError(
                    "connector_grants_unavailable",
                    "Connector grant storage returned an invalid record.",
                    status_code=503,
                ) from None

        return grants

    async def load_telegram_grants(self) -> dict[str, TelegramGrant]:
        # Reuses the existing grants table and granted_capabilities_json
        # column: no schema migration is introduced by the Telegram promotion
        # (#2353, SCHEMA_MIGRATION=0).
        sql = (
            f"SELECT app_id, canonical_agent_id, connector_id, binding_ref, "
            f"actor_ref, granted_capabilities_json FROM {_TABLE_NAME} "
            f"WHERE connector_id = ? AND active = 1"
        )
        try:
            rows = await self._all(sql, TELEGRAM_CONNECTOR_ID)
        except Exception:
            raise ServiceContractError(
                "connector_grants_unavailable",
                "Connector grant storage returned an invalid record.",
                status_code=503,
            ) from None

        grants: dict[str, TelegramGrant] = {}
        for data in rows:
            try:
                raw_capabilities = json.loads(data["granted_capabilities_json"])
                if raw_capabilities != [TelegramCapability.READ.value]:
                    raise ValueError("Telegram grants must contain exactly the promoted READ capability")
                capabilities = (TelegramCapability.READ,)
                grants[data["app_id"]] = TelegramGrant(
                    app_id=str(data["app_id"]),
                    canonical_agent_id=str(data["canonical_agent_id"]),
                    binding_ref=str(data["binding_ref"]),
                    actor_ref=str(data["actor_ref"]),
                    granted_capabilities=capabilities,
                )
            except (ValueError, KeyError, TypeError):
                raise ServiceContractError(
                    "connector_grants_unavailable",
                    "Connector grant storage returned an invalid record.",
                    status_code=503,
                ) from None

        return grants

    async def load_slack_grants(self) -> dict[str, SlackGrant]:
        # Reuses the existing grants table and canonical capability/scope
        # columns: no schema migration is introduced by the Slack promotion
        # (#2356, SCHEMA_MIGRATION=0).
        sql = (
            f"SELECT app_id, canonical_agent_id, connector_id, binding_ref, "
            f"actor_ref, granted_capabilities_json, granted_scopes_json "
            f"FROM {_TABLE_NAME} WHERE connector_id = ? AND active = 1"
        )
        try:
            rows = await self._all(sql, SLACK_CONNECTOR_ID)
        except Exception:
            raise ServiceContractError(
                "connector_grants_unavailable",
                "Connector grant storage returned an invalid record.",
                status_code=503,
            ) from None

        grants: dict[str, SlackGrant] = {}
        for data in rows:
            try:
                raw_capabilities = json.loads(data["granted_capabilities_json"])
                raw_scopes = json.loads(data["granted_scopes_json"])
                if raw_capabilities != [SlackCapability.READ.value]:
                    raise ValueError("Slack grants must contain exactly the promoted READ capability")
                if raw_scopes != []:
                    raise ValueError("Slack grants must contain exactly an empty scope list")
                capabilities = (SlackCapability.READ,)
                grants[data["app_id"]] = SlackGrant(
                    app_id=str(data["app_id"]),
                    canonical_agent_id=str(data["canonical_agent_id"]),
                    binding_ref=str(data["binding_ref"]),
                    actor_ref=str(data["actor_ref"]),
                    granted_capabilities=capabilities,
                )
            except (ValueError, KeyError, TypeError):
                raise ServiceContractError(
                    "connector_grants_unavailable",
                    "Connector grant storage returned an invalid record.",
                    status_code=503,
                ) from None

        return grants

    async def load_calendar_grants(self) -> dict[str, CalendarGrant]:
        # Reuses the existing grants table and granted_capabilities_json
        # column: no schema migration is introduced by the Calendar
        # promotion (#2358, SCHEMA_MIGRATION=0).
        sql = (
            f"SELECT app_id, canonical_agent_id, connector_id, binding_ref, "
            f"actor_ref, granted_capabilities_json FROM {_TABLE_NAME} "
            f"WHERE connector_id = ? AND active = 1"
        )
        try:
            rows = await self._all(sql, CALENDAR_CONNECTOR_ID)
        except Exception:
            raise ServiceContractError(
                "connector_grants_unavailable",
                "Connector grant storage returned an invalid record.",
                status_code=503,
            ) from None

        grants: dict[str, CalendarGrant] = {}
        for data in rows:
            try:
                raw_capabilities = json.loads(data["granted_capabilities_json"])
                if raw_capabilities != [CalendarCapability.READ.value]:
                    raise ValueError("Calendar grants must contain exactly the promoted READ capability")
                capabilities = (CalendarCapability.READ,)
                grants[data["app_id"]] = CalendarGrant(
                    app_id=str(data["app_id"]),
                    canonical_agent_id=str(data["canonical_agent_id"]),
                    binding_ref=str(data["binding_ref"]),
                    actor_ref=str(data["actor_ref"]),
                    granted_capabilities=capabilities,
                )
            except (ValueError, KeyError, TypeError):
                raise ServiceContractError(
                    "connector_grants_unavailable",
                    "Connector grant storage returned an invalid record.",
                    status_code=503,
                ) from None

        return grants

    async def activate_calendar_read_grant(
        self,
        *,
        binding_ref: str,
        actor_ref: str,
    ) -> CalendarGrant:
        """Activate the canonical Calendar READ grant for one trusted identity.

        One statement, and it only rewrites a row that already carries the same
        ``binding_ref``/``actor_ref``: the first holder keeps the slot, a repeated activation
        of that same identity stays idempotent, and any other identity is refused without the
        row being touched. Nothing here grants a new capability or changes another connector.
        """

        try:
            grant = CalendarGrant(
                app_id=CALENDAR_REFERENCE_APP_ID,
                canonical_agent_id=CALENDAR_AGENT_ID,
                binding_ref=str(binding_ref),
                actor_ref=str(actor_ref),
                granted_capabilities=(CalendarCapability.READ,),
            )
        except (TypeError, ValueError):
            raise ServiceContractError(
                "calendar_grant_activation_invalid",
                "Calendar grant activation received invalid trusted identity.",
                status_code=503,
            ) from None

        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        sql = (
            f"INSERT INTO {_TABLE_NAME} "
            "(app_id, canonical_agent_id, connector_id, binding_ref, actor_ref, "
            "granted_scopes_json, granted_capabilities_json, active, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?) "
            "ON CONFLICT(app_id, connector_id) DO UPDATE SET "
            "canonical_agent_id=excluded.canonical_agent_id, active=1, "
            "binding_ref=excluded.binding_ref, actor_ref=excluded.actor_ref, "
            "granted_scopes_json=excluded.granted_scopes_json, "
            "granted_capabilities_json=excluded.granted_capabilities_json, "
            "updated_at=excluded.updated_at "
            f"WHERE {_TABLE_NAME}.binding_ref = excluded.binding_ref "
            f"AND {_TABLE_NAME}.actor_ref = excluded.actor_ref"
        )
        try:
            written = await _maybe_await(
                self._binding.prepare(sql).bind(
                    grant.app_id,
                    grant.canonical_agent_id,
                    CALENDAR_CONNECTOR_ID,
                    grant.binding_ref,
                    grant.actor_ref,
                    "[]",
                    json.dumps([CalendarCapability.READ.value], separators=(",", ":")),
                    now,
                    now,
                ).run()
            )
            # Reading the answer is part of trusting the adapter. A D1Result whose ``meta``
            # attribute or ``to_py()`` throws is a storage fault, not a contract outcome,
            # so the interpretation happens inside the same normalising boundary.
            succeeded = _reported_success(written)
            changes = _reported_changes(written)
        except Exception:
            # Nothing raised inside the binding is trusted, not even an exception that
            # already looks like a ServiceContractError: its code and message belong to
            # the adapter and could carry whatever the adapter put there, so every fault
            # is normalised to this route's own generic 503.
            raise _activation_unavailable(
                "Calendar grant activation storage is unavailable."
            ) from None

        if succeeded is False:
            # A statement that reports failure is never a success, and never a refusal
            # either: a result carrying both ``success: false`` and ``changes: 0`` means
            # the adapter failed, so this stays ahead of the zero-change branch.
            raise _activation_unavailable(
                "Calendar grant activation storage is unavailable."
            )

        # The refusal decision lives inside the statement above, so two workspaces
        # activating at the same instant cannot both win and neither can clobber the winner.
        # The read-back only classifies an outcome the write already committed or rejected.
        if changes == 0:
            raise _activation_refused()

        current = (await self.load_calendar_grants()).get(CALENDAR_REFERENCE_APP_ID)
        if current is None:
            raise _activation_unavailable(
                "Calendar grant activation readback did not match the reviewed grant."
            )
        if not isinstance(current, CalendarGrant):
            raise _activation_unavailable(
                "Calendar grant activation readback did not match the reviewed grant."
            )
        if current.binding_ref != grant.binding_ref or current.actor_ref != grant.actor_ref:
            # Reachable only when the binding never reports a row count: the guarded
            # statement still refused, and an unknown answer is never treated as success.
            raise _activation_refused()
        if current != grant:
            raise _activation_unavailable(
                "Calendar grant activation readback did not match the reviewed grant."
            )
        return current


__all__ = ["CloudflareD1ConnectorGrantStore"]