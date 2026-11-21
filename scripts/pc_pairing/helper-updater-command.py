"""Print a fixed register/unregister command for the approved Mesh console.

No connection to a PC is made by this generator.
"""
from __future__ import annotations

import argparse
import runpy
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("register", "unregister"))
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[2] / "apps/padiem-chat/app/pc_helper_update.py"
    updater = runpy.run_path(str(source))
    print(updater["mesh_helper_updater_command"](unregister=args.action == "unregister"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
