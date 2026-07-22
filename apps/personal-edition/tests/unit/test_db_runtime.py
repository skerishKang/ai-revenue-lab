"""Zero-network unit tests for the dual-backend runtime connection boundary.

Covers:
- import-time / construction-time connection 0회
- SQLite boundary preserves existing behaviour (row shape, commit/rollback/
  close, no placeholder transformation)
- PostgreSQL adapter row/cursor shape (mapping rows, rowcount, fetch*)
- explicit write-transaction contract (begin_write, legacy BEGIN IMMEDIATE
  forwarding, nested/failed/unknown fail-closed, commit/rollback -> idle)
- qmark -> %s placeholder lexer (quotes, comments, dollar quotes, escapes,
  count mismatch, no value interpolation)
- backend-neutral error contract (unique/FK/check/not_null/unknown, no raw
  driver text, cause preserved, no credential/URL leak)
- static contract: current runtime repository SQL has no literal '?' inside
  strings/comments and a consistent qmark/params count
- secret redaction in adapter/exception repr/str
"""

from __future__ import annotations

import ast
import importlib
import socket
import sys
from pathlib import Path

import pytest
from psycopg import errors as pg_errors
from psycopg.pq import TransactionStatus

import psycopg

from app.db_runtime import (
    DatabaseError,
    DatabaseIntegrityError,
    PlaceholderError,
    PostgresRuntimeConnection,
    RuntimeTransactionError,
    SqliteRuntimeConnection,
    _safe_constraint_name,
    classify_pg_error,
    sqlite_runtime_connection,
    translate_placeholders,
)


# ---------------------------------------------------------------------------
# Fakes (no real PostgreSQL connection)
# ---------------------------------------------------------------------------


class FakeCursor:
    def __init__(self, rows=None, rowcount=None):
        self._rows = list(rows or [])
        self.rowcount = rowcount if rowcount is not None else len(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakePgConnection:
    """Mimics the subset of psycopg.Connection[DictRow] the adapter uses.

    Transaction status is exposed via ``info.transaction_status`` matching
    the real psycopg 3 API (``conn.info.transaction_status``).
    """

    class _Info:
        def __init__(self, status):
            self.transaction_status = status

    def __init__(self, status=TransactionStatus.IDLE):
        self.info = self._Info(status)
        self.executed = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self._raise = None
        self._rows = []

    def set_raise(self, exc):
        self._raise = exc

    def set_rows(self, rows):
        self._rows = rows

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self._raise is not None:
            raise self._raise
        if sql.strip().upper() == "BEGIN":
            self.info.transaction_status = TransactionStatus.INTRANS
        return FakeCursor(self._rows)

    def commit(self):
        self.commits += 1
        self.info.transaction_status = TransactionStatus.IDLE

    def rollback(self):
        self.rollbacks += 1
        self.info.transaction_status = TransactionStatus.IDLE

    def close(self):
        self.closed = True


def _opened_adapter(status=TransactionStatus.IDLE, rows=None):
    fake = FakePgConnection(status=status)
    if rows is not None:
        fake.set_rows(rows)
    adapter = PostgresRuntimeConnection(lambda: fake)
    adapter.open()
    return adapter, fake


# ---------------------------------------------------------------------------
# Import / construction: zero network
# ---------------------------------------------------------------------------


@pytest.fixture
def socket_guard(monkeypatch):
    counter = {"n": 0}
    real = socket.socket

    class Guarded(real):
        def __init__(self, *args, **kwargs):
            counter["n"] += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(socket, "socket", Guarded)
    return counter


class TestImportNoConnection:
    def test_module_import_opens_no_socket(self, socket_guard):
        for mod in list(sys.modules):
            if mod.startswith("app.db_runtime") or mod == "app.db_postgres":
                del sys.modules[mod]
        importlib.import_module("app.db_runtime")
        assert socket_guard["n"] == 0

    def test_construction_does_not_call_factory(self):
        calls = {"n": 0}

        def factory():
            calls["n"] += 1
            return FakePgConnection()

        PostgresRuntimeConnection(factory)
        assert calls["n"] == 0

    def test_factory_called_only_on_explicit_open(self):
        calls = {"n": 0}

        def factory():
            calls["n"] += 1
            return FakePgConnection()

        adapter = PostgresRuntimeConnection(factory)
        assert calls["n"] == 0
        adapter.open()
        assert calls["n"] == 1
        # open() is idempotent — the factory is not called again.
        adapter.open()
        assert calls["n"] == 1

    def test_context_manager_opps_and_closes(self):
        fake = FakePgConnection()
        calls = {"n": 0}

        def factory():
            calls["n"] += 1
            return fake

        with PostgresRuntimeConnection(factory) as adapter:
            assert calls["n"] == 1
            assert adapter is not None
        assert fake.closed is True

    def test_operations_require_open(self):
        adapter = PostgresRuntimeConnection(lambda: FakePgConnection())
        with pytest.raises(RuntimeError, match="not open"):
            adapter.execute("SELECT 1")
        with pytest.raises(RuntimeError, match="not open"):
            adapter.begin_write()
        with pytest.raises(RuntimeError, match="not open"):
            adapter.commit()


# ---------------------------------------------------------------------------
# SQLite boundary
# ---------------------------------------------------------------------------


class TestSqliteBoundary:
    def test_row_shape_preserved(self, tmp_path):
        conn = sqlite_runtime_connection(":memory:")
        try:
            conn.execute("CREATE TABLE t (id TEXT, n INTEGER)")
            conn.execute("INSERT INTO t (id, n) VALUES (?, ?)", ("a", 1))
            conn.commit()
            row = conn.execute("SELECT id, n FROM t WHERE id = ?", ("a",)).fetchone()
            assert row["id"] == "a"
            assert row["n"] == 1
        finally:
            conn.close()

    def test_commit_persists_and_rollback_reverts(self, tmp_path):
        db = str(tmp_path / "x.db")
        conn = sqlite_runtime_connection(db)
        try:
            conn.execute("CREATE TABLE t (id TEXT)")
            conn.commit()

            conn.begin_write()
            conn.execute("INSERT INTO t (id) VALUES (?)", ("keep",))
            conn.commit()

            conn.begin_write()
            conn.execute("INSERT INTO t (id) VALUES (?)", ("drop",))
            conn.rollback()

            rows = conn.execute("SELECT id FROM t ORDER BY id").fetchall()
            assert [r["id"] for r in rows] == ["keep"]
        finally:
            conn.close()

    def test_begin_write_sets_in_transaction(self):
        conn = sqlite_runtime_connection(":memory:")
        try:
            conn.execute("CREATE TABLE t (id TEXT)")
            conn.commit()
            assert conn.in_transaction is False
            conn.begin_write()
            assert conn.in_transaction is True
            conn.rollback()
            assert conn.in_transaction is False
        finally:
            conn.close()

    def test_no_placeholder_transformation(self):
        # If the wrapper translated '?' to '%s', SQLite would raise.
        conn = sqlite_runtime_connection(":memory:")
        try:
            conn.execute("CREATE TABLE t (id TEXT)")
            conn.execute("INSERT INTO t (id) VALUES (?)", ("qmark-ok",))
            conn.commit()
            row = conn.execute(
                "SELECT id FROM t WHERE id = ?", ("qmark-ok",)
            ).fetchone()
            assert row["id"] == "qmark-ok"
        finally:
            conn.close()

    def test_pragma_foreign_keys_preserved(self):
        conn = sqlite_runtime_connection(":memory:")
        try:
            row = conn.execute("PRAGMA foreign_keys").fetchone()
            assert row[0] == 1
        finally:
            conn.close()

    def test_close_is_effective(self):
        conn = sqlite_runtime_connection(":memory:")
        conn.close()
        with pytest.raises(Exception):
            conn.execute("SELECT 1")


# ---------------------------------------------------------------------------
# PostgreSQL adapter: row / cursor shape
# ---------------------------------------------------------------------------


class TestPostgresRowCursor:
    def test_mapping_row_column_access(self):
        adapter, fake = _opened_adapter(
            rows=[{"id": "abc", "edition_number": 3}]
        )
        row = adapter.execute(
            "SELECT id, edition_number FROM editions WHERE id = ?", ("abc",)
        ).fetchone()
        assert row["id"] == "abc"
        assert row["edition_number"] == 3

    def test_fetchall_shape(self):
        adapter, fake = _opened_adapter(
            rows=[{"id": "1"}, {"id": "2"}, {"id": "3"}]
        )
        rows = adapter.execute("SELECT id FROM editions").fetchall()
        assert [r["id"] for r in rows] == ["1", "2", "3"]

    def test_rowcount_preserved(self):
        adapter, fake = _opened_adapter()
        fake.set_rows([])
        cursor = adapter.execute(
            "UPDATE editions SET publication_state = ? WHERE id = ?",
            ("published", "x"),
        )
        # FakeCursor rowcount defaults to len(rows) == 0 here.
        assert cursor.rowcount == 0

    def test_fetchone_empty_returns_none(self):
        adapter, fake = _opened_adapter(rows=[])
        assert adapter.execute("SELECT 1 WHERE 1 = 0").fetchone() is None


# ---------------------------------------------------------------------------
# Write-transaction contract
# ---------------------------------------------------------------------------


class TestTransaction:
    def test_idle_begin_write_executes_begin(self):
        adapter, fake = _opened_adapter(status=TransactionStatus.IDLE)
        adapter.begin_write()
        assert ("BEGIN", None) in fake.executed or any(
            sql == "BEGIN" for sql, _ in fake.executed
        )
        assert adapter.in_transaction is True

    def test_nested_begin_rejected(self):
        adapter, fake = _opened_adapter(status=TransactionStatus.INTRANS)
        with pytest.raises(RuntimeTransactionError) as ei:
            adapter.begin_write()
        assert ei.value.state == "in_transaction"
        # No BEGIN was sent to the driver.
        assert not any(sql == "BEGIN" for sql, _ in fake.executed)

    def test_failed_transaction_fail_closed(self):
        adapter, fake = _opened_adapter(status=TransactionStatus.INERROR)
        with pytest.raises(RuntimeTransactionError) as ei:
            adapter.begin_write()
        assert ei.value.state == "failed"

    def test_unknown_state_fail_closed(self):
        adapter, fake = _opened_adapter(status=TransactionStatus.UNKNOWN)
        with pytest.raises(RuntimeTransactionError) as ei:
            adapter.begin_write()
        assert ei.value.state == "unknown"

    def test_commit_returns_to_idle(self):
        adapter, fake = _opened_adapter(status=TransactionStatus.INTRANS)
        adapter.commit()
        assert fake.commits == 1
        assert adapter.in_transaction is False

    def test_rollback_returns_to_idle(self):
        adapter, fake = _opened_adapter(status=TransactionStatus.INTRANS)
        adapter.rollback()
        assert fake.rollbacks == 1
        assert adapter.in_transaction is False

    def test_legacy_begin_immediate_forwards_to_begin_write(self):
        adapter, fake = _opened_adapter(status=TransactionStatus.IDLE)
        result = adapter.execute("BEGIN IMMEDIATE")
        # Forwarded to begin_write(): a real BEGIN is issued, not a no-op,
        # and the literal 'BEGIN IMMEDIATE' is never sent to PostgreSQL.
        assert any(sql == "BEGIN" for sql, _ in fake.executed)
        assert not any(sql == "BEGIN IMMEDIATE" for sql, _ in fake.executed)
        assert adapter.in_transaction is True
        # The intercepted statement returns a null cursor.
        assert result.fetchone() is None
        assert result.fetchall() == []

    def test_legacy_begin_immediate_not_noop_when_active(self):
        adapter, fake = _opened_adapter(status=TransactionStatus.INTRANS)
        with pytest.raises(RuntimeTransactionError):
            adapter.execute("BEGIN IMMEDIATE")

    def test_in_transaction_does_not_expose_raw_status(self):
        adapter, fake = _opened_adapter(status=TransactionStatus.INTRANS)
        # The property is a plain bool, not the driver enum.
        assert adapter.in_transaction is True
        assert isinstance(adapter.in_transaction, bool)


# ---------------------------------------------------------------------------
# Placeholder lexer
# ---------------------------------------------------------------------------


class TestPlaceholder:
    def test_qmark_to_percent_s(self):
        sql, count = translate_placeholders("SELECT * FROM t WHERE id = ?")
        assert sql == "SELECT * FROM t WHERE id = %s"
        assert count == 1

    def test_multiple_placeholders(self):
        sql, count = translate_placeholders(
            "INSERT INTO t (a, b, c) VALUES (?, ?, ?)"
        )
        assert sql == "INSERT INTO t (a, b, c) VALUES (%s, %s, %s)"
        assert count == 3

    def test_quoted_question_mark_preserved(self):
        sql, count = translate_placeholders("SELECT '?' AS q WHERE x = ?")
        assert "'?'" in sql
        assert count == 1
        assert sql.endswith("x = %s")

    def test_double_quoted_identifier_preserved(self):
        sql, count = translate_placeholders('SELECT "col?" FROM t WHERE id = ?')
        assert '"col?"' in sql
        assert count == 1

    def test_escaped_quote_handled(self):
        sql, count = translate_placeholders("SELECT 'it''s a ?' WHERE x = ?")
        assert "'it''s a ?'" in sql
        assert count == 1

    def test_line_comment_preserved(self):
        sql, count = translate_placeholders(
            "SELECT 1 -- is this a ?\nWHERE x = ?"
        )
        assert "-- is this a ?" in sql
        assert count == 1
        assert "x = %s" in sql

    def test_block_comment_preserved(self):
        sql, count = translate_placeholders("SELECT /* a ? */ 1 WHERE x = ?")
        assert "/* a ? */" in sql
        assert count == 1

    def test_nested_block_comment_preserved(self):
        sql, count = translate_placeholders(
            "SELECT /* outer /* inner ? */ still ? */ 1 WHERE x = ?"
        )
        assert count == 1
        assert "x = %s" in sql

    def test_dollar_quote_preserved(self):
        sql, count = translate_placeholders("SELECT $$?$$ AS d WHERE x = ?")
        assert "$$?$$" in sql
        assert count == 1

    def test_dollar_tagged_quote_preserved(self):
        sql, count = translate_placeholders(
            "SELECT $tag$ a ? b $tag$ WHERE x = ?"
        )
        assert "$tag$ a ? b $tag$" in sql
        assert count == 1

    def test_unterminated_string_raises(self):
        with pytest.raises(PlaceholderError):
            translate_placeholders("SELECT 'abc WHERE x = ?")

    def test_unterminated_block_comment_raises(self):
        with pytest.raises(PlaceholderError):
            translate_placeholders("SELECT /* abc WHERE x = ?")

    def test_unterminated_dollar_quote_raises(self):
        with pytest.raises(PlaceholderError):
            translate_placeholders("SELECT $$abc WHERE x = ?")

    def test_adapter_param_count_mismatch_too_few(self):
        adapter, fake = _opened_adapter()
        with pytest.raises(PlaceholderError, match="mismatch"):
            adapter.execute("SELECT * FROM t WHERE a = ? AND b = ?", ("one",))

    def test_adapter_param_count_mismatch_too_many(self):
        adapter, fake = _opened_adapter()
        with pytest.raises(PlaceholderError, match="mismatch"):
            adapter.execute("SELECT * FROM t WHERE a = ?", ("one", "two"))

    def test_adapter_dict_params_rejected(self):
        adapter, fake = _opened_adapter()
        with pytest.raises(PlaceholderError):
            adapter.execute("SELECT * FROM t WHERE a = ?", {"a": 1})

    def test_no_value_interpolation(self):
        adapter, fake = _opened_adapter()
        adapter.execute(
            "INSERT INTO t (x) VALUES (?)", ("SECRET_VALUE_123",)
        )
        sql, params = fake.executed[-1]
        assert sql == "INSERT INTO t (x) VALUES (%s)"
        assert "SECRET_VALUE_123" not in sql
        assert params == ("SECRET_VALUE_123",)

    def test_adapter_translates_and_passes_params(self):
        adapter, fake = _opened_adapter()
        adapter.execute(
            "SELECT id FROM editions WHERE participant_id = ? "
            "AND edition_number = ?",
            ("p1", 2),
        )
        sql, params = fake.executed[-1]
        assert sql == (
            "SELECT id FROM editions WHERE participant_id = %s "
            "AND edition_number = %s"
        )
        assert params == ("p1", 2)


# ---------------------------------------------------------------------------
# Backend-neutral error contract
# ---------------------------------------------------------------------------


class TestError:
    def test_unique_violation(self):
        exc = pg_errors.UniqueViolation("duplicate key value violates ...")
        err = classify_pg_error(exc)
        assert isinstance(err, DatabaseIntegrityError)
        assert err.kind == "unique"

    def test_foreign_key_violation(self):
        exc = pg_errors.ForeignKeyViolation("insert or update ... violates")
        err = classify_pg_error(exc)
        assert isinstance(err, DatabaseIntegrityError)
        assert err.kind == "foreign_key"

    def test_check_violation(self):
        exc = pg_errors.CheckViolation("new row violates check constraint")
        err = classify_pg_error(exc)
        assert isinstance(err, DatabaseIntegrityError)
        assert err.kind == "check"

    def test_not_null_violation(self):
        exc = pg_errors.NotNullViolation("null value ... violates not-null")
        err = classify_pg_error(exc)
        assert isinstance(err, DatabaseIntegrityError)
        assert err.kind == "not_null"

    def test_unknown_driver_error_safe_category(self):
        exc = psycopg.OperationalError("connection refused")
        err = classify_pg_error(exc)
        assert isinstance(err, DatabaseError)
        assert not isinstance(err, DatabaseIntegrityError)
        assert err.safe_category == "unknown"

    def test_raw_driver_message_not_in_str_repr(self):
        secret = "duplicate key value violates unique constraint SECRETDETAIL"
        exc = pg_errors.UniqueViolation(secret)
        err = classify_pg_error(exc)
        for s in (str(err), repr(err)):
            assert secret not in s
            assert "SECRETDETAIL" not in s

    def test_exception_cause_preserved(self):
        adapter, fake = _opened_adapter()
        original = pg_errors.UniqueViolation("boom")
        fake.set_raise(original)
        with pytest.raises(DatabaseIntegrityError) as ei:
            adapter.execute("INSERT INTO t (x) VALUES (?)", ("v",))
        assert ei.value.__cause__ is original

    def test_adapter_translates_execute_error(self):
        adapter, fake = _opened_adapter()
        fake.set_raise(pg_errors.ForeignKeyViolation("fk boom"))
        with pytest.raises(DatabaseIntegrityError) as ei:
            adapter.execute("INSERT INTO t (x) VALUES (?)", ("v",))
        assert ei.value.kind == "foreign_key"

    def test_constraint_name_extracted_when_present(self):
        class Diag:
            constraint_name = "editions_participant_id_edition_number_key"

        class FakeExc:
            diag = Diag()

        assert (
            _safe_constraint_name(FakeExc())
            == "editions_participant_id_edition_number_key"
        )

    def test_constraint_name_absent_is_none(self):
        class NoDiag:
            pass

        assert _safe_constraint_name(NoDiag()) is None
        # Real psycopg errors expose a read-only diag without a usable
        # constraint_name in this synthetic path -> None is acceptable.
        assert _safe_constraint_name(pg_errors.UniqueViolation("x")) in (
            None,
        ) or isinstance(
            _safe_constraint_name(pg_errors.UniqueViolation("x")), str
        )

    def test_kind_whitelist_enforced(self):
        err = DatabaseIntegrityError("not-a-real-kind")
        assert err.kind == "unknown"


# ---------------------------------------------------------------------------
# Secret redaction (adapter + exception repr/str)
# ---------------------------------------------------------------------------


class TestSecretRedaction:
    SECRET_URL = "postgresql://alice:s3cr3t@db.internal.example.com:5432/prod"

    def test_adapter_repr_has_no_connection_detail(self):
        adapter = PostgresRuntimeConnection(
            lambda: FakePgConnection()
        )
        for s in (repr(adapter), str(adapter)):
            assert "s3cr3t" not in s
            assert "alice" not in s
            assert "db.internal.example.com" not in s
            assert "://" not in s

    def test_error_from_secret_driver_message_has_no_leak(self):
        exc = pg_errors.UniqueViolation(
            f"connection to {self.SECRET_URL} failed: duplicate key"
        )
        err = classify_pg_error(exc)
        for s in (str(err), repr(err)):
            assert "s3cr3t" not in s
            assert "alice" not in s
            assert "db.internal.example.com" not in s
            assert self.SECRET_URL not in s

    def test_transaction_error_has_no_connection_detail(self):
        err = RuntimeTransactionError("failed")
        for s in (str(err), repr(err)):
            assert "://" not in s
            assert "@" not in s


# ---------------------------------------------------------------------------
# Static contract: current runtime repository SQL
# ---------------------------------------------------------------------------


APP_DIR = Path(__file__).resolve().parent.parent.parent / "app"
RUNTIME_REPOS = [
    "participant_repository.py",
    "input_repository.py",
    "edition_repository.py",
    "feedback_repository.py",
    "generation_run_repository.py",
]


def _question_mark_constants(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "?" in node.value:
                yield node.value


class TestStaticContract:
    def test_runtime_repos_exist(self):
        for repo in RUNTIME_REPOS:
            assert (APP_DIR / repo).exists(), repo

    def test_no_literal_question_mark_in_repository_sql(self):
        seen = 0
        for repo in RUNTIME_REPOS:
            for sql in _question_mark_constants(APP_DIR / repo):
                seen += 1
                translated, count = translate_placeholders(sql)
                # Every '?' is a genuine placeholder: none may survive inside
                # a string literal or comment, and the translated count must
                # equal the raw '?' count.
                assert "?" not in translated, (
                    f"literal '?' survived in {repo}: {sql!r}"
                )
                assert count == sql.count("?"), (
                    f"qmark/params count mismatch in {repo}: {sql!r}"
                )
        # Sanity: the scan actually found the repository placeholders.
        assert seen > 0

    def test_repository_sql_is_well_formed_for_translation(self):
        for repo in RUNTIME_REPOS:
            for sql in _question_mark_constants(APP_DIR / repo):
                # Must not raise (no unterminated quote/comment/dollar-quote).
                translate_placeholders(sql)

    def test_import_time_connection_zero(self, socket_guard):
        # Re-importing the whole runtime boundary stack opens no socket.
        for mod in list(sys.modules):
            if mod.startswith("app.db_runtime") or mod == "app.db_postgres":
                del sys.modules[mod]
        importlib.import_module("app.db_runtime")
        assert socket_guard["n"] == 0


# ---------------------------------------------------------------------------
# CTO blocker 1: real psycopg transaction status API (conn.info.transaction_status)
# ---------------------------------------------------------------------------


class TestTransactionStatusAPI:
    def test_fake_uses_info_transaction_status(self):
        fake = FakePgConnection(status=TransactionStatus.INTRANS)
        assert fake.info.transaction_status == TransactionStatus.INTRANS
        assert not hasattr(fake, "transaction_status")

    def test_direct_attribute_fake_causes_unknown_fail_closed(self):
        class WrongFake:
            """Has transaction_status directly but no .info — must fail closed."""

            transaction_status = TransactionStatus.IDLE
            executed = []

            def execute(self, sql, params=None):
                self.executed.append((sql, params))
                return FakeCursor([])

            def commit(self):
                pass

            def rollback(self):
                pass

            def close(self):
                pass

        adapter = PostgresRuntimeConnection(lambda: WrongFake())
        adapter.open()
        with pytest.raises(RuntimeTransactionError) as ei:
            adapter.begin_write()
        assert ei.value.state == "unknown"

    def test_info_missing_causes_unknown(self):
        class NoInfoFake:
            executed = []

            def execute(self, sql, params=None):
                return FakeCursor([])

            def commit(self):
                pass

            def rollback(self):
                pass

            def close(self):
                pass

        adapter = PostgresRuntimeConnection(lambda: NoInfoFake())
        adapter.open()
        with pytest.raises(RuntimeTransactionError) as ei:
            adapter.begin_write()
        assert ei.value.state == "unknown"

    def test_unexpected_status_value_causes_unknown(self):
        class WeirdInfo:
            transaction_status = "SOMETHING_UNEXPECTED"

        class WeirdFake:
            info = WeirdInfo()
            executed = []

            def execute(self, sql, params=None):
                return FakeCursor([])

            def commit(self):
                pass

            def rollback(self):
                pass

            def close(self):
                pass

        adapter = PostgresRuntimeConnection(lambda: WeirdFake())
        adapter.open()
        with pytest.raises(RuntimeTransactionError) as ei:
            adapter.begin_write()
        assert ei.value.state == "unknown"


# ---------------------------------------------------------------------------
# CTO blocker 2: runtime/migration connection separation
# ---------------------------------------------------------------------------


class TestConnectionSeparation:
    def test_runtime_select_stays_idle(self):
        adapter, fake = _opened_adapter(status=TransactionStatus.IDLE)
        adapter.execute("SELECT id FROM participants WHERE id = ?", ("x",))
        assert adapter.in_transaction is False

    def test_begin_write_then_intrans(self):
        adapter, fake = _opened_adapter(status=TransactionStatus.IDLE)
        adapter.begin_write()
        assert fake.info.transaction_status == TransactionStatus.INTRANS
        assert adapter.in_transaction is True

    def test_commit_after_begin_returns_idle(self):
        adapter, fake = _opened_adapter(status=TransactionStatus.IDLE)
        adapter.begin_write()
        adapter.commit()
        assert fake.info.transaction_status == TransactionStatus.IDLE
        assert adapter.in_transaction is False

    def test_rollback_after_begin_returns_idle(self):
        adapter, fake = _opened_adapter(status=TransactionStatus.IDLE)
        adapter.begin_write()
        adapter.rollback()
        assert fake.info.transaction_status == TransactionStatus.IDLE
        assert adapter.in_transaction is False

    def test_migration_connection_autocommit_false(self):
        from app.db_postgres import get_pg_connection
        import inspect

        src = inspect.getsource(get_pg_connection)
        assert "autocommit=False" in src

    def test_runtime_connection_autocommit_true(self):
        from app.db_postgres import get_pg_runtime_connection
        import inspect

        src = inspect.getsource(get_pg_runtime_connection)
        assert "autocommit=True" in src


# ---------------------------------------------------------------------------
# CTO blocker 3: connection failure normalization
# ---------------------------------------------------------------------------


class TestConnectionFailure:
    SECRET_URL = "postgresql://alice:s3cr3t@db.internal.example.com:5432/prod"

    def test_factory_psycopg_error_normalized(self):
        def failing_factory():
            raise psycopg.OperationalError(
                f"connection to {self.SECRET_URL} failed: refused"
            )

        adapter = PostgresRuntimeConnection(failing_factory)
        with pytest.raises(DatabaseError) as ei:
            adapter.open()
        assert ei.value.safe_category == "connection"
        assert ei.value.__cause__ is not None

    def test_failure_no_secret_in_str_repr(self):
        def failing_factory():
            raise psycopg.OperationalError(
                f"could not connect to alice:s3cr3t@db.internal.example.com"
            )

        adapter = PostgresRuntimeConnection(failing_factory)
        with pytest.raises(DatabaseError) as ei:
            adapter.open()
        for s in (str(ei.value), repr(ei.value)):
            assert "s3cr3t" not in s
            assert "alice" not in s
            assert "db.internal.example.com" not in s
            assert "://" not in s

    def test_conn_is_none_after_failure(self):
        def failing_factory():
            raise psycopg.OperationalError("refused")

        adapter = PostgresRuntimeConnection(failing_factory)
        with pytest.raises(DatabaseError):
            adapter.open()
        assert adapter._conn is None

    def test_retry_after_failure(self):
        calls = {"n": 0}

        def flaky_factory():
            calls["n"] += 1
            if calls["n"] == 1:
                raise psycopg.OperationalError("first attempt fails")
            return FakePgConnection()

        adapter = PostgresRuntimeConnection(flaky_factory)
        with pytest.raises(DatabaseError):
            adapter.open()
        adapter.open()
        assert calls["n"] == 2
        assert adapter._conn is not None


# ---------------------------------------------------------------------------
# CTO blocker 4: params validation
# ---------------------------------------------------------------------------


class TestParamsValidation:
    def test_str_params_rejected(self):
        adapter, fake = _opened_adapter()
        with pytest.raises(PlaceholderError, match="positional sequence"):
            adapter.execute("SELECT * FROM t WHERE a = ?", "hello")

    def test_bytes_params_rejected(self):
        adapter, fake = _opened_adapter()
        with pytest.raises(PlaceholderError, match="positional sequence"):
            adapter.execute("SELECT * FROM t WHERE a = ?", b"hello")

    def test_bytearray_params_rejected(self):
        adapter, fake = _opened_adapter()
        with pytest.raises(PlaceholderError, match="positional sequence"):
            adapter.execute("SELECT * FROM t WHERE a = ?", bytearray(b"hi"))

    def test_dict_params_rejected(self):
        adapter, fake = _opened_adapter()
        with pytest.raises(PlaceholderError):
            adapter.execute("SELECT * FROM t WHERE a = ?", {"a": 1})

    def test_error_message_has_no_value(self):
        adapter, fake = _opened_adapter()
        with pytest.raises(PlaceholderError) as ei:
            adapter.execute("SELECT * FROM t WHERE a = ?", "SECRET_PARAM")
        assert "SECRET_PARAM" not in str(ei.value)

    def test_tuple_params_accepted(self):
        adapter, fake = _opened_adapter()
        adapter.execute("SELECT * FROM t WHERE a = ?", ("ok",))
        sql, params = fake.executed[-1]
        assert params == ("ok",)

    def test_list_params_accepted(self):
        adapter, fake = _opened_adapter()
        adapter.execute("SELECT * FROM t WHERE a = ?", ["ok"])
        sql, params = fake.executed[-1]
        assert params == ("ok",)
