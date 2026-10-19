#!/usr/bin/env python3
"""Distribute canonical PADIEM composer to static B62/B66 without forks."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "packages/padiem-conversation-ui/composer-core.js"
TARGETS = (
    ROOT / "apps/padiem-chat/static/shared-conversation-composer.js",
    ROOT / "reference/business-66-padiem-quote-v1/shared-conversation-composer.js",
)

def sync(check=False):
    original = SOURCE.read_bytes()
    if b"PadiemConversationComposer" not in original:
        raise ValueError("INVALID_CANONICAL_COMPOSER")
    outdated = []
    for dst in TARGETS:
        if not dst.exists() or dst.read_bytes() != original:
            if check:
                outdated.append(dst.relative_to(ROOT).as_posix())
            else:
                dst.write_bytes(original)
    if outdated:
        raise SystemExit("SHARED_COMPOSER_DRIFT: " + ", ".join(outdated))
    print("SHARED_COMPOSER_PARITY=PASS; TARGETS=2; MODE=" + ("check" if check else "write"))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    sync(parser.parse_args().check)
