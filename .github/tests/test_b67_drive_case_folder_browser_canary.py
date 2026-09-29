from __future__ import annotations

import contextlib
import importlib.util
import inspect
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "b67_drive_case_folder_browser_canary.py"

spec = importlib.util.spec_from_file_location("b67_drive_case_folder_browser_canary", SCRIPT)
assert spec is not None and spec.loader is not None
canary = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = canary
spec.loader.exec_module(canary)


def test_default_invocation_is_blocked_before_playwright_or_network() -> None:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = canary.main([])
    assert rc == 1
    output = out.getvalue()
    assert "B67_A6_BROWSER_FLOW=FAIL_AUTHORIZATION_REQUIRED" in output
    assert "DEFAULT_LIVE_EXECUTION=BLOCKED" in output


@pytest.mark.parametrize(
    "value",
    [
        "http://127.0.0.1:9222",
        "http://localhost:9222",
        "http://[::1]:9222",
    ],
)
def test_cdp_url_allows_loopback_http_only(value: str) -> None:
    assert canary.validate_cdp_url(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "https://127.0.0.1:9222",
        "http://example.com:9222",
        "http://192.168.0.2:9222",
        "http://127.0.0.1",
        "http://user:pass@127.0.0.1:9222",
        "http://127.0.0.1:9222/json",
        "http://127.0.0.1:9222/?token=x",
    ],
)
def test_cdp_url_rejects_remote_or_authority_bearing_values(value: str) -> None:
    with pytest.raises(canary.CanaryFailure):
        canary.validate_cdp_url(value)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (canary.STATUS_LOADING, "loading"),
        (canary.STATUS_UNCONFIGURED, "unconfigured"),
        ("연결됨 · 내 드라이브", "connected"),
        ("연결됨 · 공유 드라이브", "connected"),
        (canary.STATUS_DRIVE_NOT_CONNECTED, "drive_not_connected"),
        ("다른 오류", "error"),
        ("", "empty"),
    ],
)
def test_status_classifier_is_closed(text: str, expected: str) -> None:
    assert canary.classify_status(text) == expected


def test_target_and_privacy_contract_are_fixed() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert canary.TARGET_URL == "https://chat.padiem.net/"
    assert '".project-manage"' in source
    assert '"#projectDrivePickButton"' in source
    assert '"#projectDriveSearchInput"' in source
    assert 'button[data-folder-select]' in source
    assert '"PUT", "/drive-case-folder"' in source
    assert '"DELETE", "/drive-case-folder"' in source
    assert 'print("RAW_PROJECT_ID_OUTPUT=0")' in source
    assert 'print("RAW_FOLDER_ID_OUTPUT=0")' in source
    assert 'print("RAW_FOLDER_NAME_OUTPUT=0")' in source
    assert 'print("RAW_USER_OUTPUT=0")' in source
    assert 'print("COOKIE_OUTPUT=0")' in source
    assert 'print("TOKEN_OUTPUT=0")' in source
    assert "storage_state" not in source
    assert "context.cookies" not in source


def test_a6_sequence_is_pinned_without_project_or_oauth_creation() -> None:
    source = inspect.getsource(canary.run_live)
    markers = [
        "_open_existing_project(page)",
        "_open_picker_and_wait_recent(page)",
        "_search_for_folder_a(page, folder_a)",
        "_select_folder(page, folder_a.folder_id)",
        "page.reload(",
        "_open_existing_project(page, project_id)",
        "_select_folder(page, folder_b.folder_id)",
        "_clear_folder(page)",
    ]
    positions = [source.index(marker) for marker in markers]
    assert positions == sorted(positions)
    assert 'print("PROJECT_CREATE=0")' in source
    assert 'print("OAUTH_CONNECT=0")' in source
    assert "/api/auth/" not in source
    assert 'method="POST"' not in source


def test_existing_configured_baseline_fails_closed() -> None:
    source = inspect.getsource(canary.run_live)
    assert 'raise CanaryFailure("baseline_already_configured")' in source
    # The runner never clears first just to manufacture a clean baseline.
    baseline_pos = source.index('baseline = _wait_status')
    clear_pos = source.index("_clear_folder(page)")
    assert baseline_pos < clear_pos


def test_browser_runner_explicitly_leaves_d1_readback_for_separate_gate() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'print("D1_READBACK=NOT_PERFORMED_BY_BROWSER_RUNNER")' in source


def test_d1_readback_checkpoints_are_opt_in_closed_and_privacy_bounded(monkeypatch) -> None:
    calls: list[str] = []

    def fail_input(prompt: str) -> str:
        calls.append(prompt)
        raise AssertionError("checkpoint input must not run when disabled")

    monkeypatch.setattr("builtins.input", fail_input)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        canary._checkpoint("SELECT_A", enabled=False)
    assert calls == []
    assert out.getvalue() == ""

    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: calls.append(prompt) or "",
    )
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        canary._checkpoint("SELECT_A", enabled=True)
    output = out.getvalue()
    assert output.splitlines() == [
        "A6_D1_CHECKPOINT=SELECT_A",
        "A6_D1_READBACK_READY=YES",
    ]
    assert len(calls) == 1
    assert "project" not in output.lower()
    assert "folder" not in output.lower()
    assert "user" not in output.lower()
    assert "token" not in output.lower()

    with pytest.raises(canary.CanaryFailure) as exc:
        canary._checkpoint("NOT_A_PHASE", enabled=True)
    assert exc.value.code == "invalid_d1_checkpoint"


def test_d1_checkpoint_sequence_and_cli_flag_are_pinned() -> None:
    run_source = inspect.getsource(canary.run_live)
    main_source = inspect.getsource(canary.main)
    markers = [
        '_checkpoint("SELECT_A", enabled=pause_for_d1_readback)',
        '_checkpoint("REPLACE_B", enabled=pause_for_d1_readback)',
        '_checkpoint("CLEAR", enabled=pause_for_d1_readback)',
    ]
    positions = [run_source.index(marker) for marker in markers]
    assert positions == sorted(positions)
    assert run_source.index('_clear_folder(page)') < positions[2]
    assert '--pause-for-d1-readback' in main_source
    assert "pause_for_d1_readback=args.pause_for_d1_readback" in main_source
    assert canary.D1_CHECKPOINT_LABELS == frozenset({"SELECT_A", "REPLACE_B", "CLEAR"})
