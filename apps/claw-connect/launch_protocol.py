"""ShellExecute entrypoint: boot existing tray, NEVER interpret browser args.

The script is installed at the per-user Connector root so the canonical
claw_connect package resolves without a developer checkout or PYTHONPATH.
"""
import sys

from claw_connect.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main(["open-from-web", *sys.argv[1:]]))
