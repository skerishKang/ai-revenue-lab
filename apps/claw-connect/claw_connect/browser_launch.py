"""Windows browser-to-native launch boundary (NOT account pairing authority).

Only the exact zero-data URI may start the visible Connector tray. Browser URL
strings are untrusted: device credentials, owner scope, account names, pairing
codes and any query/fragment must never reach a process command line.
"""
from __future__ import annotations

BROWSER_START_URI = "padiem-connector://start"


def accepts_browser_launch_uri(uri: object) -> bool:
    """No query, fragment, port, credentials, path, Unicode or aliases."""
    return type(uri) is str and uri == BROWSER_START_URI
