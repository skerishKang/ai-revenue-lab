#!/usr/bin/env python3
"""Bounded Google auth activation/readback gate for Padiem Chat (B62 #2536).

SOURCE-ONLY. No Production mutation, no Google provider setup, no login
attempt, no Phase-B retry, and no tenant-gate change. The live Cloudflare
Worker settings dump is the only input and is classified read-only.

Existing Cloudflare helpers are reused instead of duplicated:

* ``b62_cloudflare_production_deploy_config.parse_live_bindings`` validates
  the settings envelope, supported binding types and duplicate names;
* ``b62_binding_state_guard.canonical_binding`` backs the plan-time
  unrelated-binding preservation check.

Closed output vocabulary: binding NAME/TYPE/STATE tokens only
(``exact`` | ``missing`` | ``wrong_type`` | ``invalid`` | ``drift`` |
``not_configured``) plus bounded disposition markers. Secret values, hashes,
digests, fingerprints, lengths, prefixes, suffixes, cookies, OAuth tokens,
passwords, full settings JSON and unrelated plain-text values are never read
or emitted.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

_HERE = Path(__file__).resolve().parent

_spec = importlib.util.spec_from_file_location(
    "b62_cloudflare_production_deploy_config",
    _HERE / "b62_cloudflare_production_deploy_config.py",
)
assert _spec is not None and _spec.loader is not None
_deploy_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_deploy_config)
parse_live_bindings = _deploy_config.parse_live_bindings

_guard_spec = importlib.util.spec_from_file_location(
    "b62_binding_state_guard", _HERE / "b62_binding_state_guard.py"
)
assert _guard_spec is not None and _guard_spec.loader is not None
_binding_guard = importlib.util.module_from_spec(_guard_spec)
_guard_spec.loader.exec_module(_binding_guard)
canonical_binding = _binding_guard.canonical_binding

WORKER = "padiem-chat"

AUTH_MODE_NAME = "PADIEM_CHAT_AUTH_MODE"
AUTH_MODE_EXPECTED = "google"
PUBLIC_BASE_URL_NAME = "PADIEM_CHAT_PUBLIC_BASE_URL"
GOOGLE_CLIENT_ID_NAME = "PADIEM_CHAT_GOOGLE_CLIENT_ID"
GOOGLE_CLIENT_SECRET_NAME = "PADIEM_CHAT_GOOGLE_CLIENT_SECRET"
SESSION_SECRET_NAME = "PADIEM_CHAT_SESSION_SECRET"
SESSION_MAX_AGE_NAME = "PADIEM_CHAT_SESSION_MAX_AGE_SECONDS"
SESSION_MAX_AGE_MIN = 300
SESSION_MAX_AGE_MAX = 30 * 24 * 3600

# Required Google-auth activation allowlist (NAME -> expected binding type).
AUTH_TARGET_TYPES = {
    AUTH_MODE_NAME: "plain_text",
    PUBLIC_BASE_URL_NAME: "plain_text",
    GOOGLE_CLIENT_ID_NAME: "plain_text",
    GOOGLE_CLIENT_SECRET_NAME: "secret_text",
    SESSION_SECRET_NAME: "secret_text",
}
OPTIONAL_AUTH_TYPES = {SESSION_MAX_AGE_NAME: "plain_text"}
AUTH_ALLOWLIST = frozenset(AUTH_TARGET_TYPES) | frozenset(OPTIONAL_AUTH_TYPES)

PREREQ_D1_NAME = "PADIEM_CHAT_DB"
PREREQ_IDENTITY_NAME = "IDENTITY_AUTHORITY_SERVICE"
PREREQ_IDENTITY_SERVICE = "padiem-control-plane-identity"
PREREQ_R2_NAME = "PADIEM_WORKSPACE_FILES"
PREREQ_NAMES = (PREREQ_D1_NAME, PREREQ_IDENTITY_NAME, PREREQ_R2_NAME)

# Closed state vocabulary. ``not_configured`` is informational and reserved
# for the optional session-TTL binding when it is simply absent.
STATES = frozenset({"exact", "missing", "wrong_type", "invalid", "drift", "not_configured"})


class AuthGateError(RuntimeError):
    pass


def _raw_bindings(settings_payload: object) -> list[dict]:
    """Validate the payload through the deploy-config authority."""
    parse_live_bindings(settings_payload)
    result = settings_payload["result"]  # validated by parse_live_bindings
    return result["bindings"]


def _public_base_url_shape_ok(value: object) -> bool:
    """Mirror ``config._normalize_base_url(https_only, root_only)`` as bool."""
    if not isinstance(value, str):
        return False
    raw = value.strip()
    if not raw:
        return False
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    if not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    if parsed.query or parsed.fragment:
        return False
    if parsed.path.rstrip("/"):
        return False
    return True


def _nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _session_max_age_ok(value: object) -> bool:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return False
    return SESSION_MAX_AGE_MIN <= parsed <= SESSION_MAX_AGE_MAX


def classify_auth_config(
    settings_payload: object,
    *,
    expected_public_base_url: str,
) -> dict[str, str]:
    """Classify Google-auth activation bindings with a closed vocabulary.

    ``exact`` means present with the expected type AND a valid shape:
    AUTH_MODE is exactly ``google``; PUBLIC_BASE_URL is https, root-only,
    no query/fragment, and equals the expected origin; GOOGLE_CLIENT_ID is
    non-empty; secrets are ``secret_text`` presence-only (never inspected).
    The optional session TTL is ``exact`` when valid, ``invalid`` when
    malformed, and ``not_configured`` when absent (never blocking).
    """
    if not _nonempty_text(expected_public_base_url):
        raise AuthGateError("expected public base URL input is required")
    if not _public_base_url_shape_ok(expected_public_base_url):
        raise AuthGateError("expected public base URL must be an https root origin")
    by_name = {binding["name"]: binding for binding in _raw_bindings(settings_payload)}
    states: dict[str, str] = {}

    mode = by_name.get(AUTH_MODE_NAME)
    if mode is None:
        states[AUTH_MODE_NAME] = "missing"
    elif mode.get("type") != "plain_text":
        states[AUTH_MODE_NAME] = "wrong_type"
    elif str(mode.get("text", "")).strip().lower() != AUTH_MODE_EXPECTED:
        states[AUTH_MODE_NAME] = "invalid"
    else:
        states[AUTH_MODE_NAME] = "exact"

    public = by_name.get(PUBLIC_BASE_URL_NAME)
    if public is None:
        states[PUBLIC_BASE_URL_NAME] = "missing"
    elif public.get("type") != "plain_text":
        states[PUBLIC_BASE_URL_NAME] = "wrong_type"
    elif not _public_base_url_shape_ok(public.get("text")):
        states[PUBLIC_BASE_URL_NAME] = "invalid"
    elif str(public.get("text", "")).strip() != expected_public_base_url.strip():
        states[PUBLIC_BASE_URL_NAME] = "drift"
    else:
        states[PUBLIC_BASE_URL_NAME] = "exact"

    client_id = by_name.get(GOOGLE_CLIENT_ID_NAME)
    if client_id is None:
        states[GOOGLE_CLIENT_ID_NAME] = "missing"
    elif client_id.get("type") != "plain_text":
        states[GOOGLE_CLIENT_ID_NAME] = "wrong_type"
    elif not _nonempty_text(client_id.get("text")):
        states[GOOGLE_CLIENT_ID_NAME] = "invalid"
    else:
        states[GOOGLE_CLIENT_ID_NAME] = "exact"

    for name in (GOOGLE_CLIENT_SECRET_NAME, SESSION_SECRET_NAME):
        binding = by_name.get(name)
        if binding is None:
            states[name] = "missing"
        elif binding.get("type") != "secret_text":
            states[name] = "wrong_type"
        else:
            # Presence and type only. The value, length, hash, digest,
            # fingerprint, prefix and suffix are never read or emitted.
            states[name] = "exact"

    ttl = by_name.get(SESSION_MAX_AGE_NAME)
    if ttl is None:
        states[SESSION_MAX_AGE_NAME] = "not_configured"
    elif ttl.get("type") != "plain_text":
        states[SESSION_MAX_AGE_NAME] = "wrong_type"
    elif not _session_max_age_ok(ttl.get("text")):
        states[SESSION_MAX_AGE_NAME] = "invalid"
    else:
        states[SESSION_MAX_AGE_NAME] = "exact"

    for name, state in states.items():
        if state not in STATES:
            raise AuthGateError(f"internal state vocabulary violation on {name}")
    return states


def read_prerequisites(settings_payload: object) -> dict[str, str]:
    """Read-only presence/type/shape check for auth-adjacent prerequisites."""
    by_name = {binding["name"]: binding for binding in _raw_bindings(settings_payload)}
    states: dict[str, str] = {}

    d1 = by_name.get(PREREQ_D1_NAME)
    if d1 is None:
        states[PREREQ_D1_NAME] = "missing"
    elif d1.get("type") != "d1":
        states[PREREQ_D1_NAME] = "wrong_type"
    elif not _nonempty_text(d1.get("id")):
        states[PREREQ_D1_NAME] = "invalid"
    else:
        states[PREREQ_D1_NAME] = "exact"

    identity = by_name.get(PREREQ_IDENTITY_NAME)
    if identity is None:
        states[PREREQ_IDENTITY_NAME] = "missing"
    elif identity.get("type") != "service":
        states[PREREQ_IDENTITY_NAME] = "wrong_type"
    elif identity.get("service") != PREREQ_IDENTITY_SERVICE:
        states[PREREQ_IDENTITY_NAME] = "drift"
    else:
        states[PREREQ_IDENTITY_NAME] = "exact"

    r2 = by_name.get(PREREQ_R2_NAME)
    if r2 is None:
        states[PREREQ_R2_NAME] = "missing"
    elif r2.get("type") != "r2_bucket":
        states[PREREQ_R2_NAME] = "wrong_type"
    elif not _nonempty_text(r2.get("bucket_name")):
        states[PREREQ_R2_NAME] = "invalid"
    else:
        states[PREREQ_R2_NAME] = "exact"
    return states


def disposition(auth_states: dict[str, str]) -> str:
    """Aggregate the required auth allowlist into one closed disposition."""
    unknown = [name for name, state in auth_states.items() if state not in STATES]
    if unknown:
        raise AuthGateError("auth states are outside the closed vocabulary")
    required: dict[str, str] = {}
    for name in AUTH_TARGET_TYPES:
        if name not in auth_states:
            raise AuthGateError(f"auth state is missing for {name}")
        required[name] = auth_states[name]
    if any(state == "wrong_type" for state in required.values()):
        return "REFUSE_WRONG_TYPE"
    if any(state in {"invalid", "drift"} for state in required.values()):
        return "REFUSE_INVALID"
    if any(state == "missing" for state in required.values()):
        return "ACTIVATION_REQUIRED"
    if all(state == "exact" for state in required.values()):
        return "ALREADY_EXACT"
    raise AuthGateError("auth states are outside the closed vocabulary")


def _inherit(name: str) -> dict:
    return {"name": name, "type": "inherit", "version_id": "latest"}


def build_activation_plan(
    settings_payload: object,
    *,
    expected_public_base_url: str,
    session_max_age_text: str = "",
    target_sha: str = "",
) -> dict:
    """Build a bounded future-activation patch plan without mutating anything.

    Only allowlisted auth bindings may change; every unrelated binding is
    carried as ``inherit``/``latest``. Secrets are name-only placeholders:
    real values are supplied only by a future CENTRAL-authorized dispatch.
    """
    auth_states = classify_auth_config(
        settings_payload, expected_public_base_url=expected_public_base_url
    )
    overall = disposition(auth_states)
    if overall.startswith("REFUSE"):
        refused = sorted(
            name for name in AUTH_TARGET_TYPES if auth_states[name] != "exact"
        )
        raise AuthGateError(
            f"{overall}: refusing to plan auth activation: {', '.join(refused)}"
        )
    if not target_sha or len(target_sha) != 40:
        raise AuthGateError("target_sha must be an exact 40-character main SHA")

    bindings = _raw_bindings(settings_payload)
    seen: set[str] = set()
    for binding in bindings:
        canonical_binding(binding)
        name = str(binding.get("name"))
        if name in seen:
            raise AuthGateError("duplicate binding names in live settings")
        seen.add(name)

    ttl_text = str(session_max_age_text or "").strip()
    if ttl_text and not _session_max_age_ok(ttl_text):
        raise AuthGateError("session max age input is outside 300..2592000")

    patch_bindings: list[dict] = []
    changes: list[str] = []
    for binding in bindings:
        name = str(binding.get("name"))
        if name in AUTH_ALLOWLIST:
            continue
        patch_bindings.append(_inherit(name))

    desired = {
        AUTH_MODE_NAME: AUTH_MODE_EXPECTED,
        PUBLIC_BASE_URL_NAME: expected_public_base_url.strip(),
    }
    for name in sorted(desired):
        live = next((b for b in bindings if b.get("name") == name), None)
        candidate = desired[name]
        same = False
        if live is not None and live.get("type") == "plain_text":
            if name == AUTH_MODE_NAME:
                same = str(live.get("text", "")).strip().lower() == candidate
            else:
                same = str(live.get("text", "")).strip() == candidate
        if same:
            patch_bindings.append(_inherit(name))
        else:
            patch_bindings.append({"name": name, "type": "plain_text", "text": candidate})
            changes.append(f"AUTH_SET_{name}")

    client_live = next((b for b in bindings if b.get("name") == GOOGLE_CLIENT_ID_NAME), None)
    if client_live is not None and client_live.get("type") == "plain_text":
        # Client-id value stays deployment-owned; the plan asserts
        # presence/type only and never rewrites or echoes the live value.
        patch_bindings.append(_inherit(GOOGLE_CLIENT_ID_NAME))
    else:
        changes.append(f"AUTH_PLACEHOLDER_{GOOGLE_CLIENT_ID_NAME}")

    for name in (GOOGLE_CLIENT_SECRET_NAME, SESSION_SECRET_NAME):
        live = next((b for b in bindings if b.get("name") == name), None)
        if live is not None and live.get("type") == "secret_text":
            patch_bindings.append(_inherit(name))
        else:
            patch_bindings.append({"name": name, "type": "secret_text"})
            changes.append(f"AUTH_SECRET_PLACEHOLDER_{name}")

    ttl_live = next((b for b in bindings if b.get("name") == SESSION_MAX_AGE_NAME), None)
    if ttl_text:
        if (
            ttl_live is not None
            and ttl_live.get("type") == "plain_text"
            and str(ttl_live.get("text", "")).strip() == ttl_text
        ):
            patch_bindings.append(_inherit(SESSION_MAX_AGE_NAME))
        else:
            patch_bindings.append(
                {"name": SESSION_MAX_AGE_NAME, "type": "plain_text", "text": ttl_text}
            )
            changes.append(f"AUTH_SET_{SESSION_MAX_AGE_NAME}")
    elif ttl_live is not None:
        patch_bindings.append(_inherit(SESSION_MAX_AGE_NAME))

    payload = {
        "bindings": patch_bindings,
        "annotations": {
            "workers/message": f"B62 Google auth activation plan {target_sha}",
            "workers/triggered_by": "b62-google-auth-activation-gate",
        },
    }
    return {
        "payload": payload,
        "changes": sorted(changes),
        "no_op": not changes,
        "disposition": overall,
        "preserved": sum(1 for b in patch_bindings if b.get("type") == "inherit"),
    }


def _emit_states(auth_states: dict[str, str], prereq: dict[str, str]) -> None:
    for name in sorted(auth_states):
        print(f"AUTH_STATE {name}={auth_states[name]}")
    for name in PREREQ_NAMES:
        print(f"PREREQ_STATE {name}={prereq.get(name, 'missing')}")


def main(argv: list[str] | None = None) -> int:
    args_in = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("classify", "plan", "verify", "prereq"))
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--expected-public-base-url", default="")
    parser.add_argument("--session-max-age", default="")
    parser.add_argument("--target-sha", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(args_in)

    if not args.settings:
        print(f"usage: {args.command} requires --settings", file=sys.stderr)
        return 2
    if not args.expected_public_base_url:
        print(f"usage: {args.command} requires --expected-public-base-url", file=sys.stderr)
        return 2
    try:
        payload = json.loads(args.settings.read_text(encoding="utf-8"))
        auth_states = classify_auth_config(
            payload, expected_public_base_url=args.expected_public_base_url
        )
        prereq = read_prerequisites(payload)
    except (OSError, json.JSONDecodeError, AuthGateError,
            _deploy_config.ProductionConfigError) as exc:
        print(f"B62_GOOGLE_AUTH_{args.command.upper()}=FAIL\nREASON={exc}", file=sys.stderr)
        return 1

    if args.command == "prereq":
        _emit_states(auth_states, prereq)
        print(f"PREREQ_D1_EXACT={'PASS' if prereq.get(PREREQ_D1_NAME) == 'exact' else 'FAIL'}")
        print("PREREQ_IDENTITY_EXACT="
              f"{'PASS' if prereq.get(PREREQ_IDENTITY_NAME) == 'exact' else 'FAIL'}")
        print(f"PREREQ_R2_EXACT={'PASS' if prereq.get(PREREQ_R2_NAME) == 'exact' else 'FAIL'}")
        print("SECRET_VALUES_READ=0")
        print("SECRET_VALUES_EMITTED=0")
        missing = [n for n in PREREQ_NAMES if prereq.get(n) != "exact"]
        if missing:
            print("B62_GOOGLE_AUTH_PREREQ=INCOMPLETE "
                  f"MISSING={','.join(sorted(missing))}", file=sys.stderr)
            return 1
        print("B62_GOOGLE_AUTH_PREREQ=PASS")
        return 0

    overall = disposition(auth_states)
    if args.command in ("verify", "classify"):
        _emit_states(auth_states, prereq)
        print(f"B62_GOOGLE_AUTH_DISPOSITION={overall}")
        print("AUTH_VALUE_OUTPUT=0")
        print("SECRET_VALUES_READ=0")
        print("SECRET_VALUES_EMITTED=0")
        print("PRODUCTION_MUTATION=0")
        if args.command == "verify":
            if overall == "ALREADY_EXACT":
                print("B62_GOOGLE_AUTH_VERIFY=EXACT")
                return 0
            print(f"B62_GOOGLE_AUTH_VERIFY=INCOMPLETE\nDISPOSITION={overall}",
                  file=sys.stderr)
            return 1
        return 0 if not overall.startswith("REFUSE") else 1

    if not args.output or not args.target_sha:
        print("usage: plan requires --output and --target-sha", file=sys.stderr)
        return 2
    try:
        plan = build_activation_plan(
            payload,
            expected_public_base_url=args.expected_public_base_url,
            session_max_age_text=args.session_max_age,
            target_sha=args.target_sha,
        )
    except AuthGateError as exc:
        print(f"B62_GOOGLE_AUTH_PLAN=FAIL\nREASON={exc}", file=sys.stderr)
        return 1
    if args.output.exists():
        print("B62_GOOGLE_AUTH_PLAN=FAIL\nREASON=output path already exists", file=sys.stderr)
        return 1
    args.output.write_text(
        json.dumps(plan["payload"], separators=(",", ":")), encoding="utf-8"
    )
    _emit_states(auth_states, prereq)
    for change in plan["changes"]:
        print(f"CONFIG_CHANGE {change}")
    print(f"B62_GOOGLE_AUTH_PLAN=PASS DISPOSITION={overall}")
    print(f"B62_GOOGLE_AUTH_NO_OP={'1' if plan['no_op'] else '0'}")
    print("UNRELATED_BINDINGS_PRESERVED=PASS")
    print(f"PRESERVED_BINDINGS={plan['preserved']}")
    print("AUTH_VALUE_OUTPUT=0")
    print("SECRET_VALUES_READ=0")
    print("SECRET_VALUES_EMITTED=0")
    print("PRODUCTION_MUTATION=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
