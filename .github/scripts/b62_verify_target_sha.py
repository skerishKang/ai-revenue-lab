"""The one rule every B62 deploy gate applies to its `target_sha` input.

Why the rule is inline in the workflows instead of a call to this file: the gate
has to reject a malformed SHA *before* it checks anything out, and a step that
runs before `actions/checkout` has no repository to read a script from. So the
text between the two markers below is embedded verbatim as the first step of each
gate's first job, and this module stays the single authority for what that text
is and how it behaves.

    .github/tests/test_b62_verify_target_sha.py pins three things at once:
      * the behaviour of the rule (lengths 9/39/41, non-hex, empty, 40, uppercase),
      * that every B62 workflow taking `target_sha` embeds exactly this text,
      * that the guard step precedes any `actions/checkout` in that job.

What the rule accepts: exactly 40 hexadecimal characters. Case is the only thing
forgiven, because `git rev-parse` prints lowercase while an operator can paste
uppercase; the normalized lowercase value is what the rest of the job consumes,
so the whole run stays on one SHA. Everything else — a short SHA from
`git rev-parse --short`, a 39- or 41-character typo, a stray space inside the
value, an empty input — fails the step immediately with the Korean message the
operator sees in the run log.
"""

from __future__ import annotations

import pathlib
import re

GUARD_BEGIN = "# B62_TARGET_SHA_GUARD_BEGIN"
GUARD_END = "# B62_TARGET_SHA_GUARD_END"

# B62_TARGET_SHA_GUARD_BEGIN
import os
import re
import sys

_SHA = re.compile(r"^[0-9a-f]{40}$")


def canonical_target_sha(raw):
    # Case is the only forgiveness: a short or non-hex value is not a commit.
    value = (raw or "").strip()
    if len(value) != 40:
        return None
    candidate = value.lower()
    return candidate if _SHA.match(candidate) else None


def failure_message(raw):
    return f"target_sha는 40자리 전체 SHA여야 합니다(입력: {len((raw or '').strip())}자리). git rev-parse origin/main 값을 넣으세요"


def main():
    raw = os.environ.get("B62_TARGET_SHA_RAW", "")
    canonical = canonical_target_sha(raw)
    if canonical is None:
        sys.stdout.write("::error::" + failure_message(raw) + "\n")
        return 1
    for key, name in (("GITHUB_OUTPUT", "target_sha"), ("GITHUB_ENV", "TARGET_SHA")):
        path = os.environ.get(key)
        if path:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(f"{name}={canonical}\n")
    sys.stdout.write("B62_TARGET_SHA_INPUT_SHAPE=PASS\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
# B62_TARGET_SHA_GUARD_END


def guard_text() -> str:
    """The exact program the gates embed, without the marker lines."""
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    begin = re.search(r"^" + re.escape(GUARD_BEGIN) + r"$", source, re.M)
    end = re.search(r"^" + re.escape(GUARD_END) + r"$", source, re.M)
    return source[begin.end() : end.start()].strip("\n")
