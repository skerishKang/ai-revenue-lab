#!/usr/bin/env python3
"""Read-only Cloudflare operating-asset snapshot for COM2 recovery checks.

The snapshot covers the Worker fleet that PADIEM runs on Cloudflare, each
Worker's current version, binding names and targets, plus the account's D1
databases and R2 buckets. It reads through the existing Wrangler session and
never reads or writes secret values.

Guarantees:
* Only Wrangler read commands are invoked (``whoami`` is not needed;
  ``deployments status/list``, ``versions view``, ``d1 list``, ``r2 bucket
  list``). No deploy, SQL execution, object write, secret read or setting
  change is implemented here.
* Secret values and plaintext binding values are dropped while summarizing.
  Only binding names, secret names and resource identifiers remain.
* The JSON snapshot is a private local artifact. Do not commit it.

Usage:
    python scripts/ops/cloudflare_asset_snapshot.py capture \\
        --out D:/private/cf-snapshot.json --worker padiem-chat --worker ...

    python scripts/ops/cloudflare_asset_snapshot.py verify \\
        --snapshot D:/private/cf-snapshot.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

SNAPSHOT_KIND = "PADIEM_CLOUDFLARE_ASSET_SNAPSHOT_V1"
SNAPSHOT_VERSION = 1

Runner = Callable[[Sequence[str], Mapping[str, str], float], tuple[int, str]]

_BUCKET_NAME = re.compile(r"^name:\s+(\S+)\s*$")
_BUCKET_CREATED = re.compile(r"^creation_date:\s+(\S+)\s*$")


class SnapshotError(Exception):
    """A read-only capture step failed. The message is a stable code, not output."""


def _default_runner(command: Sequence[str], env: Mapping[str, str], timeout: float) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=dict(env),
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, ""
    except OSError:
        return 127, ""
    return completed.returncode, completed.stdout


def _wrangler(
    command: Sequence[str],
    *,
    wrangler: str,
    env: Mapping[str, str],
    timeout: float,
    runner: Runner,
) -> str:
    code, stdout = runner([wrangler, *command], env, timeout)
    if code != 0:
        raise SnapshotError("wrangler_command_failed")
    return stdout


def _load_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise SnapshotError("wrangler_output_not_json") from error


def _annotation(payload: Mapping[str, Any], key: str) -> str | None:
    annotations = payload.get("annotations")
    if not isinstance(annotations, dict):
        return None
    value = annotations.get(key)
    return value if isinstance(value, str) and value else None


def _safe_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def summarize_bindings(bindings: Any) -> dict[str, Any]:
    """Project version bindings to names and targets, never values."""
    if not isinstance(bindings, list):
        raise SnapshotError("version_bindings_unavailable")
    counts: dict[str, int] = {}
    secrets: list[dict[str, str | None]] = []
    databases: list[dict[str, str | None]] = []
    buckets: list[dict[str, str | None]] = []
    services: list[dict[str, str | None]] = []
    durable_objects: list[dict[str, str | None]] = []
    key_values: list[dict[str, str | None]] = []
    other: list[dict[str, str | None]] = []

    for row in bindings:
        if not isinstance(row, dict):
            continue
        kind = _safe_str(row.get("type")) or "unknown"
        counts[kind] = counts.get(kind, 0) + 1
        name = _safe_str(row.get("name"))
        if kind == "secret_text":
            secrets.append({"binding": name, "type": kind})
        elif kind == "secrets_store_secret":
            secrets.append(
                {
                    "binding": name,
                    "type": kind,
                    "secret_name": _safe_str(row.get("secret_name")),
                    "store_id": _safe_str(row.get("store_id")),
                }
            )
        elif kind == "d1":
            databases.append(
                {
                    "binding": name,
                    "database_id": _safe_str(row.get("database_id")) or _safe_str(row.get("id")),
                }
            )
        elif kind == "r2_bucket":
            buckets.append({"binding": name, "bucket_name": _safe_str(row.get("bucket_name"))})
        elif kind == "service":
            services.append({"binding": name, "worker": _safe_str(row.get("service"))})
        elif kind == "durable_object_namespace":
            durable_objects.append({"binding": name, "class_name": _safe_str(row.get("class_name"))})
        elif kind == "kv_namespace":
            key_values.append({"binding": name, "namespace_id": _safe_str(row.get("namespace_id"))})
        else:
            # plain_text/json/assets/browser/version_metadata: keep the type and
            # name only. Values are intentionally discarded.
            other.append({"binding": name, "type": kind})

    def ordered(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(rows, key=lambda item: (item.get("binding") or "", json.dumps(item, sort_keys=True)))

    return {
        "counts": dict(sorted(counts.items())),
        "secrets": ordered(secrets),
        "d1": ordered(databases),
        "r2": ordered(buckets),
        "service": ordered(services),
        "durable_object": ordered(durable_objects),
        "kv": ordered(key_values),
        "other": ordered(other),
    }


def _parse_bucket_list(raw: str) -> list[dict[str, str | None]]:
    buckets: list[dict[str, str | None]] = []
    current: dict[str, str | None] | None = None
    for line in raw.splitlines():
        name_match = _BUCKET_NAME.match(line.strip())
        if name_match:
            current = {"name": name_match.group(1), "creation_date": None}
            buckets.append(current)
            continue
        created_match = _BUCKET_CREATED.match(line.strip())
        if created_match and current is not None:
            current["creation_date"] = created_match.group(1)
    return sorted(buckets, key=lambda item: item.get("name") or "")


def capture_worker(
    name: str,
    *,
    wrangler: str,
    env: Mapping[str, str],
    timeout: float,
    runner: Runner,
) -> dict[str, Any]:
    common = {"wrangler": wrangler, "env": env, "timeout": timeout, "runner": runner}
    try:
        status = _load_json(_wrangler(["deployments", "status", "--name", name, "--json"], **common))
        if not isinstance(status, dict):
            raise SnapshotError("deployment_status_invalid")
        active = status.get("versions")
        if not isinstance(active, list) or not active or not isinstance(active[0], dict):
            raise SnapshotError("deployment_status_invalid")
        version_id = _safe_str(active[0].get("version_id"))
        if version_id is None:
            raise SnapshotError("deployment_status_invalid")
        version = _load_json(
            _wrangler(["versions", "view", version_id, "--name", name, "--json"], **common)
        )
        if not isinstance(version, dict):
            raise SnapshotError("version_view_invalid")
        metadata = version.get("metadata") if isinstance(version.get("metadata"), dict) else {}
        resources = version.get("resources") if isinstance(version.get("resources"), dict) else {}
        script = resources.get("script") if isinstance(resources.get("script"), dict) else {}
        runtime = resources.get("script_runtime") if isinstance(resources.get("script_runtime"), dict) else {}
        history_raw = _load_json(_wrangler(["deployments", "list", "--name", name, "--json"], **common))
        history: list[dict[str, Any]] = []
        if isinstance(history_raw, list):
            for row in history_raw:
                if not isinstance(row, dict):
                    continue
                versions = row.get("versions")
                current_id = None
                if isinstance(versions, list) and versions and isinstance(versions[0], dict):
                    current_id = _safe_str(versions[0].get("version_id"))
                history.append(
                    {
                        "version_id": current_id,
                        "created_on": _safe_str(row.get("created_on")),
                        "message": _annotation(row, "workers/message"),
                        "source": _safe_str(row.get("source")),
                    }
                )
        history.sort(key=lambda item: item.get("created_on") or "", reverse=True)
        return {
            "name": name,
            "state": "deployed",
            "version_id": version_id,
            "version_number": version.get("number"),
            "created_on": _safe_str(metadata.get("created_on")) or _safe_str(status.get("created_on")),
            "source": _safe_str(status.get("source")),
            "message": _annotation(status, "workers/message"),
            "git_tag": _annotation(version, "workers/tag"),
            "compatibility_date": _safe_str(runtime.get("compatibility_date")),
            "compatibility_flags": sorted(
                flag for flag in runtime.get("compatibility_flags", []) if isinstance(flag, str)
            ),
            "handlers": sorted(handler for handler in script.get("handlers", []) if isinstance(handler, str)),
            "bindings": summarize_bindings(resources.get("bindings")),
            "history": history[:10],
        }
    except SnapshotError as error:
        return {"name": name, "state": "unavailable", "error": str(error)}


def capture_snapshot(
    workers: Sequence[str],
    *,
    wrangler: str = "wrangler",
    account_id: str | None = None,
    timeout: float = 120.0,
    runner: Runner = _default_runner,
    now: str | None = None,
) -> dict[str, Any]:
    if not workers:
        raise SnapshotError("worker_list_required")
    env = dict(os.environ)
    if account_id:
        env["CLOUDFLARE_ACCOUNT_ID"] = account_id

    common = {"wrangler": wrangler, "env": env, "timeout": timeout, "runner": runner}
    d1_rows = _load_json(_wrangler(["d1", "list", "--json"], **common))
    if not isinstance(d1_rows, list):
        raise SnapshotError("d1_list_invalid")
    databases = [
        {
            "name": _safe_str(row.get("name")),
            "uuid": _safe_str(row.get("uuid")),
            "created_at": _safe_str(row.get("created_at")),
            "version": _safe_str(row.get("version")),
            "num_tables": row.get("num_tables") if isinstance(row.get("num_tables"), int) else None,
            "file_size": row.get("file_size") if isinstance(row.get("file_size"), int) else None,
        }
        for row in d1_rows
        if isinstance(row, dict)
    ]
    databases.sort(key=lambda item: item.get("name") or "")

    r2_text = _wrangler(["r2", "bucket", "list"], **common)
    buckets = _parse_bucket_list(r2_text)

    return {
        "kind": SNAPSHOT_KIND,
        "version": SNAPSHOT_VERSION,
        "captured_utc": now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "account_id": account_id,
        "workers": [capture_worker(name, **common) for name in sorted(set(workers))],
        "d1": databases,
        "r2": buckets,
    }


def _binding_identity(kind: str, row: Mapping[str, Any]) -> str:
    if kind == "secrets":
        suffix = row.get("secret_name") or row.get("type") or ""
        return f"{row.get('binding')}|{suffix}"
    if kind == "d1":
        return f"{row.get('binding')}|{row.get('database_id')}"
    if kind == "r2":
        return f"{row.get('binding')}|{row.get('bucket_name')}"
    if kind == "service":
        return f"{row.get('binding')}|{row.get('worker')}"
    if kind == "durable_object":
        return f"{row.get('binding')}|{row.get('class_name')}"
    return f"{row.get('binding')}|{row.get('namespace_id')}"


def compare_snapshots(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    report: dict[str, Any] = {
        "ok": True,
        "previous_captured_utc": previous.get("captured_utc"),
        "current_captured_utc": current.get("captured_utc"),
        "workers": {"missing": [], "version_changed": [], "binding_changed": []},
        "d1": {"missing": [], "added": [], "changed": []},
        "r2": {"missing": [], "added": []},
    }

    old_workers = {
        row.get("name"): row for row in previous.get("workers", []) if isinstance(row, dict) and row.get("name")
    }
    new_workers = {
        row.get("name"): row for row in current.get("workers", []) if isinstance(row, dict) and row.get("name")
    }
    for name in sorted(old_workers):
        old = old_workers[name]
        new = new_workers.get(name)
        if new is None or new.get("state") != "deployed":
            report["workers"]["missing"].append(name)
            continue
        if old.get("version_id") != new.get("version_id"):
            report["workers"]["version_changed"].append(
                {
                    "worker": name,
                    "from": old.get("version_id"),
                    "to": new.get("version_id"),
                    "from_created_on": old.get("created_on"),
                    "to_created_on": new.get("created_on"),
                }
            )
        old_bindings = old.get("bindings") if isinstance(old.get("bindings"), dict) else {}
        new_bindings = new.get("bindings") if isinstance(new.get("bindings"), dict) else {}
        for kind in ("secrets", "d1", "r2", "service", "durable_object", "kv"):
            old_ids = {
                _binding_identity(kind, row)
                for row in old_bindings.get(kind, [])
                if isinstance(row, dict)
            }
            new_ids = {
                _binding_identity(kind, row)
                for row in new_bindings.get(kind, [])
                if isinstance(row, dict)
            }
            added = sorted(new_ids - old_ids)
            removed = sorted(old_ids - new_ids)
            if added or removed:
                report["workers"]["binding_changed"].append(
                    {"worker": name, "kind": kind, "added": added, "removed": removed}
                )

    old_d1 = {row.get("name"): row for row in previous.get("d1", []) if isinstance(row, dict) and row.get("name")}
    new_d1 = {row.get("name"): row for row in current.get("d1", []) if isinstance(row, dict) and row.get("name")}
    report["d1"]["missing"] = sorted(set(old_d1) - set(new_d1))
    report["d1"]["added"] = sorted(set(new_d1) - set(old_d1))
    for name in sorted(set(old_d1) & set(new_d1)):
        old = old_d1[name]
        new = new_d1[name]
        changed = {
            field: {"from": old.get(field), "to": new.get(field)}
            for field in ("uuid", "version", "num_tables", "file_size")
            if old.get(field) != new.get(field)
        }
        if changed:
            report["d1"]["changed"].append({"database": name, "fields": changed})

    old_r2 = {row.get("name") for row in previous.get("r2", []) if isinstance(row, dict) and row.get("name")}
    new_r2 = {row.get("name") for row in current.get("r2", []) if isinstance(row, dict) and row.get("name")}
    report["r2"]["missing"] = sorted(old_r2 - new_r2)
    report["r2"]["added"] = sorted(new_r2 - old_r2)

    report["ok"] = not any(
        report["workers"][key] for key in ("missing", "version_changed", "binding_changed")
    ) and not any(report["d1"][key] for key in ("missing", "added", "changed")) and not any(
        report["r2"][key] for key in ("missing", "added")
    )
    return report


def _capture_options(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "wrangler": args.wrangler,
        "account_id": args.account_id,
        "timeout": args.timeout,
    }


def _command_capture(args: argparse.Namespace) -> int:
    try:
        snapshot = capture_snapshot(args.workers, **_capture_options(args))
    except SnapshotError as error:
        print(f"CAPTURE_FAILED reason={error}", file=sys.stderr)
        return 2
    destination = Path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"CAPTURE_OK workers={len(snapshot['workers'])} d1={len(snapshot['d1'])} "
        f"r2={len(snapshot['r2'])} out={destination}"
    )
    return 0


def _command_verify(args: argparse.Namespace) -> int:
    try:
        previous = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"VERIFY_FAILED reason=snapshot_unreadable", file=sys.stderr)
        return 2
    if not isinstance(previous, dict) or previous.get("kind") != SNAPSHOT_KIND:
        print("VERIFY_FAILED reason=snapshot_kind_mismatch", file=sys.stderr)
        return 2
    workers = [
        row.get("name") for row in previous.get("workers", []) if isinstance(row, dict) and row.get("name")
    ]
    try:
        current = capture_snapshot(workers, **_capture_options(args))
    except SnapshotError as error:
        print(f"VERIFY_FAILED reason={error}", file=sys.stderr)
        return 2
    report = compare_snapshots(previous, current)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subparsers = parser.add_subparsers(dest="command", required=True)

    def common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--wrangler", default=os.environ.get("WRANGLER", "wrangler"))
        sub.add_argument("--account-id", default=os.environ.get("CLOUDFLARE_ACCOUNT_ID"))
        sub.add_argument("--timeout", type=float, default=120.0)

    capture = subparsers.add_parser("capture", help="write a private read-only asset snapshot")
    capture.add_argument("--out", required=True)
    capture.add_argument("--worker", action="append", required=True, dest="workers")
    common(capture)
    capture.set_defaults(handler=_command_capture)

    verify = subparsers.add_parser("verify", help="compare the live surface with a stored snapshot")
    verify.add_argument("--snapshot", required=True)
    common(verify)
    verify.set_defaults(handler=_command_verify)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
