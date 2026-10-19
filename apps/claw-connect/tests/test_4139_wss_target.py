"""No hostname/path confusion is allowed before a future WSS dialer exists."""
from __future__ import annotations

import pytest
from claw_connect.wss_target import (
    REVIEW_WSS_URL, REVIEW_WSS_HOST, REVIEW_WSS_PATH,
    WSS_PRODUCTION_DIALER_ENABLED, WssTargetNotApproved,
    review_only_pinned_wss_target,
)


def test_review_only_wss_target_is_pinned_but_production_dialer_is_off():
    assert REVIEW_WSS_HOST == "chat.padiem.net"
    assert REVIEW_WSS_PATH == "/api/claw/connector/gateway/session"
    assert WSS_PRODUCTION_DIALER_ENABLED is False
    assert review_only_pinned_wss_target(REVIEW_WSS_URL) == REVIEW_WSS_URL


@pytest.mark.parametrize("uri", [
    "", None, 1,
    "ws://chat.padiem.net/api/claw/connector/gateway/session",
    "https://chat.padiem.net/api/claw/connector/gateway/session",
    "wss://chat.padiem.net:443/api/claw/connector/gateway/session",
    "wss://chat.padiem.net./api/claw/connector/gateway/session",
    "wss://CHAT.PADIEM.NET/api/claw/connector/gateway/session",
    "wss://chat.padiem.net@evil.example/api/claw/connector/gateway/session",
    "wss://chat.padiem.net.evil.example/api/claw/connector/gateway/session",
    "wss://127.0.0.1/api/claw/connector/gateway/session",
    "wss://localhost/api/claw/connector/gateway/session",
    "wss://chat.padiem.net/api/claw/connector/gateway/session?key=secret",
    "wss://chat.padiem.net/api/claw/connector/gateway/session#fragment",
    "wss://chat.padiem.net/api/claw/connector/gateway/%73ession",
    "wss://chat.padiem.net/api/claw/connector/gateway/../session",
    "wss://chat.padiem.net/api/claw/connector/gateway/other",
    "wss://chat.padiem.net/api/claw/connector/gateway/session/",
])
def test_unapproved_targets_are_refused_before_any_transport(uri):
    with pytest.raises(WssTargetNotApproved, match="unreviewed_connector_wss_target"):
        review_only_pinned_wss_target(uri)
