"""B14 owner-pinned default and ordered fallback roster per validated product tier.

Free's Google primary uses its owner-pinned recovery chain on recoverable
429, 5xx, and timeout failures. Other grades retain their own model routes.

Owner decision 2026-10-25: the test-phase Plus/Pro/Max/admin lanes use
Google with the same ordered backups as the shared Control Plane.
Free retains its primary and uses Gemma 4 31B as its first recovery model per Owner instruction 2026-11-04.

Owner decision 2026-11-04: Plus/Pro/Max/admin use TokenHarbor DeepSeek as
the single grade fallback. Free appends Kilo Crouton Alpha as its third
recovery model.
"""
TIER_DEFAULT_B14_MODEL = "google/gemini-3.1-flash-lite"
TIER_FALLBACK_B14_MODELS: dict[str, tuple[str, ...]] = {
    "max": ("google/gemini-3.1-flash-lite", "tokenharbor/deepseek-v4.1-flash:free"),
    "pro": ("google/gemini-3.1-flash-lite", "tokenharbor/deepseek-v4.1-flash:free"),
    "plus": ("google/gemini-3.1-flash-lite", "tokenharbor/deepseek-v4.1-flash:free"),
    "free": ("google/gemma-4-31b-it", "google/gemini-3.5-flash-lite", "kilo/stealth/crouton-alpha"),
    "admin": ("google/gemini-3.1-flash-lite", "tokenharbor/deepseek-v4.1-flash:free"),
}
