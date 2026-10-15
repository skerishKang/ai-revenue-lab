#!/usr/bin/env python3
"""Build the exact production wrangler config for one B62 production code deploy.

The live Cloudflare settings dump is the single authority for bindings and
plain-text variables; the repository wrangler.toml only supplies build inputs
(entrypoint, compatibility, assets directory). Secret bindings are carried by
the platform and are never read or emitted here. Anything unsupported fails
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
from b62_web_secrets_store_contract import expected_web_secret_bindings, require_exact_web_secrets_store

EXPECTED_WORKER = "padiem-chat"
OWNER_P01_D1_BINDING = "BROWSER_CONTROL_OWNER_P01_D1"
GRAFANA_OTLP_BINDING = {
    "type": "secrets_store_secret", "name": "PADIEM_GRAFANA_OTLP_TOKEN",
    "store_id": "f0b09ca04a7b43248154c773704a5616",
    "secret_name": "PADIEM_GRAFANA_OTLP_TOKEN",
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


def parse_live_bindings(settings_payload: object) -> dict[str, object]:
    if not isinstance(settings_payload, dict) or settings_payload.get("success") is not True:
        raise ProductionConfigError("settings payload is not a successful Cloudflare API response")
    result = settings_payload.get("result")
    if not isinstance(result, dict):
        raise ProductionConfigError("settings payload has no result object")
    bindings = result.get("bindings")
    if not isinstance(bindings, list) or not bindings:
        raise ProductionConfigError("settings payload has no bindings array")

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
            if name != HARK_BROWSER_BINDING:
                raise ProductionConfigError("unexpected live Browser Rendering binding name")
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
    }


def build_production_config(
    live: dict[str, object],
    repo_config_path: Path,
    public_base_url: str,
    owner_d1_database_id: str | None = None,
    attach_web_secrets_store: bool = False,
    commission_hark_browser: bool = False,
    attach_connector_broker_service: bool = False,
    activate_claw_public_search: bool = False,
    attach_grafana_telemetry: bool = False,
) -> str:
    try:
        repo = tomllib.loads(repo_config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ProductionConfigError(f"cannot read repository wrangler config: {exc}") from exc

    if repo.get("name") != EXPECTED_WORKER:
        raise ProductionConfigError(f"repository config Worker name must be {EXPECTED_WORKER!r}")
    for key in ("main", "compatibility_date"):
        if not isinstance(repo.get(key), str) or not repo[key]:
            raise ProductionConfigError(f"repository config must define {key!r}")
    base_dir = repo.get("base_dir")
    if base_dir is not None and (not isinstance(base_dir, str) or not base_dir):
        raise ProductionConfigError("repository base_dir must be a non-empty string")
    build = repo.get("build")
    build_command = None
    if build is not None:
        if not isinstance(build, dict):
            raise ProductionConfigError("repository [build] must be a table")
        build_command = build.get("command")
        if not isinstance(build_command, str) or not build_command:
            raise ProductionConfigError("repository [build].command must be a non-empty string")

    assets_dir = (repo.get("assets") or {}).get("directory")
    assets_binding = (repo.get("assets") or {}).get("binding")
    if not isinstance(assets_dir, str) or not assets_dir:
        raise ProductionConfigError("repository config must define [assets].directory")
    if not isinstance(assets_binding, str) or not assets_binding:
        raise ProductionConfigError("repository config must define [assets].binding")

    if not isinstance(public_base_url, str) or not public_base_url.startswith("https://"):
        raise ProductionConfigError("expected public base URL must be an https origin")

    assets = live["assets"]
    if len(assets) != 1 or assets[0].get("name") != assets_binding:
        raise ProductionConfigError(
            f"live settings must carry exactly one {assets_binding!r} assets binding"
        )

    lines: list[str] = []
    lines.append("# GENERATED by b62_cloudflare_production_deploy_config.py — do not commit")
    lines.append(f"name = {_toml_string(EXPECTED_WORKER)}")
    lines.append(f"main = {_toml_string(repo['main'])}")
    lines.append(f"compatibility_date = {_toml_string(repo['compatibility_date'])}")
    flags = repo.get("compatibility_flags") or []
    if not isinstance(flags, list) or not all(isinstance(f, str) for f in flags):
        raise ProductionConfigError("repository compatibility_flags must be a string list")
    flag_text = ", ".join(_toml_string(f) for f in flags)
    lines.append(f"compatibility_flags = [{flag_text}]")
    lines.append("workers_dev = true")
    # Existing live Worker exposes version/preview URLs; match that remote
    # state explicitly so --strict never attempts to disable them on upload.
    lines.append("preview_urls = true")
    if base_dir is not None:
        lines.append(f"base_dir = {_toml_string(base_dir)}")
    # Preserve the already-attached canonical production Custom Domain. Without
    # this exact route, Wrangler --strict correctly rejects a deploy that would
    # detach chat.padiem.net from the production Worker.
    if public_base_url == "https://chat.padiem.net":
        lines.append("")
        lines.append("[[routes]]")
        lines.append('pattern = "chat.padiem.net"')
        lines.append("custom_domain = true")
    lines.append("")
    if build_command is not None:
        lines.append("[build]")
        lines.append(f"command = {_toml_string(build_command)}")
        lines.append("")
    lines.append("[assets]")
    lines.append(f"directory = {_toml_string(assets_dir)}")
    lines.append(f"binding = {_toml_string(assets_binding)}")
    lines.append("")

    # #3933: preserve an already provisioned Hark Browser Rendering binding.
    # A repository [browser] declaration is NOT operational authorization to
    # commission it; the live account/settings inventory remains authoritative.
    live_browser = live["browser"]
    repo_browser = repo.get("browser")
    if live_browser is not None or commission_hark_browser:
        if (not isinstance(repo_browser, dict)
                or repo_browser.get("binding") != HARK_BROWSER_BINDING):
            raise ProductionConfigError("live Browser Rendering binding lacks matching source declaration")
        lines.append("[browser]")
        lines.append(f"binding = {_toml_string(HARK_BROWSER_BINDING)}")
        lines.append("")

    # #3252: the repository config may declare the expected version_metadata
    # source binding name, but the LIVE settings remain the production
    # authority. The binding is preserved verbatim when live has one and is
    # never invented when live does not.
    repo_version_metadata = repo.get("version_metadata") or {}
    repo_version_binding = (
        repo_version_metadata.get("binding") if isinstance(repo_version_metadata, dict) else None
    )
    live_version_metadata = live["version_metadata"]
    if live_version_metadata is not None:
        live_name = live_version_metadata.get("name")
        if repo_version_binding is not None and repo_version_binding != live_name:
            raise ProductionConfigError(
                "repository version_metadata binding "
                f"{repo_version_binding!r} drifts from live binding {live_name!r}"
            )
        lines.append("[version_metadata]")
        lines.append(f"binding = {_toml_string(str(live_name))}")
        lines.append("")

    # Source-only candidate. This function cannot write Cloudflare metadata.
    # Exactly ONE new service is allowed and the existing canonical Identity
    # target must be present. No implicit new Broker, Edge or account authority.
    services_for_output = list(live["services"])
    if attach_connector_broker_service:
        if (owner_d1_database_id is not None or attach_web_secrets_store
                or commission_hark_browser):
            raise ProductionConfigError("multiple additive authority modes prohibited")
        live_names = (
            {item["name"] for key in ("assets", "services", "d1", "r2") for item in live[key]}
            | set(live["vars"]) | set(live["secret_names"])
            | {item["name"] for item in live["secrets_store"]}
        )
        if live["browser"] is not None:
            live_names.add(live["browser"]["name"])
        if live["version_metadata"] is not None:
            live_names.add(live["version_metadata"]["name"])
        broker_live = [item for item in live["services"]
                       if item.get("name") == CONNECTOR_BROKER_BINDING]
        if broker_live:
            # Retry after a rolled-back upload: the mutable settings plane may
            # already carry the approved binding. Reuse the exactly identical
            # entry verbatim; never duplicate it. Wrong target, type
            # collision, unexpected environment, or an entrypoint (which this
            # generator never emits and would otherwise be silently dropped)
            # still fails closed.
            if len(broker_live) != 1:
                raise ProductionConfigError("duplicate Connector Broker bindings in live settings")
            entry = broker_live[0]
            if entry.get("service") != CONNECTOR_BROKER_TARGET:
                raise ProductionConfigError("Connector Broker binding target drift; refusing reuse")
            if entry.get("entrypoint"):
                raise ProductionConfigError("Connector Broker entrypoint must be absent")
            if entry.get("environment") not in (None, "production"):
                raise ProductionConfigError("Connector Broker environment drift; refusing reuse")
        else:
            if CONNECTOR_BROKER_BINDING in live_names:
                raise ProductionConfigError(
                    "Connector Broker name collides outside service bindings"
                )
            identity = [item for item in live["services"] if item["name"] == CONNECTOR_IDENTITY_BINDING]
            if len(identity) != 1 or identity[0].get("service") != CONNECTOR_IDENTITY_TARGET:
                raise ProductionConfigError("Canonical Identity binding is not proven at expected target")
            services_for_output.append({"type": "service", "name": CONNECTOR_BROKER_BINDING,
                                        "service": CONNECTOR_BROKER_TARGET})

    for service in services_for_output:
        target = service.get("service")
        if not isinstance(target, str) or not target:
            raise ProductionConfigError(
                f"service binding {service.get('name')!r} has no target service"
            )
        lines.append("[[services]]")
        lines.append(f"binding = {_toml_string(str(service['name']))}")
        lines.append(f"service = {_toml_string(target)}")
        environment = service.get("environment")
        if isinstance(environment, str) and environment:
            lines.append(f"environment = {_toml_string(environment)}")
        lines.append("")

    if owner_d1_database_id is not None:
        # This opt-in merely builds a candidate config; it does not deploy.
        try:
            parsed = UUID(owner_d1_database_id)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ProductionConfigError("Owner D1 ID must be a UUID") from exc
        if str(parsed) != owner_d1_database_id or parsed.int == 0:
            raise ProductionConfigError("Owner D1 ID must be a nonzero canonical UUID")
        all_names = (
            [item["name"] for item in live["assets"]]
            + [item["name"] for item in live["services"]]
            + [item["name"] for item in live["d1"]]
            + [item["name"] for item in live["r2"]]
            + list(live["vars"])
            + list(live["secret_names"])
            + [item["name"] for item in live["secrets_store"]]
        )
        if live["version_metadata"] is not None:
            all_names.append(live["version_metadata"]["name"])
        if OWNER_P01_D1_BINDING in all_names:
            raise ProductionConfigError("Owner D1 binding already exists in live settings")
        if any(entry.get("id") == owner_d1_database_id for entry in live["d1"]):
            raise ProductionConfigError("Owner D1 aliases a live D1 database")

    for database in live["d1"]:
        database_id = database.get("id")
        if not isinstance(database_id, str) or not database_id:
            raise ProductionConfigError(
                f"d1 binding {database.get('name')!r} has no database id"
            )
        lines.append("[[d1_databases]]")
        lines.append(f"binding = {_toml_string(str(database['name']))}")
        lines.append(f"database_id = {_toml_string(database_id)}")
        lines.append("")

    if owner_d1_database_id is not None:
        lines.append("[[d1_databases]]")
        lines.append(f"binding = {_toml_string(OWNER_P01_D1_BINDING)}")
        lines.append('database_name = "padiem-browser-owner-p01"')
        lines.append(f"database_id = {_toml_string(owner_d1_database_id)}")
        lines.append("")

    for bucket in live["r2"]:
        bucket_name = bucket.get("bucket_name")
        if not isinstance(bucket_name, str) or not bucket_name:
            raise ProductionConfigError(
                f"r2 binding {bucket.get('name')!r} has no bucket_name"
            )
        lines.append("[[r2_buckets]]")
        lines.append(f"binding = {_toml_string(str(bucket['name']))}")
        lines.append(f"bucket_name = {_toml_string(bucket_name)}")
        jurisdiction = bucket.get("jurisdiction")
        if isinstance(jurisdiction, str) and jurisdiction:
            lines.append(f"jurisdiction = {_toml_string(jurisdiction)}")
        lines.append("")

    # Existing bindings are still the authority; this opt-in release may add
    # exactly the two Owner-confirmed same-account Secrets Store identities,
    # never replace or drop a pre-existing Worker binding.
    store_bindings = list(live["secrets_store"])
    if attach_web_secrets_store:
        all_other_names = (
            {item["name"] for key in ("assets", "services", "d1", "r2") for item in live[key]}
            | set(live["vars"])
            | set(live["secret_names"])
        )
        if live["version_metadata"] is not None:
            all_other_names.add(live["version_metadata"]["name"])
        if all_other_names & set(expected_web_secret_bindings()):
            raise ProductionConfigError("web Secrets Store alias collides with live Worker binding")
        try:
            additions = require_exact_web_secrets_store(store_bindings, allow_absent=True)
        except ValueError as exc:
            raise ProductionConfigError("web Secrets Store identity drift") from exc
        store_bindings.extend(additions.values())
    if attach_grafana_telemetry:
        declarations = repo.get("secrets_store_secrets")
        if not isinstance(declarations, list) or [
            d for d in declarations if isinstance(d, dict)
            and d.get("binding") == GRAFANA_OTLP_BINDING["name"]
        ] != [{
            "binding": GRAFANA_OTLP_BINDING["name"],
            "store_id": GRAFANA_OTLP_BINDING["store_id"],
            "secret_name": GRAFANA_OTLP_BINDING["secret_name"],
        }]:
            raise ProductionConfigError("Grafana source binding identity mismatch")
        all_other_names = (
            {i["name"] for key in ("assets", "services", "d1", "r2") for i in live[key]}
            | set(live["vars"]) | set(live["secret_names"])
        )
        if live["version_metadata"] is not None:
            all_other_names.add(live["version_metadata"]["name"])
        if live["browser"] is not None:
            all_other_names.add(live["browser"]["name"])
        if GRAFANA_OTLP_BINDING["name"] in all_other_names:
            raise ProductionConfigError("Grafana binding name collides with live authority")
        existing = [item for item in store_bindings
                    if item["name"] == GRAFANA_OTLP_BINDING["name"]]
        if existing:
            if len(existing) != 1 or existing[0] != GRAFANA_OTLP_BINDING:
                raise ProductionConfigError("Grafana live Secrets Store metadata drift")
        else:
            store_bindings.append(dict(GRAFANA_OTLP_BINDING))
    for item in store_bindings:
        lines.append("[[secrets_store_secrets]]")
        lines.append(f"binding = {_toml_string(item['name'])}")
        lines.append(f"store_id = {_toml_string(item['store_id'])}")
        lines.append(f"secret_name = {_toml_string(item['secret_name'])}")
        lines.append("")

    plain_vars = live["vars"]
    assert isinstance(plain_vars, dict)
    for required in REQUIRED_VARS:
        if required not in plain_vars:
            raise ProductionConfigError(f"live settings must define {required}")
    if plain_vars.get("PADIEM_CHAT_RUNTIME_MODE") == "mock":
        raise ProductionConfigError("live runtime mode is mock; production code deploy aborted")
    if plain_vars.get("PADIEM_CHAT_LIVE_ENABLED") != "true":
        raise ProductionConfigError("live arm is not enabled in live settings; deploy aborted")

    # The deploy never injects or rewrites plain-text variables. The live settings
    # are the authority; the expected public base URL must already be present and
    # exact, otherwise this run fails closed and the activation gate owns the fix.
    existing_public = plain_vars.get(PUBLIC_BASE_URL_VAR)
    if existing_public is None:
        raise ProductionConfigError(
            f"{PUBLIC_BASE_URL_VAR} is absent from live settings; deploy does not inject it"
        )
    if existing_public != public_base_url:
        raise ProductionConfigError(
            f"{PUBLIC_BASE_URL_VAR} drift: live value differs from the expected production origin"
        )

    # #4719 LOCAL1: Connector mode reflects exactly the allowlisted Connector
    # values on top of live vars. Every other live var (b14/live=true,
    # base URL, operational settings) is preserved verbatim. Normal deploys
    # never take this path.
    output_vars = dict(plain_vars)
    if attach_connector_broker_service:
        for key, expected in CONNECTOR_EXPLICIT_VARS.items():
            existing = output_vars.get(key)
            if existing is not None and existing != expected:
                raise ProductionConfigError(
                    f"Connector var drift on {key!r}; activation owns the live value"
                )
            output_vars[key] = expected

    if activate_claw_public_search:
        # #4469: the owner approved public research, not a generic var copy.
        # A contradictory existing binding requires the separate config gate;
        # this additive rollout can only add the exact missing ON flag.
        existing = output_vars.get(CLAW_SEARCH_FLAG)
        if existing is not None and existing != "true":
            raise ProductionConfigError("Claw search flag conflicts with existing live authority")
        output_vars[CLAW_SEARCH_FLAG] = "true"

    lines.append("[vars]")
    for name in sorted(output_vars):
        lines.append(f"{name} = {_toml_string(output_vars[name])}")
    lines.append("")
    return "\n".join(lines) + ""


def verify_mutation_zero(
    config_text: str,
    live: dict[str, object],
    allow_connector_broker: bool = False,
    allow_claw_public_search: bool = False,
) -> None:
    """The generated [vars] block must equal the live plain-text variables exactly.

    Normal deploys require exact equality. Connector mode additionally permits
    exactly the CONNECTOR_EXPLICIT_VARS allowlist (missing keys added with
    their explicit values); any other var addition, removal, or value drift
    still fails closed.
    """
    plain_vars = live["vars"]
    assert isinstance(plain_vars, dict)
    generated: dict[str, str] = {}
    in_vars = False
    for line in config_text.splitlines():
        if line.strip() == "[vars]":
            in_vars = True
            continue
        if in_vars:
            if line.startswith("["):
                break
            if not line.strip():
                continue
            name, _, value = line.partition("=")
            generated[name.strip()] = json.loads(value)
    expected: dict[str, str] = dict(plain_vars)
    if allow_connector_broker:
        for key, value in CONNECTOR_EXPLICIT_VARS.items():
            if key in expected and expected[key] != value:
                raise ProductionConfigError(
                    f"Connector var drift on {key!r}; activation owns the live value"
                )
            expected.setdefault(key, value)
    if allow_claw_public_search:
        existing = expected.get(CLAW_SEARCH_FLAG)
        if existing is not None and existing != "true":
            raise ProductionConfigError("Claw search flag conflicts with existing live authority")
        expected[CLAW_SEARCH_FLAG] = "true"
    if generated != expected:
        changed = sorted(
            name for name in set(generated) | set(expected)
            if generated.get(name) != expected.get(name)
        )
        raise ProductionConfigError(
            f"generated config mutates live plain-text vars: {', '.join(changed)}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", required=True, type=Path)
    parser.add_argument("--repo-config", required=True, type=Path)
    parser.add_argument("--public-base-url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--owner-d1-database-id", help="candidate-only approved D1 UUID; never deploys")
    parser.add_argument("--attach-existing-web-secrets-store", action="store_true", help="add exactly two Owner-approved same-account web Secret Store bindings")
    parser.add_argument("--commission-hark-browser", action="store_true", help="owner-authorized additive BROWSER binding, no PDF calls")
    parser.add_argument("--attach-existing-connector-broker", action="store_true",
                        help="generate a candidate with only the existing canonical Broker Service Binding; does not deploy")
    parser.add_argument("--attach-existing-grafana-telemetry", action="store_true",
                        help="only the existing exact Grafana Secrets Store reference")
    parser.add_argument("--activate-claw-public-search", action="store_true",
                        help="owner-reviewed single exact Claw public search ON var, preserving every other live binding")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    try:
        payload = json.loads(args.settings.read_text(encoding="utf-8"))
        live = parse_live_bindings(payload)
        if args.attach_existing_grafana_telemetry and (
            args.attach_existing_connector_broker or args.commission_hark_browser
            or args.attach_existing_web_secrets_store or args.owner_d1_database_id is not None
            or args.activate_claw_public_search
        ):
            raise ProductionConfigError("Grafana activation must be the only additive mode")
        if args.activate_claw_public_search and (
            args.attach_existing_connector_broker or args.commission_hark_browser
            or args.attach_existing_web_secrets_store or args.owner_d1_database_id is not None
        ):
            raise ProductionConfigError("Claw search activation must be the only additive mode")
        if args.attach_existing_connector_broker and (
            args.commission_hark_browser or args.attach_existing_web_secrets_store
            or args.owner_d1_database_id is not None
        ):
            raise ProductionConfigError("Connector Broker candidate must be the only additive mode")
        if args.commission_hark_browser and args.attach_existing_web_secrets_store:
            raise ProductionConfigError("multiple additive authority modes prohibited")
        if args.commission_hark_browser:
            # No Hark write/PDF activation as a side effect of Browser install.
            for flag in (
                "PADIEM_WEB_XLSX_QUOTE_PDF_ENABLED",
                "PADIEM_WEB_XLSX_QUOTE_WRITE_ENABLED",
                "PADIEM_WEB_XLSX_QUOTE_WRITE_ENGINE_ENABLED",
                "PADIEM_WEB_XLSX_QUOTE_WRITE_DURABLE_ENABLED",
                "PADIEM_WEB_XLSX_QUOTE_WRITE_OWNER_DECISION_ENABLED",
            ):
                if live["vars"].get(flag, "false").lower() == "true":
                    raise ProductionConfigError("active Hark flag blocks Browser install: " + flag)
        config_text = build_production_config(
            live, args.repo_config, args.public_base_url, args.owner_d1_database_id,
            attach_web_secrets_store=args.attach_existing_web_secrets_store,
            commission_hark_browser=args.commission_hark_browser,
            attach_connector_broker_service=args.attach_existing_connector_broker,
            activate_claw_public_search=args.activate_claw_public_search,
            attach_grafana_telemetry=args.attach_existing_grafana_telemetry,
        )
        verify_mutation_zero(
            config_text, live,
            allow_connector_broker=args.attach_existing_connector_broker,
            allow_claw_public_search=args.activate_claw_public_search,
        )
    except (ProductionConfigError, OSError, json.JSONDecodeError) as exc:
        print(f"B62_PRODUCTION_CONFIG_GENERATED=FAIL\nREASON={exc}", file=sys.stderr)
        return 1

    if args.output.exists():
        print("B62_PRODUCTION_CONFIG_GENERATED=FAIL", file=sys.stderr)
        print("REASON=output path already exists", file=sys.stderr)
        return 1
    args.output.write_text(config_text, encoding="utf-8")

    secret_names = live["secret_names"]
    plain_vars = live["vars"]
    assert isinstance(secret_names, list)
    assert isinstance(plain_vars, dict)
    print("B62_PRODUCTION_CONFIG_GENERATED=PASS")
    print(f"OWNER_P01_D1_CANDIDATE_ADDITION={int(args.owner_d1_database_id is not None)}")
    print(f"SERVICE_BINDINGS={len(live['services'])}")
    print(f"D1_BINDINGS={len(live['d1'])}")
    print(f"R2_BINDINGS={len(live['r2'])}")
    print(f"PLAIN_TEXT_VARS={len(plain_vars)}")
    print(f"SECRET_BINDINGS_PRESERVED_BY_PLATFORM={len(secret_names)}")
    print(f"SECRETS_STORE_BINDINGS_PRESERVED={len(live['secrets_store'])}")
    print(f"WEB_SECRETS_STORE_ATTACH_REQUESTED={int(args.attach_existing_web_secrets_store)}")
    print(f"GRAFANA_TELEMETRY_ATTACH_REQUESTED={int(args.attach_existing_grafana_telemetry)}")
    print(f"CONNECTOR_BROKER_BINDING_CANDIDATE={int(args.attach_existing_connector_broker)}")
    if args.attach_existing_connector_broker:
        assert isinstance(plain_vars, dict)
        applied = sum(1 for key in CONNECTOR_EXPLICIT_VARS if key not in plain_vars)
        reused = any(item.get("name") == CONNECTOR_BROKER_BINDING
                     for item in live["services"])
        print(f"CONNECTOR_VARS_APPLIED={applied}")
        print(f"CONNECTOR_VARS_ALLOWLISTED={len(CONNECTOR_EXPLICIT_VARS)}")
        print(f"CONNECTOR_BROKER_BINDING_REUSED={int(reused)}")
    else:
        print("CONNECTOR_VARS_APPLIED=0")
        print(f"CONNECTOR_VARS_ALLOWLISTED={len(CONNECTOR_EXPLICIT_VARS)}")
    print(f"CLAW_PUBLIC_SEARCH_EXPLICIT_ACTIVATION={int(args.activate_claw_public_search)}")
    print("CONNECTOR_BROKER_RELEASE_AUTHORIZED=NO")
    print("SECRET_VALUES_READ=0")
    print("SECRET_VALUES_EMITTED=0")
    print("PADIEM_CHAT_PUBLIC_BASE_URL_PRESTATE=EXPECTED")
    print("DEPLOY_CONFIG_MUTATION_ZERO=PASS")
    print(f"VERSION_METADATA_PRESERVED={1 if live['version_metadata'] is not None else 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
