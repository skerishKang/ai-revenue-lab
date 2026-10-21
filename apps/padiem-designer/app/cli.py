"""Run the Designer preview app.

    python -m app.cli --host 127.0.0.1 --port 8788

The model route, the credential and the tenant come from the environment. The
app never asks the user for a key.
"""

from __future__ import annotations

import argparse
import os

from .app_factory import build_app
from .config import load_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="padiem-designer",
        description="PADIEM Designer generative UI preview.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument(
        "--print-status",
        action="store_true",
        help="Print the effective configuration and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = load_settings()
    if args.print_status:
        import json

        print(json.dumps(settings.to_public_dict(), ensure_ascii=False, indent=2))
        return 0

    try:
        import uvicorn
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency is declared
        raise SystemExit("uvicorn is required to run the Designer preview.") from exc

    os.environ.setdefault("PYTHONPATH", str(os.getcwd()))
    uvicorn.run(build_app(settings=settings), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
