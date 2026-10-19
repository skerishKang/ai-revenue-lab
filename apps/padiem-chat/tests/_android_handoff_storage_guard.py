"""The Android sign-in handoff is the only browser storage app.js may use.

The raw-text static guards banned every browser persistence primitive because
the app must not keep a hidden second source of truth. #5015 added exactly one
reviewed exception: the WebView must hold a one-time claim secret across a page
recreation, and that secret may never travel through a URL or a cookie shared
with the external browser.

This helper keeps the exception narrow and auditable: the seam must still
exist (so a guard cannot pass by deleting the feature), and every line that
touches the temporary store must name the one reviewed handoff key.
"""

from __future__ import annotations

ANDROID_HANDOFF_STORAGE_SYMBOL = "ANDROID_HANDOFF_STORAGE_KEY"
ANDROID_HANDOFF_STORAGE_KEY = "padiem.androidHandoff.v1"


def assert_session_storage_is_handoff_only(source: str) -> None:
    assert (
        f'const {ANDROID_HANDOFF_STORAGE_SYMBOL} = "{ANDROID_HANDOFF_STORAGE_KEY}";'
        in source
    ), "the handoff storage key declaration changed"
    lines = [line for line in source.splitlines() if "sessionStorage" in line]
    assert lines, "expected the reviewed Android handoff storage seam"
    for line in lines:
        assert ANDROID_HANDOFF_STORAGE_SYMBOL in line, line
