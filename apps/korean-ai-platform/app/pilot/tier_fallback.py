"""B14-owned exact per-grade provider fallback roster, separate from product auth.

Only the trusted PADIEM backend supplies the grade. Nothing here grants a
customer a paid entitlement or overrides model/provider availability.
"""

TIER_FALLBACK_B14_MODELS: dict[str, str] = {
    "free": "google/gemini-3.1-flash-lite",
    "plus": "google/gemini-3.5-flash-lite",
    "pro": "opencode-go/muse-spark-1.2-contributor",
    "max": "opencode-go/muse-spark-1.3-contributor",
}
