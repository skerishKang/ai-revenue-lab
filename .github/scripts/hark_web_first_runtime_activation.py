#!/usr/bin/env python3
"""Hark WEB-FIRST: bounded production flag activation with exact binding parity.

Pure/offline: no Cloudflare API calls. Both Workers retain all binding identities;
one stage may append ONLY the reviewed plain-text 'true' flags, never secrets,
D1/R2/services, Browser invocation or customer file operations.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from b62_binding_state_guard import canonical_state, BindingStateError

STAGES = {
    "engine_read": (
        "padiem-ai-engine",
        ("PADIEM_WEB_XLSX_P01_ENGINE_SCOPE_ENABLED",
         "PADIEM_WEB_XLSX_P01_DURABLE_TOOL_ENABLED",
         "PADIEM_WEB_XLSX_P01_OWNER_DECISION_ENABLED"),
        (), ("WEB_XLSX_PRIVATE_B62_D1", "ENGINE_CONTINUATION"),
    ),
    "chat_read": (
        "padiem-chat",
        ("PADIEM_WEB_XLSX_P01_TOOL_DISPATCH_ENABLED",
         "PADIEM_WEB_XLSX_P01_OWNER_DECISION_ENABLED",
         "PADIEM_WEB_XLSX_WORKCOPY_AFTER_P01_ENABLED"),
        ("PADIEM_WEB_XLSX_P01_ENGINE_SCOPE_ENABLED",
         "PADIEM_WEB_XLSX_P01_DURABLE_TOOL_ENABLED",
         "PADIEM_WEB_XLSX_P01_OWNER_DECISION_ENABLED"),
        ("PADIEM_CHAT_DB", "PADIEM_WORKSPACE_FILES", "P01_ENGINE_SERVICE"),
    ),
    "engine_write": (
        "padiem-ai-engine",
        ("PADIEM_WEB_XLSX_QUOTE_WRITE_ENGINE_ENABLED",
         "PADIEM_WEB_XLSX_QUOTE_WRITE_DURABLE_ENABLED",
         "PADIEM_WEB_XLSX_QUOTE_WRITE_OWNER_DECISION_ENABLED"),
        ("PADIEM_WEB_XLSX_P01_TOOL_DISPATCH_ENABLED",
         "PADIEM_WEB_XLSX_P01_OWNER_DECISION_ENABLED",
         "PADIEM_WEB_XLSX_WORKCOPY_AFTER_P01_ENABLED"),
        ("WEB_XLSX_PRIVATE_B62_D1", "ENGINE_CONTINUATION"),
    ),
    "chat_write": (
        "padiem-chat",
        ("PADIEM_WEB_XLSX_QUOTE_WRITE_ENABLED",),
        ("PADIEM_WEB_XLSX_QUOTE_WRITE_ENGINE_ENABLED",
         "PADIEM_WEB_XLSX_QUOTE_WRITE_DURABLE_ENABLED",
         "PADIEM_WEB_XLSX_QUOTE_WRITE_OWNER_DECISION_ENABLED"),
        ("PADIEM_CHAT_DB", "PADIEM_WORKSPACE_FILES", "P01_ENGINE_SERVICE"),
    ),
    "chat_pdf": (
        "padiem-chat",
        ("PADIEM_WEB_XLSX_QUOTE_PDF_ENABLED",),
        ("PADIEM_WEB_XLSX_QUOTE_WRITE_ENGINE_ENABLED",
         "PADIEM_WEB_XLSX_QUOTE_WRITE_DURABLE_ENABLED",
         "PADIEM_WEB_XLSX_QUOTE_WRITE_OWNER_DECISION_ENABLED"),
        ("BROWSER", "PADIEM_CHAT_DB", "PADIEM_WORKSPACE_FILES"),
    ),
}
WORKERS = {"padiem-ai-engine", "padiem-chat"}
B62_D1_ID = "702bb62b-36f5-41a0-973f-c4f663ee01e6"


class ActivationError(ValueError):
    pass


def _entries(payload: object) -> dict[str, dict]:
    canonical_state(payload)  # complete type/identity/duplicate validation
    result = payload["result"]
    raw = result.get("bindings")
    if raw is None:
        raw = result.get("resources", {}).get("bindings")
    if not isinstance(raw, list):
        raise ActivationError("Cloudflare binding list is required")
    return {item["name"]: item for item in raw}


def _require_true(names: tuple[str, ...], lookup: dict[str, dict], label: str):
    if any(lookup.get(name) != {"name": name, "type": "plain_text", "text": "true"}
           for name in names):
        raise ActivationError(label + " prerequisite feature flags not all live")


def _verify_stage_identity(stage: str, current: dict[str, dict],
                           peer: dict[str, dict]):
    worker, flags, requirements, required_bindings = STAGES[stage]
    for name in required_bindings:
        if name not in current:
            raise ActivationError("required live Worker binding absent: " + name)
    if stage.startswith("engine"):
        database = current["WEB_XLSX_PRIVATE_B62_D1"]
        if database.get("type") != "d1" or (
            database.get("id") or database.get("database_id")
        ) != B62_D1_ID:
            raise ActivationError("Engine trusted Hark D1 identity mismatch")
    if stage == "chat_pdf" and current["BROWSER"].get("type") != "browser":
        raise ActivationError("Hark Browser binding type mismatch")
    if stage == "chat_pdf":
        _require_true(("PADIEM_WEB_XLSX_QUOTE_WRITE_ENABLED",),
                      current, "local WRITE")
    _require_true(requirements, peer, "peer")


def plan(stage: str, settings: dict, peer_settings: dict) -> dict:
    if stage not in STAGES:
        raise ActivationError("unrecognized activation stage")
    worker, flags, _, _ = STAGES[stage]
    live, peer = _entries(settings), _entries(peer_settings)
    _verify_stage_identity(stage, live, peer)
    if all(live.get(flag) == {"name": flag, "type": "plain_text", "text": "true"}
           for flag in flags):
        raise ActivationError("stage already active: no mutation required")
    for flag in flags:
        if flag in live:
            raise ActivationError("refuse to rewrite existing flag: " + flag)
    # All live auth/services/D1/R2/secrets remain inherited from the currently
    # serving version. No caller or repo template can inject another binding.
    bindings = [
        {"name": name, "type": "inherit", "version_id": "latest"}
        for name in sorted(live)
    ] + [
        {"name": name, "type": "plain_text", "text": "true"}
        for name in flags
    ]
    return {
        "bindings": bindings,
        "annotations": {"workers/message": "Hark WEB-FIRST gated feature stage " + stage,
                        "workers/triggered_by": "hark-web-first-runtime-activation"},
    }


def verify(stage: str, before: dict, after: dict) -> None:
    if stage not in STAGES:
        raise ActivationError("unrecognized activation stage")
    old = canonical_state(before)
    now = canonical_state(after)
    expected = tuple(sorted(
        (*old, *(( "plain_text", name, "true") for name in STAGES[stage][1])),
        key=lambda e: (str(e[0]), str(e[1])),
    ))
    if now != expected:
        raise ActivationError("post-release binding identity drift or missing Hark flags")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("plan", "verify"))
    parser.add_argument("--stage", required=True, choices=tuple(STAGES))
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--peer", type=Path)
    parser.add_argument("--after", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        old = _load(args.before)
        if args.action == "plan":
            if args.peer is None or args.output is None or args.after is not None:
                raise ActivationError("plan requires --peer and --output")
            body = plan(args.stage, old, _load(args.peer))
            with args.output.open("x", encoding="utf-8") as handle:
                json.dump(body, handle, separators=(",", ":"))
            print("HARK_STAGE_PLAN=PASS")
            print("BINDING_INHERIT_COUNT=" + str(len(_entries(old))))
            print("APPROVED_NEW_FLAGS=" + str(len(STAGES[args.stage][1])))
        else:
            if args.after is None or args.output is not None or args.peer is not None:
                raise ActivationError("verify requires --after")
            verify(args.stage, old, _load(args.after))
            print("HARK_STAGE_EXACT_BINDING_PARITY=PASS")
        print("SECRET_VALUES_READ=0")
        print("BROWSER_QUICK_ACTION_CALLS=0")
        return 0
    except (ActivationError, BindingStateError, OSError, ValueError, KeyError) as exc:
        print("HARK_STAGE=BLOCKED " + type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
