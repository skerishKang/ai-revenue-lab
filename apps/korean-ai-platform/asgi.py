"""B14 ASGI entrypoint for a host that has no Cloudflare Workers.

``worker.py`` remains the Cloudflare Python Worker entrypoint and the production
binding authority. This module is the second door for the same application:

    python3 -m uvicorn asgi:app --host 127.0.0.1 --port 8789

or, with the defaults read from the environment:

    python3 asgi.py

Both forms build the app through ``app.local_runtime.create_local_app``, which
loads ``.env`` first (the documented owner startup contract), binds the
request-scoped credential handles and the local ledger, and adds the response
policy the Worker entrypoint applies. ``app.main:app`` stays the plain
no-adapter app the existing runbooks and browser tests use.

Uvicorn's own access log is off: it would write request targets that the
platform's structure logs deliberately keep out of a second, unrotated stream.
"""

from __future__ import annotations

import os

from app.local_runtime import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    HOST_ENV,
    PORT_ENV,
    create_local_app,
)

app = create_local_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get(HOST_ENV, DEFAULT_HOST),
        port=int(os.environ.get(PORT_ENV, str(DEFAULT_PORT))),
        proxy_headers=False,
        access_log=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
