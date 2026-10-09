"""#3782 read-only Browser P01 binding graph preflight; NOT Production approval.

This tool inspects supplied Cloudflare Worker TOML declarations without making
Cloudflare API calls, creating D1 databases, applying SQL, or starting Browser Use.
A PASS means source declarations are structurally consistent ONLY. It does
not attest provisioned remote D1, migrations, secrets, first-party login/P01,
service identity, authorized release, or Windows browser-control activation.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import tomllib

ROOT = Path(__file__).resolve().parents[1]
CHAT_WRANGLER = ROOT / "apps/padiem-chat/wrangler.toml"
ENGINE_WRANGLER = ROOT / "apps/padiem-ai-engine/wrangler.toml"

# #3782: proposed exact browser-owner binding name in BOTH B54 and Engine.
# This is a commissioning contract, not a deployed or provisioned binding.
OWNER_D1 = "BROWSER_CONTROL_OWNER_P01_D1"
CHAT_DB = "PADIEM_CHAT_DB"
ENGINE_DB = "ENGINE_CONTINUATION"
CHAT_ENGINE_SERVICE = "P01_ENGINE_SERVICE"
CHAT_IDENTITY_SERVICE = "IDENTITY_AUTHORITY_SERVICE"
ENGINE_CP_IDENTITY_SERVICE = "CONTROL_PLANE_IDENTITY"
EXPECTED_ENGINE_SERVICE = "padiem-ai-engine"
EXPECTED_CP_IDENTITY_SERVICE = "padiem-control-plane-identity"


@dataclass(frozen=True)
class BrowserP01SourceBindingGate:
    blockers: tuple[str, ...]
    def summary(self) -> dict[str, Any]:
        return {
            "scope": "source_declarations_only",
            "outcome": "BLOCKED" if self.blockers else "SOURCE_GRAPH_VALID_NOT_AUTHORIZED",
            "blockers": list(self.blockers),
            "remote_database_provision_verified": False,
            "owner_schema_applied_verified": False,
            "real_user_p01_verified": False,
            "production_activation_authorized": False,
        }


def _binding_index(doc: Mapping[str, Any], section: str) -> tuple[dict[str, Mapping[str, Any]], bool]:
    raw = doc.get(section, [])
    if type(raw) is not list:
        return {}, True
    found: dict[str, Mapping[str, Any]] = {}
    malformed = False
    for entry in raw:
        if type(entry) is not dict:
            malformed = True
            continue
        binding = entry.get("binding")
        if type(binding) is not str or not binding or binding in found:
            malformed = True
            continue
        found[binding] = entry
    return found, malformed


def _d1_id(items: Mapping[str, Mapping[str, Any]], key: str) -> str | None:
    candidate = items.get(key)
    if candidate is None:
        return None
    db_id = candidate.get("database_id")
    if type(db_id) is not str or not db_id.strip():
        return None
    try:
        normalized = str(UUID(db_id.strip()))
    except (ValueError, AttributeError):
        return None
    return normalized if normalized == db_id.strip().lower() else None


def _check_service(
    blockers: list[str], items: Mapping[str, Mapping[str, Any]],
    binding: str, expected: str, reason_prefix: str,
) -> None:
    item = items.get(binding)
    if item is None:
        blockers.append(f"{reason_prefix}_MISSING")
    elif item.get("service") != expected:
        blockers.append(f"{reason_prefix}_TARGET_MISMATCH")


def evaluate(
    *, chat: Mapping[str, Any], engine: Mapping[str, Any],
) -> BrowserP01SourceBindingGate:
    """Check explicit SOURCE declarations, never values of Worker secrets."""
    problems: list[str] = []
    chat_d1, chat_bad_d1 = _binding_index(chat, "d1_databases")
    engine_d1, engine_bad_d1 = _binding_index(engine, "d1_databases")
    chat_services, chat_bad_service = _binding_index(chat, "services")
    engine_services, engine_bad_service = _binding_index(engine, "services")
    if chat_bad_d1 or engine_bad_d1:
        problems.append("D1_BINDING_DECLARATIONS_INVALID")
    if chat_bad_service or engine_bad_service:
        problems.append("SERVICE_BINDING_DECLARATIONS_INVALID")

    _check_service(
        problems, chat_services, CHAT_ENGINE_SERVICE,
        EXPECTED_ENGINE_SERVICE, "B54_EXISTING_P01_ENGINE_SERVICE",
    )
    _check_service(
        problems, chat_services, CHAT_IDENTITY_SERVICE,
        EXPECTED_CP_IDENTITY_SERVICE, "B54_CURRENT_USER_IDENTITY_SERVICE",
    )
    _check_service(
        problems, engine_services, ENGINE_CP_IDENTITY_SERVICE,
        EXPECTED_CP_IDENTITY_SERVICE, "ENGINE_CURRENT_USER_IDENTITY_SERVICE",
    )

    chat_primary = _d1_id(chat_d1, CHAT_DB)
    engine_primary = _d1_id(engine_d1, ENGINE_DB)
    chat_owner = _d1_id(chat_d1, OWNER_D1)
    engine_owner = _d1_id(engine_d1, OWNER_D1)

    for db_id, reason in (
        (chat_primary, "B54_PRIMARY_D1_MISSING_OR_NO_ID"),
        (engine_primary, "ENGINE_ORIGINAL_CONTINUATION_D1_MISSING_OR_NO_ID"),
        (chat_owner, "B54_INDEPENDENT_OWNER_D1_MISSING_OR_NO_ID"),
        (engine_owner, "ENGINE_INDEPENDENT_OWNER_D1_MISSING_OR_NO_ID"),
    ):
        if db_id is None:
            problems.append(reason)

    if chat_owner is not None and engine_owner is not None:
        if chat_owner != engine_owner:
            problems.append("OWNER_D1_CROSS_SERVICE_DATABASE_ID_MISMATCH")
        if chat_owner in (chat_primary, engine_primary):
            problems.append("OWNER_D1_ALIASES_PRIMARY_OR_ORIGINAL_ENGINE")
    if engine_primary is not None and chat_primary is not None and engine_primary == chat_primary:
        problems.append("ENGINE_D1_ALIASES_CHAT_PRIMARY")

    # The actual owner schema is deliberately absent from Engine migrations:
    # this gate cannot prove remote schema application from a contract file.
    return BrowserP01SourceBindingGate(tuple(sorted(set(problems))))


def inspect_source_config(
    chat_path: Path = CHAT_WRANGLER,
    engine_path: Path = ENGINE_WRANGLER,
) -> BrowserP01SourceBindingGate:
    try:
        chat = tomllib.loads(chat_path.read_text(encoding="utf-8"))
        engine = tomllib.loads(engine_path.read_text(encoding="utf-8"))
        if type(chat) is not dict or type(engine) is not dict:
            raise ValueError("bad Worker source config")
    except (OSError, UnicodeError, ValueError, tomllib.TOMLDecodeError):
        return BrowserP01SourceBindingGate(("SOURCE_CONFIG_UNAVAILABLE_OR_INVALID",))
    return evaluate(chat=chat, engine=engine)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only #3782 B54/Engine Browser P01 binding graph gate.",
    )
    parser.add_argument("--chat-config", type=Path, default=CHAT_WRANGLER)
    parser.add_argument("--engine-config", type=Path, default=ENGINE_WRANGLER)
    args = parser.parse_args(argv)
    result = inspect_source_config(args.chat_config, args.engine_config)
    print(json.dumps(result.summary(), sort_keys=True))
    return 2 if result.blockers else 0


if __name__ == "__main__":
    sys.exit(main())
