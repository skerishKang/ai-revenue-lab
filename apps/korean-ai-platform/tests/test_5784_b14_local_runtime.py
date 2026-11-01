"""#5784 B14 runs on a plain host: what the local adapter must keep true.

The adapter exists so the same application can serve COM2 without Cloudflare
Workers. These tests pin both halves of that claim: the local equivalents do the
real work (schema, write, read, credential resolution), and nothing the Worker
runtime already decided gets weakened on the way — the response policy, the
service-proof boundary, the fail-open ledger posture and the fail-closed missing
binding behaviour all stay the authorities they already are.
"""

from __future__ import annotations

import ast
import os
import stat
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.local_runtime import (
    LEDGER_PATH_ENV,
    SECRET_DIR_ENV,
    SECURITY_HEADERS,
    SERVICE_PROOF_BINDING,
    SqliteLedger,
    build_local_env,
    configure_stdout_logging,
    create_local_app,
    credential_binding_names,
)
from app.pilot.call_ledger import AttemptRecord, CallRecord, new_log_id, utc_now_iso
from app.pilot.call_ledger_store import CallLedgerStore, storage_state
from app.pilot.deployment_entry import PRODUCT_ENTRY_PATH
from app.pilot import model_registry_file

APP_ROOT = Path(__file__).resolve().parents[1]
WORKER_SRC = (APP_ROOT / "worker.py").read_text(encoding="utf-8")
ADMIN_LIST = "/api/pilot/v1/admin/model-calls"

GRAFANA_BINDING = "PADIEM_GRAFANA_OTLP_TOKEN"

_WORKER_TREE = ast.parse(WORKER_SRC)


def _worker_assignment(name: str):
    return next(
        (
            node for node in _WORKER_TREE.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == name
                for target in node.targets
            )
        ),
        None,
    )


def _worker_env_keys() -> set[str]:
    """The request scope worker.py actually builds, by evaluating its own code.

    Unioning the two halves here would keep passing if the entrypoint stopped
    reading the registry, which is the coupling this file exists to detect.
    """
    nodes = [_worker_assignment("_FIXED_ENV_KEYS"), _worker_assignment("_ENV_KEYS")]
    if any(node is None for node in nodes):
        raise AssertionError("worker.py lost _FIXED_ENV_KEYS or _ENV_KEYS")
    scope: dict[str, object] = {}
    for node in nodes:
        exec(
            compile(ast.Module(body=[node], type_ignores=[]), "worker.py", "exec"),
            {"credential_binding_names": model_registry_file.credential_binding_names},
            scope,
        )
    return set(scope["_ENV_KEYS"])


def _worker_literal(name: str):
    node = _worker_assignment(name)
    if node is None:
        raise AssertionError("%s is no longer a literal in worker.py" % name)
    if name == "_ENV_KEYS":
        return _worker_env_keys()
    return ast.literal_eval(node.value)


@pytest.fixture()
def host_dirs(tmp_path, monkeypatch):
    """A host that declares a ledger file and a private secret directory."""
    ledger = tmp_path / "ledger" / "b14-call-ledger.db"
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    monkeypatch.setenv(LEDGER_PATH_ENV, str(ledger))
    monkeypatch.setenv(SECRET_DIR_ENV, str(secrets))
    return ledger, secrets


def _call(**overrides) -> CallRecord:
    base = dict(
        log_id=new_log_id(),
        request_id="b14req_local01",
        endpoint="/api/pilot/v1/chat/completions",
        started_at=utc_now_iso(),
    )
    base.update(overrides)
    return CallRecord(**base)


def _attempt(log_id: str, index: int) -> AttemptRecord:
    return AttemptRecord(
        log_id=log_id,
        attempt_index=index,
        provider="Agnes AI",
        model_id="agnes-ai/agnes-3.0-flash",
        upstream_model="agnes-3.0-flash",
        outcome="success" if index else "error",
        error_code=None if index else "upstream_timeout",
    )


# ---------------------------------------------------------------------------
# The ledger: the committed migration, on this host's disk
# ---------------------------------------------------------------------------


def test_ledger_applies_the_committed_migration_and_creates_the_file(host_dirs) -> None:
    path, _ = host_dirs
    ledger = SqliteLedger(path)
    assert ledger.apply_migrations() >= 1
    assert path.is_file()
    import sqlite3

    connection = sqlite3.connect(str(path))
    names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    connection.close()
    assert {"b14_model_call", "b14_model_call_attempt", "b14_model_call_started"} <= names


def test_a_second_start_applies_nothing_and_records_the_same_migrations(host_dirs) -> None:
    """Re-running 0001 at every boot only worked while 0001 was re-runnable.

    The applied names are what makes the second, third and hundredth start the
    same as the first, so a restart must apply zero and still find its schema.
    """
    path, _ = host_dirs
    first = SqliteLedger(path)
    assert first.apply_migrations() == 3
    recorded = first.recorded_migrations()
    assert [name[:4] for name in recorded] == ["0001", "0002", "0003"]
    first.close()

    restarted = SqliteLedger(path)
    assert restarted.apply_migrations() == 0
    assert restarted.recorded_migrations() == recorded
    import sqlite3

    connection = sqlite3.connect(str(path))
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    finally:
        connection.close()
    assert {"b14_model_call", "b14_model_call_attempt"} <= tables


def test_a_later_migration_runs_once_and_in_order_after_the_first(host_dirs, tmp_path) -> None:
    """A migration added after the committed pair runs once, in name order.

    The committed 0002 is the case this ordering protects: an ``ALTER TABLE``
    that a second boot would re-run is exactly the non-replayable file the
    recorded-name list exists to skip.
    """
    import shutil

    path, _ = host_dirs
    source = tmp_path / "migrations"
    shutil.copytree(APP_ROOT / "migrations", source)
    ledger = SqliteLedger(path, migrations_dir=source)
    assert ledger.apply_migrations() == 3

    (source / "0004_b14_local_marker.sql").write_text(
        "CREATE TABLE b14_local_marker (id INTEGER PRIMARY KEY CHECK (id = 1));",
        encoding="utf-8",
    )
    assert ledger.apply_migrations() == 1
    assert [name[:4] for name in ledger.recorded_migrations()] == [
        "0001", "0002", "0003", "0004",
    ]
    # A third start sees both names recorded and runs neither script again.
    assert ledger.apply_migrations() == 0
    import sqlite3

    connection = sqlite3.connect(str(path))
    try:
        connection.execute("INSERT INTO b14_local_marker (id) VALUES (1)")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO b14_local_marker (id) VALUES (2)")
    finally:
        connection.close()


def test_migration_constraints_are_the_same_constraints(host_dirs) -> None:
    """A look-alike table would pass a round-trip and still lie later."""
    path, _ = host_dirs
    ledger = SqliteLedger(path)
    ledger.apply_migrations()
    import sqlite3

    connection = sqlite3.connect(str(path))
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO b14_model_call (log_id, request_id, product, protocol,"
            " outcome, latency_source, token_source, cost_basis)"
            " VALUES ('log_a12345678','r1','not-a-product','native','success',"
            " 'measured','missing','unknown')"
        )
    connection.close()


def test_the_credential_source_column_names_two_states_and_defaults_to_pool(host_dirs) -> None:
    """#5824 PR-3a: 0002 adds the pool/user label without touching old rows.

    The column is a category, so the only thing proven here is the vocabulary:
    a row that omits it is platform consumption, a row that names anything else
    is refused, and the ALTER never rewrites what 0001 already stored.
    """
    path, _ = host_dirs
    ledger = SqliteLedger(path)
    assert ledger.apply_migrations() == 3
    import sqlite3

    connection = sqlite3.connect(str(path))
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(b14_model_call)")}
        assert "credential_source" in columns
        minimum = (
            "INSERT INTO b14_model_call (log_id, request_id, product, origin_source,"
            " protocol, outcome, latency_source, token_source, cost_basis)"
            " VALUES ('log_a12345678','r1','chat','b14_observed','chat/completions',"
            " 'success','unknown','missing','unknown')"
        )
        connection.execute(minimum)
        assert connection.execute(
            "SELECT credential_source FROM b14_model_call WHERE log_id = 'log_a12345678'"
        ).fetchone()[0] == "pool"
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO b14_model_call (log_id, request_id, product, origin_source,"
                " protocol, outcome, latency_source, token_source, cost_basis,"
                " credential_source)"
                " VALUES ('log_b12345678','r2','chat','b14_observed',"
                " 'chat/completions','success','unknown','missing','unknown',"
                " 'service_account')"
            )
        connection.execute(
            "INSERT INTO b14_model_call (log_id, request_id, product, origin_source,"
            " protocol, outcome, latency_source, token_source, cost_basis,"
            " credential_source)"
            " VALUES ('log_c12345678','r3','chat','b14_observed',"
            " 'chat/completions','success','unknown','missing','unknown','user')"
        )
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_call_and_attempts_round_trip(host_dirs) -> None:
    path, _ = host_dirs
    ledger = SqliteLedger(path)
    ledger.apply_migrations()
    store = CallLedgerStore(ledger)

    log_id = new_log_id()
    call = _call(log_id=log_id, attempt_count=2, attempts=(_attempt(log_id, 0), _attempt(log_id, 1)))
    assert await store.record(call) == "written"

    rows = await store.list_calls()
    assert [row["log_id"] for row in rows] == [log_id]
    assert await store.count_calls() == 1

    detail = await store.get_call(log_id)
    assert detail is not None
    assert detail["request_id"] == call.request_id
    assert [row["attempt_index"] for row in detail["attempts"]] == [0, 1]
    assert [row["outcome"] for row in detail["attempts"]] == ["error", "success"]


@pytest.mark.asyncio
async def test_a_repeated_log_id_is_ignored_not_duplicated(host_dirs) -> None:
    path, _ = host_dirs
    ledger = SqliteLedger(path)
    ledger.apply_migrations()
    store = CallLedgerStore(ledger)
    call = _call()
    assert await store.record(call) == "written"
    assert await store.record(call) == "written"
    assert await store.count_calls() == 1


@pytest.mark.asyncio
async def test_a_storage_fault_returns_a_status_not_an_exception(host_dirs) -> None:
    path, _ = host_dirs
    ledger = SqliteLedger(path)
    ledger.apply_migrations()
    ledger.close()
    path.unlink()
    path.write_text("not a database", encoding="utf-8")
    store = CallLedgerStore(ledger)
    assert await store.record(_call()) == "storage_unavailable"


@pytest.mark.asyncio
async def test_a_host_without_a_declared_ledger_serves_answers(monkeypatch) -> None:
    monkeypatch.delenv(LEDGER_PATH_ENV, raising=False)
    env = build_local_env()
    assert storage_state(env) == "not_configured"
    with TestClient(create_local_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["app"] == "korean-ai-platform"


@pytest.mark.asyncio
async def test_a_batch_that_fails_leaves_no_partial_rows(host_dirs) -> None:
    """A D1 batch is one transaction; half an attempt set would mislead the console."""
    path, _ = host_dirs
    ledger = SqliteLedger(path)
    ledger.apply_migrations()
    log_id = new_log_id()
    good = ledger.prepare(
        "INSERT INTO b14_model_call_attempt (log_id, attempt_index, provider, outcome,"
        " latency_source, token_source, cost_basis) VALUES (?,?,?,?,?,?,?)"
    ).bind(log_id, 0, "Agnes AI", "success", "measured", "missing", "unknown")
    bad = ledger.prepare(
        "INSERT INTO b14_model_call (log_id, request_id, product, protocol, outcome,"
        " latency_source, token_source, cost_basis) VALUES (?,?,?,?,?,?,?,?)"
    ).bind(log_id, "r1", "not-a-product", "native", "success", "measured", "missing", "unknown")
    with pytest.raises(Exception):
        await ledger.batch([good, bad])
    store = CallLedgerStore(ledger)
    assert await store.get_call(log_id) is None
    import sqlite3

    connection = sqlite3.connect(str(path))
    remaining = connection.execute(
        "SELECT COUNT(*) FROM b14_model_call_attempt WHERE log_id = ?", (log_id,)
    ).fetchone()[0]
    connection.close()
    assert remaining == 0


def test_an_unreachable_ledger_path_degrades_the_posture_not_the_app(tmp_path, monkeypatch) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file", encoding="utf-8")
    monkeypatch.setenv(LEDGER_PATH_ENV, str(blocker / "ledger.db"))
    env = build_local_env()
    assert storage_state(env) == "not_configured"


# ---------------------------------------------------------------------------
# Credentials: env first, then the named file, never a printed value
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_environment_wins_and_the_named_file_is_the_fallback(host_dirs, monkeypatch) -> None:
    from app.local_runtime import FileOrEnvSecret

    _, secrets = host_dirs
    binding = "PADIEM_B14_CREDENTIAL_01"
    path = secrets / binding
    path.write_text("file-value\n", encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)

    monkeypatch.setenv(binding, "env-value")
    assert await FileOrEnvSecret(binding).get() == "env-value"
    monkeypatch.delenv(binding)
    assert await FileOrEnvSecret(binding).get() == "file-value"


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
@pytest.mark.asyncio
async def test_a_secret_the_whole_host_can_read_is_refused(host_dirs) -> None:
    from app.local_runtime import FileOrEnvSecret

    _, secrets = host_dirs
    binding = "PADIEM_B14_CREDENTIAL_02"
    path = secrets / binding
    path.write_text("exposed-value", encoding="utf-8")
    os.chmod(path, 0o644)
    assert await FileOrEnvSecret(binding).get() == ""


@pytest.mark.asyncio
async def test_an_unnamed_binding_is_not_a_handle(host_dirs) -> None:
    env = build_local_env()
    with pytest.raises(AttributeError):
        env.NOT_A_BINDING_NAME
    with pytest.raises(AttributeError):
        env.lowercase_name


def test_credential_names_come_from_the_catalog_and_stay_inside_worker_scope() -> None:
    """No second allowlist: the names the app asks for are a subset of the Worker's.

    The names come from the package registry file, so the answer does not depend
    on which modules happen to be imported first.
    """
    collected = _worker_literal("_ENV_KEYS")
    names = set(credential_binding_names())
    platform = {name for name in names if name.startswith("PADIEM_B14_CREDENTIAL_")}
    assert platform and platform <= collected
    assert SERVICE_PROOF_BINDING in collected and SERVICE_PROOF_BINDING in names
    # The telemetry token is read straight off the env object by stack_telemetry,
    # in the Worker and here alike; it never travelled through the per-request
    # bridge, so it must not appear in that bridge's scope.
    assert GRAFANA_BINDING not in collected
    assert GRAFANA_BINDING in names


# ---------------------------------------------------------------------------
# The response policy and scope isolation the Worker entrypoint applies
# ---------------------------------------------------------------------------


def test_root_redirects_to_the_product_entrypoint_with_the_header_policy() -> None:
    with TestClient(create_local_app()) as client:
        response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == PRODUCT_ENTRY_PATH
    for header, value in SECURITY_HEADERS.items():
        assert response.headers[header] == value


def test_an_ordinary_answer_carries_the_same_header_policy() -> None:
    """The redirect is not the only response the entrypoint can produce."""
    with TestClient(create_local_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    for header, value in SECURITY_HEADERS.items():
        assert response.headers[header] == value


def test_security_policy_is_the_worker_policy_value_for_value() -> None:
    assert _worker_literal("_SECURITY_HEADERS") == SECURITY_HEADERS
    assert '"Location": "%s"' % PRODUCT_ENTRY_PATH in WORKER_SRC


def test_adapter_keeps_the_plain_route_table() -> None:
    """The 8789 adapter keeps the Worker route table with no management routes."""
    def paths(app):
        return sorted(getattr(route, "path", None) or repr(route) for route in app.routes)
    plain = paths(create_app())
    local = paths(create_local_app())
    assert local == plain
    assert not any(path.startswith("/com2/admin") for path in local)


def test_service_proof_boundary_is_unchanged_in_adapter_mode(monkeypatch) -> None:
    """The adapter must not become a second, unproven way in."""
    monkeypatch.delenv(SERVICE_PROOF_BINDING, raising=False)
    with TestClient(create_local_app()) as client:
        unproven = client.get(ADMIN_LIST)
    assert unproven.status_code in (401, 503)
    assert unproven.json()["error"]["code"] in (
        "b14_service_proof_required",
        "b14_service_proof_unconfigured",
    )


def test_request_scope_does_not_leak_into_the_next_request(host_dirs, monkeypatch) -> None:
    from app.pilot.worker_env import scoped_secret

    monkeypatch.setenv(SERVICE_PROOF_BINDING, "a-proof-secret-for-this-host-0123456789")
    with TestClient(create_local_app()) as client:
        assert client.get("/health").status_code == 200
    assert scoped_secret(SERVICE_PROOF_BINDING) is None


def test_stdout_logging_is_installed_once_and_points_at_stdout() -> None:
    import logging

    target = logging.getLogger("korean-ai-platform")
    configure_stdout_logging()
    configure_stdout_logging()
    installed = [h for h in target.handlers if getattr(h, "_b14_local_stdout", False)]
    assert len(installed) == 1
    assert installed[0].stream is sys.stdout


def test_the_catalog_and_assets_are_package_files_not_an_assets_binding() -> None:
    """The ASSETS replacement is already the shipped authority: read from disk.

    The owner model registry and the static surface were package reads before
    this adapter existed, so the local runtime needs no second asset service and
    gains no new authority here.
    """
    from app.pilot.model_registry_file import REGISTRY_PATH

    assert REGISTRY_PATH.is_file() and REGISTRY_PATH.name == "b14_models.json"
    with TestClient(create_local_app()) as client:
        catalog = client.get("/api/pilot/models")
        stylesheet = client.get("/app.css")
    assert catalog.status_code == 200
    assert catalog.json()["catalog"], "the package registry did not answer the catalog"
    assert stylesheet.status_code == 200
    assert "text/css" in stylesheet.headers["content-type"]


def test_entrypoint_imports_without_the_workers_runtime() -> None:
    import subprocess

    result = subprocess.run(
        [sys.executable, "-c", "import asgi, sys; print('workers' in sys.modules)"],
        cwd=str(APP_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr[-800:]
    assert result.stdout.strip() == "False"


# ---------------------------------------------------------------------------
# The declared name list the Owner types on the machine
# ---------------------------------------------------------------------------


def test_env_example_lists_names_and_never_values() -> None:
    text = (APP_ROOT / "b14.env.example").read_text(encoding="utf-8")
    entries = {
        line.split("=", 1)[0]: line.split("=", 1)[1].strip()
        for line in text.splitlines()
        if line and not line.startswith("#") and "=" in line
    }
    credentials = {f"PADIEM_B14_CREDENTIAL_{index:02d}" for index in range(1, 15)}
    assert credentials <= set(entries)
    for binding in credentials | {SERVICE_PROOF_BINDING, GRAFANA_BINDING}:
        assert entries[binding] == "", binding
    assert len(credentials) == 14
