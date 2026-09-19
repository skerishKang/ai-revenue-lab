from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from google_oauth_durable_store import (
    CloudflareDurableGoogleOAuthStore,
    DurableGoogleOAuthAuthorizationState,
)
from local_agent_broker_sql_state import rows_written as local_agent_rows_written
from padiem_control_plane.contracts import ControlPlaneContractError


NOW = datetime(2026, 9, 17, 11, 0, tzinfo=timezone.utc)
SEALED_SESSION = "sealed:v1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


class DelayedRowsWrittenCursor:
    """Mimic Cloudflare SQL cursors whose counters finalize on consumption."""

    def __init__(self, *, rows: list[dict], final_rows_written: int) -> None:
        self._rows = rows
        self._final_rows_written = final_rows_written
        self.rowsWritten = 0
        self.consumed = False

    def toArray(self) -> list[dict]:
        self.consumed = True
        self.rowsWritten = self._final_rows_written
        return list(self._rows)


class DelayedRowsWrittenSql:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def exec(self, statement: str, *args):
        cursor = self._connection.execute(statement, args)
        if statement.lstrip().upper().startswith("SELECT"):
            columns = [item[0] for item in cursor.description or ()]
            rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
            return DelayedRowsWrittenCursor(rows=rows, final_rows_written=0)
        rows_written = cursor.rowcount if cursor.rowcount >= 0 else 0
        return DelayedRowsWrittenCursor(rows=[], final_rows_written=rows_written)


class DelayedRowsWrittenStorage:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.sql = DelayedRowsWrittenSql(self.connection)

    def transactionSync(self, operation):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            result = operation()
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")
        return result

    def scalar(self, statement: str, *args):
        return self.connection.execute(statement, args).fetchone()[0]


def _state(*, state_ref: str, ticket_id: str) -> DurableGoogleOAuthAuthorizationState:
    return DurableGoogleOAuthAuthorizationState(
        state_ref=state_ref,
        ticket_id=ticket_id,
        connector_id="google-drive",
        sealed_session=SEALED_SESSION,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )


def test_oauth_write_cursor_is_consumed_before_rows_written_is_validated() -> None:
    storage = DelayedRowsWrittenStorage()
    store = CloudflareDurableGoogleOAuthStore(storage)
    first = _state(state_ref="state.delayed.1", ticket_id="ticket.delayed.1")

    assert store.begin_authorization(
        ticket_id=first.ticket_id,
        connector_id=first.connector_id,
        ticket_expires_at=NOW + timedelta(minutes=3),
        state=first,
        now=NOW,
    ) == first
    assert storage.scalar("SELECT count(*) FROM google_oauth_connect_ticket_use") == 1
    assert storage.scalar("SELECT count(*) FROM google_oauth_authorization_state") == 1

    with pytest.raises(ControlPlaneContractError) as replay:
        store.begin_authorization(
            ticket_id=first.ticket_id,
            connector_id=first.connector_id,
            ticket_expires_at=NOW + timedelta(minutes=3),
            state=_state(state_ref="state.delayed.2", ticket_id=first.ticket_id),
            now=NOW,
        )
    assert replay.value.code == "replayed_connect_ticket"
    assert storage.scalar("SELECT count(*) FROM google_oauth_connect_ticket_use") == 1
    assert storage.scalar("SELECT count(*) FROM google_oauth_authorization_state") == 1


def test_local_agent_rows_written_finalizes_cursor_before_reading_counter() -> None:
    cursor = DelayedRowsWrittenCursor(rows=[], final_rows_written=1)

    assert cursor.rowsWritten == 0
    assert local_agent_rows_written(cursor) == 1
    assert cursor.consumed is True


def test_rows_written_validation_still_fails_closed_after_cursor_consumption() -> None:
    cursor = DelayedRowsWrittenCursor(rows=[], final_rows_written=-1)

    with pytest.raises(RuntimeError, match="invalid rowsWritten"):
        local_agent_rows_written(cursor)
    assert cursor.consumed is True
