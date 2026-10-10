"""ExLab-only HTTP 429 provenance, derived from allow-listed error vocabulary.

No upstream error messages, raw code strings, headers, model inputs, account IDs,
response bodies, secrets or customer data are logged. Never infer rate/quota
causality from the HTTP status alone. See vendor stable errors documentation.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

_MAX_JSON_BODY_CHARS = 4096

# Experiential Labs official /docs/errors stable error-code vocabulary.
_CODE_TO_GROUP = {
    "insufficient_quota": "quota",
    "org_under_review": "org_review",
    "unavailable_route": "route_unavailable",
    "gateway_overloaded": "capacity",
    "card_required": "billing",
    "free_limit_reached": "quota",
    "model_requires_payment": "billing",
    "model_requires_purchase": "billing",
}

# Documented *message prefixes* for insufficient_quota only. These fixed
# tokens cannot leak personal information from the provider's freeform text.
_QUOTA_PREFIXES = (
    "org_token_rate_limit_hour",
    "org_token_rate_limit_day",
    "org_token_rate_limit",
    "free_limit_reached",
    "insufficient_credits",
    "org_rate_limit",
    "key_daily_cap",
    "promo_byok_only",
)


def classify_exlab_429(
    provider_id: str,
    status: int,
    headers: Mapping[str, str],
    body: str,
) -> dict[str, str | bool] | None:
    if provider_id != "experiential" or status != 429:
        return None

    content_type = str(headers.get("content-type", "")).split(";", 1)[0].strip().lower()
    media = (
        "json" if content_type in ("application/json", "application/problem+json")
        else "html" if content_type in ("text/html", "application/xhtml+xml")
        else "other"
    )
    group = "unclassified"
    subtype = "none"
    if media == "json" and len(body) <= _MAX_JSON_BODY_CHARS:
        try:
            data: Any = json.loads(body)
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict) and isinstance(data.get("error"), dict):
            error = data["error"]
            code = error.get("code")
            if isinstance(code, str) and code in _CODE_TO_GROUP:
                group = _CODE_TO_GROUP[code]
                if code == "insufficient_quota":
                    message = error.get("message")
                    if isinstance(message, str):
                        prefix = message.lstrip().lower()
                        for permitted in _QUOTA_PREFIXES:
                            if prefix == permitted or (
                                prefix.startswith(permitted)
                                and len(prefix) > len(permitted)
                                and prefix[len(permitted)] in " :(-"
                            ):
                                subtype = permitted
                                break
    return {
        "media": media,
        "reason_group": group,
        "quota_subtype": subtype,
        "retry_after_present": bool(headers.get("retry-after")),
        "cf_ray_present": bool(headers.get("cf-ray")),
    }


def log_exlab_429(
    logger: logging.Logger,
    provider_id: str,
    status: int,
    headers: Mapping[str, str],
    body: str,
) -> None:
    classified = classify_exlab_429(provider_id, status, headers, body)
    if classified is None:
        return
    logger.warning(
        "b14_exlab_429_safe_metadata media=%s reason_group=%s "
        "quota_subtype=%s retry_after_present=%s cf_ray_present=%s",
        classified["media"],
        classified["reason_group"],
        classified["quota_subtype"],
        classified["retry_after_present"],
        classified["cf_ray_present"],
    )
