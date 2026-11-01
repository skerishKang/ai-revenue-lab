# -*- coding: utf-8 -*-
"""대표 결정 11-01·02 — 뺀 문구는 되살아나지 않고, 남겨 둔 것은 살아 있어야 한다.

2026-11-01 대표 요청으로 운영 배포본(fix/councillor-good-news-261101, dc0985ccb)
에서 뺀 것: 위원 사임 항목, 득표수·득표율(12,844표·17.99%), 확인 안 된 SNS 링크,
방어적 안내 문구(출처 확인 안내·촬영 당시 직위 안내). 이 시험은 main 소스와 빌드
산물 어디에도 그 문구가 되돌아오지 않게 가드한다.

대표 결정으로 남겨 둔 것: 생년월일(1965년 8월 6일)과 옛 위원회 사진(의정활동
이미지)은 지우지 않는다 — 삭제 가드를 함께 단다.

docs·README·scripts는 페이지에 서빙되지 않는 개발 문서이므로 검사 대상이 아니고,
dist/는 빌드 산물이라 존재할 때만 같은 규칙으로 검사한다.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"

FORBIDDEN_PHRASES = (
    "사임",            # 위원 사임 항목
    "12,844",          # 득표수
    "17.99",           # 득표율
    "확인한 내용입니다",  # 방어적 출처 안내
    "직위는 촬영 당시",   # 방어적 영상 안내
)

SERVED_SUFFIXES = {".html", ".json", ".js", ".css", ".txt", ".xml"}


def served_files(base: Path) -> list[Path]:
    files = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if "docs" in path.relative_to(base).parts or "tests" in path.relative_to(base).parts:
            continue
        if path.suffix in SERVED_SUFFIXES:
            files.append(path)
    return files


def test_forbidden_phrases_are_gone_from_every_served_file() -> None:
    for base, label in [(ROOT, "source"), *([(DIST, "dist")] if DIST.is_dir() else [])]:
        violations = []
        for path in served_files(base):
            text = path.read_text(encoding="utf-8", errors="replace")
            rel = path.relative_to(base)
            for phrase in FORBIDDEN_PHRASES:
                if phrase in text:
                    violations.append(f"{label}/{rel}: {phrase}")
        assert not violations, "대표 요청으로 뺀 문구가 되돌아왔다:\n" + "\n".join(violations)


def test_no_unconfirmed_social_link_is_served() -> None:
    for base, label in [(ROOT, "source"), *([(DIST, "dist")] if DIST.is_dir() else [])]:
        for path in (base / "static/miraen.json", *served_files(base)):
            if path.name != "miraen.json" or not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            unconfirmed = [
                entry.get("label")
                for entry in data.get("socials", [])
                if not entry.get("confirmed", True)
            ]
            assert not unconfirmed, f"{label}/{path.name}: 확인 안 된 SNS 링크 {unconfirmed}"


def test_owner_decision_keeps_birthdate_and_old_committee_photos() -> None:
    data = json.loads((ROOT / "static/miraen.json").read_text(encoding="utf-8"))
    birth = [row for row in data.get("profile", []) if "1965년 8월 6일" in str(row.get("value", ""))]
    assert birth, "생년월일은 대표 결정으로 유지 대상 — 지워지면 안 된다"
    photo_refs = [item.get("thumb", "") for item in data.get("activity", {}).get("items", [])]
    photo_refs = [ref for ref in photo_refs if ref.endswith(".jpg")]
    assert photo_refs, "옛 위원회 사진 참조는 유지 대상 — 지워지면 안 된다"
    for ref in photo_refs:
        assert (ROOT / ref.replace("./", "")).is_file(), f"참조된 사진 파일이 소스에 없다: {ref}"
