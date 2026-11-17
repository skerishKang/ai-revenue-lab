"""#6724 3번 1단계 — 일일 브라우저 캡처를 튜토리얼 자산으로 반영한다.

캡처 원본은 저장소에 커밋하지 않는다. 임시 디렉터리에 발급 규칙에 맞춰 펼친 뒤
`build_tutorials.py --shots`로 문서·정적 페이지·단계 이미지를 재생성하고, 변경된
자산만 Draft PR로 연다. 계정 표시는 생성물에 남지 않는다.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BUILD = REPO / "tools" / "tutorial" / "build_tutorials.py"
DOC_DIR = REPO / "docs" / "help" / "tutorials"
PAGE_DIR = REPO / "apps" / "padiem-chat" / "static" / "help-tutorials"
#: 일일 캡처 흐름 → 튜토리얼 시나리오 키. 매핑 밖의 흐름은 무시한다.
CAPTURE_TO_SCENE = {"browser_chat": "01-first-visit"}
MAX_CAPTURES = 12
MAX_BYTES = 8_000_000


def layout_captures(captures: Path, shots_dir: Path) -> int:
    """캡처를 `<scene>/step-NN.png` 구조로 임시 복사하고 개수를 돌려준다."""
    count = 0
    for flow, scene in sorted(CAPTURE_TO_SCENE.items()):
        target = shots_dir / scene
        for path in sorted(captures.glob(flow + "_*.png")):
            match = re.match(r"^" + re.escape(flow) + r"_(\d{2})_", path.name)
            if match is None or count >= MAX_CAPTURES:
                continue
            if not path.is_file() or path.stat().st_size > MAX_BYTES:
                continue
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target / ("step-" + match.group(1) + ".png"))
            count += 1
    return count


def account_masked(paths: list[Path], username: str) -> bool:
    """생성물에 계정 표시가 남지 않았는지 확인한다(값은 출력하지 않는다)."""
    if not username:
        return True
    needle = username.encode("utf-8")
    for path in paths:
        if not path.is_file():
            continue
        if needle in path.read_bytes():
            return False
    return True


def changed_assets() -> list[str]:
    """추적 중인 튜토리얼 자산의 변경 경로만 돌려준다."""
    done = subprocess.run(
        ["git", "-C", str(REPO), "diff", "--name-only", "--",
         "docs/help/tutorials", "apps/padiem-chat/static/help-tutorials"],
        capture_output=True, text=True, encoding="utf-8",
    )
    if done.returncode != 0:
        return []
    return [line.strip() for line in done.stdout.splitlines() if line.strip()]


def _run(*args: str) -> int:
    return subprocess.run(list(args), cwd=str(REPO)).returncode


def open_draft_pr(branch: str, title: str, body: str, assets: list[str]) -> bool:
    """자산만 커밋해 올리고 Draft PR을 연다. 캡처 원본은 넣지 않는다."""
    if _run("git", "checkout", "-b", branch) != 0:
        return False
    if _run("git", "add", "--", *assets) != 0:
        return False
    if _run("git", "commit", "-m", "docs(tutorial): refresh from daily captures (#6724)") != 0:
        return False
    if _run("git", "push", "origin", "HEAD") != 0:
        return False
    return _run("gh", "pr", "create", "--draft", "--base", "main",
                "--head", branch, "--title", title, "--body", body) == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    shots_dir = Path(tempfile.mkdtemp(prefix="padiem-tutorial-shots-"))
    try:
        count = layout_captures(args.captures, shots_dir)
        if count == 0:
            print("tutorial_daily=no_captures")
            return 0
        if subprocess.run(
            [sys.executable, str(BUILD), "--shots", str(shots_dir)], cwd=str(REPO)
        ).returncode != 0:
            print("tutorial_daily=build_failed")
            return 1
        if subprocess.run(
            [sys.executable, str(BUILD), "--check"], cwd=str(REPO)
        ).returncode != 0:
            print("tutorial_daily=contract_failed")
            return 1
        assets = changed_assets()
        generated = [path for asset in assets for path in (REPO / asset,)]
        if not account_masked(generated, os.environ.get("QA_SMOKE_USERNAME", "")):
            print("tutorial_daily=mask_failed")
            return 1
        if not assets:
            print("tutorial_daily=no_change")
            return 0
        if args.dry_run:
            print(f"tutorial_daily=dry_run assets={len(assets)}")
            return 0
        branch = "tutorial/daily-capture-" + datetime.now(timezone.utc).strftime("%Y%m%d")
        if not open_draft_pr(
            branch,
            "docs(tutorial): daily capture refresh (#6724)",
            "일일 브라우저 캡처에서 재생성한 튜토리얼 자산. 캡처 원본은 포함하지 않습니다.",
            assets,
        ):
            print("tutorial_daily=pr_failed")
            return 1
        print("tutorial_daily=pr_opened")
        return 0
    finally:
        shutil.rmtree(shots_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
