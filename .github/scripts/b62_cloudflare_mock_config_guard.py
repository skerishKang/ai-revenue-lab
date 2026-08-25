#!/usr/bin/env python3
"""Fail closed unless the repository is configured for a mock-only B62 deploy."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tomllib

EXPECTED_WORKER = "padiem-chat"
EXPECTED_RUNTIME = "mock"
EXPECTED_LIVE_ENABLED = "false"
FORBIDDEN_PLAINTEXT_VARS = {
    "PADIEM_CHAT_B14_BASE_URL",
    "PADIEM_CHAT_QUOTA_SALT",
    "OPENROUTER_API_KEY",
    "BUSINESS14_PROVIDER_KEY",
}


def validate_config(path: Path) -> list[str]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        return [f"cannot read valid TOML: {exc}"]

    errors: list[str] = []
    if data.get("name") != EXPECTED_WORKER:
        errors.append(f"Worker name must be {EXPECTED_WORKER!r}")

    raw_vars = data.get("vars", {})
    if not isinstance(raw_vars, dict):
        return errors + ["[vars] must be a TOML table"]

    runtime = raw_vars.get("PADIEM_CHAT_RUNTIME_MODE")
    if runtime != EXPECTED_RUNTIME:
        errors.append(
            f"PADIEM_CHAT_RUNTIME_MODE must be {EXPECTED_RUNTIME!r}; got {runtime!r}"
        )

    live_enabled = raw_vars.get("PADIEM_CHAT_LIVE_ENABLED")
    if live_enabled != EXPECTED_LIVE_ENABLED:
        errors.append(
            "PADIEM_CHAT_LIVE_ENABLED must be the string 'false' for the mock deploy workflow; "
            f"got {live_enabled!r}"
        )

    present_forbidden = sorted(FORBIDDEN_PLAINTEXT_VARS.intersection(raw_vars))
    if present_forbidden:
        errors.append(
            "mock deploy wrangler [vars] must not contain live/secret bindings: "
            + ", ".join(present_forbidden)
        )

    return errors


def append_summary(lines: list[str]) -> None:
    target = os.getenv("GITHUB_STEP_SUMMARY")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    path = Path(args[0]) if args else Path("apps/padiem-chat/wrangler.toml")
    errors = validate_config(path)
    if errors:
        print("B62_MOCK_CONFIG_GUARD=FAIL", file=sys.stderr)
        for error in errors:
            print(f"B62_MOCK_CONFIG_ERROR={error}", file=sys.stderr)
        return 1

    print("B62_MOCK_CONFIG_GUARD=PASS")
    print(f"WORKER_NAME={EXPECTED_WORKER}")
    print("RUNTIME=mock")
    print("LIVE_ENABLED=false")
    print("PLAINTEXT_LIVE_OR_SECRET_VARS=0")
    append_summary([
        "## B62 pre-deploy mock config guard",
        "",
        "- Worker identity: `padiem-chat`",
        "- Repository runtime: `mock`",
        "- Public live arm: `false`",
        "- Plaintext live/secret vars in wrangler `[vars]`: `0`",
        "- Result: PASS before any deploy command can run",
    ])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
