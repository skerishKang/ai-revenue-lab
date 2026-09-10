#!/usr/bin/env python3
"""Classify live padiem-ai-engine caller-authority bindings by NAME/TYPE only.

Consumes the bounded Cloudflare Worker ``settings`` GET response produced by
the read-only gate. Emits exactly four NAME/TYPE states plus aggregate safety
markers. Never emits any binding value, identifier, raw settings JSON, or the
Cloudflare account id.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ENGINE_WORKER = "padiem-ai-engine"

TARGET_NAMES = (
    "PADIEM_ENGINE_CALLER_REGISTRY_V1",
    "PADIEM_ENGINE_CALLER_ID",
    "PADIEM_ENGINE_CALLER_SECRET",
    "PADIEM_ENGINE_ALLOWED_APPS",
)

# Only the binding ``type`` discriminator is echoed. Values are never read.
_EMITTED_FIELDS = ("name", "type")


class CallerAuthorityEvidenceError(RuntimeError):
    pass


def _bindings(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise CallerAuthorityEvidenceError("worker settings response is not successful")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise CallerAuthorityEvidenceError("worker settings result is malformed")
    bindings = result.get("bindings")
    if not isinstance(bindings, list) or not all(isinstance(b, dict) for b in bindings):
        raise CallerAuthorityEvidenceError("worker settings bindings array is malformed")
    return bindings


def classify_authority(payload: object) -> dict[str, str]:
    """Return a NAME -> ``PRESENT:<type>``/``ABSENT`` map for the four targets.

    Fails closed on duplicate target names and on malformed settings.
    """
    bindings = _bindings(payload)
    states: dict[str, str] = {}
    for name in TARGET_NAMES:
        matches = [b for b in bindings if b.get("name") == name]
        if len(matches) > 1:
            raise CallerAuthorityEvidenceError(
                f"duplicate target binding present: {name}"
            )
        if not matches:
            states[name] = "ABSENT"
            continue
        binding_type = matches[0].get("type")
        if not isinstance(binding_type, str) or not binding_type.strip():
            raise CallerAuthorityEvidenceError(
                f"target binding has no valid type: {name}"
            )
        states[name] = f"PRESENT:{binding_type.strip()}"
    return states


def render(states: dict[str, str]) -> str:
    """Render bounded stdout: only NAME/TYPE state and safety markers."""
    lines = [f"{name}={states[name]}" for name in TARGET_NAMES]
    present = sum(1 for name in TARGET_NAMES if states[name] != "ABSENT")
    lines.append(f"ENGINE_CALLER_AUTHORITY_TARGET_COUNT={present}")
    lines.append("RAW_BINDING_VALUE_OUTPUT=0")
    lines.append("SECRET_VALUE_OUTPUT=0")
    lines.append("PRODUCTION_MUTATION=0")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(
            "usage: b54_engine_caller_authority_readonly.py <worker-settings.json>",
            file=sys.stderr,
        )
        return 2
    try:
        payload = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        states = classify_authority(payload)
    except (OSError, json.JSONDecodeError, CallerAuthorityEvidenceError) as exc:
        print("B54_ENGINE_CALLER_AUTHORITY_READONLY=FAIL", file=sys.stderr)
        print(f"REASON={exc}", file=sys.stderr)
        return 1
    print(render(states))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
