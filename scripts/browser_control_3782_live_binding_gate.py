"""#3782 READ-ONLY actual Cloudflare deployed Worker binding inspection.

Read-only Wrangler CLI: deployments list + versions view. No config mutations,
D1 queries, secrets reads, deploy, live browser control, or HTTP user actions.
The tool passes source-verified structure through the ONE canonical evaluator
in browser_control_3782_source_binding_gate.py; do not duplicate standards.

CLI output contains ONLY bounded reason codes, not Worker plain_text values,
database IDs, tokens, session information or raw Wrangler error messages.
Even when all version bindings match, this NEVER approves live P01 activation.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from typing import Any

from browser_control_3782_source_binding_gate import evaluate

WORKERS = ("padiem-chat", "padiem-ai-engine")
TIMEOUT_SECONDS = 45


def _wrangler_read_only(*args: str) -> Any:
    # Explicit account required: Wrangler's interactive fallback may choose
    # an unrelated account; never ship a hardcoded account identifier.
    if not os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip():
        raise ValueError("CLOUDFLARE_ACCOUNT_UNSELECTED")
    executable = shutil.which("wrangler.cmd" if os.name == "nt" else "wrangler")
    if not executable:
        raise ValueError("LIVE_CLOUDFLARE_READ_UNAVAILABLE")
    try:
        result = subprocess.run(
            [executable, *args, "--json"], capture_output=True,
            text=True, check=False, timeout=TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("LIVE_CLOUDFLARE_READ_UNAVAILABLE") from exc
    if result.returncode != 0:
        # Never include stdout/stderr which might expose secrets or account IDs.
        raise ValueError("LIVE_CLOUDFLARE_READ_UNAVAILABLE")
    try:
        return json.loads(result.stdout)
    except (TypeError, ValueError) as exc:
        raise ValueError("LIVE_CLOUDFLARE_METADATA_INVALID") from exc


def _active_version_id(deployments: Any) -> str:
    """Select newest fully active deployment; never an uploaded draft version."""
    if type(deployments) is not list or not deployments:
        raise ValueError("ACTIVE_DEPLOYMENT_NOT_VERIFIED")
    dated: list[tuple[str, dict[str, Any]]] = []
    for row in deployments:
        if (
            type(row) is not dict
            or type(row.get("created_on")) is not str
            or type(row.get("versions")) is not list
        ):
            raise ValueError("ACTIVE_DEPLOYMENT_NOT_VERIFIED")
        dated.append((row["created_on"], row))
    newest = max(dated, key=lambda x: x[0])[1]
    versions = newest["versions"]
    if len(versions) != 1 or type(versions[0]) is not dict:
        raise ValueError("ACTIVE_DEPLOYMENT_NOT_VERIFIED")
    selected = versions[0]
    if selected.get("percentage") != 100:
        raise ValueError("ACTIVE_DEPLOYMENT_NOT_VERIFIED")
    v = selected.get("version_id")
    if type(v) is not str or len(v) != 36:
        raise ValueError("ACTIVE_DEPLOYMENT_NOT_VERIFIED")
    return v


def _version_binding_snapshot(version: Any) -> dict[str, Any]:
    if type(version) is not dict:
        raise ValueError("LIVE_CLOUDFLARE_METADATA_INVALID")
    resources = version.get("resources")
    if type(resources) is not dict or type(resources.get("bindings")) is not list:
        raise ValueError("LIVE_CLOUDFLARE_METADATA_INVALID")
    d1, services = [], []
    seen: set[tuple[str, str]] = set()
    # Whitelist only the fields needed for the canonical graph evaluation.
    for binding in resources["bindings"]:
        if type(binding) is not dict:
            raise ValueError("LIVE_CLOUDFLARE_METADATA_INVALID")
        kind, name = binding.get("type"), binding.get("name")
        if type(kind) is not str or type(name) is not str:
            raise ValueError("LIVE_CLOUDFLARE_METADATA_INVALID")
        if (kind, name) in seen:
            raise ValueError("LIVE_CLOUDFLARE_METADATA_INVALID")
        seen.add((kind, name))
        if kind == "d1":
            d1.append({"binding": name, "database_id": binding.get("database_id")})
        elif kind == "service":
            services.append({"binding": name, "service": binding.get("service")})
        # Deliberately ignore every plain_text, secret_text, KV, and token.
    return {"d1_databases": d1, "services": services}


def evaluate_live_versions(chat_version: Any, engine_version: Any) -> dict[str, Any]:
    """Call the existing single source-of-truth binding evaluator."""
    chat = _version_binding_snapshot(chat_version)
    engine = _version_binding_snapshot(engine_version)
    common = evaluate(chat=chat, engine=engine)
    chat_bindings = chat_version["resources"]["bindings"]
    by_name = {b.get("name"): b.get("type") for b in chat_bindings}
    extra = []
    if by_name.get("P01_ENGINE_CREDENTIAL") != "secret_text":
        extra.append("B54_P01_CALLER_CREDENTIAL_SECRET_MISSING")
    if by_name.get("P01_ENGINE_CALLER_ID") not in ("secret_text", "plain_text"):
        extra.append("B54_P01_CALLER_ID_MISSING")
    blockers = sorted(set(common.blockers).union(extra))
    return {
        "scope": "authenticated_cloudflare_worker_deployments_readonly",
        "outcome": "BLOCKED" if blockers else "LIVE_BINDING_GRAPH_VALID_NOT_AUTHORIZED",
        "blockers": blockers,
        "real_deployed_worker_versions_read": True,
        "remote_owner_d1_provision_verified": False,
        "owner_schema_applied_verified": False,
        "human_p01_verified": False,
        "production_activation_authorized": False,
    }


def inspect_live() -> dict[str, Any]:
    try:
        results = []
        for name in WORKERS:
            deployments = _wrangler_read_only(
                "deployments", "list", "--name", name,
            )
            version_id = _active_version_id(deployments)
            version = _wrangler_read_only(
                "versions", "view", version_id, "--name", name,
            )
            if version.get("id") != version_id:
                raise ValueError("LIVE_CLOUDFLARE_METADATA_INVALID")
            results.append(version)
        return evaluate_live_versions(*results)
    except ValueError as exc:
        code = str(exc)
        permitted = {
            "CLOUDFLARE_ACCOUNT_UNSELECTED", "LIVE_CLOUDFLARE_READ_UNAVAILABLE",
            "LIVE_CLOUDFLARE_METADATA_INVALID", "ACTIVE_DEPLOYMENT_NOT_VERIFIED",
        }
        return {
            "scope": "authenticated_cloudflare_worker_deployments_readonly",
            "outcome": "BLOCKED",
            "blockers": [code if code in permitted else "LIVE_CLOUDFLARE_READ_UNAVAILABLE"],
            "real_deployed_worker_versions_read": False,
            "remote_owner_d1_provision_verified": False,
            "owner_schema_applied_verified": False,
            "human_p01_verified": False,
            "production_activation_authorized": False,
        }


def main() -> int:
    assessment = inspect_live()
    print(json.dumps(assessment, sort_keys=True))
    return 2 if assessment["outcome"] == "BLOCKED" else 0


if __name__ == "__main__":
    sys.exit(main())
