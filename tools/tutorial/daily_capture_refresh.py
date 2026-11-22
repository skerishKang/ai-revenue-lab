"""#6724 3번 1단계 — 일일 캡처로 튜토리얼 자산을 재생성해 아티팩트로 남긴다.

캡처 원본과 재생성 자산 모두 저장소에 커밋하지 않는다. PR은 사람이 확인한 뒤
연다. 계정 표시는 생성물에 남지 않는다.

빌드는 항상 부분 모드(#7943 후속)로 돈다: 캡처가 있는 단계만 PNG→webp 로
다시 만들고, 일일 흐름이 못 찍는 대표 세션 단계는 커밋된 webp 를 그대로 둔다.

이 단계는 일일 점검 판정을 바꾸지 않는다(#7935): 성공·무변화·실패 모두 상태를
CHANGE_SUMMARY.md 에 적고 항상 0 으로 끝난다. 실패 내용은 아티팩트로 확인한다.
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
#: 특정 단계만 시나리오로 가져오는 흐름: {flow: {step: scene}}. 공용 로그인
# 흐름의 로그인된 Chat 화면(4단계)은 같은 시나리오의 촬영 단계다(#7943 후속).
# 이 흐름의 나머지 단계(1–3: 로그인 폼·콜백)는 튜토리얼 화면이 아니므로
# 가져오지 않는다.
CAPTURE_STEP_TO_SCENE = {"browser_shared_login": {4: "01-first-visit"}}
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
    for flow, step_scene in sorted(CAPTURE_STEP_TO_SCENE.items()):
        for path in sorted(captures.glob(flow + "_*.png")):
            match = re.match(r"^" + re.escape(flow) + r"_(\d{2})_", path.name)
            if match is None or int(match.group(1)) not in step_scene:
                continue
            if count >= MAX_CAPTURES:
                break
            if not path.is_file() or path.stat().st_size > MAX_BYTES:
                continue
            target = shots_dir / step_scene[int(match.group(1))]
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


def parse_partial(stdout: str) -> dict[str, tuple[str, str]]:
    """build_tutorials --partial 의 보고 줄을 장면별 (regenerated, kept) 로.

    줄 형식: TUTORIAL_PARTIAL scene=<key> regenerated=1,2,3 kept=4
    """
    plan: dict[str, tuple[str, str]] = {}
    for line in stdout.splitlines():
        match = re.match(
            r"^TUTORIAL_PARTIAL scene=(\S+) regenerated=(\S*) kept=(\S*)$",
            line.strip(),
        )
        if match:
            plan[match.group(1)] = (match.group(2), match.group(3))
    return plan


def write_summary(out: Path, assets: list[str], status: str,
                  partial: dict[str, tuple[str, str]] | None = None) -> None:
    """결과 상태와 바뀐 파일 목록을 적는다(값·경로 내용 없음).

    실패 상태(build_failed 등)도 이 파일에 남는다 — 이 단계는 일일 점검
    판정을 바꾸지 않으므로(#7935), 아티팩트가 유일한 실패 기록이다.
    부분 모드로 재생성한 장면은 어떤 단계를 다시 만들고 어떤 단계를 커밋된
    webp 로 두었는지(캡처 없음) 함께 적는다.
    """
    scenes = sorted(set(CAPTURE_TO_SCENE.values()))
    lines = [
        "# Daily tutorial refresh",
        "",
        "generated_at=" + datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status=" + status,
        "",
        "## changed files",
        "",
    ]
    lines.extend("- " + name for name in assets)
    if not assets:
        lines.append("- (none)")
    lines.extend(["", "## per-scene changes", ""])
    for scene in scenes:
        if partial and scene in partial:
            regenerated, kept = partial[scene]
            lines.append(f"- {scene}: regenerated={regenerated or 'none'} "
                         f"kept={kept or 'none'}")
        else:
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
    return copied


def _refresh(captures: Path, out: Path) -> tuple[str, int, dict[str, tuple[str, str]]]:
    """일일 캡처로 자산을 재생성해 아티팩트 디렉터리에 놓는다.

    (상태, 복사한 파일 수, 장면별 재생성·보존 계획)을 돌려준다. 예외는
    main 이 받아 상태로 기록한다. 빌드는 부분 모드 — 캡처가 있는 단계만
    다시 만든다(#7943 후속).
    """
    shots_dir = Path(tempfile.mkdtemp(prefix="padiem-tutorial-shots-"))
    try:
        count = layout_captures(captures, shots_dir)
        if count == 0:
            return "no_captures", 0, {}
        build_run = subprocess.run(
            [sys.executable, str(BUILD), "--shots", str(shots_dir), "--partial"],
            cwd=str(REPO), capture_output=True, text=True, encoding="utf-8",
        )
        # 빌드 출력은 그대로 로그에 남긴다(장면별 보고 줄 포함).
        if build_run.stdout:
            print(build_run.stdout, end="")
        if build_run.returncode != 0:
            return "build_failed", 0, {}
        partial = parse_partial(build_run.stdout)
        if subprocess.run(
            [sys.executable, str(BUILD), "--check"], cwd=str(REPO)
        ).returncode != 0:
            return "contract_failed", 0, partial
        assets = changed_assets()
        generated = [REPO / asset for asset in assets]
        if not account_masked(generated, os.environ.get("QA_SMOKE_USERNAME", "")):
            return "mask_failed", 0, partial
        if not assets:
            return "no_change", 0, partial
        return "artifact_ready", stage_artifact(out, assets), partial
    finally:
        shutil.rmtree(shots_dir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    # #7935: 이 단계는 일일 점검 판정에 영향을 주지 않는다. 알려진 실패와
    # 예상 밖 오류 모두 상태를 CHANGE_SUMMARY.md 에 적고 항상 0 으로 끝난다.
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        status, copied, partial = _refresh(args.captures, args.out)
    except Exception:  # noqa: BLE001 — 판정 보호가 우선, 상세는 로그·아티팩트로
        status, copied, partial = "unexpected_error", 0, {}
    try:
        assets = changed_assets()
    except Exception:  # noqa: BLE001 — 목록은 부가 기록일 뿐이다
        assets = []
    write_summary(args.out, assets, status, partial)
    print("tutorial_daily=" + status + (f" files={copied}" if copied else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
