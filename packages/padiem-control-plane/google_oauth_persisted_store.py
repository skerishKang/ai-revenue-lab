from __future__ import annotations

from datetime import datetime, timedelta
import json
from typing import Any

from padiem_control_plane.contracts import ControlPlaneContractError

from google_oauth_durable_store import (
    MAX_CONNECT_TICKET_RESIDUAL_LIFETIME_SECONDS,
    CloudflareDurableGoogleOAuthStore as _RowsWrittenGoogleOAuthStore,
    DurableGoogleOAuthAuthorizationState,
    DurableGoogleOAuthCredential,
    _REVIEWED_SCOPES,
    _iso,
    _parse_iso,
    _row_value,
    _rows,
    _safe_ref,
    _utc,
)


def _single_or_none(rows: list[Any], *, label: str) -> Any | None:
    if len(rows) > 1:
        raise RuntimeError(f"durable Google OAuth {label} contains duplicate primary rows")
    return rows[0] if rows else None


def _require_exact(row: Any, expected: dict[str, Any], *, label: str) -> None:
    for name, value in expected.items():
        if _row_value(row, name) != value:
            raise RuntimeError(f"durable Google OAuth {label} did not persist the expected row")


class CloudflareDurableGoogleOAuthStore(_RowsWrittenGoogleOAuthStore):
    """Production OAuth store whose correctness is anchored to persisted SQL rows.

    Cloudflare exposes ``rowsWritten`` as a cursor progress/billing counter. The
    production runtime has repeatedly returned a non-final value even after the
    write itself became visible. This adapter therefore keeps the reviewed base
    schema and validation contract, but proves every security-relevant write by
    reading the durable row inside the same synchronous transaction.
    """

    def begin_authorization(
        self,
        *,
        ticket_id: str,
        connector_id: str,
        ticket_expires_at: datetime,
        state: DurableGoogleOAuthAuthorizationState,
        now: datetime,
    ) -> DurableGoogleOAuthAuthorizationState:
        ticket_id = _safe_ref(ticket_id, "ticket_id")
        connector_id = _safe_ref(connector_id, "connector_id")
        if connector_id not in _REVIEWED_SCOPES:
            raise ControlPlaneContractError(
                "invalid_google_oauth_durable_record",
                "connector_id is not a reviewed Google readonly connector",
            )
        now = _utc(now, "now")
        ticket_expires_at = _utc(ticket_expires_at, "ticket_expires_at")
        if now >= ticket_expires_at:
            raise ControlPlaneContractError("expired_connect_ticket", "connector ticket has expired")
        if ticket_expires_at > now + timedelta(seconds=MAX_CONNECT_TICKET_RESIDUAL_LIFETIME_SECONDS):
            raise ControlPlaneContractError(
                "invalid_connect_ticket",
                "connector ticket residual lifetime exceeds the trusted bound",
            )
        if not isinstance(state, DurableGoogleOAuthAuthorizationState):
            raise ValueError("state must be DurableGoogleOAuthAuthorizationState")
        if state.ticket_id != ticket_id or state.connector_id != connector_id:
            raise ControlPlaneContractError(
                "google_oauth_state_mismatch",
                "authorization state does not match the consumed connector ticket",
            )
        if now < state.created_at - timedelta(seconds=30) or now >= state.expires_at:
            raise ControlPlaneContractError(
                "invalid_google_oauth_authorization_state",
                "authorization state is not currently usable",
            )

        consumed_at = _iso(now)
        ticket_expiry = _iso(ticket_expires_at)
        state_created = _iso(state.created_at)
        state_expiry = _iso(state.expires_at)

        def operation() -> DurableGoogleOAuthAuthorizationState:
            existing_ticket = _single_or_none(
                _rows(
                    self._sql.exec(
                        "SELECT ticket_id FROM google_oauth_connect_ticket_use WHERE ticket_id = ?",
                        ticket_id,
                    )
                ),
                label="connect-ticket table",
            )
            if existing_ticket is not None:
                raise ControlPlaneContractError(
                    "replayed_connect_ticket",
                    "connector connect ticket was already consumed",
                )

            _rows(
                self._sql.exec(
                    "INSERT INTO google_oauth_connect_ticket_use "
                    "(ticket_id, connector_id, consumed_at, ticket_expires_at) VALUES (?, ?, ?, ?)",
                    ticket_id,
                    connector_id,
                    consumed_at,
                    ticket_expiry,
                )
            )
            persisted_ticket = _single_or_none(
                _rows(
                    self._sql.exec(
                        "SELECT ticket_id, connector_id, consumed_at, ticket_expires_at "
                        "FROM google_oauth_connect_ticket_use WHERE ticket_id = ?",
                        ticket_id,
                    )
                ),
                label="connect-ticket table",
            )
            if persisted_ticket is None:
                raise RuntimeError("connect-ticket consumption was not durably persisted")
            _require_exact(
                persisted_ticket,
                {
                    "ticket_id": ticket_id,
                    "connector_id": connector_id,
                    "consumed_at": consumed_at,
                    "ticket_expires_at": ticket_expiry,
                },
                label="connect-ticket consumption",
            )

            state_conflicts = _rows(
                self._sql.exec(
                    "SELECT state_ref, ticket_id FROM google_oauth_authorization_state "
                    "WHERE state_ref = ? OR ticket_id = ?",
                    state.state_ref,
                    state.ticket_id,
                )
            )
            if state_conflicts:
                raise ControlPlaneContractError(
                    "duplicate_google_oauth_state",
                    "authorization state reference already exists",
                )

            _rows(
                self._sql.exec(
                    "INSERT INTO google_oauth_authorization_state "
                    "(state_ref, ticket_id, connector_id, sealed_session, created_at, expires_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    state.state_ref,
                    state.ticket_id,
                    state.connector_id,
                    state.sealed_session,
                    state_created,
                    state_expiry,
                )
            )
            persisted_state = _single_or_none(
                _rows(
                    self._sql.exec(
                        "SELECT state_ref, ticket_id, connector_id, sealed_session, created_at, expires_at "
                        "FROM google_oauth_authorization_state WHERE state_ref = ?",
                        state.state_ref,
                    )
                ),
                label="authorization-state table",
            )
            if persisted_state is None:
                raise RuntimeError("authorization state was not durably persisted")
            _require_exact(
                persisted_state,
                {
                    "state_ref": state.state_ref,
                    "ticket_id": state.ticket_id,
                    "connector_id": state.connector_id,
                    "sealed_session": state.sealed_session,
                    "created_at": state_created,
                    "expires_at": state_expiry,
                },
                label="authorization state",
            )
            return state

        return self.transaction(operation)

    def consume_authorization_state(
        self,
        *,
        state_ref: str,
        now: datetime,
    ) -> DurableGoogleOAuthAuthorizationState:
        state_ref = _safe_ref(state_ref, "state_ref")
        now = _utc(now, "now")

        def operation() -> DurableGoogleOAuthAuthorizationState:
            row = _single_or_none(
                _rows(
                    self._sql.exec(
                        "SELECT state_ref, ticket_id, connector_id, sealed_session, created_at, expires_at "
                        "FROM google_oauth_authorization_state WHERE state_ref = ?",
                        state_ref,
                    )
                ),
                label="authorization-state table",
            )
            if row is None:
                raise ControlPlaneContractError(
                    "missing_google_oauth_state",
                    "authorization state is missing or already consumed",
                )
            state = DurableGoogleOAuthAuthorizationState(
                state_ref=_row_value(row, "state_ref"),
                ticket_id=_row_value(row, "ticket_id"),
                connector_id=_row_value(row, "connector_id"),
                sealed_session=_row_value(row, "sealed_session"),
                created_at=_parse_iso(_row_value(row, "created_at"), "created_at"),
                expires_at=_parse_iso(_row_value(row, "expires_at"), "expires_at"),
            )
            _rows(
                self._sql.exec(
                    "DELETE FROM google_oauth_authorization_state WHERE state_ref = ?",
                    state_ref,
                )
            )
            remaining = _rows(
                self._sql.exec(
                    "SELECT state_ref FROM google_oauth_authorization_state WHERE state_ref = ?",
                    state_ref,
                )
            )
            if remaining:
                raise RuntimeError("authorization state remained after atomic consume")
            return state

        state = self.transaction(operation)
        if now >= state.expires_at:
            raise ControlPlaneContractError(
                "expired_google_oauth_state",
                "authorization state has expired and was permanently consumed",
            )
        return state

    def save_credential(self, record: DurableGoogleOAuthCredential) -> None:
        if not isinstance(record, DurableGoogleOAuthCredential):
            raise ValueError("record must be DurableGoogleOAuthCredential")

        scopes_json = json.dumps(list(record.scopes), separators=(",", ":"), ensure_ascii=True)
        issued_at = _iso(record.issued_at)
        expires_at = _iso(record.expires_at) if record.expires_at is not None else None
        revoked_at = _iso(record.revoked_at) if record.revoked_at is not None else None

        def operation() -> None:
            existing = _single_or_none(
                _rows(
                    self._sql.exec(
                        "SELECT binding_ref FROM google_oauth_refresh_credential WHERE binding_ref = ?",
                        record.binding_ref,
                    )
                ),
                label="credential table",
            )
            if existing is not None:
                raise ControlPlaneContractError(
                    "duplicate_google_oauth_binding",
                    "Google OAuth credential binding already exists",
                )

            _rows(
                self._sql.exec(
                    "INSERT INTO google_oauth_refresh_credential "
                    "(binding_ref, connector_id, actor_ref, account_ref, workspace_ref, scopes_json, "
                    "sealed_refresh_token, issued_at, expires_at, revoked_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    record.binding_ref,
                    record.connector_id,
                    record.actor_ref,
                    record.account_ref,
                    record.workspace_ref,
                    scopes_json,
                    record.sealed_refresh_token,
                    issued_at,
                    expires_at,
                    revoked_at,
                )
            )
            persisted = _single_or_none(
                _rows(
                    self._sql.exec(
                        "SELECT binding_ref, connector_id, actor_ref, account_ref, workspace_ref, scopes_json, "
                        "sealed_refresh_token, issued_at, expires_at, revoked_at "
                        "FROM google_oauth_refresh_credential WHERE binding_ref = ?",
                        record.binding_ref,
                    )
                ),
                label="credential table",
            )
            if persisted is None:
                raise RuntimeError("Google OAuth credential was not durably persisted")
            _require_exact(
                persisted,
                {
                    "binding_ref": record.binding_ref,
                    "connector_id": record.connector_id,
                    "actor_ref": record.actor_ref,
                    "account_ref": record.account_ref,
                    "workspace_ref": record.workspace_ref,
                    "scopes_json": scopes_json,
                    "sealed_refresh_token": record.sealed_refresh_token,
                    "issued_at": issued_at,
                    "expires_at": expires_at,
                    "revoked_at": revoked_at,
                },
                label="credential",
            )

        self.transaction(operation)

    def revoke_credential(self, *, binding_ref: str, revoked_at: datetime) -> None:
        binding_ref = _safe_ref(binding_ref, "binding_ref")
        revoked_at = _utc(revoked_at, "revoked_at")
        revoked_text = _iso(revoked_at)

        def operation() -> None:
            found = _single_or_none(
                _rows(
                    self._sql.exec(
                        "SELECT issued_at, revoked_at FROM google_oauth_refresh_credential WHERE binding_ref = ?",
                        binding_ref,
                    )
                ),
                label="credential table",
            )
            if found is None or _row_value(found, "revoked_at") is not None:
                raise ControlPlaneContractError(
                    "inactive_google_oauth_binding",
                    "Google OAuth credential is missing or already revoked",
                )
            issued_at = _parse_iso(_row_value(found, "issued_at"), "issued_at")
            if revoked_at < issued_at:
                raise ControlPlaneContractError(
                    "invalid_google_oauth_durable_record",
                    "credential revocation cannot predate issue time",
                )

            _rows(
                self._sql.exec(
                    "UPDATE google_oauth_refresh_credential SET revoked_at = ? "
                    "WHERE binding_ref = ? AND revoked_at IS NULL",
                    revoked_text,
                    binding_ref,
                )
            )
            persisted = _single_or_none(
                _rows(
                    self._sql.exec(
                        "SELECT revoked_at FROM google_oauth_refresh_credential WHERE binding_ref = ?",
                        binding_ref,
                    )
                ),
                label="credential table",
            )
            if persisted is None or _row_value(persisted, "revoked_at") != revoked_text:
                raise RuntimeError("Google OAuth credential revocation was not durably persisted")

        self.transaction(operation)


OAUTH_ROWSWRITTEN_CORRECTNESS_DEPENDENCY = False
TICKET_REPLAY_PERSISTED_ROW_PROOF = True
STATE_UNIQUENESS_PERSISTED_ROW_PROOF = True
STATE_DELETE_PERSISTED_ROW_PROOF = True
CREDENTIAL_INSERT_PERSISTED_ROW_PROOF = True
CREDENTIAL_REVOKE_PERSISTED_ROW_PROOF = True
REPLAY_PROTECTION_WEAKENED = False
CONNECT_IDEMPOTENT = False
PRODUCTION_MUTATION = False
