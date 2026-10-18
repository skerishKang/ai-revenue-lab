#!/usr/bin/env python3
"""Distribute canonical PADIEM answer-copy to static B62/B66 without forks."""

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "packages/padiem-conversation-ui/answer-copy.js"
TARGETS = (
    ROOT / "apps/padiem-chat/static/shared-answer-copy.js",
    ROOT / "reference/business-66-padiem-quote-v1/shared-answer-copy.js",
)


def sync(check=False):
    original = SOURCE.read_bytes()
    if b"PadiemAnswerCopy" not in original:
        raise ValueError("INVALID_CANONICAL_ANSWER_COPY")
    outdated = []
    for dst in TARGETS:
        if not dst.exists() or dst.read_bytes() != original:
            if check:
                outdated.append(dst.relative_to(ROOT).as_posix())
            else:
                dst.write_bytes(original)
    if outdated:
        raise SystemExit("SHARED_ANSWER_COPY_DRIFT: " + ", ".join(outdated))
    print(
        "SHARED_ANSWER_COPY_PARITY=PASS; TARGETS=2; MODE="
        + ("check" if check else "write")
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    sync(parser.parse_args().check)
