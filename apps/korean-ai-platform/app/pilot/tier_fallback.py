"""B14 owner-pinned default and ordered fallback roster per validated product tier.

Free's Google primary uses its owner-pinned recovery chain on recoverable
429, 5xx, and timeout failures. Other grades retain their own model routes.

Owner decision 2026-10-25: the test-phase Plus/Pro/Max/admin lanes use
Google with the same ordered backups as the shared Control Plane.
Free retains its primary and uses Gemma 4 31B as its first recovery model per Owner instruction 2026-11-04.

Owner decision 2026-11-04: Plus/Pro/Max/admin insert TokenHarbor DeepSeek as
the first fallback, then Kilo Crouton Alpha and OpenRouter Crouton Alpha,
keeping Gemma as the last. Free inserts Kilo Crouton Alpha as its first
fallback and OpenRouter Crouton Alpha as its second, ahead of Gemma and
Gemini 3.5.
"""
TIER_DEFAULT_B14_MODEL = "google/gemini-3.1-flash-lite"
TIER_FALLBACK_B14_MODELS: dict[str, tuple[str, ...]] = {
    "max": ("google/gemini-3.1-flash-lite", "tokenharbor/deepseek-v4.1-flash:free", "kilo/stealth/crouton-alpha", "openrouter/stealth/crouton-alpha", "google/gemma-4-31b-it"),
    "pro": ("google/gemini-3.1-flash-lite", "tokenharbor/deepseek-v4.1-flash:free", "kilo/stealth/crouton-alpha", "openrouter/stealth/crouton-alpha", "google/gemma-4-31b-it"),
    "plus": ("google/gemini-3.1-flash-lite", "tokenharbor/deepseek-v4.1-flash:free", "kilo/stealth/crouton-alpha", "openrouter/stealth/crouton-alpha", "google/gemma-4-31b-it"),
    "free": ("kilo/stealth/crouton-alpha", "openrouter/stealth/crouton-alpha", "google/gemma-4-31b-it", "google/gemini-3.5-flash-lite"),
    "admin": ("google/gemini-3.1-flash-lite", "tokenharbor/deepseek-v4.1-flash:free", "kilo/stealth/crouton-alpha", "openrouter/stealth/crouton-alpha", "google/gemma-4-31b-it"),
}
