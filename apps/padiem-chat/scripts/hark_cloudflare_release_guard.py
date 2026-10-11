"""#3933 Cloudflare release guard: NEVER replace current B62/Engine bindings.

Offline, read-only: compares Cloudflare versions-view JSON exports against
candidate version JSON. Compares NAMES AND TYPES only, never outputs
secrets, credentials, arbitrary env values, or binding payloads. An incomplete
source Wrangler config is not an authoritative production binding manifest.
"""
from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from uuid import UUID

ENGINE_PRIVATE_DB_ID = "702bb62b-36f5-41a0-973f-c4f663ee01e6"
ENGINE_PRIVATE_DB_NAME = "padiem-chat-db"
ENGINE_APP = "padiem-ai-engine"
B62_APP = "padiem-chat"
ENGINE_ADDED_BINDING = "WEB_XLSX_PRIVATE_B62_D1"
B62_ADDED_BINDING = "BROWSER"
OFF_FLAGS = (
    "PADIEM_WEB_XLSX_QUOTE_WRITE_ENABLED",
    "PADIEM_WEB_XLSX_QUOTE_PDF_ENABLED",
    "PADIEM_WEB_XLSX_P01_OWNER_DECISION_ENABLED",
    "PADIEM_WEB_XLSX_WORKCOPY_AFTER_P01_ENABLED",
    "PADIEM_WEB_XLSX_QUOTE_WRITE_ENGINE_ENABLED",
    "PADIEM_WEB_XLSX_QUOTE_WRITE_DURABLE_ENABLED",
    "PADIEM_WEB_XLSX_QUOTE_WRITE_OWNER_DECISION_ENABLED",
)


def _load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def assert_configured_source(chat_toml: Path, engine_toml: Path) -> None:
    chat = _load_toml(chat_toml)
    engine = _load_toml(engine_toml)
    if chat.get("name") != B62_APP or engine.get("name") != ENGINE_APP:
        raise ValueError("unexpected source Worker names")
    if chat.get("browser", {}).get("binding") != B62_ADDED_BINDING:
        raise ValueError("Hark Browser binding must be declared")
    if chat.get("compatibility_date", "") < "2026-03-24":
        raise ValueError("Quick Action requires compatibility date >= 2026-03-24")
    matched = [binding for binding in engine.get("d1_databases", ())
               if binding.get("binding") == ENGINE_ADDED_BINDING]
    if len(matched) != 1 or matched[0].get("database_name") != ENGINE_PRIVATE_DB_NAME \
            or matched[0].get("database_id") != ENGINE_PRIVATE_DB_ID:
        raise ValueError("Engine must use proven live B62 D1 identity")
    for document in (chat, engine):
        variables = document.get("vars", {})
        for name in OFF_FLAGS:
            if str(variables.get(name, "")).lower() == "true":
                raise ValueError("source must not auto-activate " + name)


def read_version_bindings(path: Path) -> dict[str, str]:
    result = json.loads(path.read_text(encoding="utf-8-sig"))
    entries = result.get("resources", {}).get("bindings")
    if not isinstance(entries, list):
        raise ValueError("valid Cloudflare version resources.bindings required")
    names: dict[str, str] = {}
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("binding record must be an object")
        name, kind = item.get("name"), item.get("type")
        if not isinstance(name, str) or not name or not isinstance(kind, str):
            raise ValueError("binding must have name and type")
        if name in names:
            raise ValueError("duplicate binding name")
        names[name] = kind
    return names


# Identity metadata is not secret material. Compare these where present to
# stop a same-name D1/R2/service rebind to a different customer authority.
# Secret values are intentionally not accessible via version inspection.
_RESOURCE_IDENTITY = (
    "database_id", "id", "namespace_id", "service", "environment",
    "bucket_name", "class_name",
)


def read_version_resource_identity(path: Path) -> dict[str, dict[str, str]]:
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    entries = doc.get("resources", {}).get("bindings")
    if not isinstance(entries, list):
        raise ValueError("Cloudflare resources.bindings required")
    result: dict[str, dict[str, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise ValueError("invalid resources.binding record")
        name = entry["name"]
        if name in result:
            raise ValueError("duplicate binding name")
        result[name] = {
            key: str(entry[key]) for key in _RESOURCE_IDENTITY
            if isinstance(entry.get(key), str) and entry[key]
        }
    return result


def audit_resource_identity(
    b62_old: dict[str, dict[str, str]],
    engine_old: dict[str, dict[str, str]],
    b62_new: dict[str, dict[str, str]],
    engine_new: dict[str, dict[str, str]],
) -> list[str]:
    findings: list[str] = []
    for label, previous, proposed in (
        (B62_APP, b62_old, b62_new),
        (ENGINE_APP, engine_old, engine_new),
    ):
        for name in sorted(previous.keys() & proposed.keys()):
            # Only compare IDs recorded by the prior deployed version;
            # never claim secret value parity from these metadata exports.
            for field, value in previous[name].items():
                if proposed[name].get(field) != value:
                    findings.append(f"{label} would REBIND {name}: {field}")
    # Prove the new Engine verifier can only read the actual B62 D1.
    b62_live_d1 = b62_old.get("PADIEM_CHAT_DB", {}).get("database_id")
    engine_binding = engine_new.get(ENGINE_ADDED_BINDING, {})
    if (b62_live_d1 != ENGINE_PRIVATE_DB_ID
            or engine_binding.get("database_id") != b62_live_d1):
        findings.append("Engine private D1 target does not match live B62 D1")
    return findings


def missing_or_retyped(base: dict[str, str],
                       candidate: dict[str, str]) -> tuple[list[str], list[str]]:
    missing = sorted(set(base) - set(candidate))
    changed = sorted(name for name in base.keys() & candidate.keys()
                     if base[name] != candidate[name])
    return missing, changed


def audit_replacement(b62_base: dict[str, str], engine_base: dict[str, str],
                      b62_next: dict[str, str],
                      engine_next: dict[str, str]) -> list[str]:
    errors = []
    for service, old, new in (
        (B62_APP, b62_base, b62_next),
        (ENGINE_APP, engine_base, engine_next),
    ):
        missing, retyped = missing_or_retyped(old, new)
        if missing:
            errors.append(service + " would DROP bindings: " + ", ".join(missing))
        if retyped:
            errors.append(service + " would RETYPE bindings: " + ", ".join(retyped))
    if b62_next.get(B62_ADDED_BINDING) != "browser":
        errors.append("B62 requires BROWSER of type browser")
    if engine_next.get(ENGINE_ADDED_BINDING) != "d1":
        errors.append("Engine requires WEB_XLSX_PRIVATE_B62_D1 of type d1")
    # Hark may introduce only the two explicitly authorized identities;
    # unrelated new resource authority fails closed.
    for worker, old, next_bindings, approved in (
        (B62_APP, b62_base, b62_next, {B62_ADDED_BINDING: "browser"}),
        (ENGINE_APP, engine_base, engine_next, {ENGINE_ADDED_BINDING: "d1"}),
    ):
        extras = sorted(name for name in set(next_bindings) - set(old)
                        if approved.get(name) != next_bindings[name])
        if extras:
            errors.append(worker + " would ADD unapproved bindings: "
                          + ", ".join(extras))
    return errors


def read_immutable_version_proof(path: Path) -> str:
    """Require Cloudflare versions-view shape and an immutable version ID.

    Offline exports are NOT remote attestation. An operational release must
    fetch these from the real account immediately before release.
    """
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    version_id = doc.get("id")
    try:
        uuid = UUID(version_id)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("immutable Cloudflare version id missing/invalid") from exc
    if str(uuid) != version_id or uuid.int == 0:
        raise ValueError("immutable Cloudflare version id missing/invalid")
    resources = doc.get("resources")
    if not isinstance(resources, dict):
        raise ValueError("immutable Cloudflare resources missing")
    script = resources.get("script")
    runtime = resources.get("script_runtime")
    if (not isinstance(script, dict)
            or not isinstance(script.get("etag"), str)
            or not script["etag"]
            or not isinstance(runtime, dict)
            or not isinstance(runtime.get("compatibility_date"), str)
            or not runtime["compatibility_date"]
            or not isinstance(resources.get("bindings"), list)):
        raise ValueError("immutable Cloudflare script/runtime/binding proof incomplete")
    return version_id


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chat-toml", type=Path, required=True)
    parser.add_argument("--engine-toml", type=Path, required=True)
    parser.add_argument("--live-b62-version", type=Path, required=True)
    parser.add_argument("--live-engine-version", type=Path, required=True)
    parser.add_argument("--candidate-b62-version", type=Path)
    parser.add_argument("--candidate-engine-version", type=Path)
    opts = parser.parse_args(argv)
    try:
        assert_configured_source(opts.chat_toml, opts.engine_toml)
        old_b62 = read_version_bindings(opts.live_b62_version)
        old_engine = read_version_bindings(opts.live_engine_version)
        print("SOURCE_BINDINGS=PASS default_off=YES")
        print(f"BASELINE_BINDINGS b62={len(old_b62)} engine={len(old_engine)}")
        if not opts.candidate_b62_version or not opts.candidate_engine_version:
            print("PRODUCTION_DEPLOYMENT=BLOCKED candidate version manifests absent")
            return 2
        # Candidate must be a distinct immutable Worker version, never
        # a synthetic binding list or re-labeled copy of the served version.
        live_b62_id = read_immutable_version_proof(opts.live_b62_version)
        live_engine_id = read_immutable_version_proof(opts.live_engine_version)
        candidate_b62_id = read_immutable_version_proof(opts.candidate_b62_version)
        candidate_engine_id = read_immutable_version_proof(opts.candidate_engine_version)
        if live_b62_id == candidate_b62_id or live_engine_id == candidate_engine_id:
            print("BLOCKED candidate must be a distinct immutable Worker version")
            return 2
        errors = audit_replacement(
            old_b62, old_engine, read_version_bindings(opts.candidate_b62_version),
            read_version_bindings(opts.candidate_engine_version))
        errors.extend(audit_resource_identity(
            read_version_resource_identity(opts.live_b62_version),
            read_version_resource_identity(opts.live_engine_version),
            read_version_resource_identity(opts.candidate_b62_version),
            read_version_resource_identity(opts.candidate_engine_version),
        ))
        if errors:
            for error in errors:
                print("BLOCKED " + error)
            return 2
        print("IMMUTABLE_VERSION_SHAPE_AND_DISTINCT_ID=PASS")
        print("BINDING_NAME_TYPE_RESOURCE_ID_PARITY=PASS")
        print("RELEASE=NOT_AUTHORIZED; this tool never deploys or enables flags")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print("BLOCKED " + str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())
