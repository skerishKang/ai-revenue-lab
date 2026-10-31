"""B14 owner-pinned default and ordered fallback roster per validated product tier.

Free's Google primary uses its owner-pinned recovery chain on recoverable
429, 5xx, and timeout failures. Other grades retain their own model routes.

Owner decision 2026-10-25: the test-phase Plus/Pro/Max/admin lanes use
Google with the same ordered backups as the shared Control Plane.
Free retains its existing primary and recovery roster.
"""
TIER_DEFAULT_B14_MODEL = "google/gemini-3.1-flash-lite"
TIER_FALLBACK_B14_MODELS: dict[str, tuple[str, ...]] = {
    "max": ("google/gemini-3.1-flash-lite", "google/gemma-4-31b-it"),
    "pro": ("google/gemini-3.1-flash-lite", "google/gemma-4-31b-it"),
    "plus": ("google/gemini-3.1-flash-lite", "google/gemma-4-31b-it"),
    "free": ("google/gemma-4-26b-a4b-it", "google/gemini-3.5-flash-lite", "google/gemma-4-31b-it"),
    "admin": ("google/gemini-3.1-flash-lite", "google/gemma-4-31b-it"),
}
