"""The response policy a B14 request must carry, independent of the runtime.

``worker.py`` owns these values for the Cloudflare runtime and its contract tests
pin them as source text there, so they are not moved. This module is the copy the
local (COM2) runtime reads, and ``tests/test_5784_b14_local_runtime.py`` asserts
the two stay byte-identical: a header dropped here or there fails the drift guard
rather than shipping two different security postures.
"""

from __future__ import annotations

SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

# The public root is the product entrypoint, not the legacy demo home page.
PRODUCT_ENTRY_PATH = "/workspace"
