"""Read-only owner-approved B14 evaluation selector.

Canonical source: apps/korean-ai-platform/app/pilot/b14_models.json.
Discovery results, legacy candidate fixtures and old PR/issue prose are NOT
authorization. This file performs no HTTP calls, auth lookups or deployments.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_REGISTRY = ROOT / "apps/korean-ai-platform/app/pilot/b14_models.json"
OWNER_RETIRED = frozenset({
    "b-ai/qwen3.8-flash",
    "experiential/gpt-5.6-luna",
    "infron/motif/motif-3",
    "kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
    "kilo/poolside-laguna-s-2.1-free",
    "kilo/stepfun/step-3.7-flash",
    "kilo/stepfun-step-3.7-flash",
    "stepfun/step-3.7-flash",
    "thinkingmachines/inkling-small:free",
    "kilo/thinkingmachines/inkling-small:free",
    "kilo/thinkingmachines-inkling-small-free",
})
# Historical #2676 benchmark selectors. These must NOT form an independent
# evaluation allowlist after the 2026-10-08 Owner registry migration.
HISTORICAL_SELECTORS = {
    "agnes": "agnes-ai/agnes-3.0-flash",
    "mercury": "inception/mercury-2.5",
    "atria": "atria/Atria-Dawn-Preview",
    "motif": "infron/motif/motif-3",
    "luna": "experiential/gpt-5.6-luna",
}
MAX_EVALUATION_BATCH = 16


def _disallowed_model_id(model_id: str) -> bool:
    if model_id in OWNER_RETIRED:
        return True
    lowered = model_id.lower()
    # The Owner removed ALL Kilo-routed Laguna aliases, regardless of how
    # upstream model discovery spells the free route. Direct Poolside differs.
    if lowered.startswith("kilo/") and "poolside" in lowered and "laguna" in lowered:
        return True
    # Owner removed Step 3.7 Flash from *all* candidate routes. Step 5 stays.
    if "stepfun/step-3.7-flash" in lowered or "stepfun-step-3.7-flash" in lowered:
        return True
    # Owner also retired only Thinking Machines Inkling Small, not all
    # smaller-capacity models. Treat free-route and Kilo aliases identically.
    return re.search(
        r"(?:^|/)thinkingmachines(?:/|-)inkling-small(?=$|[:/\-])", lowered
    ) is not None


def load_current_models(path: Path = CANONICAL_REGISTRY) -> dict[str, dict[str, Any]]:
    """Load only enabled exact registry models, never provider search output."""
    data = json.loads(path.read_text(encoding="utf-8"))
    providers = data.get("providers")
    rows = data.get("models")
    if not isinstance(providers, dict) or not isinstance(rows, list):
        raise ValueError("registry_shape_invalid")
    allowed: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("registry_model_invalid")
        model_id = row.get("id")
        provider_id = row.get("provider_id")
        upstream = row.get("upstream_model")
        if not all(isinstance(x, str) and x.strip() for x in (model_id, provider_id, upstream)):
            raise ValueError("registry_model_identity_invalid")
        if model_id in allowed:
            raise ValueError("registry_duplicate_model_id")
        if _disallowed_model_id(model_id) or _disallowed_model_id(upstream):
            raise ValueError("owner_retired_model_in_registry")
        provider = providers.get(provider_id)
        if not isinstance(provider, dict) or not provider.get("enabled", False):
            raise ValueError("model_provider_unavailable")
        if model_id.split("/", 1)[0] != provider_id:
            raise ValueError("model_provider_identity_mismatch")
        if row.get("enabled") is not True:
            continue
        if provider_id == "poolside":
            if (
                model_id != "poolside/laguna-s-2.1"
                or upstream != "poolside/laguna-s-2.1"
                or provider.get("base_origin") != "https://inference.poolside.ai/v1"
                or provider.get("credential_source") != "platform_secret"
                or provider.get("credential_binding_name") != "PADIEM_POOLSIDE_API_KEY"
            ):
                raise ValueError("poolside_must_use_direct_provider")
        allowed[model_id] = row
    return allowed


def authorize_exact_models(
    model_ids: Iterable[str], *, path: Path = CANONICAL_REGISTRY
) -> tuple[str, ...]:
    """Fail closed before any evaluation/provider call; no replacement route."""
    selected = tuple(model_ids)
    if not selected or len(selected) > MAX_EVALUATION_BATCH:
        raise ValueError("evaluation_candidate_count_invalid")
    if len(set(selected)) != len(selected):
        raise ValueError("evaluation_duplicate_candidates")
    available = load_current_models(path)
    for model_id in selected:
        if not isinstance(model_id, str) or _disallowed_model_id(model_id):
            raise ValueError("owner_excluded_evaluation_model")
        if model_id not in available:
            raise ValueError("model_not_in_canonical_registry")
    return selected


def authorize_historical_selector(
    selector: str, *, path: Path = CANONICAL_REGISTRY
) -> tuple[str, ...]:
    """Protect the old six-case live workflow; old 5-model set is withdrawn."""
    if selector == "all-five":
        raise ValueError("legacy_all_five_contains_retired_models")
    model_id = HISTORICAL_SELECTORS.get(selector)
    if model_id is None:
        raise ValueError("legacy_selector_unrecognized")
    return authorize_exact_models((model_id,), path=path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only B14 Owner model gate")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true")
    group.add_argument("--check", metavar="EXACT_MODEL_ID")
    group.add_argument("--legacy-check", metavar="LEGACY_SELECTOR")
    args = parser.parse_args(argv)
    try:
        models = load_current_models()
        if args.check:
            ids = authorize_exact_models((args.check,))
        elif args.legacy_check:
            ids = authorize_historical_selector(args.legacy_check)
        else:
            ids = tuple(models)
        result = {
            "authority": "B14_CANONICAL_REGISTRY_ONLY",
            "source": CANONICAL_REGISTRY.relative_to(ROOT).as_posix(),
            "candidate_count": len(ids),
            "model_ids": list(ids),
            "network_calls": 0,
            "automatic_fallbacks": 0,
            "customer_tier_activated": False,
            "production_changed": False,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"B14_OWNER_EVALUATION=BLOCKED:{exc}")
        print("LIVE_PROVIDER_CALL=0")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
