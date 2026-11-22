"""Shipped-source reads and parsed facts for the #7368 status-retry contracts.

Raw reads live here (reusing claw_static); the test keeps its Node behavior
harness and asserts on named call-site facts and parsed script order.
"""
from __future__ import annotations

from _support.claw_static import sheet
from _support.html_tags import tags_for_page


def transport_source() -> str:
    return sheet("chat-transport.js")


def call_site_facts() -> dict:
    app = sheet("app.js")
    connectors = sheet("chat-connectors-module.js")
    manager = sheet("claw-connector-management.js")
    device = sheet("claw-device-manager.js")
    return {
        "connectors_routes_through_helper": (
            'PadiemChatTransport.fetchStatusWithRetry("/api/connectors/status"' in connectors
        ),
        "connectors_has_direct_fetch": 'fetch("/api/connectors/status"' in connectors,
        "app_has_direct_fetch": 'fetch("/api/connectors/status"' in app,
        "device_routes_through_helper": "PadiemChatTransport.fetchStatusWithRetry(ENDPOINT" in device,
        "manager_routes_through_helper": "PadiemChatTransport.fetchStatusWithRetry(url" in manager,
        "front_marker_sources": [
            name for name, source in (
                ("app.js", app), ("claw-connector-management.js", manager), ("claw-device-manager.js", device),
            ) if "x-padiem-front" in source
        ],
    }


def script_order_facts() -> dict:
    scripts = [
        attrs["src"].rsplit("/", 1)[-1]
        for tag, attrs in tags_for_page("index.html")
        if tag == "script" and attrs.get("src")
    ]
    transport_at = scripts.index("chat-transport.js")
    return {
        "transport_at": transport_at,
        "app_at": scripts.index("app.js"),
        "management_at": scripts.index("claw-connector-management.js"),
        "device_at": scripts.index("claw-device-manager.js"),
    }
