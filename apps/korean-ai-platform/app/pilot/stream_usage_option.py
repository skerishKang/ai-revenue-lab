"""Streaming usage request option for OpenAI-compatible calls (#6812 stage 2).

A streamed answer consumed input tokens the ledger could not see: the streaming
request never asked for a usage report, so ``prompt_tokens`` stayed empty for
every streamed attempt while the same call in completed mode recorded it. The
option asks the endpoint for its final usage frame.

An endpoint that rejects an unknown request field would lose its answer to this
option, so two safety paths exist and both are provider-name-free:

* a deployment may exclude routes by their B14 platform route id through
  ``B14_STREAM_USAGE_OPT_OUT`` (comma-separated);
* a request-level rejection that names the field is retried once without it.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

STREAM_USAGE_OPT_OUT_ENV = "B14_STREAM_USAGE_OPT_OUT"
STREAM_USAGE_FIELD = "stream_options"
STREAM_USAGE_VALUE = "include_usage"


def stream_usage_opt_out(
    environ: Mapping[str, str] | None = None,
) -> frozenset[str]:
    """Route ids a deployment has excluded from the usage option."""
    values = os.environ if environ is None else environ
    raw = values.get(STREAM_USAGE_OPT_OUT_ENV) or ""
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def stream_options_payload() -> dict[str, bool]:
    """The exact request field this platform sends when the option is on."""
    return {STREAM_USAGE_VALUE: True}


def stream_usage_option_enabled(
    platform_provider_id: str | None,
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Whether this route may carry the usage option."""
    if not isinstance(platform_provider_id, str) or not platform_provider_id.strip():
        return False
    route = platform_provider_id.strip().lower()
    return route not in stream_usage_opt_out(environ)


def rejects_stream_usage_option(error_body: bytes | str | None) -> bool:
    """A request-level rejection that names the field is the one retry signal.

    Only the field name is inspected: the retry exists because the endpoint did
    not understand the request shape, not because of anything in the content.
    """
    if isinstance(error_body, bytes):
        text = error_body.decode("utf-8", "replace")
    elif isinstance(error_body, str):
        text = error_body
    else:
        return False
    lowered = text.lower()
    return STREAM_USAGE_FIELD in lowered or STREAM_USAGE_VALUE in lowered
