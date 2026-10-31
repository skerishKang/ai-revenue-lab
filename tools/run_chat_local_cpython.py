#!/usr/bin/env python
"""Run padiem-chat on this machine's plain CPython — #5573 stage 2.

    python tools/run_chat_local_cpython.py [--port 8773] [--data-dir PATH]

Sets the explicit local flag and the loopback-only defaults (mock model,
password auth, insecure cookies on 127.0.0.1) and serves the SAME Starlette
app the Cloudflare Worker composes, over a local SQLite file and a disk
folder for R2. The Cloudflare deployment path is not involved: no wrangler,
no workerd, no production bindings.

The import pinning mirrors lane_pytest.py: on shared-authoring PCs another
lane's editable installs can hijack `app`, so this process drops the
editable finders and puts THIS checkout's paths first.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

for finder in list(sys.meta_path):
    if "editable" in type(finder).__name__.lower():
        sys.meta_path.remove(finder)

for rel in (
    REPO_ROOT / "apps" / "padiem-chat",
    REPO_ROOT / "packages" / "padiem-ai-core",
    REPO_ROOT / "packages" / "padiem-control-plane",
    REPO_ROOT / "apps" / "korean-ai-code-agent" / "src",
    REPO_ROOT / "apps" / "padiem-ai-engine" / "clients" / "python",
):
    path = str(rel)
    if path not in sys.path:
        sys.path.insert(0, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8773)
    parser.add_argument("--data-dir", default=None,
                        help="local DB/R2 folder (default: apps/padiem-chat/local_dev_data)")
    parser.add_argument("--runtime-mode", default=os.getenv("PADIEM_CHAT_RUNTIME_MODE", "mock"),
                        choices=["mock", "b14"],
                        help="model lane; b14 additionally needs PADIEM_CHAT_B14_BASE_URL "
                             "in the environment — this script never guesses a model endpoint")
    args = parser.parse_args()

    if args.runtime_mode == "b14" and not os.getenv("PADIEM_CHAT_B14_BASE_URL"):
        parser.error("b14 runs must set PADIEM_CHAT_B14_BASE_URL (owner-approved endpoint only)")

    os.environ["PADIEM_LOCAL_DEV"] = "1"
    os.environ["PADIEM_CHAT_RUNTIME_MODE"] = args.runtime_mode
    os.environ.setdefault("PADIEM_CHAT_AUTH_MODE", "password")
    os.environ.setdefault("PADIEM_CHAT_COOKIE_SECURE", "false")
    os.environ.setdefault("PADIEM_CHAT_WEB_PROVIDER", "off")
    os.environ.setdefault("PADIEM_CHAT_LIVE_ENABLED", "false")
    os.environ["PADIEM_CHAT_PUBLIC_BASE_URL"] = f"http://127.0.0.1:{args.port}"
    if args.data_dir:
        os.environ["PADIEM_CHAT_LOCAL_DATA_DIR"] = str(Path(args.data_dir).resolve())

    import uvicorn

    from app.local_cpython import build_app, local_data_dir

    app = build_app()
    print(f"[local] data dir: {local_data_dir()}")
    print(f"[local] open http://127.0.0.1:{args.port}/ after signing up on the first screen")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
