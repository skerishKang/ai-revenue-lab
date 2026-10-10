"""Agnes-only HTTP429 observability without upstream PII or secret exposure.

Issue #3913: classify only allow-listed response metadata. No logging of
request/response bodies, raw upstream error codes, headers, model inputs,
credentials, account ids, or customer data. A signal is not a WAF diagnosis.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Mapping

_MAX_CLASSIFIER_BODY_CHARS = 4096


def classify_agnes_429(
    provider_id: str,
    status_code: int,
    headers: Mapping[str, str],
    error_body: str,
) -> dict[str, str | bool] | None:
    if provider_id != "agnes-ai" or status_code != 429:
        return None
    content_type = str(headers.get("content-type", "")).split(";", 1)[0].strip().lower()
    media = "json" if "json" in content_type else ("html" if "html" in content_type else "other")
    category = "unclassified"
    if media == "json":
        try:
            parsed: Any = json.loads(error_body[:_MAX_CLASSIFIER_BODY_CHARS])
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
            error = parsed["error"]
            # Whitelist a small, non-sensitive classification surface.
            identifiers = []
            for k in ("code", "type"):
                v = error.get(k)
                if isinstance(v, str):
                    identifiers.append(v.lower()[:100])
            flags = " ".join(identifiers)
            if "quota" in flags or "balance" in flags or "credit" in flags:
                category = "quota"
            elif "rate" in flags or "too_many" in flags or "throttle" in flags:
                category = "rate_limit"
            elif "busy" in flags or "capacity" in flags or "overload" in flags:
                category = "capacity"
            elif "block" in flags or "policy" in flags or "waf" in flags:
                category = "policy"
    return {
        "media": media,
        "reason_group": category,
        "retry_after_present": bool(headers.get("retry-after")),
        "cf_ray_present": bool(headers.get("cf-ray")),
        "server_cloudflare": str(headers.get("server", "")).strip().lower() == "cloudflare",
    }


def log_agnes_429(
    logger: logging.Logger,
    provider_id: str,
    status_code: int,
    headers: Mapping[str, str],
    error_body: str,
) -> None:
    safe = classify_agnes_429(provider_id, status_code, headers, error_body)
    if safe is None:
        return
    logger.warning(
        "agnes_429_safe_metadata media=%s reason_group=%s "
        "retry_after_present=%s cf_ray_present=%s server_cloudflare=%s",
        safe["media"],
        safe["reason_group"],
        safe["retry_after_present"],
        safe["cf_ray_present"],
        safe["server_cloudflare"],
    )
