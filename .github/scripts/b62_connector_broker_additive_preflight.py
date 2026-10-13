#!/usr/bin/env python3
"""#4139 read-only, secret-redacted B62 production binding preservation proof.

Read current production settings once via Cloudflare GET, then use the EXISTING
B62 production config builder to construct two IN-MEMORY configs:
  A) baseline reconstructed only from live settings,
  B) EXACTLY A plus LOCAL_AGENT_BROKER_AUTHORITY_SERVICE → existing Broker state.
Compare all parsed TOML sections and key values in memory; only output counts
and a bounded status. Never emit config text, secrets, vars, D1 IDs, R2 names,
account IDs or API response. Do not write a candidate to disk or deploy.

Strictly negative release boundary: a structurally safe candidate alone does
not authorize a B62 Worker deploy or PADIEM Connector gateway activation.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys
import tomllib
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from b62_cloudflare_connector_binding_readonly import API, HOST, get_json
from b62_cloudflare_production_deploy_config import (
    ProductionConfigError,
    CONNECTOR_BROKER_BINDING,
    CONNECTOR_BROKER_TARGET,
    build_production_config,
    parse_live_bindings,
    verify_mutation_zero,
)

VERSION = "padiem.connector-broker-additive-preservation.readonly.v1"
PUBLIC_ORIGIN = "https://chat.padiem.net"
REPO_CONFIG = _HERE.parents[1] / "apps" / "padiem-chat" / "wrangler.toml"


def candidate_preservation(
    live_settings: object, repo_config: Path = REPO_CONFIG,
) -> dict[str, object]:
    """Compare base and one-addition outputs, fail closed on unsupported data.

    Assumes existing B62 production generator is the only source of the
    release config. Never use the source mock wrangler.toml as live authority.
    """
    live = parse_live_bindings(live_settings)
    baseline = build_production_config(
        live, repo_config, PUBLIC_ORIGIN,
    )
    proposed = build_production_config(
        live, repo_config, PUBLIC_ORIGIN,
        attach_connector_broker_service=True,
    )
    verify_mutation_zero(baseline, live)
    verify_mutation_zero(proposed, live)
    old = tomllib.loads(baseline)
    new = tomllib.loads(proposed)
    prior_services = old.get("services", [])
    candidate_services = new.get("services", [])
    if type(prior_services) is not list or type(candidate_services) is not list:
        raise ProductionConfigError("Generated service declarations invalid")
    new_copy = dict(new)
    new_copy["services"] = prior_services
    if new_copy != old:
        raise ProductionConfigError("Generated candidate changed non-Broker config")
    expected = {
        "binding": CONNECTOR_BROKER_BINDING,
        "service": CONNECTOR_BROKER_TARGET,
    }
    if candidate_services != prior_services + [expected]:
        raise ProductionConfigError("Generated candidate changed other services")
    binding_types = {
        kind: len(live[kind])
        for kind in ("assets", "services", "d1", "r2", "vars", "secret_names",
                     "secrets_store")
    }
    # The Cloudflare Worker platform preserves existing secret_text bindings
    # separately. Secret contents cannot be read back or fully proven here.
    return {
        "status": "ADDITIVE_CANDIDATE_STRUCTURAL_PASS",
        "preserved_existing_bindings_count": sum(binding_types.values()) +
            int(live["version_metadata"] is not None) +
            int(live["browser"] is not None),
        "preserved_existing_binding_types_count": binding_types,
        "additional_service_bindings_count": 1,
        "target_worker": CONNECTOR_BROKER_TARGET,
        "existing_secret_values_read": False,
        "secret_survival_requires_deployment_readback": True,
        "deploy_authorized": False,
        "public_gateway_authorized": False,
        "production_mutation": 0,
    }


def main() -> int:
    token = os.getenv("CLOUDFLARE_API_TOKEN", "")
    account = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
    if not token or not account:
        print("CONNECTOR_BROKER_PRESERVATION=UNAVAILABLE")
        print("PRODUCTION_MUTATION=0")
        return 1
    try:
        import re
        if not re.fullmatch(r"[a-zA-Z0-9_-]{8,64}", account):
            raise ValueError("Cloudflare account identifier invalid")
        url = f"{API}/accounts/{account}/workers/scripts/{HOST}/settings"
        status, payload = get_json(url, token=token)
        if status != 200:
            raise ValueError("Cloudflare live settings unavailable")
        projection = candidate_preservation(payload)
    except (ValueError, ProductionConfigError, OSError, TypeError):
        # HOLD is a valid safety outcome, NOT a permission to deploy.
        print(json.dumps({
            "version": VERSION,
            "candidate_status": "HOLD",
            "existing_settings_preservation_proven": False,
            "deploy_authorized": False,
            "public_gateway_authorized": False,
            "production_mutation": 0,
        }, sort_keys=True))
        print("CONNECTOR_BROKER_PRESERVATION=HOLD")
        print("PRODUCTION_MUTATION=0")
        return 0
    print(json.dumps({
        "version": VERSION,
        "candidate_status": projection["status"],
        "evidence": projection,
    }, sort_keys=True))
    print("CONNECTOR_BROKER_PRESERVATION=PASS_READONLY")
    print("PRODUCTION_MUTATION=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
