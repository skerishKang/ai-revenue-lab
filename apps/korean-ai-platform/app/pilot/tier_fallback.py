"""B14 owner-pinned default and ordered fallback roster per validated product tier.

Free's Google primary uses its owner-pinned recovery chain on recoverable
429, 5xx, and timeout failures. Other grades retain their own model routes.

Owner decision 2026-10-21 (#2505): an OpenCode Go free model is never an
execution candidate, so it leaves every designated per-grade roster. The paid
OpenCode Go model stays in the roster it belongs to.
"""
TIER_DEFAULT_B14_MODEL = "google/gemini-3.1-flash-lite"
TIER_FALLBACK_B14_MODELS: dict[str, tuple[str, ...]] = {
    "max": ("opencode-go/muse-spark-1.3-contributor",),
    "pro": ("google/gemma-4-31b-it",),
    "plus": ("google/gemini-3.5-flash-lite", "google/gemma-4-31b-it"),
    "free": ("google/gemma-4-26b-a4b-it", "google/gemini-3.5-flash-lite", "google/gemma-4-31b-it"),
}
