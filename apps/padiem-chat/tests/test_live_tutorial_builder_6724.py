from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_tutorial_builder_links_step_images_and_video_timeline(tmp_path):
    artifacts = tmp_path / "live-artifacts"
    case = artifacts / "guest-home"
    case.mkdir(parents=True)
    (case / "step-01.png").write_bytes(b"synthetic screenshot")
    (case / "guest.webm").write_bytes(b"synthetic video")
    (case / "guest-second.webm").write_bytes(b"synthetic second-device video")
    result = artifacts / "summary-test.json"
    result.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "synthetic-run",
                "base_origin": "https://example.invalid",
                "generated_at_utc": "2026-11-03T00:00:00+00:00",
                "exit_status": 0,
                "scenarios": [
                    {
                        "scenario": "guest-home",
                        "outcome": "passed",
                        "steps": [
                            {
                                "name": "home",
                                "caption": "첫 화면을 확인해요.",
                                "duration_ms": 125,
                                "status_code": 200,
                                "http_504": False,
                                "outcome": "passed",
                                "screenshot": "guest-home/step-01.png",
                            }
                        ],
                        "video": "guest-home/guest.webm",
                        "extra_videos": ["guest-home/guest-second.webm"],
                    },
                    {
                        "scenario": "account",
                        "outcome": "skipped",
                        "skip_reason": "test_account_missing",
                        "steps": [],
                        "video": None,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "build_live_tutorial.py"
    )
    output = tmp_path / "tutorial.md"
    completed = subprocess.run(
        [sys.executable, str(script), str(result), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    rendered = output.read_text(encoding="utf-8")
    assert "첫 화면을 확인해요." in rendered
    assert "![첫 화면을 확인해요.](live-artifacts/guest-home/step-01.png)" in rendered
    assert "0 | 125 | 200 | 아니오 | passed" in rendered
    assert "[guest.webm](live-artifacts/guest-home/guest.webm)" in rendered
    assert "(전체 시나리오 녹화)" in rendered
    assert "[guest-second.webm](live-artifacts/guest-home/guest-second.webm)" in rendered
    assert "(보조 기기 녹화)" in rendered
    assert "test_account_missing" in rendered
