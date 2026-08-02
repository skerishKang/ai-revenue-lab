"""Live smoke test for Business 14 Alpha OpenRouter integration.

Conditions:
- Opens when no OPENROUTER_API_KEY → SKIP
- Not run in automatic CI
- Uses a free or very low-cost model
- Sets max_tokens to a very low value
- Makes only one request
- Does NOT print API key, Authorization header, or full response body
- Only sanitizes output: model, request ID, usage, success/failure

Usage:
    python3 -m app.pilot.smoke_live
"""

from __future__ import annotations

import json
import sys

from app.pilot.openrouter_config import openrouter_config
from app.pilot.catalog import get_catalog_by_id
from app.pilot.openrouter import call_openrouter_chat_completions


def run_live_smoke() -> int:
    print("=== Business 14 Alpha — Live Smoke Test ===")
    print(f"Provider mode: {openrouter_config.provider_mode}")
    print(f"Has key: {'yes' if openrouter_config.has_key else 'no'}")
    print()

    if not openrouter_config.has_key:
        print("LIVE_SMOKE_READY_NOT_EXECUTED")
        print("OPENROUTER_API_KEY not set or is a placeholder.")
        print("Set B14_PROVIDER_MODE=live and OPENROUTER_API_KEY in .env, then re-run.")
        return 0

    if openrouter_config.is_mock:
        print("LIVE_SMOKE_READY_NOT_EXECUTED")
        print("B14_PROVIDER_MODE=mock — live smoke requires B14_PROVIDER_MODE=live.")
        return 0

    # Use the free model to minimize cost
    cm = get_catalog_by_id("openrouter/free")
    if cm is None:
        print("ERROR: openrouter/free not found in catalog")
        return 1

    model_id = cm.model_id
    upstream_model = cm.upstream_model

    messages = [
        {"role": "user", "content": "한국어로 세 문장으로 설명해줘"},
    ]

    print(f"Model: {model_id} (upstream: {upstream_model})")
    print(f"Max tokens: 16 (very low for smoke test)")
    print("Sending request...")

    import asyncio

    try:
        result = asyncio.run(
            call_openrouter_chat_completions(
                messages=messages,
                temperature=0.2,
                max_tokens=16,
                model_id=model_id,
                upstream_model=upstream_model,
                provider=cm.provider,
            )
        )
    except Exception as e:
        print(f"FAILED: {type(e).__name__}")
        print("No API key, Authorization header, or response body is shown.")
        return 1

    # Sanitized output only
    usage = result.get("usage") or {}
    choices = result.get("choices", [])
    content_preview = ""
    if choices and len(choices) > 0:
        msg = choices[0].get("message", {})
        content_preview = msg.get("content", "")[:100]

    print()
    print("SMOKE_TEST_OK")
    print(f"  model: {model_id}")
    print(f"  request_id: {result.get('id', '-')}")
    print(f"  prompt_tokens: {usage.get('prompt_tokens', '?')}")
    print(f"  completion_tokens: {usage.get('completion_tokens', '?')}")
    print(f"  total_tokens: {usage.get('total_tokens', '?')}")
    print(f"  response_preview: {content_preview[:80]}...")
    print()
    print("No API key, Authorization header, or full response body was printed.")
    return 0


if __name__ == "__main__":
    sys.exit(run_live_smoke())
