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
from app.connector_bindings import GMAIL_CONNECTOR_ID, GmailGrant, DriveGrant
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
                capabilities = tuple(
                    DriveCapability(item)
                    for item in json.loads(data["granted_capabilities_json"])
                )
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


__all__ = ["CloudflareD1ConnectorGrantStore"]