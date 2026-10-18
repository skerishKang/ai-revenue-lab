#!/usr/bin/env python3
"""Distribute canonical PADIEM conversation scroll follow to B62/B66."""

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "packages/padiem-conversation-ui/scroll-follow.js"
TARGETS = (
    ROOT / "apps/padiem-chat/static/shared-conversation-scroll.js",
    ROOT / "reference/business-66-padiem-quote-v1/shared-conversation-scroll.js",
)


def sync(check=False):
    original = SOURCE.read_bytes()
    if b"PadiemConversationScroll" not in original:
        raise ValueError("INVALID_CANONICAL_SCROLL")
    outdated = []
    for dst in TARGETS:
        if not dst.exists() or dst.read_bytes() != original:
            if check:
                outdated.append(dst.relative_to(ROOT).as_posix())
            else:
                dst.write_bytes(original)
    if outdated:
        raise SystemExit("SHARED_SCROLL_DRIFT: " + ", ".join(outdated))
    print("SHARED_SCROLL_PARITY=PASS; TARGETS=2; MODE=" + ("check" if check else "write"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    sync(parser.parse_args().check)
