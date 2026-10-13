"""Read-only live #4139 Connector Worker inventory via existing Wrangler OAuth.

Never invokes deploy/config updates, never displays auth tokens, raw binding
values, account IDs, cookie state, or exception text from a provider.
The outdated CLOUDFLARE_API_TOKEN can shadow the valid Wrangler OAuth login.
Remove it ONLY in the command child, leaving the Windows environment intact.

Usage (Windows, from any directory):
    python apps/padiem-chat/scripts/connector_cloudflare_runtime_readiness.py

Exit 0: all publicly verifiable CONNECTOR runtime wiring exists (NOT proof
        of PC consent or authenticated pairing).
Exit 2: missing/unverified runtime prerequisites; safe to repeat.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
CHAT = ROOT / "apps" / "padiem-chat"
CONTROL = ROOT / "packages" / "padiem-control-plane"

_TARGETS: tuple[tuple[str, Path], ...] = (
    ("chat", CHAT / "wrangler.toml"),
    ("identity", CONTROL / "wrangler.identity-authority.jsonc"),
    ("broker", CONTROL / "wrangler.local-agent-broker.jsonc"),
    ("acceptance_chat", CHAT / "wrangler.connector-acceptance-4139.toml"),
    ("acceptance_identity", CONTROL / "wrangler.identity-authority-acceptance-4139.jsonc"),
    ("acceptance_broker", CONTROL / "wrangler.local-agent-broker-acceptance-4139.jsonc"),
)
_PRIVATE_CHAT_BINDINGS = (
    "IDENTITY_AUTHORITY_SERVICE",
    "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE",
)
_ACCEPTANCE_FLAGS = (
    "PADIEM_CONNECTOR_OWNER_ENROLLMENT_ENABLED",
    "PADIEM_CONNECTOR_GATEWAY_WSS_ENABLED",
    "PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE",
)
# The per-PC staging overlay is gitignored and holds this machine's dedicated
# D1 UUID. Only bounded booleans are ever read back from it; the identifier
# itself, and every other provider answer, stay on disk.
OWNER_OVERLAY = CHAT / "wrangler.connector-acceptance-4139.local.toml"


def _run_readonly(*, wrangler: str, config: Path, args: list[str]) -> Any:
    # Do not use the Windows environment's stale Bearer token. The user's
    # authenticated Wrangler OAuth profile is selected without changing it.
    env = os.environ.copy()
    env.pop("CLOUDFLARE_API_TOKEN", None)
    env.pop("CLOUDFLARE_API_KEY", None)
    env.pop("CLOUDFLARE_EMAIL", None)
    try:
        out = subprocess.run(
            [wrangler, *args, "--config", str(config)],
            cwd=config.parent,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
            check=False,
        )
        if out.returncode != 0:
            return None
        data = out.stdout.strip()
        # Wrangler should emit JSON with --json; never echo an unexpected
        # response, even if it contains a provider's error or secret.
        if not data.startswith(("[", "{")):
            return None
        return json.loads(data)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _latest_live_version(wrangler: str, config: Path) -> dict[str, Any]:
    deployments = _run_readonly(
        wrangler=wrangler, config=config,
        args=["deployments", "list", "--json"],
    )
    if not isinstance(deployments, list):
        return {"readable": False, "deployed": None}
    if not deployments:
        return {"readable": True, "deployed": False}
    good = [
        item for item in deployments
        if isinstance(item, dict)
        and isinstance(item.get("created_on"), str)
        and isinstance(item.get("versions"), list)
    ]
    if not good:
        return {"readable": False, "deployed": None}
    latest = max(good, key=lambda row: row["created_on"])
    versions = latest["versions"]
    active = [
        v for v in versions if isinstance(v, dict)
        and v.get("percentage") == 100
        and isinstance(v.get("version_id"), str)
    ]
    if len(active) != 1:
        return {"readable": True, "deployed": True,
                "last_deployed_utc": latest["created_on"],
                "active_version_readable": False}
    view = _run_readonly(
        wrangler=wrangler, config=config,
        args=["versions", "view", active[0]["version_id"], "--json"],
    )
    result: dict[str, Any] = {
        "readable": True,
        "deployed": True,
        "last_deployed_utc": latest["created_on"],
        "active_version_readable": isinstance(view, dict),
    }
    if not isinstance(view, dict):
        return result
    resources = view.get("resources")
    bindings = resources.get("bindings") if isinstance(resources, dict) else None
    if not isinstance(bindings, list):
        result["active_version_readable"] = False
        return result
    # Only names/types. Never serialize values, environment variables,
    # API responses, protected secrets, account identifiers, or URLs.
    safe = {
        x.get("name"): x.get("type")
        for x in bindings
        if isinstance(x, dict)
        and isinstance(x.get("name"), str)
        and isinstance(x.get("type"), str)
    }
    if config == CHAT / "wrangler.toml":
        result["connector_private_bindings"] = {
            name: safe.get(name) == "service" for name in _PRIVATE_CHAT_BINDINGS
        }
        result["connector_runtime_flags_present"] = {
            name: name in safe for name in _ACCEPTANCE_FLAGS
        }
    elif config.name == "wrangler.connector-acceptance-4139.toml":
        # Bounded names/types from the actual deployed private Worker only.
        result["acceptance_private_services"] = {
            name: safe.get(name) == "service" for name in _PRIVATE_CHAT_BINDINGS
        }
        result["acceptance_d1_bound"] = safe.get("PADIEM_CHAT_DB") == "d1"
        result["acceptance_session_secret_bound"] = (
            safe.get("PADIEM_CHAT_SESSION_SECRET") == "secret_text"
        )
        result["acceptance_password_auth_setting_present"] = (
            safe.get("PADIEM_CHAT_AUTH_MODE") == "plain_text"
        )
    elif config.name in (
        "wrangler.identity-authority-acceptance-4139.jsonc",
        "wrangler.local-agent-broker-acceptance-4139.jsonc",
    ):
        identity = config.name.startswith("wrangler.identity")
        state = "CONTROL_PLANE_IDENTITY" if identity else "LOCAL_AGENT_BROKER_STATE"
        secrets = (
            ("CONTROL_PLANE_IDENTITY_LOOKUP_KEY", "GOOGLE_CONNECT_TICKET_KEY")
            if identity else ("LOCAL_AGENT_BROKER_PEPPER",)
        )
        result["acceptance_canonical_durable_state_bound"] = state in safe
        result["acceptance_secrets_bound"] = all(
            safe.get(name) == "secret_text" for name in secrets
        )
    else:
        result["canonical_state_binding_present"] = (
            "LOCAL_AGENT_BROKER_STATE" in safe
            if config.name == "wrangler.local-agent-broker.jsonc"
            else "CONTROL_PLANE_IDENTITY" in safe
            if config.name == "wrangler.identity-authority.jsonc"
            else None
        )
    return result


def _owner_local_overlay() -> dict[str, Any]:
    """Bounded, read-only facts about the gitignored per-PC staging overlay."""
    if not OWNER_OVERLAY.exists():
        return {"present": False}
    try:
        with OWNER_OVERLAY.open("rb") as src:
            config = tomllib.load(src)
    except (OSError, tomllib.TOMLDecodeError):
        return {"present": True, "readable": False}
    routes = config.get("route") or config.get("routes") or []
    return {
        "present": True,
        "readable": True,
        "password_auth_selected":
            config.get("vars", {}).get("PADIEM_CHAT_AUTH_MODE") == "password",
        "exactly_one_d1_bound": len(config.get("d1_databases") or []) == 1,
        # A published HTTPS route would need its own explicit authorization.
        "public_route_published": bool(routes),
    }


def inventory() -> dict[str, Any]:
    wrangler = shutil.which("wrangler")
    if wrangler is None:
        return {"readiness": "blocked", "reason": "wrangler_unavailable",
                "changes_made": False}
    findings = {
        name: _latest_live_version(wrangler, config)
        for name, config in _TARGETS
    }
    with (CHAT / "wrangler.connector-acceptance-4139.toml").open("rb") as src:
        isolated = tomllib.load(src)
    # The source-only acceptance profile intentionally provides NO public
    # route nor login/DB/OAuth, even though its private RPC wiring compiles.
    acceptance_login_ready = (
        isolated.get("vars", {}).get("PADIEM_CHAT_AUTH_MODE") in
        {"google", "password", "hybrid"}
        and bool(isolated.get("d1_databases"))
        and bool(isolated.get("vars", {}).get("PADIEM_CHAT_PUBLIC_BASE_URL"))
        and bool(isolated.get("routes"))
    )
    chat = findings["chat"]
    broker = findings["broker"]
    identity = findings["identity"]
    bindings = chat.get("connector_private_bindings", {})
    flags = chat.get("connector_runtime_flags_present", {})
    live_ready = (
        all(x.get("deployed") is True and x.get("active_version_readable") is True
            for x in (chat, broker, identity))
        and all(bindings.get(x) is True for x in _PRIVATE_CHAT_BINDINGS)
        and all(flags.get(x) is True for x in _ACCEPTANCE_FLAGS)
    )
    blockers: list[str] = []
    if not bindings.get("LOCAL_AGENT_BROKER_AUTHORITY_SERVICE"):
        blockers.append("chat_broker_service_binding_not_confirmed")
    if not all(flags.get(x) for x in _ACCEPTANCE_FLAGS):
        blockers.append("chat_connector_operator_release_not_enabled")
    acceptance_chat = findings["acceptance_chat"]
    acceptance_identity = findings["acceptance_identity"]
    acceptance_broker = findings["acceptance_broker"]
    owner_overlay = _owner_local_overlay()
    owner_auth_prepared = (
        owner_overlay.get("readable") is True
        and owner_overlay.get("password_auth_selected") is True
        and owner_overlay.get("exactly_one_d1_bound") is True
        and owner_overlay.get("public_route_published") is False
    )
    acceptance_private_stack_ready = (
        all(findings[x].get("deployed") is True
            and findings[x].get("active_version_readable") is True
            for x in ("acceptance_chat", "acceptance_identity", "acceptance_broker"))
        and all(acceptance_chat.get("acceptance_private_services", {}).get(x) is True
                for x in _PRIVATE_CHAT_BINDINGS)
        and acceptance_chat.get("acceptance_d1_bound") is True
        and acceptance_chat.get("acceptance_session_secret_bound") is True
        and acceptance_chat.get("acceptance_password_auth_setting_present") is True
        and acceptance_identity.get("acceptance_canonical_durable_state_bound") is True
        and acceptance_identity.get("acceptance_secrets_bound") is True
        and acceptance_broker.get("acceptance_canonical_durable_state_bound") is True
        and acceptance_broker.get("acceptance_secrets_bound") is True
        and owner_auth_prepared
    )
    if not acceptance_private_stack_ready:
        blockers.append("isolated_acceptance_runtime_bindings_not_ready")
    if owner_overlay.get("public_route_published") is True:
        blockers.append("acceptance_https_route_published_without_authorization")
    if not acceptance_login_ready:
        blockers.append("acceptance_browser_login_not_yet_proven")
    return {
        "readiness": "runtime_wired_only_not_owner_pairing_proven"
        if live_ready else "blocked",
        "checked_via": "wrangler_oauth_read_only",
        "workers": findings,
        "acceptance_browser_login_ready": acceptance_login_ready,
        "acceptance_owner_local_manifest": owner_overlay,
        "blocking_facts": blockers,
        "actual_owner_windows_pairing_proven": False,
        "changes_made": False,
    }


def main() -> int:
    try:
        report = inventory()
    except Exception:
        report = {
            "readiness": "blocked", "reason": "readonly_inventory_unavailable",
            "changes_made": False,
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if report.get("readiness") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
