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
import sys
import tomllib
from pathlib import Path

EXPECTED_WORKER = "padiem-chat"
SUPPORTED_BINDING_TYPES = {"assets", "service", "d1", "r2_bucket", "plain_text", "secret_text"}
REQUIRED_VARS = ("PADIEM_CHAT_RUNTIME_MODE", "PADIEM_CHAT_LIVE_ENABLED")
PUBLIC_BASE_URL_VAR = "PADIEM_CHAT_PUBLIC_BASE_URL"


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
        elif kind == "plain_text":
            text = raw.get("text")
            if not isinstance(text, str):
                raise ProductionConfigError(f"plain_text binding {name!r} has no text value")
            plain_vars[name] = text
        else:
            secret_names.append(name)
    if len(names) != len(set(names)):
        raise ProductionConfigError("duplicate binding names in live settings")
    return {
        "assets": assets,
        "services": services,
        "d1": d1,
        "r2": r2,
        "vars": plain_vars,
        "secret_names": secret_names,
    }


def build_production_config(
    live: dict[str, object],
    repo_config_path: Path,
    public_base_url: str,
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
    lines.append("")
    lines.append("[assets]")
    lines.append(f"directory = {_toml_string(assets_dir)}")
    lines.append(f"binding = {_toml_string(assets_binding)}")
    lines.append("")

    for service in live["services"]:
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

    lines.append("[vars]")
    for name in sorted(plain_vars):
        lines.append(f"{name} = {_toml_string(plain_vars[name])}")
    lines.append("")
    return "\n".join(lines) + ""


def verify_mutation_zero(config_text: str, live: dict[str, object]) -> None:
    """The generated [vars] block must equal the live plain-text variables exactly."""
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
    if generated != plain_vars:
        changed = sorted(
            name for name in set(generated) | set(plain_vars)
            if generated.get(name) != plain_vars.get(name)
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
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    try:
        payload = json.loads(args.settings.read_text(encoding="utf-8"))
        live = parse_live_bindings(payload)
        config_text = build_production_config(live, args.repo_config, args.public_base_url)
        verify_mutation_zero(config_text, live)
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
    print(f"SERVICE_BINDINGS={len(live['services'])}")
    print(f"D1_BINDINGS={len(live['d1'])}")
    print(f"R2_BINDINGS={len(live['r2'])}")
    print(f"PLAIN_TEXT_VARS={len(plain_vars)}")
    print(f"SECRET_BINDINGS_PRESERVED_BY_PLATFORM={len(secret_names)}")
    print("SECRET_VALUES_READ=0")
    print("SECRET_VALUES_EMITTED=0")
    print("PADIEM_CHAT_PUBLIC_BASE_URL_PRESTATE=EXPECTED")
    print("DEPLOY_CONFIG_MUTATION_ZERO=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
