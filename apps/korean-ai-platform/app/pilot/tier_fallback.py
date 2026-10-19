"""B14 owner-pinned default and ordered fallback roster per validated product tier.

Free's Google primary uses its owner-pinned recovery chain on recoverable
429, 5xx, and timeout failures. Other grades retain their own model routes.
"""
TIER_DEFAULT_B14_MODEL = "google/gemini-3.1-flash-lite"
TIER_FALLBACK_B14_MODELS: dict[str, tuple[str, ...]] = {
    "max": ("opencode-go/longcat-2.5-preview-free", "opencode-go/muse-spark-1.3-contributor"),
    "pro": ("opencode-go/longcat-2.5-preview-free", "google/gemma-4-31b-it"),
    "plus": ("opencode-go/longcat-2.5-preview-free", "google/gemini-3.5-flash-lite", "google/gemma-4-31b-it"),
    "free": ("google/gemma-4-26b-a4b-it", "google/gemini-3.5-flash-lite", "google/gemma-4-31b-it"),
}
