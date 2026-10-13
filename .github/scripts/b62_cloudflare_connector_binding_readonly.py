#!/usr/bin/env python3
"""#4139 CENTRAL: actual deployed Cloudflare Worker private binding inventory.

Cloudflare API GET requests only; NO deploy, model, D1, POST or mutation.
Never render bearer token, account ID, complete settings response, internal
customer secrets, or unknown binding values. Existing public B62 chat rollout
is independent; a missing Connector binding means Connector HOLDS, not that
already-running Chat should be disabled.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

API = "https://api.cloudflare.com/client/v4"
HOST = "padiem-chat"
REQUIRED = (
    "IDENTITY_AUTHORITY_SERVICE",
    "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE",
)
_BINDING_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,79}\Z")
_WORKER_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\Z")
VERSION = "padiem.connector-live-worker-bindings.readonly.v1"


@dataclass(frozen=True)
class BindingEvidence:
    name: str
    status: str
    target: str | None = None

    def safe(self) -> dict[str, str]:
        # Only Cloudflare worker script names are printed, never binding values.
        result = {"binding": self.name, "status": self.status}
        if self.target is not None and _WORKER_NAME.fullmatch(self.target):
            result["target_worker"] = self.target
        return result


def parse_deployed_settings(payload: object) -> dict[str, str | None]:
    """Exact service binding metadata only; ignore all nonservice/secret data."""
    if type(payload) is not dict or payload.get("success") is not True:
        raise ValueError("Worker settings response invalid")
    result = payload.get("result")
    if type(result) is not dict or type(result.get("bindings")) is not list:
        raise ValueError("Worker bindings unavailable")
    found: dict[str, str | None] = {}
    seen: set[str] = set()
    for row in result["bindings"]:
        if type(row) is not dict:
            continue
        name = row.get("name")
        if name not in REQUIRED:
            continue
        if name in seen:
            raise ValueError("Duplicate canonical Connector binding")
        seen.add(name)
        if row.get("type") != "service":
            found[name] = None
            continue
        target = row.get("service")
        found[name] = (
            target if type(target) is str and _WORKER_NAME.fullmatch(target)
            else None
        )
    return found


def get_json(
    url: str, *,
    token: str, transport: Callable[..., Any] = urlopen,
) -> tuple[int, object]:
    if not url.startswith(API + "/") or not token:
        raise ValueError("Unapproved Cloudflare audit input")
    request = Request(
        url, method="GET",
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
            "User-Agent": "padiem-central-connector-readonly/1",
        },
    )
    try:
        with transport(request, timeout=15) as response:
            # Never echo raw response. Bound one account settings response.
            raw = response.read(262144)
            if len(raw) >= 262144:
                raise ValueError("Cloudflare settings response too large")
            return response.status, json.loads(raw)
    except HTTPError as exc:
        return exc.code, {}
    except (URLError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Cloudflare metadata GET could not be verified") from exc


def inspect_deployed_gateway_bindings(
    *, account_id: str, token: str,
    requester: Callable[[str], tuple[int, object]],
) -> tuple[BindingEvidence, ...]:
    """Read installed Chat settings + optional private target settings.

    Target GET only if the settings document explicitly declares a canonical
    service binding. The mere existence of a script is not authorization to
    call Broker APIs, and a 403 / 404 is NOT converted into a success.
    """
    if not account_id or not token:
        raise ValueError("Cloudflare audit credentials unavailable")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{8,64}", account_id):
        raise ValueError("Cloudflare account identifier invalid")
    base = f"{API}/accounts/{quote(account_id, safe='')}/workers/scripts/"
    status, data = requester(base + HOST + "/settings")
    if status != 200:
        raise ValueError("Deployed PADIEM Chat settings not readable")
    names = parse_deployed_settings(data)
    evidence = []
    for key in REQUIRED:
        if key not in names:
            evidence.append(BindingEvidence(key, "absent"))
            continue
        target = names[key]
        if target is None:
            evidence.append(BindingEvidence(key, "invalid_type_or_target"))
            continue
        target_code, target_metadata = requester(base + quote(target, safe="") + "/settings")
        if (target_code == 200 and type(target_metadata) is dict
            and target_metadata.get("success") is True):
            evidence.append(BindingEvidence(key, "target_settings_readable", target))
        elif target_code in (403, 404):
            evidence.append(BindingEvidence(key, "target_not_verified", target))
        else:
            evidence.append(BindingEvidence(key, "target_settings_unavailable", target))
    return tuple(evidence)


def main() -> int:
    token = os.getenv("CLOUDFLARE_API_TOKEN", "")
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
    try:
        if not token or not account_id:
            raise ValueError("Cloudflare audit credentials unavailable")
        def requester(url: str) -> tuple[int, object]:
            return get_json(url, token=token)
        evidence = inspect_deployed_gateway_bindings(
            account_id=account_id, token=token, requester=requester,
        )
    except ValueError:
        print("CONNECTOR_LIVE_BINDING_AUDIT=UNAVAILABLE")
        print("PRODUCTION_MUTATION=0")
        return 1
    print(json.dumps({
        "version": VERSION,
        "worker": HOST,
        "binding_evidence": [item.safe() for item in evidence],
        "connector_live_authorized": False,
        "tls_edge_attested": False,
        "deployed_websocket_upgrade_proven": False,
        "production_mutation": 0,
    }, ensure_ascii=True, sort_keys=True))
    print("CONNECTOR_LIVE_BINDING_AUDIT=PASS_READONLY")
    print("PRODUCTION_MUTATION=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
