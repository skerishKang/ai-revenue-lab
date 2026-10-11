#!/usr/bin/env python3
"""Bounded activation helper for PADIEM_CHAT_B66_QUOTE_BASE_URL (#3326)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import b62_cloudflare_production_deploy_config as _deploy_config

TARGET = "PADIEM_CHAT_B66_QUOTE_BASE_URL"


class ActivationError(RuntimeError):
    pass


def normalize_expected_origin(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ActivationError("expected origin is required")
    raw = value.strip()
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ActivationError("expected origin must be https")
    if parsed.username or parsed.password:
        raise ActivationError("expected origin must not contain userinfo")
    if parsed.query or parsed.fragment:
        raise ActivationError("expected origin must not contain query or fragment")
    if parsed.path not in {"", "/"}:
        raise ActivationError("expected origin must be root-only")
    return urlunsplit(("https", parsed.netloc, "", "", ""))


def _bindings(payload: object) -> list[dict]:
    # Reuse the canonical Production live-settings parser so unsupported types,
    # malformed structural bindings and duplicate names fail closed here too.
    _deploy_config.parse_live_bindings(payload)
    result = payload.get("result") if isinstance(payload, dict) else None
    bindings = result.get("bindings") if isinstance(result, dict) else None
    if not isinstance(bindings, list):
        raise ActivationError("settings payload has no bindings array")
    return [dict(binding) for binding in bindings]


def classify(settings_payload: object, expected_origin: object) -> tuple[str, str]:
    expected = normalize_expected_origin(expected_origin)
    by_name = {binding["name"]: binding for binding in _bindings(settings_payload)}
    target = by_name.get(TARGET)
    if target is None:
        return "missing", expected
    if target.get("type") != "plain_text":
        return "wrong_type", expected
    text = target.get("text")
    if not isinstance(text, str):
        return "invalid", expected
    try:
        normalized = normalize_expected_origin(text)
    except ActivationError:
        return "invalid", expected
    if text != normalized:
        return "invalid", expected
    return ("exact" if normalized == expected else "drift"), expected


def _canonical(binding: dict) -> tuple[object, ...]:
    kind = binding["type"]
    name = binding["name"]
    if kind in {"assets", "secret_text", "version_metadata"}:
        return (kind, name)
    if kind == "plain_text":
        text = binding.get("text")
        if not isinstance(text, str):
            raise ActivationError(f"plain_text binding {name!r} has no text")
        return (kind, name, text)
    if kind == "service":
        service = binding.get("service")
        if not isinstance(service, str) or not service:
            raise ActivationError(f"service binding {name!r} has no service")
        return (kind, name, service, binding.get("environment"))
    if kind == "d1":
        value = binding.get("id")
        if not isinstance(value, str) or not value:
            raise ActivationError(f"d1 binding {name!r} has no id")
        return (kind, name, value)
    if kind == "r2_bucket":
        bucket = binding.get("bucket_name")
        if not isinstance(bucket, str) or not bucket:
            raise ActivationError(f"r2 binding {name!r} has no bucket_name")
        return (kind, name, bucket, binding.get("jurisdiction"))
    raise ActivationError(f"unsupported binding type {kind!r}")


def build_plan(settings_payload: object, expected_origin: object, target_sha: str) -> dict:
    state, expected = classify(settings_payload, expected_origin)
    if state not in {"missing", "exact"}:
        raise ActivationError(f"refusing target state {state}")
    bindings = _bindings(settings_payload)
    if state == "exact":
        return {
            "payload": None,
            "state": state,
            "expected_origin": expected,
            "no_op": True,
            "preserved_bindings": len(bindings),
        }
    patch_bindings = [
        {"name": binding["name"], "type": "inherit", "version_id": "latest"}
        for binding in bindings
    ]
    patch_bindings.append({"name": TARGET, "type": "plain_text", "text": expected})
    return {
        "payload": {
            "bindings": patch_bindings,
            "annotations": {
                "workers/message": f"B66 quote URL activation gate {target_sha}",
                "workers/triggered_by": "b62-b66-quote-url-activation-gate",
            },
        },
        "state": state,
        "expected_origin": expected,
        "no_op": False,
        "preserved_bindings": len(bindings),
    }


def verify_readback(before_payload: object, after_payload: object, expected_origin: object) -> None:
    before_state, expected = classify(before_payload, expected_origin)
    if before_state not in {"missing", "exact"}:
        raise ActivationError(f"pre-mutation target state is not activatable: {before_state}")
    after_state, _ = classify(after_payload, expected)
    if after_state != "exact":
        raise ActivationError(f"post-mutation target is not exact: {after_state}")

    before = {binding["name"]: _canonical(binding) for binding in _bindings(before_payload)}
    after = {binding["name"]: _canonical(binding) for binding in _bindings(after_payload)}
    for name, canonical in before.items():
        if name == TARGET and before_state == "missing":
            continue
        if after.get(name) != canonical:
            raise ActivationError(f"unrelated binding drift: {name}")
    allowed = set(before)
    allowed.add(TARGET)
    extra = sorted(set(after) - allowed)
    if extra:
        raise ActivationError(f"unexpected binding additions: {', '.join(extra)}")


def _load(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ActivationError(f"cannot read settings payload: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("classify", "plan", "verify"))
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--before", type=Path)
    parser.add_argument("--after", type=Path)
    parser.add_argument("--expected-origin", required=True)
    parser.add_argument("--target-sha", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.command == "classify":
            if not args.settings:
                raise ActivationError("classify requires --settings")
            state, expected = classify(_load(args.settings), args.expected_origin)
            print(f"B62_B66_QUOTE_URL_STATE={state}")
            print(f"B62_B66_QUOTE_URL_EXPECTED_ORIGIN={expected}")
            print("SECRET_VALUES_READ=0")
            print("PRODUCTION_MUTATION=0")
            return 0

        if args.command == "plan":
            if not args.settings or not args.output or not args.target_sha:
                raise ActivationError("plan requires --settings, --output and --target-sha")
            plan = build_plan(_load(args.settings), args.expected_origin, args.target_sha)
            if args.output.exists():
                raise ActivationError("output path already exists")
            if plan["payload"] is not None:
                args.output.write_text(
                    json.dumps(plan["payload"], separators=(",", ":")),
                    encoding="utf-8",
                )
            print("B62_B66_QUOTE_URL_PLAN=PASS")
            print(f"B62_B66_QUOTE_URL_NO_OP={1 if plan['no_op'] else 0}")
            print(f"INHERITED_BINDINGS={plan['preserved_bindings']}")
            print("SECRET_VALUES_READ=0")
            print("SECRET_VALUES_EMITTED=0")
            return 0

        if not args.before or not args.after:
            raise ActivationError("verify requires --before and --after")
        verify_readback(_load(args.before), _load(args.after), args.expected_origin)
        print("B62_B66_QUOTE_URL_POST_READBACK=PASS")
        print("UNRELATED_BINDINGS_PRESERVED=PASS")
        print("SECRET_VALUES_READ=0")
        return 0
    except (ActivationError, _deploy_config.ProductionConfigError) as exc:
        print(f"B62_B66_QUOTE_URL_{args.command.upper()}=FAIL", file=sys.stderr)
        print(f"REASON={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
