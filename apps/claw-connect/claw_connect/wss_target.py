"""Closed, source-only PADIEM Connector WSS target admission (#4139).

This is a configuration validation primitive, NOT a TLS trust verifier,
certificate pin, registered hostname, dialer or permission to redeem a code.
The actual WSS connection is intentionally not enabled. A future authenticated
client MUST independently check certificate chain and DNS hostname using its
platform TLS library, and the receiving Worker MUST establish ingress trust.
"""
from __future__ import annotations

from urllib.parse import urlsplit

REVIEW_WSS_HOST = "chat.padiem.net"
REVIEW_WSS_PATH = "/api/claw/connector/gateway/session"
REVIEW_WSS_URL = "wss://" + REVIEW_WSS_HOST + REVIEW_WSS_PATH
WSS_PRODUCTION_DIALER_ENABLED = False


class WssTargetNotApproved(ValueError):
    """Target was not the single reviewed product origin and route."""


def review_only_pinned_wss_target(candidate: str) -> str:
    """Refuse any unreviewed authority, scheme, path, port, or URL decoration.

    Strict byte-exact matching prevents encoded separators, IDN homoglyphs,
    redirects and userinfo from being confused for the reviewed endpoint.
    It deliberately does NOT prove that the route is mounted/functional.
    """
    if type(candidate) is not str or candidate != REVIEW_WSS_URL:
        raise WssTargetNotApproved("unreviewed_connector_wss_target")
    parsed = urlsplit(candidate)
    if (
        parsed.scheme != "wss"
        or parsed.hostname != REVIEW_WSS_HOST
        or parsed.netloc != REVIEW_WSS_HOST
        or parsed.path != REVIEW_WSS_PATH
        or parsed.query or parsed.fragment or parsed.username or parsed.password
        or parsed.port is not None
    ):
        raise WssTargetNotApproved("unreviewed_connector_wss_target")
    return REVIEW_WSS_URL
