from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import re
from typing import Any, Protocol

from .connector_trust import ConnectorWriteIntent
from .contracts import ContractError
from .security import redact_secrets

MAX_SQL_CHARS = 50_000
MAX_RESULT_ROWS = 500
MAX_RESULT_BYTES = 1_000_000
MAX_CELL_CHARS = 4_000
MAX_STATEMENT_TIMEOUT_MS = 30_000
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")

_FORBIDDEN_WORDS = frozenset(
    {
        "INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "ALTER", "DROP", "TRUNCATE",
        "GRANT", "REVOKE", "COPY", "CALL", "DO", "SET", "RESET", "VACUUM", "ANALYZE",
        "LOCK", "LISTEN", "NOTIFY", "UNLISTEN", "LOAD", "DISCARD", "PREPARE", "EXECUTE",
        "DEALLOCATE", "CLUSTER", "REINDEX", "REFRESH", "COMMENT", "SECURITY", "LABEL",
        "IMPORT", "REASSIGN", "CHECKPOINT", "BEGIN", "START", "COMMIT", "ROLLBACK",
        "SAVEPOINT", "RELEASE", "ABORT", "END", "INTO",
    }
)
_FORBIDDEN_FUNCTIONS = frozenset(
    {
        "NEXTVAL", "SETVAL", "PG_NOTIFY", "PG_CANCEL_BACKEND", "PG_TERMINATE_BACKEND",
        "PG_RELOAD_CONF", "PG_ROTATE_LOGFILE", "PG_SWITCH_WAL", "PG_CREATE_RESTORE_POINT",
        "PG_BACKUP_START", "PG_BACKUP_STOP", "SET_CONFIG", "LO_IMPORT", "LO_EXPORT", "LO_UNLINK",
        "PG_ADVISORY_LOCK", "PG_ADVISORY_XACT_LOCK", "PG_TRY_ADVISORY_LOCK",
        "PG_TRY_ADVISORY_XACT_LOCK", "PG_ADVISORY_UNLOCK", "PG_ADVISORY_UNLOCK_ALL",
    }
)
_ROW_LOCK_PHRASES = (
    ("FOR", "UPDATE"),
    ("FOR", "SHARE"),
    ("FOR", "NO", "KEY", "UPDATE"),
    ("FOR", "KEY", "SHARE"),
)


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    normalized = value.strip()
    if redact_secrets(normalized) != normalized:
        raise ContractError(f"{field_name} must not contain credential material")
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _positive_int(value: int, field_name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ContractError(f"{field_name} must be between 1 and {maximum}")
    return value


def _non_negative_int(value: int, field_name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ContractError(f"{field_name} must be between 0 and {maximum}")
    return value


def _identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _IDENT_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a simple SQL identifier")
    return value.strip()


class SqlTokenKind(str, Enum):
    WORD = "word"
    SYMBOL = "symbol"
    LITERAL = "literal"
    QUOTED_IDENTIFIER = "quoted_identifier"


@dataclass(frozen=True, slots=True)
class SqlToken:
    kind: SqlTokenKind
    value: str

    def keyword(self) -> str | None:
        return self.value.upper() if self.kind is SqlTokenKind.WORD else None


def _scan_sql(sql: str) -> tuple[SqlToken, ...]:
    if not isinstance(sql, str) or not sql.strip() or len(sql) > MAX_SQL_CHARS or "\x00" in sql:
        raise ContractError("sql must be non-empty bounded text without NUL bytes")
    tokens: list[SqlToken] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch.isspace():
            i += 1
            continue
        if sql.startswith("--", i):
            end = sql.find("\n", i + 2)
            i = n if end < 0 else end + 1
            continue
        if sql.startswith("/*", i):
            depth = 1
            i += 2
            while i < n and depth:
                if sql.startswith("/*", i):
                    depth += 1
                    i += 2
                elif sql.startswith("*/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            if depth:
                raise ContractError("unterminated SQL block comment")
            continue
        if ch == "'":
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                # PostgreSQL escape-string syntax can use a backslash; treating
                # an escaped next byte as part of the literal is conservative.
                if sql[i] == "\\" and i + 1 < n:
                    i += 2
                else:
                    i += 1
            else:
                raise ContractError("unterminated SQL string literal")
            tokens.append(SqlToken(SqlTokenKind.LITERAL, "<literal>"))
            continue
        if ch == '"':
            start = i
            i += 1
            while i < n:
                if sql[i] == '"':
                    if i + 1 < n and sql[i + 1] == '"':
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            else:
                raise ContractError("unterminated quoted identifier")
            tokens.append(SqlToken(SqlTokenKind.QUOTED_IDENTIFIER, sql[start:i]))
            continue
        if ch == "$":
            match = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", sql[i:])
            if match:
                tag = match.group(0)
                end = sql.find(tag, i + len(tag))
                if end < 0:
                    raise ContractError("unterminated dollar-quoted literal")
                i = end + len(tag)
                tokens.append(SqlToken(SqlTokenKind.LITERAL, "<dollar_literal>"))
                continue
        if ch.isalpha() or ch == "_":
            start = i
            i += 1
            while i < n and (sql[i].isalnum() or sql[i] in {"_", "$"}):
                i += 1
            tokens.append(SqlToken(SqlTokenKind.WORD, sql[start:i]))
            continue
        if ch == ";":
            tokens.append(SqlToken(SqlTokenKind.SYMBOL, ";"))
            i += 1
            continue
        tokens.append(SqlToken(SqlTokenKind.SYMBOL, ch))
        i += 1

    if not tokens:
        raise ContractError("sql contains no executable statement")
    semicolons = [idx for idx, token in enumerate(tokens) if token.kind is SqlTokenKind.SYMBOL and token.value == ";"]
    if len(semicolons) > 1 or (semicolons and semicolons[0] != len(tokens) - 1):
        raise ContractError("multiple SQL statements are prohibited")
    if semicolons:
        tokens.pop()
    if not tokens:
        raise ContractError("sql contains no executable statement")
    return tuple(tokens)


class PostgresReadKind(str, Enum):
    SELECT = "select"
    EXPLAIN = "explain"


@dataclass(frozen=True, slots=True)
class PostgresReadAnalysis:
    kind: PostgresReadKind
    sql_fingerprint: str
    token_count: int

    def safe_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "sql_fingerprint": self.sql_fingerprint,
            "token_count": self.token_count,
            "sql_text_present": False,
            "read_only_classification": True,
        }


def _word_sequence(tokens: tuple[SqlToken, ...]) -> tuple[str, ...]:
    return tuple(token.value.upper() for token in tokens if token.kind is SqlTokenKind.WORD)


def _contains_phrase(words: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    width = len(phrase)
    return any(words[i:i + width] == phrase for i in range(0, len(words) - width + 1))


def _quoted_identifier_keyword(token: SqlToken) -> str | None:
    if token.kind is not SqlTokenKind.QUOTED_IDENTIFIER:
        return None
    raw = token.value
    if len(raw) < 2 or raw[0] != '"' or raw[-1] != '"':
        return None
    inner = raw[1:-1].replace('""', '"')
    if not _IDENT_RE.fullmatch(inner):
        return None
    return inner.upper()


def _callable_keyword(token: SqlToken) -> str | None:
    if token.kind is SqlTokenKind.WORD:
        return token.value.upper()
    return _quoted_identifier_keyword(token)


def _top_level_words(tokens: tuple[SqlToken, ...]) -> tuple[str, ...]:
    words: list[str] = []
    depth = 0
    for token in tokens:
        if token.kind is SqlTokenKind.SYMBOL and token.value == "(":
            depth += 1
            continue
        if token.kind is SqlTokenKind.SYMBOL and token.value == ")":
            depth -= 1
            if depth < 0:
                raise ContractError("unbalanced SQL parentheses")
            continue
        if depth == 0 and token.kind is SqlTokenKind.WORD:
            words.append(token.value.upper())
    if depth != 0:
        raise ContractError("unbalanced SQL parentheses")
    return tuple(words)


def classify_postgres_read_sql(sql: str) -> PostgresReadAnalysis:
    tokens = _scan_sql(sql)
    words = _word_sequence(tokens)
    top_words = _top_level_words(tokens)
    if not words or not top_words:
        raise ContractError("read SQL must contain SQL keywords")

    forbidden = sorted(set(words) & _FORBIDDEN_WORDS)
    if forbidden:
        raise ContractError(f"read SQL contains prohibited operation: {forbidden[0]}")
    for phrase in _ROW_LOCK_PHRASES:
        if _contains_phrase(words, phrase):
            raise ContractError("row-locking SELECT forms are prohibited in read mode")
    for idx, token in enumerate(tokens[:-1]):
        callable_name = _callable_keyword(token)
        if callable_name in _FORBIDDEN_FUNCTIONS:
            if tokens[idx + 1].kind is SqlTokenKind.SYMBOL and tokens[idx + 1].value == "(":
                raise ContractError(f"read SQL calls prohibited side-effect function: {callable_name}")

    first = top_words[0]
    kind: PostgresReadKind
    if first == "EXPLAIN":
        kind = PostgresReadKind.EXPLAIN
        if "ANALYZE" in top_words or "ANALYZE" in words:
            raise ContractError("EXPLAIN ANALYZE is prohibited in read mode")
        # EXPLAIN options live inside parentheses; the explained statement must
        # still have a top-level SELECT or WITH that terminates in SELECT.
        if "SELECT" not in top_words:
            raise ContractError("EXPLAIN must target a read-only SELECT/CTE")
    elif first == "SELECT":
        kind = PostgresReadKind.SELECT
    elif first == "WITH":
        kind = PostgresReadKind.SELECT
        # SELECT inside a CTE body is not enough: the final top-level statement
        # itself must be SELECT. This rejects `WITH x AS (SELECT 1) VALUES (1)`.
        if "SELECT" not in top_words[1:]:
            raise ContractError("WITH statement must terminate in a top-level SELECT")
    else:
        raise ContractError("read mode accepts only SELECT, WITH ... SELECT, or EXPLAIN of a read query")

    fingerprint = hashlib.sha256(sql.strip().encode("utf-8")).hexdigest()
    return PostgresReadAnalysis(kind=kind, sql_fingerprint=fingerprint, token_count=len(tokens))


@dataclass(frozen=True, slots=True)
class PostgresBindingProjection:
    binding_ref: str
    workspace_ref: str
    project_ref: str
    branch_ref: str
    database_ref: str
    role_ref: str
    allowed_schemas: tuple[str, ...]
    tls_required: bool = True
    channel_binding_required: bool = True
    least_privilege_read_role: bool = True
    function_execute_allowlist_required: bool = True

    def __post_init__(self) -> None:
        for field_name in ("binding_ref", "workspace_ref", "project_ref", "branch_ref", "database_ref", "role_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        schemas = tuple(_identifier(item, "allowed_schema") for item in self.allowed_schemas)
        if not schemas or len(schemas) != len(set(schemas)):
            raise ContractError("allowed_schemas must be a non-empty unique tuple")
        object.__setattr__(self, "allowed_schemas", schemas)
        if not all((self.tls_required, self.least_privilege_read_role, self.function_execute_allowlist_required)):
            raise ContractError("Postgres read binding requires TLS, least privilege and function execution policy")
        if not isinstance(self.channel_binding_required, bool):
            raise ContractError("channel_binding_required must be boolean")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "project_ref": self.project_ref,
            "branch_ref": self.branch_ref,
            "database_ref": self.database_ref,
            "role_ref": self.role_ref,
            "allowed_schemas": list(self.allowed_schemas),
            "tls_required": self.tls_required,
            "channel_binding_required": self.channel_binding_required,
            "least_privilege_read_role": self.least_privilege_read_role,
            "function_execute_allowlist_required": self.function_execute_allowlist_required,
            "raw_dsn": False,
            "raw_password": False,
        }


@dataclass(frozen=True, slots=True)
class PostgresQueryBudget:
    max_rows: int = 100
    max_bytes: int = 200_000
    statement_timeout_ms: int = 5_000

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_rows", _positive_int(self.max_rows, "max_rows", MAX_RESULT_ROWS))
        object.__setattr__(self, "max_bytes", _positive_int(self.max_bytes, "max_bytes", MAX_RESULT_BYTES))
        object.__setattr__(
            self,
            "statement_timeout_ms",
            _positive_int(self.statement_timeout_ms, "statement_timeout_ms", MAX_STATEMENT_TIMEOUT_MS),
        )


@dataclass(frozen=True, slots=True)
class PostgresReadRequest:
    binding_ref: str
    workspace_ref: str
    sql: str
    parameters: tuple[Any, ...]
    budget: PostgresQueryBudget
    requested_at: datetime
    schema_scope: tuple[str, ...]
    analysis: PostgresReadAnalysis | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_ref", _ref(self.binding_ref, "binding_ref"))
        object.__setattr__(self, "workspace_ref", _ref(self.workspace_ref, "workspace_ref"))
        if not isinstance(self.parameters, tuple) or len(self.parameters) > 64:
            raise ContractError("parameters must be a tuple of at most 64 values")
        if any(isinstance(value, (dict, list, set)) for value in self.parameters):
            raise ContractError("read query parameters must be scalar values")
        if not isinstance(self.budget, PostgresQueryBudget):
            raise ContractError("budget must be PostgresQueryBudget")
        object.__setattr__(self, "requested_at", _aware(self.requested_at, "requested_at"))
        scope = tuple(_identifier(item, "schema_scope") for item in self.schema_scope)
        if not scope or len(scope) != len(set(scope)):
            raise ContractError("schema_scope must be a non-empty unique tuple")
        object.__setattr__(self, "schema_scope", scope)
        analysis = classify_postgres_read_sql(self.sql)
        if self.analysis is not None and self.analysis != analysis:
            raise ContractError("provided SQL analysis does not match SQL text")
        object.__setattr__(self, "analysis", analysis)

    def safe_dict(self) -> dict[str, Any]:
        assert self.analysis is not None
        return {
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "analysis": self.analysis.safe_dict(),
            "parameter_count": len(self.parameters),
            "schema_scope": list(self.schema_scope),
            "max_rows": self.budget.max_rows,
            "max_bytes": self.budget.max_bytes,
            "statement_timeout_ms": self.budget.statement_timeout_ms,
            "requested_at": self.requested_at.isoformat().replace("+00:00", "Z"),
            "sql_text_present": False,
            "parameter_values_present": False,
        }


def validate_postgres_read_request(binding: PostgresBindingProjection, request: PostgresReadRequest) -> None:
    if not isinstance(binding, PostgresBindingProjection) or not isinstance(request, PostgresReadRequest):
        raise ContractError("binding/request must be Postgres read contract values")
    if request.binding_ref != binding.binding_ref or request.workspace_ref != binding.workspace_ref:
        raise ContractError("Postgres read request binding/workspace mismatch")
    if not set(request.schema_scope).issubset(set(binding.allowed_schemas)):
        raise ContractError("Postgres read request exceeds allowed schema scope")


def _safe_cell(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = redact_secrets(str(value))
    return text if len(text) <= MAX_CELL_CHARS else text[:MAX_CELL_CHARS]


@dataclass(frozen=True, slots=True)
class PostgresQueryResult:
    query_ref: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    total_rows_observed: int
    total_bytes_observed: int
    truncated: bool
    masked_columns: tuple[str, ...]
    transaction_read_only: bool
    statement_timeout_applied: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_ref", _ref(self.query_ref, "query_ref"))
        columns = tuple(_identifier(item, "column") for item in self.columns)
        if len(columns) != len(set(columns)):
            raise ContractError("result columns must be unique")
        object.__setattr__(self, "columns", columns)
        if len(self.rows) > MAX_RESULT_ROWS:
            raise ContractError("result rows exceed repository hard bound")
        normalized_rows: list[tuple[Any, ...]] = []
        for row in self.rows:
            if not isinstance(row, tuple) or len(row) != len(columns):
                raise ContractError("each result row must match result columns")
            normalized_rows.append(tuple(_safe_cell(value) for value in row))
        object.__setattr__(self, "rows", tuple(normalized_rows))
        object.__setattr__(
            self,
            "total_rows_observed",
            _non_negative_int(self.total_rows_observed, "total_rows_observed", 10_000_000),
        )
        object.__setattr__(
            self,
            "total_bytes_observed",
            _non_negative_int(self.total_bytes_observed, "total_bytes_observed", 100_000_000),
        )
        if not isinstance(self.truncated, bool):
            raise ContractError("truncated must be boolean")
        masks = tuple(_identifier(item, "masked_column") for item in self.masked_columns)
        if any(item not in columns for item in masks) or len(masks) != len(set(masks)):
            raise ContractError("masked_columns must be unique result columns")
        object.__setattr__(self, "masked_columns", masks)
        if not self.transaction_read_only or not self.statement_timeout_applied:
            raise ContractError("trusted adapter must prove read-only transaction and statement timeout")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "query_ref": self.query_ref,
            "columns": list(self.columns),
            "rows": [list(row) for row in self.rows],
            "row_count": len(self.rows),
            "total_rows_observed": self.total_rows_observed,
            "total_bytes_observed": self.total_bytes_observed,
            "truncated": self.truncated,
            "masked_columns": list(self.masked_columns),
            "transaction_read_only": self.transaction_read_only,
            "statement_timeout_applied": self.statement_timeout_applied,
            "result_trusted_instruction": False,
            "raw_dsn": False,
        }


@dataclass(frozen=True, slots=True)
class PostgresSchemaProjection:
    database_ref: str
    schema_ref: str
    relation_ref: str
    relation_kind: str
    columns: tuple[tuple[str, str], ...]
    indexes: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("database_ref", "schema_ref", "relation_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if self.relation_kind not in {"table", "view", "materialized_view"}:
            raise ContractError("unsupported relation_kind")
        normalized_columns = tuple((_identifier(name, "column_name"), str(data_type)[:256]) for name, data_type in self.columns)
        if len(normalized_columns) > 512:
            raise ContractError("schema projection exceeds column bound")
        object.__setattr__(self, "columns", normalized_columns)
        object.__setattr__(self, "indexes", tuple(_ref(item, "index_ref") for item in self.indexes[:128]))
        object.__setattr__(self, "constraints", tuple(_ref(item, "constraint_ref") for item in self.constraints[:128]))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "database_ref": self.database_ref,
            "schema_ref": self.schema_ref,
            "relation_ref": self.relation_ref,
            "relation_kind": self.relation_kind,
            "columns": [{"name": name, "type": data_type} for name, data_type in self.columns],
            "indexes": list(self.indexes),
            "constraints": list(self.constraints),
            "schema_metadata_trusted_instruction": False,
        }


class TrustedPostgresReadPort(Protocol):
    def inspect_schema(self, *, binding: PostgresBindingProjection, schema: str) -> tuple[PostgresSchemaProjection, ...]:
        ...

    def execute_read(self, *, binding: PostgresBindingProjection, request: PostgresReadRequest) -> PostgresQueryResult:
        ...


class UnconfiguredPostgresReadPort:
    def inspect_schema(self, *, binding: PostgresBindingProjection, schema: str) -> tuple[PostgresSchemaProjection, ...]:
        raise ContractError("trusted Postgres read adapter is not configured")

    def execute_read(self, *, binding: PostgresBindingProjection, request: PostgresReadRequest) -> PostgresQueryResult:
        raise ContractError("trusted Postgres read adapter is not configured")


@dataclass(frozen=True, slots=True)
class PostgresMutationApproval:
    intent: ConnectorWriteIntent
    database_ref: str
    schema_ref: str
    relation_ref: str
    max_affected_rows: int
    rollback_plan_ref: str
    transaction_required: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.intent, ConnectorWriteIntent) or self.intent.connector_id != "postgres":
            raise ContractError("mutation approval requires Postgres ConnectorWriteIntent")
        for field_name in ("database_ref", "schema_ref", "relation_ref", "rollback_plan_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        object.__setattr__(self, "max_affected_rows", _positive_int(self.max_affected_rows, "max_affected_rows", 100_000))
        if not self.transaction_required:
            raise ContractError("generic Postgres mutations require a transaction")
        upper_tool = self.intent.tool_name.upper()
        if any(word in upper_tool for word in ("DDL", "GRANT", "REVOKE", "ROLE", "DROP", "TRUNCATE")):
            raise ContractError("DDL/privilege/destructive actions require dedicated stronger tools")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.safe_dict(),
            "database_ref": self.database_ref,
            "schema_ref": self.schema_ref,
            "relation_ref": self.relation_ref,
            "max_affected_rows": self.max_affected_rows,
            "rollback_plan_ref": self.rollback_plan_ref,
            "transaction_required": self.transaction_required,
            "rollback_evidence_required": True,
            "generic_ddl_authority": False,
            "generic_privilege_authority": False,
        }


POSTGRES_READ_TOOLS = ("inspect_schema", "execute_select", "explain_select")
RAW_POSTGRES_DSN_IN_B54 = False
REAL_POSTGRES_CONNECTION_CONFIGURED = False
SERVER_SIDE_READ_ONLY_TRANSACTION_REQUIRED = True
STATEMENT_TIMEOUT_REQUIRED = True
LEAST_PRIVILEGE_ROLE_REQUIRED = True
FUNCTION_EXECUTE_ALLOWLIST_REQUIRED = True
GENERIC_DDL_MUTATION_SUPPORTED = False
GENERIC_PRIVILEGE_MUTATION_SUPPORTED = False
