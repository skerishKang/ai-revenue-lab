#!/usr/bin/env python3
"""Build the exact production wrangler config for one B62 production code deploy.

The repository wrangler.toml is the authority for binding declarations.
Live plain-text values are preserved unless explicitly changed. The source supplies build inputs
(entrypoint, compatibility, assets directory) and the declared observability
settings passed through pywrangler to the Worker upload metadata. Secret
bindings are carried by the platform and are never read or emitted here. Anything unsupported fails
closed so no live binding can be silently dropped by a code deploy.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from uuid import UUID

import tomllib

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from b62_web_secrets_store_contract import (
    expected_b14_service_proof_bindings,
    expected_claw_desktop_bindings,
    expected_oracle_mesh_bindings,
    expected_resend_alert_bindings,
    expected_web_secret_bindings,
    require_exact_web_secrets_store,
)

EXPECTED_WORKER = "padiem-chat"
OWNER_P01_D1_BINDING = "BROWSER_CONTROL_OWNER_P01_D1"
GRAFANA_OTLP_BINDING = {
    "type": "secrets_store_secret", "name": "PADIEM_GRAFANA_OTLP_TOKEN",
    "store_id": "f0b09ca04a7b43248154c773704a5616",
    "secret_name": "PADIEM_GRAFANA_OTLP_TOKEN",
}
GRAFANA_OTLP_PUBLIC_VARS = {
    "PADIEM_GRAFANA_OTLP_ENDPOINT": "https://otlp-gateway-prod-ap-northeast-0.grafana.net/otlp/v1/logs",
    "PADIEM_GRAFANA_OTLP_USERNAME": "1876517",
}
SUPPORTED_BINDING_TYPES = {"assets", "service", "d1", "r2_bucket", "browser", "plain_text", "secret_text", "version_metadata", "secrets_store_secret"}
HARK_BROWSER_BINDING = "BROWSER"
# #4139 opt-in candidate builder only: never activated via production CLI.
CONNECTOR_BROKER_BINDING = "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE"
CONNECTOR_BROKER_TARGET = "padiem-local-agent-broker-state"
CONNECTOR_IDENTITY_BINDING = "IDENTITY_AUTHORITY_SERVICE"
CONNECTOR_IDENTITY_TARGET = "padiem-control-plane-identity"
# #4719 LOCAL1: default registration/WSS needs exactly these existing Connector
# plain-text values. Explicit allowlist only — never copy the source [vars]
# table wholesale, and never touch b14/live/base-url/operational settings.
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
CLAW_SEARCH_FLAG = "PADIEM_CLAW_PUBLIC_WEB_SEARCH_ENABLED"
REQUIRED_VARS = ("PADIEM_CHAT_RUNTIME_MODE", "PADIEM_CHAT_LIVE_ENABLED")
PUBLIC_BASE_URL_VAR = "PADIEM_CHAT_PUBLIC_BASE_URL"
# #3252: a live version_metadata binding is runtime provenance. Exactly one may
# exist, its name must be a bounded identifier, and it is preserved verbatim —
# never invented and never dropped.
_BINDING_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


class ProductionConfigError(RuntimeError):
    pass


def _toml_string(value: str) -> str:
    return json.dumps(value)


def live_binding_entries(payload: object) -> list[dict]:
    """Return the binding entries of either Cloudflare plane.

    ``GET /settings`` describes the newest *uploaded* version. A deploy that served a
    version and then refused it at its own post-deploy audit leaves that plane
    carrying the refused upload's additions, so a generated production config that
    copied bindings from here would inherit a residue no traffic ever ran. The served
    version is the authority, and ``GET /versions/{id}`` carries exactly what is
    answering requests.

    Both shapes are read with the same rules the reviewed baseline and the binding
    state guard already use, and a version payload is only accepted once its own
    identity is present.
    """

    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ProductionConfigError("settings payload is not a successful Cloudflare API response")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ProductionConfigError("settings payload has no result object")
    if "bindings" in result:
        bindings = result["bindings"]
    else:
        identity = result.get("id")
        resources = result.get("resources")
        if not isinstance(identity, str) or not identity or not isinstance(resources, dict):
            raise ProductionConfigError("version payload identity or resources missing")
        bindings = resources.get("bindings")
    if isinstance(bindings, dict):
        entries = []
        for key, value in bindings.items():
            if not isinstance(key, str) or not key or not isinstance(value, dict):
                raise ProductionConfigError("malformed keyed version binding")
            if "name" in value and value["name"] != key:
                raise ProductionConfigError("version binding key/name disagreement")
            entries.append({**value, "name": key})
        bindings = entries
    if not isinstance(bindings, list) or not bindings:
        raise ProductionConfigError("settings payload has no bindings array")
    return bindings


def parse_live_bindings(settings_payload: object) -> dict[str, object]:
    bindings = live_binding_entries(settings_payload)

    names: list[str] = []
    assets: list[dict] = []
    services: list[dict] = []
    d1: list[dict] = []
    r2: list[dict] = []
    plain_vars: dict[str, str] = {}
    secret_names: list[str] = []
    secrets_store: list[dict] = []
    version_metadata: list[dict] = []
    browser: list[dict] = []
    for raw in bindings:
        if not isinstance(raw, dict):
            raise ProductionConfigError("binding entry is not an object")
        kind = raw.get("type")
        name = raw.get("name")
        if kind not in SUPPORTED_BINDING_TYPES:
            raise ProductionConfigError(
                f"unsupported live binding type {kind!r} on {name!r}; refusing to drop bindings"
            )
        if not isinstance(name, str) or not name:
            raise ProductionConfigError("live binding without a usable name")
        names.append(name)
        if kind == "assets":
            assets.append(raw)
        elif kind == "service":
            services.append(raw)
        elif kind == "d1":
            d1.append(raw)
        elif kind == "r2_bucket":
            bucket_name = raw.get("bucket_name")
            if not isinstance(bucket_name, str) or not bucket_name:
                raise ProductionConfigError(f"r2 binding {name!r} has no bucket_name")
            jurisdiction = raw.get("jurisdiction")
            if jurisdiction is not None and jurisdiction not in {"eu", "fedramp", "fedramp-high", "us"}:
                raise ProductionConfigError(f"r2 binding {name!r} has unsupported jurisdiction")
            r2.append(raw)
        elif kind == "browser":
            browser.append(raw)
        elif kind == "plain_text":
            text = raw.get("text")
            if not isinstance(text, str):
                raise ProductionConfigError(f"plain_text binding {name!r} has no text value")
            plain_vars[name] = text
        elif kind == "secrets_store_secret":
            if not _BINDING_NAME_RE.fullmatch(name):
                raise ProductionConfigError("Secrets Store binding name invalid")
            store_id = raw.get("store_id")
            secret_name = raw.get("secret_name")
            if not isinstance(store_id, str) or not re.fullmatch(r"[a-f0-9]{32}", store_id):
                raise ProductionConfigError("Secrets Store store_id invalid")
            if not isinstance(secret_name, str) or not _BINDING_NAME_RE.fullmatch(secret_name):
                raise ProductionConfigError("Secrets Store secret_name invalid")
            secrets_store.append({"type": kind, "name": name, "store_id": store_id, "secret_name": secret_name})
        elif kind == "version_metadata":
            if not _BINDING_NAME_RE.fullmatch(name):
                raise ProductionConfigError(
                    f"version_metadata binding name {name!r} is not a bounded identifier"
                )
            version_metadata.append(raw)
        else:
            secret_names.append(name)
    if len(names) != len(set(names)):
        raise ProductionConfigError("duplicate binding names in live settings")
    if len(version_metadata) > 1:
        raise ProductionConfigError("duplicate version_metadata bindings in live settings")
    if len(browser) > 1:
        raise ProductionConfigError("duplicate Browser Rendering bindings in live settings")
    return {
        "assets": assets,
        "services": services,
        "d1": d1,
        "r2": r2,
        "vars": plain_vars,
        "secret_names": secret_names,
        "secrets_store": secrets_store,
        "version_metadata": version_metadata[0] if version_metadata else None,
        "browser": browser[0] if browser else None,
        "entries": bindings,
    }


def _observability_config_lines(observability: object) -> list[str]:
    """Carry repository logging intent into Wrangler's upload metadata.

    pywrangler proxies deploy --config to Wrangler, which serializes this table
    as metadata.observability. Never substitute the already-disabled live state
    or force a hardcoded enabled/sampling value over the repository setting.
    """
    if observability is None:
        return []
    if not isinstance(observability, dict) or set(observability) - {"enabled", "head_sampling_rate", "logs"}:
        raise ProductionConfigError("unsupported repository [observability] settings")
    lines: list[str] = []
    for name, table, allowed in (
        ("observability", observability, {"enabled", "head_sampling_rate", "logs"}),
        ("observability.logs", observability.get("logs"), {"enabled", "head_sampling_rate", "invocation_logs"}),
    ):
        if table is None:
            continue
        if not isinstance(table, dict) or set(table) - allowed or type(table.get("enabled")) is not bool:
            raise ProductionConfigError(f"invalid repository [{name}] settings")
        lines.extend(["", f"[{name}]"])
        for key, value in table.items():
            if key == "logs":
                continue
            if key == "head_sampling_rate":
                if type(value) not in (int, float) or not 0 <= value <= 1:
                    raise ProductionConfigError(f"invalid repository [{name}].head_sampling_rate")
            elif type(value) is not bool:
                raise ProductionConfigError(f"invalid repository [{name}].{key}")
            lines.append(f"{key} = {json.dumps(value)}")
    return lines


from b62_repo_binding_authority import (
    BindingAuthorityError, binding_diff, emit_diff, enforce_removal,
    index, inventory, verify_expected,
)


def _vars_plan(live, repo, set_var, allow_binding_removal):
    values = dict(live["vars"])
    for name, value in repo.get("vars", {}).items():
        values.setdefault(name, value)
    for name, value in (set_var or {}).items():
        if not _BINDING_NAME_RE.fullmatch(name):
            raise ProductionConfigError("invalid set_var name")
        if name not in values:
            raise ProductionConfigError("set_var requires an existing or repository-declared variable")
        if value is None:
            if not allow_binding_removal:
                raise ProductionConfigError("variable removal requires allow_binding_removal=true")
            values.pop(name, None)
        elif not isinstance(value, str):
            raise ProductionConfigError("set_var values must be strings or null")
        else:
            values[name] = value
    return values


def production_plan(live, repo, *, allow_binding_removal=False, set_var=None):
    expected = inventory(repo)
    values = _vars_plan(live, repo, set_var, allow_binding_removal)
    for name in values:
        if name in expected:
            raise ProductionConfigError("variable/binding name collision: " + name)
        expected[name] = {"name": name, "type": "plain_text"}
    before = index(live["entries"])
    diff = binding_diff(before, expected)
    # Variable values are deliberately excluded from identities and output.
    changed_names = {x["name"] for x in diff["changed"]}
    for name in sorted(set(live["vars"]) & set(values)):
        if live["vars"][name] != values[name] and name not in changed_names:
            diff["changed"].append({"name": name, "type": "plain_text", "previous_type": "plain_text"})
    emit_diff(diff)
    enforce_removal(diff, allow_binding_removal)
    return expected, values


def build_production_config(live, repo_config_path, public_base_url,
                            *, allow_binding_removal=False, set_var=None):
    source = repo_config_path.read_text(encoding="utf-8")
    repo = tomllib.loads(source)
    if repo.get("name") != EXPECTED_WORKER:
        raise ProductionConfigError("repository Worker name mismatch")
    if not repo.get("main") or not repo.get("compatibility_date"):
        raise ProductionConfigError("repository build configuration incomplete")
    _observability_config_lines(repo.get("observability"))
    expected, variables = production_plan(live, repo, allow_binding_removal=allow_binding_removal, set_var=set_var)
    if variables.get(PUBLIC_BASE_URL_VAR) != public_base_url:
        raise ProductionConfigError("public base URL must match the canonical deploy origin")
    # Keep repository binding declarations/build settings byte-for-byte. Only
    # [vars] is composed from live values + new repo names + explicit set_var.
    var_lines = "[vars]\n" + "\n".join(f"{_toml_string(k)} = {_toml_string(v)}" for k, v in sorted(variables.items())) + "\n\n"
    pattern = r"(?ms)^\[vars\][^\n]*\n.*?(?=^\[|\Z)"
    if re.search(pattern, source):
        source = re.sub(pattern, lambda _: var_lines, source, count=1)
    else:
        source += "\n" + var_lines
    # Never serialize secret_text payloads; [secrets].required contains names only.
    generated = tomllib.loads(source)
    actual = inventory(generated)
    actual.update({n: {"name": n, "type": "plain_text"} for n in generated.get("vars", {})})
    verify_expected(expected, actual)
    return source


def build_recovery_config(live, repo_config_path):
    """The existing pinned incident recovery restores its recorded inventory.

    This is not a new-code release. Its caller must pass the already validated
    immutable recovery snapshot and the protected recovery confirmation.
    """
    repo = tomllib.loads(repo_config_path.read_text())
    lines = []
    for key in ("name", "main", "compatibility_date", "compatibility_flags", "base_dir"):
        if key in repo: lines.append(f"{key} = {json.dumps(repo[key])}")
    lines += ["workers_dev = true", "preview_urls = true"]
    lines.extend(_observability_config_lines(repo.get("observability")))
    for key in ("build", "assets"):
        lines += ["", f"[{key}]"]
        lines += [f"{k} = {json.dumps(v)}" for k,v in repo[key].items()]
    lines += ["", "[[routes]]", 'pattern = "chat.padiem.net"', "custom_domain = true"]
    for entry in live["entries"]:
        kind, name = entry["type"], entry["name"]
        if kind in {"assets", "plain_text", "secret_text"}: continue
        if kind in {"browser", "version_metadata"}:
            lines += ["", f"[{kind}]", f"binding = {json.dumps(name)}"]
            continue
        table, fields = {
            "service": ("services", {"service":"service", "environment":"environment", "entrypoint":"entrypoint"}),
            "d1": ("d1_databases", {"id":"database_id"}),
            "r2_bucket": ("r2_buckets", {"bucket_name":"bucket_name", "jurisdiction":"jurisdiction"}),
            "secrets_store_secret": ("secrets_store_secrets", {"store_id":"store_id", "secret_name":"secret_name"}),
        }[kind]
        lines += ["", f"[[{table}]]", f"binding = {json.dumps(name)}"]
        lines += [f"{dest} = {json.dumps(entry[src])}" for src,dest in fields.items() if entry.get(src) is not None]
        if kind == "d1": lines.append('database_name = "padiem-chat-db"')
    lines += ["", "[secrets]", "required = " + json.dumps(live["secret_names"]), "", "[vars]"]
    lines += [f"{json.dumps(k)} = {json.dumps(v)}" for k,v in sorted(live["vars"].items())]
    return "\n".join(lines) + "\n"


def verify_mutation_zero(config_text, live):
    """Compatibility helper for other read-only tools: existing vars stay intact."""
    actual = tomllib.loads(config_text).get("vars", {})
    if any(actual.get(n) != v for n, v in live["vars"].items()):
        raise ProductionConfigError("generated config changes an existing variable without an explicit plan")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", required=True, type=Path)
    parser.add_argument("--repo-config", required=True, type=Path)
    parser.add_argument("--public-base-url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-binding-removal", action="store_true")
    parser.add_argument("--dispatch-event", type=Path, help="Read set_var privately from the GitHub event file")
    parser.add_argument("--planned-d1-settings", type=Path)
    parser.add_argument("--verify-served", type=Path)
    parser.add_argument("--recovery-snapshot", action="store_true")
    args = parser.parse_args(argv)
    try:
        live = parse_live_bindings(json.loads(args.settings.read_text()))
        repo = tomllib.loads(args.repo_config.read_text())
        changes = {}
        if args.dispatch_event:
            event = json.loads(args.dispatch_event.read_text())
            changes = json.loads(event.get("inputs", {}).get("set_var") or "{}")
            if not isinstance(changes, dict):
                raise ProductionConfigError("set_var must be a JSON object")
        if args.recovery_snapshot:
            event = json.loads(args.dispatch_event.read_text()) if args.dispatch_event else {}
            inputs = event.get("inputs", {})
            if inputs.get("mode") != "recover_p01_sse_off" or inputs.get("confirmation") != "RECOVER_B62_P01_SSE_OFF_FROM_PINNED_SNAPSHOT" or changes:
                raise ProductionConfigError("pinned recovery authority missing")
        if args.verify_served:
            expected, variables = ((index(live["entries"]), live["vars"]) if args.recovery_snapshot else
                                   production_plan(live, repo, allow_binding_removal=args.allow_binding_removal, set_var=changes))
            served = parse_live_bindings(json.loads(args.verify_served.read_text()))
            verify_expected(expected, index(served["entries"]))
            if served["vars"] != variables:
                raise ProductionConfigError("served variable values differ from the private deploy plan")
            print("B62_REPO_BINDINGS_SERVED=PASS")
            return 0
        text = (build_recovery_config(live, args.repo_config) if args.recovery_snapshot else
                build_production_config(live, args.repo_config, args.public_base_url,
                                        allow_binding_removal=args.allow_binding_removal, set_var=changes))
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(text)
        args.output.chmod(0o600)
        if args.planned_d1_settings:
            declared = index(live["entries"]) if args.recovery_snapshot else inventory(repo)
            rows = [b for b in declared.values() if b["type"] == "d1"]
            args.planned_d1_settings.write_text(json.dumps({"success": True, "result": {"bindings": rows}}))
        print("B62_PRODUCTION_CONFIG_GENERATED=PASS")
        print("SECRET_VALUES_READ=0\nSECRET_VALUES_EMITTED=0\nPRODUCTION_MUTATION=0")
        return 0
    except (ProductionConfigError, BindingAuthorityError, ValueError, KeyError, TypeError, OSError):
        # Parsing/validation exceptions may contain private input, including
        # set_var values and TOML snippets. Emit only a stable stage code.
        print("B62_PRODUCTION_CONFIG_GENERATED=FAIL\nSTAGE=repo_binding_plan_invalid", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
