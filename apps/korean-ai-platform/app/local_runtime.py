"""Local (COM2) runtime adapter for the B14 platform.

The Cloudflare Python Worker entrypoint in ``worker.py`` stays the production
authority. This module supplies the three things a plain Linux host has to own
for itself when the Worker platform is not there to provide them:

* the call-ledger database — a local SQLite file behind the same D1-shaped
  ``prepare().bind().run()/.first()/.all()`` surface, carrying the exact
  ``migrations/0001_b14_model_call_ledger.sql`` schema;
* the named credentials — process environment first, then one file per binding
  name under ``B14_SECRET_DIR``;
* request scope — the same per-request binding isolation, security headers and
  product entrypoint redirect that ``worker.fetch`` performs.

Nothing here replaces a decision the Worker owns. Service-proof verification,
the ledger contract, provider credential isolation, fail-open storage posture
and the catalog are read through the existing modules unchanged, and no secret
value is ever returned, logged or written into a response by this adapter.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
import sys
import threading
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from app.pilot.deployment_entry import PRODUCT_ENTRY_PATH, SECURITY_HEADERS

logger = logging.getLogger("korean-ai-platform.local")

LEDGER_PATH_ENV = "B14_CALL_LEDGER_PATH"
SECRET_DIR_ENV = "B14_SECRET_DIR"
HOST_ENV = "B14_HOST"
PORT_ENV = "B14_PORT"
TEST_RUNTIME_ENV = "B14_TEST_RUNTIME"


def adapter_selected() -> bool:
    """Whether this process was started to test the local runtime.

    The suite runs the same tests against either application so one command can
    prove the adapter, and tests that describe a deliberately different product
    contract read this instead of guessing.
    """
    return os.environ.get(TEST_RUNTIME_ENV, "plain") == "local"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8789

SERVICE_PROOF_BINDING = "PADIEM_B14_SERVICE_PROOF_SECRET"
OBSERVABILITY_BINDING = "PADIEM_GRAFANA_OTLP_TOKEN"
SENSENOVA_BINDING = "PADIEM_SENSENOVA_API_KEY"

# Cloudflare binding identifier shape. Anything else is not a binding name and
# must not be turned into a credential handle by attribute probing.
_BINDING_NAME = re.compile(r"\A[A-Z][A-Z0-9_]{2,63}\Z")

# A ledger connection is opened once per process. Writes arrive from deferred
# drain tasks that may run outside the request task, so every statement crosses
# a single lock instead of sharing a connection between threads.
_BUSY_TIMEOUT_MILLISECONDS = 2500


def ledger_path() -> Path | None:
    """Return the configured ledger file, or None when this host declared none."""
    raw = os.environ.get(LEDGER_PATH_ENV, "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def secret_dir() -> Path | None:
    raw = os.environ.get(SECRET_DIR_ENV, "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _secret_file_is_private(path: Path) -> bool:
    """Refuse a credential file that any other user on this host can read.

    POSIX only: a Windows checkout reports modes this check would misread, and
    COM2 runs the service under systemd on Linux.
    """
    if os.name != "posix":
        return True
    try:
        return not (path.stat().st_mode & 0o077)
    except OSError:
        return False


class FileOrEnvSecret:
    """One named credential, resolved lazily and value-free on failure.

    The handle exists so ``worker_env.load_request_secret`` keeps its current
    contract: exactly one read per binding per request, a missing binding
    resolves to ``""`` (fail closed), and the value never enters ``os.environ``.
    """

    __slots__ = ("binding_name",)

    def __init__(self, binding_name: str) -> None:
        self.binding_name = binding_name

    async def get(self) -> str:
        return await asyncio.to_thread(self._read)

    def _read(self) -> str:
        value = os.environ.get(self.binding_name, "")
        if value:
            return value
        directory = secret_dir()
        if directory is None:
            return ""
        path = directory / self.binding_name
        if not path.is_file():
            return ""
        if not _secret_file_is_private(path):
            # Name only: a loose mode is an operational fault, and quoting the
            # path would put a host filesystem location into a log line.
            logger.warning("b14_secret_file_rejected binding=%s", self.binding_name)
            return ""
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            logger.warning("b14_secret_file_unreadable binding=%s", self.binding_name)
            return ""


def credential_binding_names() -> tuple[str, ...]:
    """Every platform credential name this catalog can ask for.

    Read from the package registry file (the same authority the catalog installs
    from) plus anything registered later, so the set does not depend on import
    order and no second allowlist is created. A name the catalog never registers
    cannot appear here, which is what keeps the adapter from becoming a way to
    request an arbitrary secret.
    """
    from app.pilot.model_registry_file import read_registry, validate_registry
    from app.pilot.platform_secrets import CredentialSource, list_platform_providers

    names: set[str] = set()
    try:
        providers = validate_registry(read_registry())["providers"]
    except Exception as exc:
        # An unreadable catalog is a deployment fault, not a reason to widen or
        # narrow the scope silently: the fixed name below says which.
        logger.warning("b14_local_registry_unreadable reason=%s", type(exc).__name__)
        providers = {}
    for entry in providers.values():
        if entry.get("credential_source") == CredentialSource.PLATFORM_SECRET.value:
            binding = entry.get("credential_binding_name") or ""
            if binding:
                names.add(binding)
    names.update(
        spec.credential_binding_name
        for spec in list_platform_providers()
        if spec.credential_source == CredentialSource.PLATFORM_SECRET
        and spec.credential_binding_name
    )
    names.update({SERVICE_PROOF_BINDING, OBSERVABILITY_BINDING, SENSENOVA_BINDING})
    return tuple(sorted(names))


class _LedgerStatement:
    """A prepared statement with the D1 surface the ledger store already uses."""

    __slots__ = ("_binding", "_sql", "_params")

    def __init__(self, binding: "SqliteLedger", sql: str, params: tuple[Any, ...] = ()) -> None:
        self._binding = binding
        self._sql = sql
        self._params = params

    def bind(self, *params: Any) -> "_LedgerStatement":
        return _LedgerStatement(self._binding, self._sql, tuple(params))

    async def run(self) -> dict[str, Any]:
        return await self._binding._execute(self._sql, self._params, mode="run")

    async def first(self) -> dict[str, Any] | None:
        return await self._binding._execute(self._sql, self._params, mode="first")

    async def all(self) -> dict[str, Any]:
        return {"results": await self._binding._execute(self._sql, self._params, mode="all")}


class SqliteLedger:
    """The local stand-in for the ``B14_CALL_LEDGER_D1`` binding.

    Only the D1 call surface the ledger store touches is implemented. Errors
    propagate as exceptions, which is exactly how the store already converts a
    storage fault into the bounded ``storage_unavailable`` status instead of
    letting a database problem undo an answer a customer received.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._connection: sqlite3.Connection | None = None

    @property
    def path(self) -> Path:
        return self._path

    def connect(self) -> sqlite3.Connection:
        if self._connection is not None:
            return self._connection
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            str(self._path), check_same_thread=False, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MILLISECONDS}")
        connection.execute("PRAGMA foreign_keys=ON")
        self._connection = connection
        return connection

    def apply_migrations(self) -> int:
        """Apply the committed ledger migrations verbatim; return the count."""
        migrations = sorted((Path(__file__).resolve().parents[1] / "migrations").glob("*.sql"))
        if not migrations:
            raise RuntimeError("b14_ledger_migrations_missing")
        with self._lock:
            connection = self.connect()
            for migration in migrations:
                connection.executescript(migration.read_text(encoding="utf-8"))
        return len(migrations)

    def prepare(self, sql: str) -> _LedgerStatement:
        return _LedgerStatement(self, sql)

    async def batch(self, statements: Sequence[_LedgerStatement]) -> list[dict[str, Any]]:
        """Run the group in one transaction, the way a D1 batch does.

        A parent row and its attempts are one unit of evidence: half of them
        landing would let the dashboard count a call whose attempts vanished.
        """
        prepared = [(statement._sql, statement._params) for statement in statements]
        return await asyncio.to_thread(self._batch_sync, prepared)

    def _batch_sync(self, prepared: list[tuple[str, tuple[Any, ...]]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        with self._lock:
            connection = self.connect()
            connection.execute("BEGIN IMMEDIATE")
            try:
                for sql, params in prepared:
                    cursor = connection.execute(sql, params)
                    results.append({"success": True, "meta": {"changes": cursor.rowcount}})
                    cursor.close()
            except Exception:
                connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT")
        return results

    async def _execute(
        self, sql: str, params: tuple[Any, ...], *, mode: str
    ) -> Any:
        return await asyncio.to_thread(self._execute_sync, sql, params, mode)

    def _execute_sync(self, sql: str, params: tuple[Any, ...], mode: str) -> Any:
        with self._lock:
            connection = self.connect()
            cursor = connection.execute(sql, params)
            if cursor.description is None:
                changed = cursor.rowcount
                cursor.close()
                if mode == "all":
                    return []
                if mode == "first":
                    return None
                return {"success": True, "meta": {"changes": changed}}
            rows = [dict(row) for row in cursor.fetchall()]
            cursor.close()
            if mode == "all":
                return rows
            if mode == "first":
                return rows[0] if rows else None
            return {"success": True, "meta": {"changes": len(rows)}}

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None


class LocalEnv:
    """An env-shaped object: attributes for bindings that exist on this host."""

    __slots__ = ("_secrets", "_ledger")

    def __init__(self, binding_names: Iterable[str], ledger: SqliteLedger | None) -> None:
        self._secrets = frozenset(binding_names)
        self._ledger = ledger

    def __getattr__(self, name: str) -> Any:
        if name == "B14_CALL_LEDGER_D1":
            return self._ledger
        if name in self._secrets or self._has_own_value(name):
            return FileOrEnvSecret(name)
        raise AttributeError(name)

    @staticmethod
    def _has_own_value(name: str) -> bool:
        """A binding a caller asked for that this host actually carries.

        A provider onboarded after startup (or by a test fixture) declares its
        own binding name. Covering it here keeps the adapter from silently
        turning a configured credential into an unresolved one, which would
        close a route the Worker runtime would have served.
        """
        if not _BINDING_NAME.fullmatch(name):
            return False
        if os.environ.get(name):
            return True
        directory = secret_dir()
        return bool(directory is not None and (directory / name).is_file())


def build_local_env() -> LocalEnv:
    ledger: SqliteLedger | None = None
    path = ledger_path()
    if path is not None:
        candidate = SqliteLedger(path)
        try:
            applied = candidate.apply_migrations()
        except Exception as exc:  # never a path or driver message: a fault name only
            candidate.close()
            logger.warning(
                "b14_local_ledger_unavailable reason=%s storage_state=not_configured",
                type(exc).__name__,
            )
        else:
            ledger = candidate
            logger.info(
                "b14_local_ledger bound migrations=%d storage_state=bound", applied
            )
    else:
        logger.info("b14_local_ledger unset storage_state=not_configured")
    return LocalEnv(credential_binding_names(), ledger)


def _apply_security_headers(headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    replaced = {name.lower() for name in SECURITY_HEADERS}
    kept = [(name, value) for name, value in headers if name.lower() not in replaced]
    for name, value in SECURITY_HEADERS.items():
        kept.append((name.encode("ascii"), value.encode("ascii")))
    return kept


class LocalRequestScopeMiddleware:
    """Give a plain host the per-request isolation ``worker.fetch`` provides.

    Binding handles are retained, not read; the ledger handle travels as an
    object rather than through the string-coercing env bridge; deferred writes
    drain after the answer is produced. The redirect and the header policy match
    the Worker entrypoint so the same product contract is what a caller sees.
    """

    def __init__(self, app: Any) -> None:
        self.app = app
        self.env = build_local_env()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        from app.pilot.call_ledger_store import bind_ledger_env, reset_ledger_env
        from app.pilot.deferred_writes import bind, drain, reset
        from app.pilot.worker_env import bind_request_env, collect_request_bindings, reset_request_env

        if scope.get("path", "") == "/":
            await self._redirect(scope, receive, send)
            return

        names = credential_binding_names()
        overrides = collect_request_bindings(self.env, names)
        # An empty scope is left unbound on purpose: with no binding on this host
        # the application must behave exactly as it does today (fail closed per
        # route) rather than as a Worker request that has lost its values.
        request_token = bind_request_env(overrides) if overrides else None
        ledger = getattr(self.env, "B14_CALL_LEDGER_D1", None)
        ledger_token = bind_ledger_env(self.env) if ledger is not None else None
        writes_token = bind()

        async def send_with_policy(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": _apply_security_headers(list(message.get("headers") or [])),
                }
            await send(message)

        try:
            await self.app(scope, receive, send_with_policy)
        finally:
            if request_token is not None:
                reset_request_env(request_token)
            try:
                await drain()
            finally:
                reset(writes_token)
                if ledger_token is not None:
                    reset_ledger_env(ledger_token)

    async def _redirect(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        headers = _apply_security_headers([(b"location", PRODUCT_ENTRY_PATH.encode("ascii"))])
        await send({"type": "http.response.start", "status": 307, "headers": headers})
        await send({"type": "http.response.body", "body": b"", "more_body": False})


def configure_stdout_logging() -> None:
    """Route structure logs to stdout so journald collects one stream.

    Handlers are added once and only to the platform's own logger namespace, so
    a host that configures its own logging keeps control and a re-import inside
    one process cannot double-print every line.
    """
    target = logging.getLogger("korean-ai-platform")
    for handler in target.handlers:
        if getattr(handler, "_b14_local_stdout", False):
            return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S%z"
        )
    )
    handler._b14_local_stdout = True
    target.addHandler(handler)
    target.setLevel(os.environ.get("B14_LOG_LEVEL", "INFO").upper() or "INFO")


def create_local_app() -> Any:
    """Build the ASGI application a COM2 host runs without Cloudflare."""
    from app.env_bootstrap import load_env_file

    load_env_file()
    configure_stdout_logging()

    from app.factory import create_app

    app = create_app()
    app.add_middleware(LocalRequestScopeMiddleware)
    return app
