"""No-mutation gate for a separately uploaded B14 Worker version.

Only immutable IDs/verdicts are printed; never print the Cloudflare metadata
envelope, credential values, provider mapping, or upstream response payload.
The candidate's SHA tag is an uploader attestation, not a cryptographic code proof.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_VERSION = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$")
_SHA = re.compile(r"^[a-f0-9]{40}$")
_ALIAS = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def resolve_preview_alias(version_id: str, main_sha: str, versions: object) -> str:
    if not _VERSION.fullmatch(version_id) or not _SHA.fullmatch(main_sha):
        raise ValueError("INVALID_ID_OR_SHA")
    if not isinstance(versions, list):
        raise ValueError("VERSIONS_NOT_LIST")
    matched = [v for v in versions if isinstance(v, dict) and v.get("id") == version_id]
    if len(matched) != 1:
        raise ValueError("CANDIDATE_VERSION_NOT_UNIQUE_OR_ABSENT")
    annotation = matched[0].get("annotations")
    if not isinstance(annotation, dict) or annotation.get("workers/tag") != f"padiem-main-{main_sha}":
        raise ValueError("CANDIDATE_MAIN_ATTESTATION_MISSING")
    alias = annotation.get("workers/alias")
    if not isinstance(alias, str) or not _ALIAS.fullmatch(alias):
        raise ValueError("CANDIDATE_PREVIEW_ALIAS_UNAVAILABLE")
    return alias


def verify_candidate(version_id: str, main_sha: str, versions: object, health: object, models: object) -> None:
    resolve_preview_alias(version_id, main_sha, versions)
    if not isinstance(health, dict) or health.get("status") != "ok":
        raise ValueError("CANDIDATE_HEALTH_NOT_OK")
    b14 = health.get("business14")
    providers = b14.get("providers") if isinstance(b14, dict) else None
    if not isinstance(providers, list) or len(providers) != 11:
        raise ValueError("CANDIDATE_PROVIDER_COUNT_UNEXPECTED")
    if any(not isinstance(p, dict) or p.get("has_key") is not True for p in providers):
        raise ValueError("CANDIDATE_CREDENTIAL_GETTER_NOT_READY")
    if not isinstance(models, dict) or not isinstance(models.get("catalog"), list) or not models["catalog"]:
        raise ValueError("CANDIDATE_CATALOG_NOT_AVAILABLE")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version-id", required=True)
    parser.add_argument("--main-sha", required=True)
    parser.add_argument("--versions-json", type=Path, required=True)
    parser.add_argument("--health-json", type=Path)
    parser.add_argument("--models-json", type=Path)
    parser.add_argument("--preview-alias-only", action="store_true")
    args = parser.parse_args()
    try:
        versions = json.loads(args.versions_json.read_text(encoding="utf-8"))
        if args.preview_alias_only:
            print(resolve_preview_alias(args.version_id, args.main_sha, versions))
            return 0
        if args.health_json is None or args.models_json is None:
            raise ValueError("CANDIDATE_HEALTH_AND_CATALOG_REQUIRED")
        verify_candidate(
            args.version_id, args.main_sha, versions,
            json.loads(args.health_json.read_text(encoding="utf-8")),
            json.loads(args.models_json.read_text(encoding="utf-8")),
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        # Fixed errors only. Do not leak exception messages from external input.
        reason = str(exc) if isinstance(exc, ValueError) and str(exc).isupper() else "CANDIDATE_EVIDENCE_UNREADABLE"
        print(f"B14_PRIVATE_CANDIDATE_PREFLIGHT=FAIL:{reason}")
        print("PRODUCTION_MUTATION=NO")
        return 2
    print("B14_PRIVATE_CANDIDATE_PREFLIGHT=PASS")
    print("CANDIDATE_BINDING_GETTER=11_OF_11_PASS")
    print("CANDIDATE_SOURCE_TAG=EXACT_MAIN_ATTESTED")
    print("PRODUCTION_MUTATION=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
