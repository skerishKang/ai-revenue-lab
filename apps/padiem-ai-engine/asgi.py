"""P01 Engine ASGI entrypoint for a host that has no Cloudflare Workers.

``worker_identity.py`` is the Cloudflare Python Worker entrypoint
(``wrangler.toml`` ``main``) and the production binding authority. This module is
the second door for the same application and dispatches through that same
canonical entry:

    python3 -m uvicorn asgi:app --host 127.0.0.1 --port 8811

or, with the defaults read from the environment:

    python3 asgi.py

Both forms build the app through ``app.local_runtime.create_local_app``, which
installs the minimal CPython stand-in for the Workers runtime package, binds the
loopback B14 service the runbook documents, and hands every request to the
Worker's own ``Default.fetch`` dispatch. No route, authentication rule or
composition exists twice.

The entry refuses to build without an explicit host flag
(``PADIEM_ENGINE_CPYTHON_HOST=1`` on COM2, or ``PADIEM_LOCAL_DEV=1`` for a
loopback dev run) and refuses a routable bind: P01 is an internal service, and
the Chat host reaches it over 127.0.0.1 only.
"""

from __future__ import annotations

import os

from app.local_runtime import (
    BIND_HOST_ENV,
    BIND_PORT_ENV,
    DEFAULT_HOST,
    DEFAULT_PORT,
    bind_address,
    create_local_app,
)

app = create_local_app()


def main() -> None:
    import uvicorn

    host, port = bind_address(os.environ)
    uvicorn.run(
        app,
        host=host,
        port=port,
        proxy_headers=False,
        access_log=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()


__all__ = ["app", "main", "DEFAULT_HOST", "DEFAULT_PORT", "BIND_HOST_ENV", "BIND_PORT_ENV"]
