#!/usr/bin/env python3
"""#5121 BYOK dedicated-key transition preflight and gated operator actions.

`preflight` is read-only. It checks the COM2 DPAPI store, the deployed Worker
secret names, migration 053 and the served BYOK route, and prints presence
flags only. It never prints a secret value.

Mutation subcommands are explicit and confirmation-gated:

    register-local   generate and store the dedicated key in COM2 DPAPI
    upload-worker    pipe the DPAPI value to `wrangler secret put`
    apply-migration  apply the additive 053 table from an exact main checkout

The Worker upload must run under the existing hidden-input store, which injects
the value without putting it in argv:

    py -3 D:\\PADIEM-Servers\\infrastructure\\secret-store\\store.py run ^
        py -3 scripts/ops/byok_key_transition.py upload-worker ^
        --account-id <account-id> --confirm-upload

No production secret, database, Worker or DNS change is performed by
`preflight`, `plan` or the tests for this module.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Sequence

SECRET_NAME = "PADIEM_CHAT_CUSTOM_KEY_SECRET"
PREVIOUS_SECRETS_NAME = "PADIEM_CHAT_CUSTOM_KEY_PREVIOUS_SECRETS"
LEGACY_SESSION_SECRETS_NAME = "PADIEM_CHAT_CUSTOM_KEY_LEGACY_SESSION_SECRETS"
MIN_SECRET_CHARS = 32
MIGRATION_CONFIRMATION = "APPLY_BYOK_053_FROM_EXACT_MAIN"
MIGRATION_RELATIVE = Path("apps/padiem-chat/migrations/053_chat_custom_provider_credentials.sql")

DEFAULT_STORE_SCRIPT = Path(r"D:\PADIEM-Servers\infrastructure\secret-store\store.py")
DEFAULT_WRANGLER = Path(r"D:\cli\wrangler.cmd")
DEFAULT_WORKER = "padiem-chat"
DEFAULT_DATABASE = "padiem-chat-db"
DEFAULT_BASE_URL = "https://chat.padiem.net"
_USER_AGENT = "PadiemOpsPreflight/1.0"

_TOKEN_ENV_NAMES = (
    "CLOUDFLARE_API_TOKEN",
    "CF_API_TOKEN",
    "CLOUDFLARE_API_KEY",
    "CF_API_KEY",
    "CLOUDFLARE_EMAIL",
    "CF_EMAIL",
)

_SECRET_NAME_PATTERN = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"


class TransitionError(Exception):
    """The operation cannot continue. The message is a stable code."""


class _Completed:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _run(
    command: Sequence[str],
    *,
    env: dict[str, str] | None = None,
    input_bytes: bytes | None = None,
    cwd: Path | None = None,
    timeout: int = 120,
) -> _Completed:
    try:
        completed = subprocess.run(
            list(command),
            input=input_bytes,
            env=env,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise TransitionError("command_execution_failed") from error
    return _Completed(
        completed.returncode,
        completed.stdout.decode("utf-8", "replace"),
        completed.stderr.decode("utf-8", "replace"),
    )


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _scrub(text: str, secret: str | None) -> str:
    if secret:
        text = text.replace(secret, "[REDACTED]")
    return text


def _bounded(text: str, limit: int = 240) -> str:
    text = " ".join(text.split())
    return text[:limit]


def _valid_secret_name(value: str) -> bool:
    return bool(value) and value[0].isalpha() and value.isupper() and all(
        char in _SECRET_NAME_PATTERN for char in value
    )


def _parse_dpapi_names(output: str) -> set[str]:
    names: set[str] = set()
    for line in output.splitlines():
        value = line.strip()
        if not value or value.startswith("COUNT "):
            continue
        if _valid_secret_name(value):
            names.add(value)
    return names


def read_dpapi_names(store_script: Path, python_executable: str) -> set[str]:
    store_script = Path(store_script)
    if not store_script.is_file():
        raise TransitionError("dpapi_store_missing")
    completed = _run([python_executable, str(store_script), "list"])
    if completed.returncode != 0:
        raise TransitionError("dpapi_list_failed")
    return _parse_dpapi_names(completed.stdout)


def _oauth_env(account_id: str) -> dict[str, str]:
    env = os.environ.copy()
    for name in _TOKEN_ENV_NAMES:
        env.pop(name, None)
    env["CLOUDFLARE_ACCOUNT_ID"] = account_id
    return env


def _worker_account(account_id: str | None) -> str:
    value = (account_id or os.environ.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
    if not value:
        raise TransitionError("cloudflare_account_id_required")
    return value


def _parse_worker_names(output: str) -> set[str]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise TransitionError("worker_secret_list_invalid") from error
    if isinstance(payload, dict):
        payload = payload.get("result", payload.get("secrets"))
    if not isinstance(payload, list):
        raise TransitionError("worker_secret_list_invalid")
    names: set[str] = set()
    for item in payload:
        name = item.get("name") if isinstance(item, dict) else None
        if isinstance(name, str) and _valid_secret_name(name):
            names.add(name)
    return names


def read_worker_secret_names(
    wrangler: Path, worker: str, account_id: str, *, cwd: Path | None = None
) -> set[str]:
    if not Path(wrangler).is_file():
        raise TransitionError("wrangler_missing")
    completed = _run(
        [str(wrangler), "secret", "list", "--name", worker],
        env=_oauth_env(account_id),
        cwd=cwd or repo_root(),
    )
    if completed.returncode != 0:
        raise TransitionError("worker_secret_list_failed")
    return _parse_worker_names(completed.stdout)


def _parse_d1_rows(output: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise TransitionError("d1_query_invalid") from error
    if not isinstance(payload, list) or not payload:
        raise TransitionError("d1_query_invalid")
    first = payload[0]
    if not isinstance(first, dict) or first.get("success") is not True:
        raise TransitionError("d1_query_failed")
    rows = first.get("results")
    if not isinstance(rows, list):
        raise TransitionError("d1_query_invalid")
    return [row for row in rows if isinstance(row, dict)]


def _d1_query(wrangler: Path, database: str, account_id: str, sql: str) -> list[dict[str, Any]]:
    completed = _run(
        [str(wrangler), "d1", "execute", database, "--remote", "--json", "--command", sql],
        env=_oauth_env(account_id),
        cwd=repo_root(),
    )
    if completed.returncode != 0:
        raise TransitionError("d1_query_failed")
    return _parse_d1_rows(completed.stdout)


def read_d1_state(
    wrangler: Path, database: str, account_id: str
) -> dict[str, Any]:
    present = _d1_query(
        wrangler,
        database,
        account_id,
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='chat_custom_provider_credentials';",
    )
    if not present:
        return {"migration_053": "MISSING", "rows": None}
    counted = _d1_query(
        wrangler,
        database,
        account_id,
        "SELECT COUNT(*) AS n FROM chat_custom_provider_credentials;",
    )
    rows = counted[0].get("n") if counted else 0
    if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
        raise TransitionError("d1_row_count_invalid")
    return {"migration_053": "APPLIED", "rows": rows}


def _classify_probe(status: int, content_type: str) -> str:
    if status in (401, 403):
        # Cloudflare answers the default Python user agent with an HTML 403
        # challenge before the request reaches the Worker. Only a JSON auth
        # response proves the BYOK route itself is served.
        return "PRESENT" if "application/json" in (content_type or "").lower() else "UNKNOWN"
    if status == 404:
        return "ABSENT"
    return f"UNEXPECTED_{status}"


def probe_route(base_url: str, timeout: int = 15) -> str:
    url = base_url.rstrip("/") + "/api/chat/custom/credential"
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _classify_probe(
                response.status, response.headers.get("Content-Type", "")
            )
    except urllib.error.HTTPError as error:
        content_type = error.headers.get("Content-Type", "") if error.headers else ""
        return _classify_probe(error.code, content_type)
    except (urllib.error.URLError, TimeoutError, OSError):
        return "UNKNOWN"


def preflight(
    *,
    store_script: Path = DEFAULT_STORE_SCRIPT,
    wrangler: Path = DEFAULT_WRANGLER,
    python_executable: str = sys.executable,
    worker: str = DEFAULT_WORKER,
    database: str = DEFAULT_DATABASE,
    base_url: str = DEFAULT_BASE_URL,
    account_id: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Read-only state report. Each check fails independently."""
    result: dict[str, Any] = {
        "dpapi_custom_key_secret": "UNKNOWN",
        "worker_custom_key_secret": "UNKNOWN",
        "d1_migration_053": "UNKNOWN",
        "custom_credential_rows": "UNKNOWN",
        "deployed_byok_route": "UNKNOWN",
        "secret_values_printed": 0,
    }
    errors: list[str] = []

    try:
        names = read_dpapi_names(store_script, python_executable)
        result["dpapi_custom_key_secret"] = "PRESENT" if SECRET_NAME in names else "MISSING"
    except TransitionError as error:
        errors.append(str(error))
        result["dpapi_custom_key_secret"] = f"ERROR:{error}"

    try:
        selected_account = _worker_account(account_id)
        names = read_worker_secret_names(wrangler, worker, selected_account)
        result["worker_custom_key_secret"] = "PRESENT" if SECRET_NAME in names else "MISSING"
    except TransitionError as error:
        errors.append(str(error))
        result["worker_custom_key_secret"] = f"ERROR:{error}"

    try:
        selected_account = _worker_account(account_id)
        d1_state = read_d1_state(wrangler, database, selected_account)
        result["d1_migration_053"] = d1_state["migration_053"]
        result["custom_credential_rows"] = (
            "TABLE_MISSING" if d1_state["rows"] is None else d1_state["rows"]
        )
    except TransitionError as error:
        errors.append(str(error))
        result["d1_migration_053"] = f"ERROR:{error}"
        result["custom_credential_rows"] = f"ERROR:{error}"

    result["deployed_byok_route"] = probe_route(base_url)

    ready = (
        result["dpapi_custom_key_secret"] == "PRESENT"
        and result["worker_custom_key_secret"] == "PRESENT"
        and result["d1_migration_053"] == "APPLIED"
        and result["deployed_byok_route"] == "PRESENT"
    )
    result["ready"] = ready
    return result, errors


def _print_preflight(result: dict[str, Any], errors: list[str]) -> None:
    print(f"DPAPI_CUSTOM_KEY_SECRET={result['dpapi_custom_key_secret']}")
    print(f"WORKER_CUSTOM_KEY_SECRET={result['worker_custom_key_secret']}")
    print(f"D1_MIGRATION_053={result['d1_migration_053']}")
    print(f"CUSTOM_CREDENTIAL_ROWS={result['custom_credential_rows']}")
    print(f"DEPLOYED_BYOK_ROUTE={result['deployed_byok_route']}")
    for error in errors:
        print(f"CHECK_FAILED reason={error}", file=sys.stderr)
    print(f"BYOK_TRANSITION_READY={'YES' if result['ready'] else 'NO'}")
    print(f"SECRET_VALUES_PRINTED={result['secret_values_printed']}")


def _step_state(value: bool) -> str:
    return "DONE" if value else "PENDING"


def print_plan(result: dict[str, Any]) -> None:
    dpapi = result["dpapi_custom_key_secret"] == "PRESENT"
    worker = result["worker_custom_key_secret"] == "PRESENT"
    migration = result["d1_migration_053"] == "APPLIED"
    route = result["deployed_byok_route"] == "PRESENT"
    print(f"STEP_1_DEPLOY_EXACT_MAIN_BYOK_CODE={_step_state(route)}")
    print(f"STEP_2_APPLY_MIGRATION_053={_step_state(migration)}")
    print(f"STEP_3_REGISTER_COM2_DPAPI_SECRET={_step_state(dpapi)}")
    print(f"STEP_4_UPLOAD_WORKER_SECRET={_step_state(worker)}")
    print(f"STEP_5_PREFLIGHT_REQUIRE_READY={_step_state(bool(result['ready']))}")
    print("STEP_6_OWNER_BOUNDED_BYOK_VERIFY=PENDING")
    print("STEP_7_LEGACY_RESEAL_HASH_CHECK=" + ("NOT_APPLICABLE" if result["custom_credential_rows"] in (0, "TABLE_MISSING") else "PENDING"))
    print("SECRET_VALUES_PRINTED=0")
    print("NEXT=" + _next_action(result))


def _next_action(result: dict[str, Any]) -> str:
    if result["deployed_byok_route"] != "PRESENT":
        return "deploy_exact_main_to_worker_and_refresh_local_release"
    if result["d1_migration_053"] != "APPLIED":
        return "apply-migration"
    if result["dpapi_custom_key_secret"] != "PRESENT":
        return "register-local"
    if result["worker_custom_key_secret"] != "PRESENT":
        return "upload-worker"
    return "owner_bounded_byok_verify"


def register_local(
    *,
    store_script: Path = DEFAULT_STORE_SCRIPT,
    python_executable: str = sys.executable,
    confirm: bool = False,
    replace: bool = False,
) -> None:
    if not confirm:
        raise TransitionError("register_confirmation_required")
    names = read_dpapi_names(store_script, python_executable)
    if SECRET_NAME in names and not replace:
        raise TransitionError("custom_key_secret_already_present_use_replace")
    value = secrets.token_urlsafe(48)
    completed = _run(
        [python_executable, str(store_script), "put-stdin", SECRET_NAME],
        input_bytes=value.encode("utf-8"),
    )
    if completed.returncode != 0:
        raise TransitionError("dpapi_store_failed")
    stored = read_dpapi_names(store_script, python_executable)
    if SECRET_NAME not in stored:
        raise TransitionError("dpapi_store_verification_failed")
    print("DPAPI_SECRET_STORED=YES")
    print(f"SECRET_LENGTH_OK={'YES' if len(value) >= MIN_SECRET_CHARS else 'NO'}")
    print("SECRET_VALUES_PRINTED=0")


def upload_worker(
    *,
    wrangler: Path = DEFAULT_WRANGLER,
    worker: str = DEFAULT_WORKER,
    account_id: str | None = None,
    confirm: bool = False,
) -> None:
    if not confirm:
        raise TransitionError("upload_confirmation_required")
    value = os.environ.get(SECRET_NAME)
    if not value:
        raise TransitionError("custom_key_secret_missing_run_under_store_py")
    if len(value) < MIN_SECRET_CHARS or value != value.strip():
        raise TransitionError("custom_key_secret_invalid")
    selected_account = _worker_account(account_id)
    completed = _run(
        [str(wrangler), "secret", "put", SECRET_NAME, "--name", worker],
        env=_oauth_env(selected_account),
        input_bytes=value.encode("utf-8"),
        cwd=repo_root(),
    )
    stdout = _scrub(completed.stdout, value)
    stderr = _scrub(completed.stderr, value)
    if completed.returncode != 0:
        raise TransitionError("worker_secret_upload_failed:" + _bounded(stderr or stdout))
    names = read_worker_secret_names(wrangler, worker, selected_account)
    if SECRET_NAME not in names:
        raise TransitionError("worker_secret_verification_failed")
    print("WORKER_SECRET_UPLOADED=YES")
    print("WORKER_SECRET_VERIFIED=YES")
    print("SECRET_VALUES_PRINTED=0")


def _git_head(repo: Path) -> str:
    completed = _run(["git", "-C", str(repo), "rev-parse", "HEAD"])
    if completed.returncode != 0:
        raise TransitionError("git_head_unavailable")
    value = completed.stdout.strip()
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise TransitionError("git_head_invalid")
    return value


def apply_migration(
    *,
    wrangler: Path = DEFAULT_WRANGLER,
    database: str = DEFAULT_DATABASE,
    account_id: str | None = None,
    expected_main: str,
    confirmation: str,
    repo: Path | None = None,
) -> None:
    if confirmation != MIGRATION_CONFIRMATION:
        raise TransitionError("migration_confirmation_required")
    selected_account = _worker_account(account_id)
    root = Path(repo) if repo else repo_root()
    migration = root / MIGRATION_RELATIVE
    if not migration.is_file():
        raise TransitionError("migration_file_missing")
    expected = (expected_main or "").strip().lower()
    if len(expected) != 40 or any(char not in "0123456789abcdef" for char in expected):
        raise TransitionError("expected_main_invalid")
    if _git_head(root) != expected:
        raise TransitionError("expected_main_mismatch")
    completed = _run(
        [
            str(wrangler),
            "d1",
            "execute",
            database,
            "--remote",
            "--file",
            str(migration),
        ],
        env=_oauth_env(selected_account),
        cwd=root,
    )
    if completed.returncode != 0:
        raise TransitionError("d1_migration_apply_failed:" + _bounded(completed.stderr))
    state = read_d1_state(wrangler, database, selected_account)
    if state["migration_053"] != "APPLIED":
        raise TransitionError("d1_migration_verification_failed")
    print("D1_MIGRATION_053=APPLIED")
    print(f"CUSTOM_CREDENTIAL_ROWS={state['rows']}")
    print("SECRET_VALUES_PRINTED=0")


def _preflight_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--store-script", default=str(DEFAULT_STORE_SCRIPT))
    parser.add_argument("--wrangler", default=str(DEFAULT_WRANGLER))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--worker", default=DEFAULT_WORKER)
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--account-id", default=None)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight_parser = subparsers.add_parser("preflight", help="read-only state report")
    _preflight_options(preflight_parser)
    preflight_parser.add_argument("--json", action="store_true")
    preflight_parser.add_argument("--require-ready", action="store_true")

    plan_parser = subparsers.add_parser("plan", help="ordered transition steps")
    _preflight_options(plan_parser)

    register = subparsers.add_parser("register-local", help="store the key in COM2 DPAPI")
    register.add_argument("--store-script", default=str(DEFAULT_STORE_SCRIPT))
    register.add_argument("--python", default=sys.executable)
    register.add_argument("--confirm-register", action="store_true")
    register.add_argument("--replace", action="store_true")

    upload = subparsers.add_parser("upload-worker", help="upload the key to the Worker")
    upload.add_argument("--wrangler", default=str(DEFAULT_WRANGLER))
    upload.add_argument("--worker", default=DEFAULT_WORKER)
    upload.add_argument("--account-id", default=None)
    upload.add_argument("--confirm-upload", action="store_true")

    apply_parser = subparsers.add_parser("apply-migration", help="apply additive migration 053")
    apply_parser.add_argument("--wrangler", default=str(DEFAULT_WRANGLER))
    apply_parser.add_argument("--database", default=DEFAULT_DATABASE)
    apply_parser.add_argument("--account-id", default=None)
    apply_parser.add_argument("--expected-main", required=True)
    apply_parser.add_argument("--confirm-apply", default="")
    apply_parser.add_argument("--repo", default=None)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "preflight":
            result, errors = preflight(
                store_script=Path(args.store_script),
                wrangler=Path(args.wrangler),
                python_executable=args.python,
                worker=args.worker,
                database=args.database,
                base_url=args.base_url,
                account_id=args.account_id,
            )
            if args.json:
                print(json.dumps(result, indent=2, sort_keys=True))
                for error in errors:
                    print(f"CHECK_FAILED reason={error}", file=sys.stderr)
            else:
                _print_preflight(result, errors)
            return 1 if args.require_ready and not result["ready"] else 0
        if args.command == "plan":
            result, errors = preflight(
                store_script=Path(args.store_script),
                wrangler=Path(args.wrangler),
                python_executable=args.python,
                worker=args.worker,
                database=args.database,
                base_url=args.base_url,
                account_id=args.account_id,
            )
            for error in errors:
                print(f"CHECK_FAILED reason={error}", file=sys.stderr)
            print_plan(result)
            return 0
        if args.command == "register-local":
            register_local(
                store_script=Path(args.store_script),
                python_executable=args.python,
                confirm=args.confirm_register,
                replace=args.replace,
            )
            return 0
        if args.command == "upload-worker":
            upload_worker(
                wrangler=Path(args.wrangler),
                worker=args.worker,
                account_id=args.account_id,
                confirm=args.confirm_upload,
            )
            return 0
        if args.command == "apply-migration":
            apply_migration(
                wrangler=Path(args.wrangler),
                database=args.database,
                account_id=args.account_id,
                expected_main=args.expected_main,
                confirmation=args.confirm_apply,
                repo=Path(args.repo) if args.repo else None,
            )
            return 0
    except TransitionError as error:
        print(f"BYOK_TRANSITION_FAILED reason={error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
