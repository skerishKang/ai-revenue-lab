#!/usr/bin/env python3
"""#7404 운영 문서 위치 가드(경고 전용 — 실패 아님).

공개 경로(docs/operations 등)에 새로 추가된 파일 중 운영 기록으로 보이는 것에
경고를 남기고 비공개 운영 기록 위치를 안내한다. 이 스크립트는 결코 0이 아닌
코드로 끝나지 않는다(경고는 빌드를 깨지 않는다).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

GUARDED_PREFIXES = (
    "docs/operations/",
    "docs/ops/",
    "docs/validation/",
)

OPS_NAME_PATTERN = re.compile(
    r"(RUNBOOK|런북|INCIDENT|사고|POSTMORTEM|CUTOVER|컷오버|HANDOVER|인수인계"
    r"|RECOVERY|복구|FAILOVER|STATUS_|상태보고|현황|WORKLOG|워크로그"
    r"|COM2|컴2|CHECKLIST|INVENTORY|TOPOLOGY|위상)",
    re.IGNORECASE,
)

# 공개 정책 정본(코드·시험·레인 지침이 참조하는 문서 체계)은 운영 기록이 아니다.
ALLOWED_NAME_PATTERN = re.compile(
    r"(POLICY|POLICIES|STANDARD|MODEL|GATE|GATES|SCOPE|EVIDENCE|TEMPLATE"
    r"|REQUIREMENTS|RULES|GUIDE|MAP_|INDEX|README)",
    re.IGNORECASE,
)

GUIDANCE = (
    "운영 기록으로 보이는 문서가 공개 경로에 추가되었습니다. "
    "런북·사고 기록·컷오버 기록·운영 상태 보고·서버 구조 문서는 "
    "비공개 운영 기록 위치(거버넌스 폴더, 같은 상대 경로)에 두세요(#7404). "
    "공개 문서에는 '비공개 운영 기록으로 이동' 수준의 안내만 남깁니다."
)


def looks_like_operational_record(path: str) -> bool:
    if not path.lower().endswith((".md", ".markdown", ".txt")):
        return False
    name = path.rsplit("/", 1)[-1]
    if ALLOWED_NAME_PATTERN.search(name):
        return False
    if not path.startswith(GUARDED_PREFIXES):
        return False
    return bool(OPS_NAME_PATTERN.search(name))


def main(argv: list[str]) -> int:
    for path in argv:
        if not looks_like_operational_record(path):
            continue
        print(f"::warning file={path}::{GUIDANCE}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
