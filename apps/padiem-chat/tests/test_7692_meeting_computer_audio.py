"""#7692 meeting computer-audio option: static contract and executed unit tests."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
STATIC = TESTS.parent / "static"
SCRIPT = TESTS / "test_7692_meeting_computer_audio_node.js"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CAPTURE = (STATIC / "meeting-capture.js").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")


def test_computer_audio_unit_behavior_runs_green():
    if shutil.which("node") is None:
        pytest.skip("Node runtime unavailable; run CI for the browser contract")
    result = subprocess.run(
        ["node", "--test", str(SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "# fail 0" in result.stdout


def test_option_is_off_hidden_by_default_and_has_the_three_reviewed_lines():
    start = HTML.index('id="meetingComputerAudioRow"')
    block = HTML[start: HTML.index("</div>", start)]
    assert 'id="meetingComputerAudioRow" hidden' in block
    assert 'type="checkbox" id="meetingComputerAudio"' in block
    assert "컴퓨터 소리도 함께 받기" in block
    assert "회의 탭(또는 화면 전체)을 고르고 '소리 공유'를 체크하세요." in block
    assert "컴퓨터 소리를 함께 받을 때는 소리를 서버에서 받아씁니다." in block
    assert 'role="status"' in block and 'aria-live="polite"' in block
    for key in ("meeting-computer-audio", "meeting-computer-audio-hint",
                "meeting-computer-audio-disclosure"):
        assert f'data-locale-key="{key}"' in block
        assert f'"{key}"' in LOCALE


def test_capture_uses_display_audio_only_after_the_option_and_keeps_one_server_path():
    assert "getDisplayMedia({ video: true, audio: true })" in CAPTURE
    assert "videoTracks.forEach((track) =>" in CAPTURE
    assert "createMediaStreamDestination()" in CAPTURE
    assert "new AudioContext()" in CAPTURE
    assert 'TRANSCRIBE_PATH = "/api/voice/transcribe"' in CAPTURE
    assert "contentType" not in CAPTURE
    assert "FormData" not in CAPTURE
    # No second server surface or new authority field is introduced.
    for forbidden in ("/api/voice/computer", "user_id", "workspace_id", "tenant_id"):
        assert forbidden not in CAPTURE


def test_locale_has_both_languages_for_the_option():
    assert '"meeting-computer-audio": "Capture computer audio too"' in LOCALE
    assert '"meeting-computer-audio-hint": "Choose the meeting tab' in LOCALE
    assert '"meeting-computer-audio-disclosure": "When computer audio is included' in LOCALE
