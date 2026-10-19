"""B14 one-command existing-provider model registration; JSON only, NO provider calls.

Run once: add -> strict registry+owner checks -> one append-only JSON edit.
Separate GitHub CI already selects B14+B62 fast lanes for exact registry-only
changes. This tool never dispatches/deploys, reads credentials, or calls LLMs.
New providers need a distinct one-time reviewed binding/Secret onboarding.
"""
from __future__ import annotations

import argparse
import copy
from datetime import date
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "apps/korean-ai-platform/app/pilot/b14_models.json"
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT / "apps/korean-ai-platform") not in sys.path:
    sys.path.insert(0, str(ROOT / "apps/korean-ai-platform"))

from b14_model_registration_ci_plan import exact_append_only  # noqa: E402
from b14_owner_evaluation_registry import load_current_models  # noqa: E402
from app.pilot.model_registry_file import read_registry  # noqa: E402


class OnboardError(ValueError):
    """Non-sensitive failure code: no model input or source path is echoed."""


def checked_registry(path: Path) -> dict:
    data = read_registry(path)
    if len(load_current_models(path)) != len(data["models"]):
        raise OnboardError("some_models_disallowed_by_owner")
    return data


def make_candidate(registry: dict, *, provider: str, upstream: str, name: str,
                   source: str, checked_at: str, capabilities: list[str],
                   context_window: int = 0, input_price: float | None = None,
                   output_price: float | None = None) -> dict:
    spec = registry["providers"].get(provider)
    if spec is None:
        raise OnboardError("NEW_PROVIDER_REQUIRES_ONE_TIME_CREDENTIAL_BINDING")
    if spec.get("enabled") is not True:
        raise OnboardError("provider_not_enabled")
    if not upstream or not name.strip():
        raise OnboardError("model_name_or_upstream_missing")
    model_id = provider + "/" + upstream
    if any(row["id"] == model_id for row in registry["models"]):
        raise OnboardError("model_id_already_registered")
    try:
        date.fromisoformat(checked_at)
    except (TypeError, ValueError) as exc:
        raise OnboardError("source_checked_date_invalid") from exc
    url = urlsplit(source)
    if url.scheme != "https" or not url.netloc or url.username or url.password:
        raise OnboardError("official_source_must_be_https")
    tags = sorted(set(capabilities))
    if not tags or "chat" not in tags or not set(tags).issubset({"chat", "coding", "image"}):
        raise OnboardError("unsupported_or_unverified_capability")
    if isinstance(context_window, bool) or not isinstance(context_window, int) or context_window < 0:
        raise OnboardError("context_window_invalid")
    for price in (input_price, output_price):
        if price is not None and (isinstance(price, bool) or
                                  not isinstance(price, (float, int)) or
                                  not (0 <= price < float("inf"))):
            raise OnboardError("price_invalid")
    own = [m for m in registry["models"] if m["provider_id"] == provider]
    if not own or len({m["provider_name"] for m in own}) != 1:
        raise OnboardError("provider_display_name_ambiguous")
    return {
        "id": model_id,
        "provider_id": provider,
        "upstream_model": upstream,
        "display_name": name,
        "provider_name": own[0]["provider_name"],
        "capabilities": tags,
        "context_window": context_window,
        "input_price_usd_per_1m": input_price,
        "output_price_usd_per_1m": output_price,
        "source": source,
        "source_checked_at": checked_at,
        "enabled": True,
    }


def prepare_append(registry: dict, candidate: dict) -> dict:
    result = copy.deepcopy(registry)
    result["models"].append(candidate)
    if not exact_append_only(registry, result):
        raise OnboardError("change_not_safe_append_only")
    return result


def check_candidate_json(data: dict, path: Path) -> None:
    """Existing canonical validators, with *temporary* file never placed in Git."""
    fd, temp = tempfile.mkstemp(prefix="b14-model-check-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(data, out, ensure_ascii=False, indent=2)
        checked_registry(Path(temp))
    finally:
        Path(temp).unlink(missing_ok=True)


def safe_write(path: Path, before: str, data: dict) -> None:
    if path.read_text(encoding="utf-8") != before:
        raise OnboardError("registry_modified_during_validation")
    fd, temp = tempfile.mkstemp(prefix=".b14-registry-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
            out.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="B14 existing-provider JSON quick-add; offline only")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="Validate existing canonical registry; no HTTP")
    check.add_argument("--model-id", default=None, help="Optional exact model ID to check")
    add = sub.add_parser("add", help="Preview JSON-only append, then --write to apply")
    add.add_argument("--provider", required=True)
    add.add_argument("--upstream", required=True)
    add.add_argument("--name", required=True)
    add.add_argument("--source", required=True, help="Official HTTPS model specification")
    add.add_argument("--checked-at", required=True, help="Verified YYYY-MM-DD")
    add.add_argument("--capability", action="append", default=["chat"])
    add.add_argument("--context-window", type=int, default=0, help="0 if unknown")
    add.add_argument("--input-price", type=float, default=None)
    add.add_argument("--output-price", type=float, default=None)
    add.add_argument("--write", action="store_true", help="Explicitly append to canonical JSON")
    args = parser.parse_args(argv)
    try:
        before = REGISTRY.read_text(encoding="utf-8")
        old = checked_registry(REGISTRY)
        if args.command == "check":
            if args.model_id and args.model_id not in {x["id"] for x in old["models"]}:
                raise OnboardError("model_not_registered")
            result = {"status": "PASS", "mode": "OFFLINE_REGISTRY_VALIDATION",
                      "model_count": len(old["models"]), "providers": len(old["providers"]),
                      "provider_api_posts": 0, "production_mutation": False}
        else:
            candidate = make_candidate(
                old, provider=args.provider, upstream=args.upstream, name=args.name,
                source=args.source, checked_at=args.checked_at,
                capabilities=args.capability, context_window=args.context_window,
                input_price=args.input_price, output_price=args.output_price,
            )
            updated = prepare_append(old, candidate)
            check_candidate_json(updated, REGISTRY)
            if args.write:
                safe_write(REGISTRY, before, updated)
            result = {"status": "PASS", "mode": "JSON_APPENDED" if args.write else "DRY_RUN",
                      "model_id": candidate["id"], "existing_provider": args.provider,
                      "model_count_after": len(updated["models"]),
                      "expected_ci_lane": "model_registration_only",
                      "provider_api_posts": 0, "production_mutation": False,
                      "next": "one PR + fast CI + one authorized official deployment"}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OnboardError, OSError, ValueError, KeyError, TypeError) as exc:
        # Never print raw URL, response, path, secret, model output or exception text.
        reason = str(exc) if isinstance(exc, OnboardError) else "canonical_registry_validation_failed"
        print(json.dumps({"status": "BLOCKED", "reason": reason,
                          "provider_api_posts": 0, "production_mutation": False},
                         ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
