"""#6724 3번 1단계 — 일일 캡처로 튜토리얼 자산을 재생성해 아티팩트로 남긴다.

캡처 원본과 재생성 자산 모두 저장소에 커밋하지 않는다. PR은 사람이 확인한 뒤
연다. 계정 표시는 생성물에 남지 않는다.
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


def write_summary(out: Path, assets: list[str]) -> None:
    """바뀐 파일 목록과 장면별 차이 여부만 적는다(값·경로 내용 없음)."""
    scenes = sorted(set(CAPTURE_TO_SCENE.values()))
    lines = [
        "# Daily tutorial refresh",
        "",
        "generated_at=" + datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "",
        "## changed files",
        "",
    ]
    lines.extend("- " + name for name in assets)
    if not assets:
        lines.append("- (none)")
    lines.extend(["", "## per-scene changes", ""])
    for scene in scenes:
        changed = any(scene in name for name in assets)
        lines.append(f"- {scene}: {'changed' if changed else 'unchanged'}")
    lines.append("")
    (out / "CHANGE_SUMMARY.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def stage_artifact(out: Path, assets: list[str]) -> int:
    """변경 자산만 아티팩트 디렉터리로 복사한다. 캡처 원본은 넣지 않는다."""
    out.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name in assets:
        source = REPO / name
        if not source.is_file():
            continue
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    write_summary(out, assets)
    return copied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
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
        generated = [REPO / asset for asset in assets]
        if not account_masked(generated, os.environ.get("QA_SMOKE_USERNAME", "")):
            print("tutorial_daily=mask_failed")
            return 1
        if not assets:
            print("tutorial_daily=no_change")
            return 0
        copied = stage_artifact(args.out, assets)
        print(f"tutorial_daily=artifact_ready files={copied}")
        return 0
    finally:
        shutil.rmtree(shots_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
