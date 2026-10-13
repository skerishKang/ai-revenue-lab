#!/usr/bin/env python3
"""Fail closed when B62 script-level P01 SSE flag differs from active served version.

This read-only guard protects the code-deploy path from inheriting an unaccepted
SSE setting after a partially successful rollback. Never prints settings/secret values.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from b62_p01_sse_optin_gate import FLAG, bindings, version_bindings, version_result


class ServedSSEStateDrift(ValueError):
    pass


def _flag(binding: dict | None) -> str:
    if binding is None:
        return "absent"
    if binding.get("type") != "plain_text" or binding.get("text") not in ("true", "false"):
        raise ServedSSEStateDrift("INVALID_FLAG_SHAPE")
    return binding["text"]


def verify(settings: object, served: object) -> str:
    try:
        script_flag = _flag(bindings(settings).get(FLAG))
        served_flag = _flag(version_bindings(version_result(served)).get(FLAG))
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ServedSSEStateDrift("UNVERIFIED_SSE_SETTINGS") from exc
    if script_flag != served_flag:
        raise ServedSSEStateDrift("SSE_FLAG_LATEST_VS_ACTIVE_DRIFT")
    return script_flag


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--served-version", type=Path, required=True)
    args = parser.parse_args()
    try:
        verify(
            json.loads(args.settings.read_text(encoding="utf-8")),
            json.loads(args.served_version.read_text(encoding="utf-8")),
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print("B62_SSE_SERVED_CONFIG_PARITY=BLOCKED")
        print("B62_DEPLOY_MUTATION=0")
        return 2
    print("B62_SSE_SERVED_CONFIG_PARITY=PASS")
    print("B62_DEPLOY_MUTATION=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
