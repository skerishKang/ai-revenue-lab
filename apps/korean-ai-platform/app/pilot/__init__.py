"""Business 14 pilot package bootstrap."""

# Register approved platform-owned Providers before any catalog/router consumer
# imports their runtime view. Registration is idempotent and performs no network
# calls or secret reads beyond later readiness checks.
from app.pilot.poolside_provider import register_poolside_provider

register_poolside_provider()
