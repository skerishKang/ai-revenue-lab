#!/usr/bin/env python3
"""#3930 read-only served P01 live SSE canary readiness, no mutation.

Accepts only Wrangler current deployment status and current version view JSON.
Never emits credential values, user sessions or unknown binding values.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "p01_live_canonical_served_version",
    _HERE / "cloudflare_served_version.py",
)
assert _spec is not None and _spec.loader is not None
_served = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_served)
EXPECTED_TYPES = {
    "P01_ENGINE_SERVICE": "service",
    "P01_ENGINE_CREDENTIAL": "secret_text",
    "P01_ENGINE_CALLER_ID": "plain_text",
    "IDENTITY_AUTHORITY_SERVICE": "service",
    "PADIEM_CHAT_DB": "d1",
    "PADIEM_CHAT_SESSION_SECRET": "secret_text",
    "PADIEM_CHAT_QUOTA_SALT": "secret_text",
    "PADIEM_CLAW_P01_LIVE_CANARY_SUBJECT_ID": "secret_text",
}
SOURCE_MARKER = re.compile(r"^B62 production code ([0-9a-f]{40})$")
SHA = re.compile(r"^[0-9a-f]{40}$")


def assess(active: Any, version: Any, *, target_sha: str) -> dict[str, Any]:
    blockers: list[str] = []
    version_id: str | None = None
    source_sha: str | None = None
    if not isinstance(target_sha, str) or not SHA.fullmatch(target_sha):
        blockers.append("INVALID_TARGET_SHA")
    if not isinstance(active, dict) or not isinstance(version, dict):
        blockers.append("INVALID_EVIDENCE_SHAPE")
    else:
        # The status command returns one current deployment object. Historical
        # deployment lists are rejected, not guessed by array position.
        try:
            version_id = _served.resolve_served_version_id(
                {"success": True, "result": {"deployments": [active]}}
            )
        except _served.ServedVersionResolutionError:
            blockers.append("UNVERIFIED_ACTIVE_DEPLOYMENT")
        if version_id is not None and version.get("id") != version_id:
            blockers.append("ACTIVE_VERSION_MISMATCH")
        annotation = active.get("annotations")
        message = annotation.get("workers/message") if isinstance(annotation, dict) else None
        match = SOURCE_MARKER.fullmatch(message) if isinstance(message, str) else None
        if match:
            source_sha = match.group(1)
            if source_sha != target_sha:
                blockers.append("SERVED_SOURCE_OUTDATED")
        else:
            blockers.append("SOURCE_LINEAGE_UNVERIFIED")
        resources = version.get("resources")
        bindings = resources.get("bindings") if isinstance(resources, dict) else None
        if not isinstance(bindings, list) or any(
            not isinstance(b, dict) or not isinstance(b.get("name"), str)
            or not isinstance(b.get("type"), str)
            for b in bindings
        ):
            blockers.append("BINDING_INVENTORY_INVALID")
        else:
            names = [b["name"] for b in bindings]
            if len(names) != len(set(names)):
                blockers.append("DUPLICATE_BINDING_NAME")
            byname = {b["name"]: b for b in bindings}
            for name, typ in EXPECTED_TYPES.items():
                found = byname.get(name)
                if found is None:
                    blockers.append(f"MISSING_{name}")
                elif found.get("type") != typ:
                    blockers.append(f"WRONG_TYPE_{name}")
            for name, exact in (
                ("PADIEM_CHAT_RUNTIME_MODE", "b14"),
                ("PADIEM_CHAT_LIVE_ENABLED", "true"),
                ("PADIEM_CLAW_P01_LIVE_SSE_ENABLED", "true"),
            ):
                found = byname.get(name)
                if found is None:
                    blockers.append(f"MISSING_{name}")
                elif found.get("type") != "plain_text" or found.get("text") != exact:
                    blockers.append(f"NOT_READY_{name}")
    return {
        "disposition": "CANARY_PREFLIGHT_READY" if not blockers else "CANARY_BLOCKED",
        "blockers": sorted(set(blockers)),
        "active_version_id": version_id,
        "deployed_source_sha": source_sha,
        "provider_requests": 0,
        "settings_mutations": 0,
        "user_canary_executed": False,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--active", type=Path, required=True)
    p.add_argument("--version", type=Path, required=True)
    p.add_argument("--target-sha", required=True)
    a = p.parse_args()
    result = assess(
        json.loads(a.active.read_text(encoding="utf-8")),
        json.loads(a.version.read_text(encoding="utf-8")),
        target_sha=a.target_sha,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["disposition"] == "CANARY_PREFLIGHT_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
