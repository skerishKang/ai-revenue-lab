#!/usr/bin/env python3
"""#4139 production Identity owner-consent activation gate: Cloudflare GET ONLY.

Reads only the three explicitly allowed, nonsecret plain-text flag fields
from the canonical Identity Worker settings. Never reads, logs or prints
secrets, credentials, other vars, account IDs, Cloudflare settings JSON or
client data. A flag named like an activation gate is not sufficient evidence
of usable RPC or consent: this is an independently observed negative gate.

PADIEM Chat's existing service must remain independent: this checker does
not mutate or deploy anything and never enables the Connector.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

from b62_cloudflare_connector_binding_readonly import API, get_json

VERSION = "padiem.connector-identity-live-activation.readonly.v1"
IDENTITY = "padiem-control-plane-identity"
REQUIRED_GATES = (
    "CONTROL_PLANE_CONNECTOR_ENROLLMENT_RPC_ENABLED",
    "CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCOPE_APPROVED",
    "CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCHEMA_INSTALLED",
)
SCHEMA_INSTALL_GATE = "CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCHEMA_INSTALL_ENABLED"
ALL_GATES = (*REQUIRED_GATES, SCHEMA_INSTALL_GATE)
_ACCOUNT = re.compile(r"[A-Za-z0-9_-]{8,64}\Z")


def inspect_identity_activation(settings: object) -> dict[str, Any]:
    """Only named plain-text flags may be read; unknown representation HOLDS.

    Missing flags are default-OFF per canonical Identity `getattr(..., "")`.
    Never use generic truthiness, coercion of nonstrings or secret bindings.
    """
    if (
        type(settings) is not dict or settings.get("success") is not True
        or type(settings.get("result")) is not dict
        or type(settings["result"].get("bindings")) is not list
    ):
        raise ValueError("Identity live settings unavailable")
    flags: dict[str, bool] = {}
    seen: set[str] = set()
    for row in settings["result"]["bindings"]:
        if type(row) is not dict:
            raise ValueError("Identity binding inventory invalid")
        name = row.get("name")
        if name not in ALL_GATES:
            # Do NOT read type/text/value of any unrelated binding.
            continue
        if name in seen:
            raise ValueError("Duplicated Identity activation flag")
        seen.add(name)
        if row.get("type") != "plain_text":
            raise ValueError("Identity activation binding is not public plain text")
        value = row.get("text")
        if type(value) is not str or value not in ("true", "false", "TRUE", "FALSE"):
            raise ValueError("Identity activation flag has unreviewed encoding")
        flags[name] = value.lower() == "true"
    enabled = tuple(name for name in ALL_GATES if flags.get(name, False))
    all_required = all(flags.get(name, False) for name in REQUIRED_GATES)
    # A true flag may be an intentional staged setting, but no staging may be
    # silently interpreted as an active permission to enroll a PC.
    if all_required:
        status = "HOLD_ALL_THREE_ON"
    elif enabled:
        status = "HOLD_PARTIAL"
    else:
        status = "PASS_DEFAULT_OFF"
    return {
        "version": VERSION,
        "state": status,
        "identity_worker_settings_readable": True,
        "required_gate_count": len(REQUIRED_GATES),
        "activation_flags_explicitly_true_count": len(enabled),
        "all_required_activation_gates_true": all_required,
        "schema_install_flag_true": flags.get(SCHEMA_INSTALL_GATE, False),
        "production_connector_activation_authorized": False,
        "deployed_identity_rpc_source_parity_proven": False,
        "production_mutation": 0,
    }


def audit(*, account_id: str, token: str,
          requester: Callable[..., tuple[int, object]] = get_json) -> dict[str, Any]:
    if type(account_id) is not str or not _ACCOUNT.fullmatch(account_id):
        raise ValueError("Cloudflare account id unavailable")
    if type(token) is not str or not token:
        raise ValueError("Cloudflare GET-only token unavailable")
    url = f"{API}/accounts/{account_id}/workers/scripts/{IDENTITY}/settings"
    code, data = requester(url, token=token)
    if code != 200:
        raise ValueError("Canonical Identity Worker settings not readable")
    return inspect_identity_activation(data)


def main() -> int:
    try:
        result = audit(
            account_id=os.getenv("CLOUDFLARE_ACCOUNT_ID", ""),
            token=os.getenv("CLOUDFLARE_API_TOKEN", ""),
        )
    except (ValueError, OSError, TypeError):
        print(json.dumps({
            "version": VERSION, "state": "HOLD_UNVERIFIED",
            "production_connector_activation_authorized": False,
            "production_mutation": 0,
        }, sort_keys=True))
        print("IDENTITY_CONNECTOR_ACTIVATION_READBACK=HOLD")
        print("PRODUCTION_MUTATION=0")
        return 1
    print(json.dumps(result, sort_keys=True))
    print("IDENTITY_CONNECTOR_ACTIVATION_READBACK=" + (
        "PASS_DEFAULT_OFF" if result["state"] == "PASS_DEFAULT_OFF" else "HOLD"
    ))
    print("PRODUCTION_MUTATION=0")
    return 0 if result["state"] == "PASS_DEFAULT_OFF" else 1


if __name__ == "__main__":
    raise SystemExit(main())
