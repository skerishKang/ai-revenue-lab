#!/usr/bin/env python3
"""Turn recorded live-scenario JSON into a Markdown storyboard and video timeline."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def _artifact_path(root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def build_storyboard(result_path: Path, output_path: Path) -> None:
    result_path = result_path.resolve()
    source_root = result_path.parent
    data = json.loads(result_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("scenarios"), list):
        raise ValueError("unsupported live scenario result schema")

    lines = [
        "# 라이브 시나리오 튜토리얼",
        "",
        f"- 실행 ID: {data.get('run_id', 'unknown')}",
        f"- 확인 주소: {data.get('base_origin', 'unknown')}",
        f"- 생성 시각(UTC): {data.get('generated_at_utc', 'unknown')}",
        "",
    ]
    for scenario in data["scenarios"]:
        lines.extend([f"## {scenario.get('scenario', '시나리오')}", ""])
        if scenario.get("outcome") == "skipped":
            lines.extend([f"상태: 건너뜀 ({scenario.get('skip_reason', '사유 미기록')})", ""])
            continue
        videos = []
        elapsed = 0
        lines.extend(["| 단계 | 자막 캡션 | 시작 ms | 종료 ms | HTTP | 504 | 결과 |", "|---|---|---:|---:|---:|---|---|"])
        for step in scenario.get("steps", []):
            duration = int(step.get("duration_ms") or 0)
            start, end = elapsed, elapsed + duration
            elapsed = end
            caption = str(step.get("caption", "")).replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| {step.get('name', '')} | {caption} | {start} | {end} | "
                f"{step.get('status_code') or ''} | {'예' if step.get('http_504') else '아니오'} | "
                f"{step.get('outcome', '')} |"
            )
            image = _artifact_path(source_root, step.get("screenshot"))
            if image and image.is_file():
                relative = os.path.relpath(image, output_path.parent.resolve()).replace(os.sep, "/")
                lines.extend(["", f"![{caption}]({relative})", ""])
        for label, reference in [("전체 시나리오 녹화", scenario.get("video"))] + [
            ("보조 기기 녹화", extra) for extra in scenario.get("extra_videos") or []
        ]:
            video = _artifact_path(source_root, reference)
            if video:
                videos.append((label, video))
        if videos:
            lines.extend(["영상 파일과 시각표:", ""])
            for label, video in videos:
                if video.is_file():
                    relative = os.path.relpath(video, output_path.parent.resolve()).replace(os.sep, "/")
                    lines.append(f"- [{video.name}]({relative}) ({label})")
            lines.append("")
        lines.append(f"총 단계 시간: {elapsed} ms")
        lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_json", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build_storyboard(args.result_json, args.output)
    print(f"storyboard_written={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
