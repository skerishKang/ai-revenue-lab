"""B14 owner-pinned default and ordered fallback roster per validated product tier.

The default is shared; recoverable 429, 5xx, and timeout move through the
explicit grade-specific chain. B14 never selects arbitrary catalog models.
"""
TIER_DEFAULT_B14_MODEL = "opencode-go/beam-free"
TIER_FALLBACK_B14_MODELS: dict[str, tuple[str, ...]] = {
    "max": ("opencode-go/longcat-2.5-preview-free", "opencode-go/muse-spark-1.3-contributor"),
    "pro": ("opencode-go/longcat-2.5-preview-free", "google/gemma-4-31b-it"),
    "plus": ("opencode-go/longcat-2.5-preview-free", "google/gemini-3.5-flash-lite", "google/gemma-4-31b-it"),
    "free": ("opencode-go/longcat-2.5-preview-free", "google/gemini-3.1-flash-lite", "google/gemma-4-26b-a4b-it"),
}
