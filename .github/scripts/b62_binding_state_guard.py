#!/usr/bin/env python3
"""Compare B62 Cloudflare Worker binding structure before and after deployment.

Secret values are never read. For each supported binding type, compare only the
fields that define its deployment authority. Accept either Worker settings or
immutable served-version payloads; D1 uses `id` in settings and `database_id`
in version details. The guard fails closed on unknown
binding types, malformed entries, duplicate names, additions, removals, or
field drift.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from b62_web_secrets_store_contract import expected_web_secret_bindings
from uuid import UUID

SUPPORTED_TYPES = {"assets", "service", "d1", "r2_bucket", "browser", "version_metadata", "plain_text", "secret_text", "secrets_store_secret"}
OWNER_P01_D1_BINDING = "BROWSER_CONTROL_OWNER_P01_D1"
# #4719 LOCAL1: default PC registration/WSS needs exactly this Broker binding
# plus these explicit Connector plain-text values. No other addition, removal,
# or value drift is permitted in this mode.
CONNECTOR_BROKER_BINDING = "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE"
CONNECTOR_BROKER_TARGET = "padiem-local-agent-broker-state"
CONNECTOR_EXPLICIT_VARS: dict[str, str] = {
    "PADIEM_CONNECTOR_GATEWAY_WSS_ENABLED": "enabled",
    "PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE": "owner-controlled-production-4139",
    "PADIEM_CONNECTOR_PRODUCTION_ENABLED": "enabled",
    "PADIEM_CONNECTOR_OWNER_ENROLLMENT_ENABLED": "enabled",
    "PADIEM_CONNECTOR_OWNER_PRODUCTION_ENABLED": "enabled",
    "PADIEM_CONNECTOR_OWNER_ONE_CLICK_ENABLED": "enabled",
    "PADIEM_CONNECTOR_OWNER_PC_IDENTITY_PREFLIGHT_ENABLED": "enabled",
    "PADIEM_CONNECTOR_OWNER_PC_NATIVE_DELIVERY_ENABLED": "enabled",
}


class BindingStateError(RuntimeError):
    pass


def _optional_text(raw: dict[str, Any], field: str) -> str | None:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise BindingStateError(f"binding field {field!r} must be a non-empty string when present")
    return value


def _required_text(raw: dict[str, Any], field: str) -> str:
    value = _optional_text(raw, field)
    if value is None:
        raise BindingStateError(f"binding field {field!r} is required")
    return value


def canonical_binding(raw: object) -> tuple[object, ...]:
    if not isinstance(raw, dict):
        raise BindingStateError("binding entry is not an object")
    kind = raw.get("type")
    name = raw.get("name")
    if kind not in SUPPORTED_TYPES:
        raise BindingStateError(f"unsupported binding type {kind!r}")
    if not isinstance(name, str) or not name:
        raise BindingStateError("binding name must be a non-empty string")

    if kind == "assets":
        return (kind, name)
    if kind == "browser":
        if name != "BROWSER":
            raise BindingStateError("unexpected Browser Rendering binding name")
        return (kind, name)
    if kind == "version_metadata":
        return (kind, name)
    if kind == "service":
        return (
            kind,
            name,
            _required_text(raw, "service"),
            _optional_text(raw, "environment"),
            _optional_text(raw, "entrypoint"),
        )
    if kind == "d1":
        # GET /settings uses "id"; GET /versions/{version} uses "database_id".
        # Refuse conflicting aliases instead of silently picking one.
        settings_id = _optional_text(raw, "id")
        version_id = _optional_text(raw, "database_id")
        if settings_id is not None and version_id is not None and settings_id != version_id:
            raise BindingStateError("conflicting D1 database identities")
        db_id = settings_id or version_id
        if db_id is None:
            raise BindingStateError("D1 database identity missing")
        return (kind, name, db_id)
    if kind == "r2_bucket":
        return (
            kind,
            name,
            _required_text(raw, "bucket_name"),
            _optional_text(raw, "jurisdiction"),
        )
    if kind == "secrets_store_secret":
        return (
            kind, name,
            _required_text(raw, "store_id"),
            _required_text(raw, "secret_name"),
        )
    if kind == "plain_text":
        text = raw.get("text")
        if not isinstance(text, str):
            raise BindingStateError(f"plain_text binding {name!r} has no string text")
        return (kind, name, text)
    # Secret values are not available from Worker settings and must never be read.
    return (kind, name)


def canonical_state(payload: object) -> tuple[tuple[object, ...], ...]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise BindingStateError("settings payload is not a successful Cloudflare response")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise BindingStateError("settings payload has no result object")
    if "bindings" in result:
        bindings = result["bindings"]  # GET /settings
    else:
        # GET /versions/{id}: verify the immutable version identity before use.
        identity = result.get("id")
        resources = result.get("resources")
        if not isinstance(identity, str) or not identity or not isinstance(resources, dict):
            raise BindingStateError("version payload identity or resources missing")
        bindings = resources.get("bindings")
    if isinstance(bindings, dict):
        # Version resources may be keyed by binding name. Match the canonical
        # Engine served-version guard: an embedded name must agree with its key.
        entries = []
        for key, value in bindings.items():
            if not isinstance(key, str) or not key or not isinstance(value, dict):
                raise BindingStateError("malformed keyed version binding")
            if "name" in value and value["name"] != key:
                raise BindingStateError("version binding key/name disagreement")
            entries.append({**value, "name": key})
        bindings = entries
    if not isinstance(bindings, list):
        raise BindingStateError("Worker payload has no bindings collection")

    canonical = [canonical_binding(binding) for binding in bindings]
    names = [entry[1] for entry in canonical]
    if len(names) != len(set(names)):
        raise BindingStateError("duplicate binding names")
    return tuple(sorted(canonical, key=lambda entry: (str(entry[0]), str(entry[1]))))


def assert_preserved(before: object, after: object) -> None:
    before_state = canonical_state(before)
    after_state = canonical_state(after)
    if before_state != after_state:
        before_set = set(before_state)
        after_set = set(after_state)
        removed = sorted(before_set - after_set, key=repr)
        added = sorted(after_set - before_set, key=repr)
        raise BindingStateError(
            "binding authority drift detected; "
            f"removed_count={len(removed)} added_count={len(added)}"
        )



# #4194 guarded one-time Engine rollout after #4304:
# the existing Engine has 18 bindings; canonical main adds precisely the
# named Hark B62 D1 reference plus one non-secret Agent lease enable var.
# Never allow arbitrary additions/removals/identity drift in this mode.
_ENGINE_4194_APPROVED_ADDITIONS = frozenset({
    ("d1", "WEB_XLSX_PRIVATE_B62_D1", "702bb62b-36f5-41a0-973f-c4f663ee01e6"),
    ("plain_text", "PADIEM_ENGINE_AGENT_DURABLE_ENABLED", "true"),
})
# The observability release adds one *existing* Grafana Secrets Store reference,
# never a token value. Preserve every prior Engine binding and reject any other
# new identity (including another store, secret name, or binding type).
_ENGINE_GRAFANA_APPROVED_ADDITION = (
    "secrets_store_secret", "PADIEM_GRAFANA_OTLP_TOKEN",
    "f0b09ca04a7b43248154c773704a5616", "PADIEM_GRAFANA_OTLP_TOKEN",
)


def assert_exact_b66_membership_secret_only(before: object, after: object) -> None:
    """Single explicitly permitted B66 secret binding, preserving every other binding.

    This permits metadata-only preservation of an existing concurrent B66
    membership enforcement secret during a B62 code-only release. It does not
    read or set a secret value. Once already served, exact equality is required.
    """
    old = set(canonical_state(before))
    new = set(canonical_state(after))
    allowed = ("secret_text", "B66_MEMBERSHIP_ENFORCED")
    if allowed in old:
        if old != new:
            raise BindingStateError("B66 membership already served; unrelated authority drift")
    elif new != old | {allowed}:
        raise BindingStateError("expected only exact B66 membership secret addition")


def assert_exact_grafana_telemetry_added_only(before: object, after: object) -> None:
    """One explicit, metadata-only Grafana Secrets Store addition; no other drift."""
    prior = set(canonical_state(before))
    current = set(canonical_state(after))
    approved = _ENGINE_GRAFANA_APPROVED_ADDITION
    if approved in prior:
        if prior != current:
            raise BindingStateError("Grafana binding already present; unrelated authority drift")
    elif current != prior | {approved}:
        raise BindingStateError("expected only exact existing Grafana Secrets Store reference")


def assert_engine_4194_exact_rollout(before: object, after: object) -> None:
    """Preserve ALL previous bindings; permit only two exact reviewed additions.

    Already-commissioned bindings may be present in the before version, to
    keep later no-drift code redeploys valid. The after version MUST contain
    both approved identities and no unreviewed changes.
    """
    prior, current = set(canonical_state(before)), set(canonical_state(after))
    if not _ENGINE_4194_APPROVED_ADDITIONS.issubset(current):
        raise BindingStateError("Engine #4194 required exact binding identities missing")
    removed = prior - current
    added = current - prior
    allowed = _ENGINE_4194_APPROVED_ADDITIONS | {_ENGINE_GRAFANA_APPROVED_ADDITION}
    if removed or not added.issubset(allowed):
        raise BindingStateError(
            "Engine #4194 binding authority drift detected; "
            f"removed_count={len(removed)} unexpected_added_count="
            f"{len(added - allowed)}"
        )


def assert_hark_browser_added_only(before: object, after: object) -> None:
    """Exactly one owner-approved BROWSER addition; no other authority change.

    Idempotent when BROWSER is already present with its original type. Normal
    code deployments still require exact equality unless this mode is explicit.
    """
    old = canonical_state(before)
    new = canonical_state(after)
    expected = ("browser", "BROWSER")
    if any(item[1] == "BROWSER" and item != expected for item in old):
        raise BindingStateError("pre-existing Browser alias/type collision")
    if expected in old:
        if old != new:
            raise BindingStateError("Browser already present; unrelated authority drift")
    else:
        required = tuple(sorted((*old, expected), key=lambda item: (str(item[0]), str(item[1]))))
        if new != required:
            raise BindingStateError("expected exactly one approved BROWSER addition")


def _normalized_connector_broker_entry(entry: tuple[object, ...]) -> tuple[object, ...]:
    """Normalize ONLY the canonical Connector Broker binding's default env.

    The live API echoes the stored binding with environment=production while
    the generated config omits it; both name the same default production
    target. A non-service collision, a different target, any entrypoint, or
    any other environment still fails closed. All other services keep exact
    comparison; this normalization never applies to them.
    """
    if entry[1] != CONNECTOR_BROKER_BINDING:
        return entry
    if entry[0] != "service":
        raise BindingStateError("Connector Broker binding type collision")
    if entry[2] != CONNECTOR_BROKER_TARGET:
        raise BindingStateError("Connector Broker target drift")
    if entry[4] is not None:
        raise BindingStateError("Connector Broker entrypoint drift")
    if entry[3] not in (None, "production"):
        raise BindingStateError("Connector Broker environment drift")
    return ("service", CONNECTOR_BROKER_BINDING, CONNECTOR_BROKER_TARGET, None, None)


CONNECTOR_APPROVED_NAMES = frozenset(
    {CONNECTOR_BROKER_BINDING} | set(CONNECTOR_EXPLICIT_VARS)
)


def assert_connector_baseline_consistent(version_payload: object, settings_payload: object) -> str:
    """The mutable settings plane may differ from the active immutable version
    ONLY by the approved Broker binding plus explicit Connector settings.

    Returns FRESH (identical, deploy adds the 9), RESIDUE (settings already
    carry exactly the approved additions, e.g. after a rolled-back upload;
    deploy reuses them), or SERVED (both already carry them). Anything else —
    drops, unreviewed additions, or wrong identities on either side — fails
    closed. Pre-existing non-Connector bindings are compared by name only so
    API response-shape differences can never mask or invent drift here; their
    exact preservation is proven by the settings-to-settings post-deploy
    guard instead.
    """
    version_entries = {entry[1]: entry for entry in canonical_state(version_payload)}
    settings_entries = {entry[1]: entry for entry in canonical_state(settings_payload)}
    version_names = set(version_entries)
    settings_names = set(settings_entries)
    dropped = version_names - settings_names
    if dropped:
        raise BindingStateError(
            "active version bindings missing from settings; refusing to cement a drop"
        )
    extra = settings_names - version_names
    if not extra.issubset(CONNECTOR_APPROVED_NAMES):
        raise BindingStateError(
            "settings carry unreviewed additions beyond the active version"
        )
    for name in CONNECTOR_APPROVED_NAMES:
        for entries in (version_entries, settings_entries):
            if name not in entries:
                continue
            entry = entries[name]
            if name == CONNECTOR_BROKER_BINDING:
                _normalized_connector_broker_entry(entry)
            elif entry != ("plain_text", name, CONNECTOR_EXPLICIT_VARS[name]):
                raise BindingStateError(f"Connector setting drift on {name!r}")
    if not extra:
        return "SERVED" if CONNECTOR_BROKER_BINDING in settings_names else "FRESH"
    return "RESIDUE"


def assert_connector_broker_added_only(before: object, after: object) -> None:
    """Only the canonical Broker binding plus explicit Connector vars may appear.

    Idempotent when the Broker binding and all explicit Connector values are
    already present with exact identities. Normal code deployments still
    require exact equality unless this mode is explicit. Removal of any
    pre-existing binding, any non-allowlisted addition, or any value drift
    (including a drifted Connector value) fails closed.
    """
    old = tuple(_normalized_connector_broker_entry(entry) for entry in canonical_state(before))
    new = tuple(_normalized_connector_broker_entry(entry) for entry in canonical_state(after))
    broker_entry = ("service", CONNECTOR_BROKER_BINDING, CONNECTOR_BROKER_TARGET, None, None)
    allowed_additions = {broker_entry} | {
        ("plain_text", name, text) for name, text in CONNECTOR_EXPLICIT_VARS.items()
    }
    old_set, new_set = set(old), set(new)
    # A colliding pre-existing Broker alias/target must never pass.
    for entry in old:
        if entry[1] == CONNECTOR_BROKER_BINDING and entry != broker_entry:
            raise BindingStateError("pre-existing Connector Broker alias/type collision")
    # Drifted pre-existing Connector values are deployment drift, not an addition.
    for entry in old:
        if entry[0] == "plain_text" and entry[1] in CONNECTOR_EXPLICIT_VARS:
            if entry != ("plain_text", entry[1], CONNECTOR_EXPLICIT_VARS[entry[1]]):
                raise BindingStateError("Connector setting drift detected before additive install")
    if broker_entry in old_set and all(
        ("plain_text", name, text) in old_set for name, text in CONNECTOR_EXPLICIT_VARS.items()
    ):
        if old != new:
            raise BindingStateError("Connector Broker already served; unrelated authority drift")
        return
    removed = old_set - new_set
    added = new_set - old_set
    if removed:
        raise BindingStateError(
            "binding authority drift detected; "
            f"removed_count={len(removed)} unexpected_added_count={len(added - allowed_additions)}"
        )
    if not added.issubset(allowed_additions):
        raise BindingStateError(
            "binding authority drift; expected only canonical Broker binding "
            "and explicit Connector setting additions"
        )
    if broker_entry not in old_set and broker_entry not in added:
        raise BindingStateError("expected canonical Connector Broker binding addition")


def assert_claw_public_search_added_only(before: object, after: object) -> None:
    """Exactly the owner-approved public search ON flag; no other binding drift.

    Existing exact ON is idempotent. Missing adds the one plain-text variable.
    Any existing OFF/secret binding, unrelated addition, removal or value change
    fails closed before the protected production workflow accepts deployment.
    """
    flag = "PADIEM_CLAW_PUBLIC_WEB_SEARCH_ENABLED"
    exact = ("plain_text", flag, "true")
    old = set(canonical_state(before))
    new = set(canonical_state(after))
    if any(entry[1] == flag and entry != exact for entry in old):
        raise BindingStateError("existing Claw public search binding conflicts with owner-approved ON")
    if old - new or (new - old) - {exact} or exact not in new:
        raise BindingStateError("unexpected binding drift in Claw public search activation")


def assert_web_secret_additions_only(before: object, after: object) -> None:
    """Only missing Owner-approved same-account Secret Store entries may appear."""
    original = canonical_state(before)
    final = canonical_state(after)
    existing_names = {entry[1] for entry in original}
    expected = {
        name: canonical_binding(item)
        for name, item in expected_web_secret_bindings().items()
    }
    # If already installed, require existing identity exactly; never overwrite.
    for name, target in expected.items():
        original_match = [entry for entry in original if entry[1] == name]
        if original_match and original_match != [target]:
            raise BindingStateError("web Secrets Store binding alias collision")
    additions = tuple(target for name, target in expected.items() if name not in existing_names)
    required = tuple(sorted((*original, *additions), key=lambda e: (str(e[0]), str(e[1]))))
    if final != required:
        raise BindingStateError("binding authority drift; expected only exact web Secrets Store additions")


def validate_owner_d1_id(value: str) -> str:
    """Accept one canonical UUID, never reveal it in failure diagnostics."""
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise BindingStateError("approved Owner D1 ID is not a UUID") from exc
    if str(parsed) != value or parsed.int == 0:
        raise BindingStateError("approved Owner D1 ID must be a nonzero canonical UUID")
    return value


def assert_one_owner_d1_added(before: object, after: object, owner_database_id: str) -> None:
    """Allow exactly one approved Owner D1 addition, preserving all other authority."""
    db_id = validate_owner_d1_id(owner_database_id)
    before_state = canonical_state(before)
    after_state = canonical_state(after)
    if any(entry[1] == OWNER_P01_D1_BINDING for entry in before_state):
        raise BindingStateError("Owner D1 binding already exists before additive install")
    # Never accidentally bind the Owner click database to the Engine or Chat D1.
    if any(entry[0] == "d1" and entry[2] == db_id for entry in before_state):
        raise BindingStateError("Owner D1 aliases an existing Worker D1")
    expected = tuple(sorted(
        (*before_state, ("d1", OWNER_P01_D1_BINDING, db_id)),
        key=lambda entry: (str(entry[0]), str(entry[1])),
    ))
    if after_state != expected:
        raise BindingStateError("binding authority drift detected; expected only approved Owner D1 addition")


def assert_owner_version_integrity(before: object, after: object, owner_database_id: str) -> None:
    """Require immutable served-version code/runtime parity alongside one D1 addition.

    A binding-only equality check cannot prove that a PATCH or deployment
    preserved Python Worker code, assets, compatibility flags or runtime config.
    Compare the exact original and candidate immutable version resources, never
    mutable Worker settings. Fail closed on missing version/resource evidence.
    """

    def version_resources(payload: object) -> tuple[str, dict[str, object]]:
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise BindingStateError("immutable Worker version evidence missing")
        result = payload.get("result")
        if not isinstance(result, dict) or "bindings" in result:
            raise BindingStateError("immutable Worker version result required")
        version_id = result.get("id")
        resources = result.get("resources")
        if not isinstance(version_id, str) or not version_id:
            raise BindingStateError("Worker version identity missing")
        if not isinstance(resources, dict):
            raise BindingStateError("Worker version resources missing")
        script = resources.get("script")
        runtime = resources.get("script_runtime")
        if not isinstance(script, dict) or not isinstance(script.get("etag"), str) or not script["etag"]:
            raise BindingStateError("Worker script content identity missing")
        if not isinstance(runtime, dict):
            raise BindingStateError("Worker runtime identity missing")
        if not isinstance(runtime.get("compatibility_date"), str) or not runtime["compatibility_date"]:
            raise BindingStateError("Worker runtime compatibility identity missing")
        if "bindings" not in resources:
            raise BindingStateError("Worker immutable binding resources missing")
        return version_id, resources

    before_id, old = version_resources(before)
    after_id, new = version_resources(after)
    if before_id == after_id:
        raise BindingStateError("Worker served version did not change")
    # Compare every non-binding resource, including opaque assets descriptors;
    # no raw script, settings, secrets, or fingerprints reach diagnostics.
    if old.keys() != new.keys():
        raise BindingStateError("Worker non-binding resource structure drift")
    if any(old[key] != new[key] for key in old if key != "bindings"):
        raise BindingStateError("Worker script, assets, or runtime authority drift")
    assert_one_owner_d1_added(before, after, owner_database_id)


def _load(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BindingStateError(f"cannot read settings payload: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--expected-add-owner-d1", action="store_true")
    parser.add_argument("--expected-add-web-secrets-store", action="store_true")
    parser.add_argument("--expected-engine-4194-rollout", action="store_true")
    parser.add_argument("--expected-add-grafana-telemetry", action="store_true",
                        help="only one canonical Grafana Secrets Store binding, no values")
    parser.add_argument("--expected-add-hark-browser", action="store_true")
    parser.add_argument("--expected-add-connector-broker", action="store_true")
    parser.add_argument("--expected-add-claw-public-search", action="store_true")
    parser.add_argument("--check-connector-baseline", action="store_true",
                        help="compare active immutable version (--before) against mutable "
                             "settings (--after); the settings may only add the approved "
                             "Connector 9")
    parser.add_argument("--expected-add-b66-membership-secret", action="store_true")
    parser.add_argument("--owner-d1-database-id")
    parser.add_argument("--require-served-resource-integrity", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if sum((
            args.expected_add_owner_d1,
            args.expected_add_web_secrets_store,
            args.expected_engine_4194_rollout,
            args.expected_add_grafana_telemetry,
            args.expected_add_hark_browser,
            args.expected_add_connector_broker,
            args.expected_add_claw_public_search,
            args.check_connector_baseline,
            args.expected_add_b66_membership_secret,
        )) > 1:
            raise BindingStateError("multiple additive authority modes prohibited")
        if args.expected_engine_4194_rollout:
            if args.owner_d1_database_id is not None or args.require_served_resource_integrity:
                raise BindingStateError("Engine #4194 mode refuses unrelated authorization arguments")
            assert_engine_4194_exact_rollout(_load(args.before), _load(args.after))
        elif args.expected_add_grafana_telemetry:
            if args.owner_d1_database_id is not None or args.require_served_resource_integrity:
                raise BindingStateError("Grafana additive mode refuses unrelated authority flags")
            assert_exact_grafana_telemetry_added_only(_load(args.before), _load(args.after))
        elif args.expected_add_claw_public_search:
            if args.owner_d1_database_id is not None or args.require_served_resource_integrity:
                raise BindingStateError("Claw search mode refuses unrelated authority flags")
            assert_claw_public_search_added_only(_load(args.before), _load(args.after))
        elif args.expected_add_hark_browser:
            if args.owner_d1_database_id is not None or args.require_served_resource_integrity:
                raise BindingStateError("Hark Browser mode refuses unrelated authorization flags")
            assert_hark_browser_added_only(_load(args.before), _load(args.after))
        elif args.expected_add_connector_broker:
            if args.owner_d1_database_id is not None or args.require_served_resource_integrity:
                raise BindingStateError("Connector Broker mode refuses unrelated authorization flags")
            assert_connector_broker_added_only(_load(args.before), _load(args.after))
        elif args.check_connector_baseline:
            if args.owner_d1_database_id is not None or args.require_served_resource_integrity:
                raise BindingStateError("Connector baseline mode refuses unrelated authorization flags")
            baseline_mode = assert_connector_baseline_consistent(
                _load(args.before), _load(args.after)
            )
            print(f"CONNECTOR_BASELINE_MODE={baseline_mode}")
        elif args.expected_add_b66_membership_secret:
            if args.owner_d1_database_id is not None or args.require_served_resource_integrity:
                raise BindingStateError("B66 membership secret mode refuses unrelated authority flags")
            assert_exact_b66_membership_secret_only(_load(args.before), _load(args.after))
        elif args.expected_add_web_secrets_store:
            assert_web_secret_additions_only(_load(args.before), _load(args.after))
        elif args.expected_add_owner_d1:
            if args.owner_d1_database_id is None:
                raise BindingStateError("additive mode requires explicit Owner D1 ID")
            before_payload = _load(args.before)
            after_payload = _load(args.after)
            # Never allow real immutable Worker versions through a binding-only
            # guard just because the caller forgot a CLI safety flag.
            version_evidence = any(
                isinstance(p, dict)
                and isinstance(p.get("result"), dict)
                and "resources" in p["result"]
                for p in (before_payload, after_payload)
            )
            if args.require_served_resource_integrity or version_evidence:
                assert_owner_version_integrity(
                    before_payload, after_payload, args.owner_d1_database_id
                )
            else:
                assert_one_owner_d1_added(
                    before_payload, after_payload, args.owner_d1_database_id
                )
        else:
            if args.require_served_resource_integrity:
                raise BindingStateError("served resource verification requires additive mode")
            if args.owner_d1_database_id is not None:
                raise BindingStateError("Owner D1 ID is not accepted in standard equality mode")
            assert_preserved(_load(args.before), _load(args.after))
    except BindingStateError as exc:
        print("B62_BINDING_AUTHORITY_PRESERVED=FAIL", file=sys.stderr)
        print(f"REASON={exc}", file=sys.stderr)
        return 1
    if args.expected_engine_4194_rollout:
        print("ENGINE_4194_EXACT_ADDITIONS_AND_PREEXISTING_BINDINGS_PRESERVED=PASS")
    elif args.check_connector_baseline:
        print("CONNECTOR_BASELINE_CONSISTENT=PASS")
    elif args.expected_add_owner_d1:
        print("OWNER_P01_D1_EXACTLY_ONE_ADDITION=PASS")
        print("EXISTING_WORKER_BINDINGS_PRESERVED=PASS")
        if args.require_served_resource_integrity or version_evidence:
            print("OWNER_P01_D1_SERVED_RESOURCE_INTEGRITY=PASS")
    else:
        print("B62_BINDING_AUTHORITY_PRESERVED=PASS")
    print("SECRET_VALUES_READ=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
