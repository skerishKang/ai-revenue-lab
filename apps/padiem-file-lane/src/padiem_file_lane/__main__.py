"""Foreground process entry, usable by the existing COM2 supervisor pattern."""
import os

import uvicorn


def server():
    from .app import create_app
    return uvicorn.Server(uvicorn.Config(create_app(), host=os.environ.get("FILE_LANE_HOST", "127.0.0.1"),
        port=int(os.environ.get("FILE_LANE_PORT", "8788")), proxy_headers=False,
        access_log=False, log_level="warning"))


def main():
    server().run()


if __name__ == "__main__":
    main()
