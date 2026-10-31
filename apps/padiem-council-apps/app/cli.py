"""Run the council apps entry server.

    python -m app.cli --host 127.0.0.1 --port 8791

This serves only the static entry. Generation, storage and login run on the
PADIEM backend this deployment shares an origin with; running this entry
standalone against a backend that is not there means the page renders its
signed-out state honestly.
"""

from __future__ import annotations

import argparse

import uvicorn

from .app_factory import create_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="padiem-council-apps",
        description="PADIEM council apps (의원3종) independent entry.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8791)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
