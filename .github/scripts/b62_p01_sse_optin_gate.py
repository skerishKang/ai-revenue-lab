#!/usr/bin/env python3
"""#3930: bounded source-preserving Cloudflare P01 SSE opt-in plan/verification.

Offline only: the caller owns the existing production authorization and API transport.
No secrets are read. Never infer a deployed source SHA from repository HEAD alone.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


# Deliberate finite allowlist. Never print raw exception messages or input values.
# Updating this set requires a source review when adding a new verifier refusal.
SAFE_REFUSAL_CODES = frozenset({
    "ACTIVE_VERSION_NOT_UNIQUE",
    "CODE_IDENTITY_MISSING",
    "CORE_RUNTIME_NOT_READY",
    "FLAG_NOT_ACTIVATED",
    "FLAG_WRONG_TYPE_OR_VALUE",
    "INVALID_TARGET_SHA",
    "MISSING_BASELINE_EVIDENCE",
    "NEW_SERVED_VERSION_NOT_OBSERVED",
    "NO_OP_STATE_CHANGED",
    "OUTPUT_PATH_UNAVAILABLE",
    "POST_SERVED_BINDING_DRIFT",
    "POST_SETTINGS_DRIFT",
    "POST_VERSION_LINEAGE_UNVERIFIED",
    "PREMUTATION_STATE_CHANGED",
    "REQUIRED_BINDING_MISSING_OR_RETYPED",
    "RUNTIME_IDENTITY_MISSING",
    "SERVED_BINDING_INVENTORY_DRIFT",
    "SERVED_FLAG_DRIFT",
    "SERVED_RUNTIME_NOT_READY",
    "SOURCE_LINEAGE_UNVERIFIED",
    "SOURCE_SHA_MISMATCH",
    "VERSION_BINDING_SHAPE",
    "VERSION_DUPLICATE_BINDING",
    "VERSION_ID",
    "VERSION_MISMATCH",
    "VERSION_SHAPE",
    "WORKER_CODE_OR_RUNTIME_DRIFT",
})

def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


readiness = load("sse_readiness_authority", HERE / "b62_p01_live_sse_readiness.py")
config = load("sse_settings_authority", HERE / "b62_cloudflare_production_deploy_config.py")
FLAG = "PADIEM_CLAW_P01_LIVE_SSE_ENABLED"
SHA = re.compile(r"^[0-9a-f]{40}$")
SOURCE = re.compile(r"^B62 production code ([0-9a-f]{40})$")


class OptInRefused(ValueError):
    pass


def bindings(settings: object) -> dict[str, dict]:
    # Canonical B62 parser rejects duplicate, unsupported and malformed bindings.
    config.parse_live_bindings(settings)
    return {b["name"]: b for b in settings["result"]["bindings"]}


def version_result(version: object) -> dict:
    if not isinstance(version, dict):
        raise OptInRefused("VERSION_SHAPE")
    result = version.get("result", version)
    if not isinstance(result, dict) or not isinstance(result.get("resources"), dict):
        raise OptInRefused("VERSION_SHAPE")
    if not isinstance(result.get("id"), str):
        raise OptInRefused("VERSION_ID")
    resources = result["resources"]
    if not isinstance(resources.get("script"), dict) or not resources["script"].get("etag"):
        raise OptInRefused("CODE_IDENTITY_MISSING")
    if not isinstance(resources.get("script_runtime"), dict):
        raise OptInRefused("RUNTIME_IDENTITY_MISSING")
    return result


def active(deployments: object, *, allow_settings_generated_lineage: bool = False
           ) -> tuple[str, str | None]:
    # A settings PATCH can create a 100%-served new version whose deployment
    # annotation is provider-generated rather than the code-deploy source SHA.
    # This exception is allowed ONLY in post-PATCH verification; immutable
    # version annotations must then independently prove the exact source SHA.
    try:
        served = readiness._served.resolve_served_version_id(deployments)
    except readiness._served.ServedVersionResolutionError as exc:
        raise OptInRefused("ACTIVE_VERSION_NOT_UNIQUE") from exc
    d = deployments["result"]["deployments"][0]
    annotations = d.get("annotations")
    msg = annotations.get("workers/message") if isinstance(annotations, dict) else None
    if not isinstance(msg, str) or not msg:
        raise OptInRefused("SOURCE_LINEAGE_UNVERIFIED")
    match = SOURCE.fullmatch(msg)
    if match:
        return served, match.group(1)
    if not allow_settings_generated_lineage:
        raise OptInRefused("SOURCE_LINEAGE_UNVERIFIED")
    return served, None

def version_bindings(version: dict) -> dict[str, dict]:
    raw = version["resources"].get("bindings")
    if isinstance(raw, dict):
        raw = [{**b, "name": k} for k, b in raw.items()
               if isinstance(k, str) and isinstance(b, dict) and b.get("name", k) == k]
    if not isinstance(raw, list) or any(
        not isinstance(b, dict) or not isinstance(b.get("name"), str) or
        not isinstance(b.get("type"), str) for b in raw
    ):
        raise OptInRefused("VERSION_BINDING_SHAPE")
    names = [b["name"] for b in raw]
    if len(names) != len(set(names)):
        raise OptInRefused("VERSION_DUPLICATE_BINDING")
    return {b["name"]: b for b in raw}


def inspect(settings: object, deployments: object, version: object, target_sha: str,
            *, require_optin: bool = False,
            allow_settings_generated_lineage: bool = False) -> tuple[dict, dict, dict, str]:
    if not SHA.fullmatch(target_sha):
        raise OptInRefused("INVALID_TARGET_SHA")
    served, source = active(
        deployments, allow_settings_generated_lineage=allow_settings_generated_lineage)
    if source is not None and source != target_sha:
        raise OptInRefused("SOURCE_SHA_MISMATCH")
    v = version_result(version)
    if served != v["id"]:
        raise OptInRefused("VERSION_MISMATCH")
    if source is None:
        # A provider-generated *deployment* note is not source authority.
        # The exact immutable *version* must contain the code-deploy SHA.
        # Remaining verify() gates still require flag-only changes, equal
        # script ETag/runtime/assets, no other binding or Secret drift.
        annotation = v.get("annotations")
        if not isinstance(annotation, dict) or (
            annotation.get("workers/message") != f"B62 production code {target_sha}"
        ):
            raise OptInRefused("POST_VERSION_LINEAGE_UNVERIFIED")
    s = bindings(settings)
    vb = version_bindings(v)
    if set(s) != set(vb) or any(s[n]["type"] != vb[n]["type"] for n in s):
        raise OptInRefused("SERVED_BINDING_INVENTORY_DRIFT")
    for name, kind in readiness.EXPECTED_TYPES.items():
        if s.get(name, {}).get("type") != kind:
            raise OptInRefused("REQUIRED_BINDING_MISSING_OR_RETYPED")
    for name, text in (("PADIEM_CHAT_RUNTIME_MODE", "b14"),
                       ("PADIEM_CHAT_LIVE_ENABLED", "true")):
        if s.get(name, {}).get("type") != "plain_text" or s[name].get("text") != text:
            raise OptInRefused("CORE_RUNTIME_NOT_READY")
        if vb[name].get("text") != text:
            raise OptInRefused("SERVED_RUNTIME_NOT_READY")
    flag = s.get(FLAG)
    if flag is not None and (flag["type"] != "plain_text"
                             or flag.get("text") not in ("false", "true")):
        raise OptInRefused("FLAG_WRONG_TYPE_OR_VALUE")
    if flag is not None and (vb[FLAG].get("text") != flag["text"]):
        raise OptInRefused("SERVED_FLAG_DRIFT")
    if require_optin and (flag is None or flag.get("text") != "true"):
        raise OptInRefused("FLAG_NOT_ACTIVATED")
    return s, v, vb, served


def plan(settings: object, deployments: object, version: object, target_sha: str) -> dict:
    state, _, _, _ = inspect(settings, deployments, version, target_sha)
    no_op = FLAG in state and state[FLAG]["text"] == "true"
    patch = {"bindings": [
        {"name": name, "type": "inherit", "version_id": "latest"}
        for name in sorted(state) if name != FLAG
    ]}
    if no_op:
        patch["bindings"].append({"name": FLAG, "type": "inherit", "version_id": "latest"})
    else:
        patch["bindings"].append({"name": FLAG, "type": "plain_text", "text": "true"})
    # Cloudflare /script-and-version-settings PATCH documents
    # workers/triggered_by as server-owned/read-only. Sending it violates the
    # API contract and may fail the entire SSE settings PATCH. Preserve only
    # the exact-main worker source lineage (workers/message); do not weaken
    # any binding, Secret, script-etag or served-version verification.
    patch["annotations"] = {
        "workers/message": f"B62 production code {target_sha}",
    }
    return {"payload": patch, "no_op": no_op, "preserved_count": len(state) - (FLAG in state)}


def compare_before(s0, d0, v0, s1, d1, v1, sha: str) -> None:
    a, av, ab, aid = inspect(s0, d0, v0, sha)
    b, bv, bb, bid = inspect(s1, d1, v1, sha)
    if aid != bid or a != b or av != bv or ab != bb:
        raise OptInRefused("PREMUTATION_STATE_CHANGED")


def verify(s0, d0, v0, s1, d1, v1, sha: str, *, no_op: bool = False) -> None:
    a, av, ab, aid = inspect(s0, d0, v0, sha)
    b, bv, bb, bid = inspect(s1, d1, v1, sha, require_optin=True,
                              allow_settings_generated_lineage=not no_op)
    if no_op:
        if aid != bid or a != b or av != bv:
            raise OptInRefused("NO_OP_STATE_CHANGED")
        return
    if aid == bid:
        raise OptInRefused("NEW_SERVED_VERSION_NOT_OBSERVED")
    expected = {n: dict(v) for n, v in a.items() if n != FLAG}
    expected[FLAG] = {"name": FLAG, "type": "plain_text", "text": "true"}
    if b != expected:
        raise OptInRefused("POST_SETTINGS_DRIFT")
    expected_v = {n: dict(v) for n, v in ab.items() if n != FLAG}
    expected_v[FLAG] = {"name": FLAG, "type": "plain_text", "text": "true"}
    if bb != expected_v:
        raise OptInRefused("POST_SERVED_BINDING_DRIFT")
    # Cloudflare PATCH /settings legitimately changes one deployment-origin
    # annotation (resources.script.last_deployed_from) even when script ETag,
    # runtime, assets and every other immutable source resource stay identical.
    # Proven by GET-only immutable old/failed versions in #38440681029. Do NOT
    # permit any other script field or runtime/asset difference.
    def code_resources(version):
        resources = {k: v for k, v in version["resources"].items()
                     if k != "bindings"}
        script = resources.get("script")
        if not isinstance(script, dict) or not isinstance(script.get("etag"), str) \
                or not script["etag"]:
            raise OptInRefused("CODE_IDENTITY_MISSING")
        resources["script"] = {k: v for k, v in script.items()
                               if k != "last_deployed_from"}
        return resources

    if code_resources(av) != code_resources(bv):
        raise OptInRefused("WORKER_CODE_OR_RUNTIME_DRIFT")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("plan", "compare-before", "verify"))
    p.add_argument("--settings", required=True, type=Path)
    p.add_argument("--deployments", required=True, type=Path)
    p.add_argument("--version", required=True, type=Path)
    p.add_argument("--before-settings", type=Path)
    p.add_argument("--before-deployments", type=Path)
    p.add_argument("--before-version", type=Path)
    p.add_argument("--target-sha", required=True)
    p.add_argument("--output", type=Path)
    p.add_argument("--no-op", action="store_true")
    args = p.parse_args(argv)
    try:
        s, d, v = [json.loads(x.read_text(encoding="utf-8")) for x in
                   (args.settings, args.deployments, args.version)]
        if args.mode == "plan":
            if args.output is None or args.output.exists():
                raise OptInRefused("OUTPUT_PATH_UNAVAILABLE")
            result = plan(s, d, v, args.target_sha)
            args.output.write_text(json.dumps(result["payload"], separators=(",", ":")),
                                   encoding="utf-8")
            print("P01_SSE_OPTIN_PLAN=PASS")
            print(f"P01_SSE_OPTIN_NO_OP={int(result['no_op'])}")
        else:
            if not all((args.before_settings, args.before_deployments, args.before_version)):
                raise OptInRefused("MISSING_BASELINE_EVIDENCE")
            bs, bd, bv = [json.loads(x.read_text(encoding="utf-8")) for x in
                          (args.before_settings, args.before_deployments, args.before_version)]
            if args.mode == "compare-before":
                compare_before(bs, bd, bv, s, d, v, args.target_sha)
                print("P01_SSE_PREMUTATION_CONCURRENCY=PASS")
            else:
                verify(bs, bd, bv, s, d, v, args.target_sha, no_op=args.no_op)
                print("P01_SSE_POST_SERVED_INTEGRITY=PASS")
    except OptInRefused as exc:
        reason = str(exc)
        if reason not in SAFE_REFUSAL_CODES:
            reason = "UNCLASSIFIED"
        print(f"P01_SSE_OPTIN_GATE_REASON={reason}")
        print("P01_SSE_OPTIN_GATE=BLOCKED")
        print("SECRET_VALUES_EMITTED=0")
        return 1
    except (config.ProductionConfigError, OSError, ValueError,
            TypeError, KeyError, AttributeError):
        print("P01_SSE_OPTIN_GATE_REASON=UNCLASSIFIED")
        print("P01_SSE_OPTIN_GATE=BLOCKED")
        print("SECRET_VALUES_EMITTED=0")
        return 1
    print("SECRET_VALUES_EMITTED=0")
    print("PROVIDER_REQUESTS=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
