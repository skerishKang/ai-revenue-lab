#!/usr/bin/env python3
"""Read-only P01 SSE post-PATCH immutable version forensics (#3936).

Print bounded differences ONLY: property names, counts, comparison booleans,
and SHA256 prefixes of binding *names*. Never echo configuration values,
secret contents, resource blobs, Cloudflare tokens, or arbitrary exception text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

BEFORE = "181d637c-de84-4919-9d45-8e966a07f181"
FAILED_PATCH = "18ee50a1-ab64-4cc0-8fc2-2ed3234f63a5"
SECOND_BEFORE = "d62bef73-f9d3-4559-88f9-cecbba785bb9"
SECOND_FAILED_PATCH = "00d38813-df7b-4b73-b00a-5c7b26ed3b7a"
FLAG = "PADIEM_CLAW_P01_LIVE_SSE_ENABLED"


class ForensicRefused(ValueError):
    pass


def _result(payload: object, expected: str) -> dict:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ForensicRefused("UNTRUSTED_VERSION_RESPONSE")
    result = payload.get("result")
    if not isinstance(result, dict) or result.get("id") != expected:
        raise ForensicRefused("PINNED_VERSION_MISMATCH")
    resources = result.get("resources")
    if not isinstance(resources, dict) or not isinstance(resources.get("script"), dict):
        raise ForensicRefused("IMMUTABLE_RESOURCE_SHAPE")
    return result


def _binding_inventory(resources: dict) -> dict[str, dict]:
    raw = resources.get("bindings")
    if isinstance(raw, dict):
        raw = [{**value, "name": name} for name, value in raw.items()
               if isinstance(name, str) and isinstance(value, dict)
               and value.get("name", name) == name]
    if not isinstance(raw, list):
        raise ForensicRefused("VERSION_BINDINGS_SHAPE")
    result: dict[str, dict] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise ForensicRefused("VERSION_BINDING_INVALID")
        name = item.get("name")
        kind = item.get("type")
        if not isinstance(name, str) or not name or not isinstance(kind, str):
            raise ForensicRefused("VERSION_BINDING_INVALID")
        if name in result:
            raise ForensicRefused("VERSION_DUPLICATE_BINDING")
        result[name] = item
    return result


def compare(before: object, after: object, *, incident: str = "first") -> dict[str, object]:
    # Both historical incidents are immutable and explicitly pinned. Arbitrary
    # versions cannot be compared under this Production GET authority.
    if incident == "first":
        before_id, after_id = BEFORE, FAILED_PATCH
    elif incident == "second":
        before_id, after_id = SECOND_BEFORE, SECOND_FAILED_PATCH
    else:
        raise ForensicRefused("UNKNOWN_PINNED_INCIDENT")
    old = _result(before, before_id)
    new = _result(after, after_id)
    old_res, new_res = old["resources"], new["resources"]
    old_bind, new_bind = _binding_inventory(old_res), _binding_inventory(new_res)
    old_without = {k: v for k, v in old_bind.items() if k != FLAG}
    new_without = {k: v for k, v in new_bind.items() if k != FLAG}
    # Account for opaque version-bound Secret references: compare them exactly,
    # but never print the reference identity or its value to CI.
    delta = set(old_without) ^ set(new_without)
    delta |= {name for name in set(old_without) & set(new_without)
              if old_without[name] != new_without[name]}
    nonbinding = sorted(k for k in set(old_res) | set(new_res)
                        if k != "bindings" and old_res.get(k) != new_res.get(k))
    script_a, script_b = old_res["script"], new_res["script"]
    etag_a, etag_b = script_a.get("etag"), script_b.get("etag")
    if not isinstance(etag_a, str) or not etag_a or not isinstance(etag_b, str) or not etag_b:
        raise ForensicRefused("SCRIPT_ETAG_MISSING")
    flag = new_bind.get(FLAG)
    # Exact post-PATCH comparison used by the guarded opt-in verifier. Only
    # Cloudflare's server-owned deployment-origin script field is normalized.
    def code_resources(resources: dict) -> dict:
        result = {k: v for k, v in resources.items() if k != "bindings"}
        script = result["script"]
        result["script"] = {k: v for k, v in script.items()
                            if k != "last_deployed_from"}
        return result
    return {
        "old_bindings": len(old_bind),
        "new_bindings": len(new_bind),
        "flag_added_true": FLAG not in old_bind and
            flag is not None and flag.get("type") == "plain_text" and flag.get("text") == "true",
        "other_binding_diff_count": len(delta),
        "verifier_postbinding_exact": not delta and flag is not None and
            flag.get("type") == "plain_text" and flag.get("text") == "true",
        "verifier_code_resources_exact": code_resources(old_res) == code_resources(new_res),
        "other_binding_diff_name_hashes": sorted(
            hashlib.sha256(n.encode()).hexdigest()[:12] for n in delta),
        "nonbinding_changed_resource_keys": nonbinding,
        "script_changed_field_names": sorted(k for k in set(script_a) | set(script_b)
            if script_a.get(k) != script_b.get(k)),
        "script_etag_same": etag_a == etag_b,
        "script_runtime_same": old_res.get("script_runtime") == new_res.get("script_runtime"),
        "assets_same": old_res.get("assets") == new_res.get("assets"),
        "version_record_changed_fields": sorted(
            k for k in set(old) | set(new)
            if k not in {"id", "resources"} and old.get(k) != new.get(k)),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--before", type=Path, required=True)
    p.add_argument("--after", type=Path, required=True)
    p.add_argument("--incident", choices=("first", "second"), default="first")
    a = p.parse_args()
    try:
        result = compare(
            json.loads(a.before.read_text(encoding="utf-8")),
            json.loads(a.after.read_text(encoding="utf-8")), incident=a.incident)
    except (ForensicRefused, OSError, ValueError, TypeError, KeyError) as exc:
        print("P01_IMMUTABLE_FORENSIC=BLOCKED")
        print("P01_IMMUTABLE_FORENSIC_REASON=" + (
            str(exc) if isinstance(exc, ForensicRefused) else "INVALID_INPUT"))
        print("PRODUCTION_MUTATION=0")
        return 2
    print("P01_IMMUTABLE_FORENSIC=PASS")
    for field, value in result.items():
        print("FORENSIC_" + field.upper() + "=" + json.dumps(value, separators=(",", ":")))
    print("SECRET_VALUES_READ=0")
    print("PRODUCTION_MUTATION=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
