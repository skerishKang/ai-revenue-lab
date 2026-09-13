"""D1-backed connector grant store for the Engine Worker (WO-10 PR-C2, D28).

Stores only grant references (app/agent/binding/actor/scopes/active).
OAuth credential material (client id, client secret, refresh token) is
injected via Worker secrets and never persisted here.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Mapping
from typing import Any

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
    GmailGrant,
    DriveGrant,
    SlackGrant,
    TelegramGrant,
)
from app.continuation_d1 import _maybe_await
from app.service import ServiceContractError

_TABLE_NAME = "padiem_engine_connector_grants"


class CloudflareD1ConnectorGrantStore:
    """Durable connector grant store backed by a trusted D1-like binding."""

    def __init__(self, binding: Any) -> None:
        if binding is None or not callable(getattr(binding, "prepare", None)):
            raise ValueError("connector grant binding must provide prepare(sql)")
        self._binding = binding

    async def _all(self, sql: str, *params: Any) -> list[Mapping[str, Any]]:
        rows = await _maybe_await(self._binding.prepare(sql).bind(*params).all())
        return [dict(row) for row in rows] if rows else []

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
        # Reuses the existing grants table and granted_capabilities_json
        # column: no schema migration is introduced by the Slack promotion
        # (#2356, SCHEMA_MIGRATION=0).
        sql = (
            f"SELECT app_id, canonical_agent_id, connector_id, binding_ref, "
            f"actor_ref, granted_capabilities_json FROM {_TABLE_NAME} "
            f"WHERE connector_id = ? AND active = 1"
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
                if raw_capabilities != [SlackCapability.READ.value]:
                    raise ValueError("Slack grants must contain exactly the promoted READ capability")
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


__all__ = ["CloudflareD1ConnectorGrantStore"]