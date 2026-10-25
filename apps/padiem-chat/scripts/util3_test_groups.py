"""#5785 — run one 의원3종 test group on its own.

The three tools share one shipped module and one PADIEM backend, so their tests
were only reachable by running the whole B62 surface. This script maps a group
to the exact files that cover it, so a speech change does not have to execute the
SNS photo contract and vice versa.

Every file listed here already exists; the groups add no second copy of a
contract. ``shared`` is the "does this still use PADIEM, not a clone" group.

    python scripts/util3_test_groups.py speech
    python scripts/util3_test_groups.py sns
    python scripts/util3_test_groups.py meeting
    python scripts/util3_test_groups.py shared
    python scripts/util3_test_groups.py all
    python scripts/util3_test_groups.py --list

The exit code is pytest's, so a caller (CI included) can gate on it directly.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
from time import monotonic

CHAT_ROOT = Path(__file__).resolve().parents[1]

GROUPS: dict[str, tuple[str, ...]] = {
    # 축사·인사말: the group's own contract plus the shipped speech save/reopen
    # and util-page entry already owned by #5608.
    "speech": (
        "tests/test_5785_speech_tool.py",
        "tests/test_5608_util_page_visibility_and_reopen.py",
    ),
    # SNS 홍보: the group's own text/draft contract plus #5728's photo
    # composition contract, which stays with its owner.
    "sns": (
        "tests/test_5785_sns_tool.py",
        "tests/test_5728_sns_photo_compose.py",
    ),
    # 회의정리·활동집: the group's own summary/archive/book contract.
    "meeting": (
        "tests/test_5785_meeting_tool.py",
    ),
    # 공통: the tools use PADIEM's existing session, model lane and file store.
    "shared": (
        "tests/test_5785_util_shared_contract.py",
        "tests/test_5608_util_sidebar_submenu.py",
        "tests/test_5608_body_glass_unification.py",
    ),
}


def _all_files() -> tuple[str, ...]:
    seen: list[str] = []
    for files in GROUPS.values():
        for name in files:
            if name not in seen:
                seen.append(name)
    return tuple(seen)


def resolve(group: str) -> tuple[str, ...]:
    if group == "all":
        return _all_files()
    return GROUPS[group]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one 의원3종 test group (#5785).")
    parser.add_argument("group", nargs="?", choices=sorted([*GROUPS, "all"]))
    parser.add_argument("--list", action="store_true", help="print the group map and exit")
    parser.add_argument("pytest_args", nargs="*", help="extra arguments passed to pytest")
    args = parser.parse_args(argv)

    if args.list or not args.group:
        width = max(len(name) for name in GROUPS)
        for name, files in GROUPS.items():
            print(f"{name.ljust(width)}  {len(files)} file(s): {' '.join(files)}")
        print(f"{'all'.ljust(width)}  {len(_all_files())} file(s) after de-duplication")
        return 0

    files = resolve(args.group)
    missing = [name for name in files if not (CHAT_ROOT / name).is_file()]
    if missing:
        print(f"missing test file(s): {', '.join(missing)}", file=sys.stderr)
        return 2

    command = [sys.executable, "-m", "pytest", *files, "-q", *args.pytest_args]
    print(f"#5785 group={args.group} files={len(files)}")
    print(" ".join(command))
    started = monotonic()
    completed = subprocess.run(command, cwd=str(CHAT_ROOT), check=False)
    print(f"#5785 group={args.group} seconds={monotonic() - started:.2f} exit={completed.returncode}")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
