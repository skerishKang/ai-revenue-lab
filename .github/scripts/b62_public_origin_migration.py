#!/usr/bin/env python3
"""Bounded B62 canonical public-origin migration helper.

This helper never reads secret values. It validates the Cloudflare Worker
settings envelope, requires the legacy Padiem Chat public origin before
migration, builds one settings PATCH that changes only
PADIEM_CHAT_PUBLIC_BASE_URL, and verifies the post-state.

The only permitted origin transition is:

    https://padiem-chat.charliekant.workers.dev
      -> https://chat.padiem.net
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent

_guard_spec = importlib.util.spec_from_file_location(
    "b62_binding_state_guard", _HERE / "b62_binding_state_guard.py"
)
assert _guard_spec is not None and _guard_spec.loader is not None
_guard = importlib.util.module_from_spec(_guard_spec)
_guard_spec.loader.exec_module(_guard)

canonical_binding = _guard.canonical_binding
canonical_state = _guard.canonical_state
BindingStateError = _guard.BindingStateError

PUBLIC_BASE_URL_NAME = "PADIEM_CHAT_PUBLIC_BASE_URL"
OLD_ORIGIN = "https://padiem-chat.charliekant.workers.dev"
NEW_ORIGIN = "https://chat.padiem.net"

AUTH_REQUIRED = {
    "PADIEM_CHAT_AUTH_MODE": ("plain_text", "google"),
    "PADIEM_CHAT_GOOGLE_CLIENT_ID": ("plain_text", None),
    "PADIEM_CHAT_GOOGLE_CLIENT_SECRET": ("secret_text", None),
    "PADIEM_CHAT_SESSION_SECRET": ("secret_text", None),
}


class OriginMigrationError(RuntimeError):
    pass


def _load(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OriginMigrationError(f"cannot read settings payload: {exc}") from exc


def _bindings(payload: object) -> list[dict[str, Any]]:
    try:
        canonical_state(payload)
    except BindingStateError as exc:
        raise OriginMigrationError(str(exc)) from exc
    assert isinstance(payload, dict)
    result = payload.get("result")
    assert isinstance(result, dict)
    bindings = result.get("bindings")
    assert isinstance(bindings, list)
    return [dict(binding) for binding in bindings]


def _by_name(payload: object) -> dict[str, dict[str, Any]]:
    return {binding["name"]: binding for binding in _bindings(payload)}


def require_prestate(payload: object) -> None:
    by_name = _by_name(payload)
    public = by_name.get(PUBLIC_BASE_URL_NAME)
    if public is None:
        raise OriginMigrationError("PUBLIC_ORIGIN_PRESTATE=ABSENT")
    if public.get("type") != "plain_text":
        raise OriginMigrationError("PUBLIC_ORIGIN_PRESTATE=WRONG_TYPE")
    if public.get("text") != OLD_ORIGIN:
        raise OriginMigrationError("PUBLIC_ORIGIN_PRESTATE=NOT_LEGACY_EXPECTED")

    for name, (kind, exact_text) in AUTH_REQUIRED.items():
        binding = by_name.get(name)
        if binding is None or binding.get("type") != kind:
            raise OriginMigrationError(f"AUTH_BINDING_PRESTATE_{name}=FAIL")
        if exact_text is not None and binding.get("text") != exact_text:
            raise OriginMigrationError(f"AUTH_BINDING_PRESTATE_{name}=FAIL")
        if name == "PADIEM_CHAT_GOOGLE_CLIENT_ID" and not str(binding.get("text", "")).strip():
            raise OriginMigrationError("AUTH_BINDING_PRESTATE_PADIEM_CHAT_GOOGLE_CLIENT_ID=FAIL")


def _inherit(name: str) -> dict[str, str]:
    return {"name": name, "type": "inherit", "version_id": "latest"}


def build_patch(payload: object, *, target_origin: str, message: str) -> dict[str, Any]:
    bindings = _bindings(payload)
    out: list[dict[str, Any]] = []
    found = False
    for binding in bindings:
        name = binding["name"]
        if name == PUBLIC_BASE_URL_NAME:
            found = True
            out.append({"name": name, "type": "plain_text", "text": target_origin})
        else:
            out.append(_inherit(name))
    if not found:
        raise OriginMigrationError("PUBLIC_ORIGIN_BINDING_MISSING")
    return {
        "bindings": out,
        "annotations": {
            "workers/message": message,
            "workers/triggered_by": "b62-public-origin-migration-gate",
        },
    }


def verify_transition(before: object, after: object, *, expected_after: str) -> None:
    before_bindings = _by_name(before)
    after_bindings = _by_name(after)

    if set(before_bindings) != set(after_bindings):
        raise OriginMigrationError("BINDING_NAME_SET_DRIFT")

    before_public = before_bindings[PUBLIC_BASE_URL_NAME]
    after_public = after_bindings[PUBLIC_BASE_URL_NAME]
    if before_public.get("type") != "plain_text" or after_public.get("type") != "plain_text":
        raise OriginMigrationError("PUBLIC_ORIGIN_TYPE_DRIFT")
    if after_public.get("text") != expected_after:
        raise OriginMigrationError("PUBLIC_ORIGIN_TARGET_MISMATCH")

    for name in sorted(before_bindings):
        if name == PUBLIC_BASE_URL_NAME:
            continue
        if canonical_binding(before_bindings[name]) != canonical_binding(after_bindings[name]):
            raise OriginMigrationError(f"UNRELATED_BINDING_DRIFT_{name}")

    before_secrets = sorted(
        name for name, binding in before_bindings.items() if binding.get("type") == "secret_text"
    )
    after_secrets = sorted(
        name for name, binding in after_bindings.items() if binding.get("type") == "secret_text"
    )
    if before_secrets != after_secrets:
        raise OriginMigrationError("SECRET_BINDING_SET_DRIFT")


def _write_new(path: Path, payload: object) -> None:
    if path.exists():
        raise OriginMigrationError("output path already exists")
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("prestate", "build-target", "verify-target", "build-rollback", "verify-rollback"),
    )
    parser.add_argument("--before", type=Path)
    parser.add_argument("--after", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    try:
        if args.command == "prestate":
            if args.before is None:
                raise OriginMigrationError("--before is required")
            payload = _load(args.before)
            require_prestate(payload)
            print("PUBLIC_ORIGIN_PRESTATE=OLD_EXPECTED")
            print("AUTH_PRESTATE=PASS")
            print("SECRET_VALUES_READ=0")
            print("SECRET_VALUES_OUTPUT=0")
            print("PRODUCTION_MUTATION=0")
            return 0

        if args.command in {"build-target", "build-rollback"}:
            if args.before is None or args.output is None:
                raise OriginMigrationError("--before and --output are required")
            payload = _load(args.before)
            target = NEW_ORIGIN if args.command == "build-target" else OLD_ORIGIN
            message = (
                "B62 canonical public origin migration"
                if args.command == "build-target"
                else "B62 canonical public origin rollback"
            )
            _write_new(args.output, build_patch(payload, target_origin=target, message=message))
            print("PUBLIC_ORIGIN_PATCH_PLAN=PASS")
            print("SECRET_VALUES_READ=0")
            print("SECRET_VALUES_OUTPUT=0")
            print("PRODUCTION_MUTATION=0")
            return 0

        if args.before is None or args.after is None:
            raise OriginMigrationError("--before and --after are required")
        before = _load(args.before)
        after = _load(args.after)
        expected = NEW_ORIGIN if args.command == "verify-target" else OLD_ORIGIN
        verify_transition(before, after, expected_after=expected)
        if args.command == "verify-target":
            print("PUBLIC_ORIGIN_TARGET=CHAT_PADIEM_NET")
            print("PUBLIC_ORIGIN_PATCH=PASS")
            print("UNRELATED_BINDING_MUTATION=0")
            print("SECRET_BINDINGS_PRESERVED=PASS")
            print("FULL_SECRET_SET_EQUALITY=PASS")
        else:
            print("PUBLIC_ORIGIN_ROLLBACK=PASS")
            print("B62_PUBLIC_ORIGIN_ROLLBACK_READBACK=EXACT")
        print("SECRET_VALUES_READ=0")
        print("SECRET_VALUES_OUTPUT=0")
        return 0
    except OriginMigrationError as exc:
        print(f"B62_PUBLIC_ORIGIN_{args.command.upper().replace('-', '_')}=FAIL", file=sys.stderr)
        print(f"REASON={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
