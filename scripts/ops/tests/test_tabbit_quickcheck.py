"""Localized tests for scripts/ops/tabbit_quickcheck.py.

These exercise the launcher's own decisions — feature detection, URL refusal,
argument escaping into the Node program, the measured verdict, evidence
collection and the BLOCKED path — without requiring a connected browser.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tabbit_quickcheck.py"


def load_module():
    spec = importlib.util.spec_from_file_location("tabbit_quickcheck", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


qc = load_module()


# --- feature detection --------------------------------------------------------
def test_missing_launcher_is_reported_not_guessed(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(qc.os, "name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert qc.launcher_path() is None


def test_windows_launcher_resolved_from_localappdata(monkeypatch, tmp_path) -> None:
    binary = tmp_path / "Tabbit" / "LocalAgent" / "bin" / "tabbit-cli.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"")
    monkeypatch.setattr(qc.os, "name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert qc.launcher_path() == binary


# --- URL boundary -------------------------------------------------------------
def test_only_http_without_credentials_is_accepted() -> None:
    assert qc.validate_url("https://preview.example/x") is None
    assert qc.validate_url("http://127.0.0.1:8790/") is None
    assert qc.validate_url("file:///C:/secrets/index.html") is not None
    assert qc.validate_url("javascript:alert(1)") is not None
    assert qc.validate_url("https://user:pass@example.com/") is not None
    assert qc.validate_url("https://") is not None


# --- CLI envelope parsing -----------------------------------------------------
def test_parser_skips_the_instance_banner() -> None:
    stdout = 'TABBIT_PLAYWRIGHT_INSTANCE=ABC123\n{"ok":true,"status":"succeeded"}\n'
    assert qc.parse_cli_output(stdout) == {"ok": True, "status": "succeeded"}


def test_parser_returns_none_for_unstructured_output() -> None:
    assert qc.parse_cli_output("TABBIT_PLAYWRIGHT_INSTANCE=ABC123\nboom\n") is None


# --- argument escaping into the Node program ----------------------------------
def test_hostile_arguments_cannot_escape_into_code() -> None:
    payload = '");process.exit(1);//'
    url = f"https://example.test/{payload}"
    program = qc.build_program(url, "click", 390, 1440, "button", payload)
    assert f"page.goto({json.dumps(url)}," in program
    assert f"name: {json.dumps(payload)}" in program
    assert program.count("page.goto(") == 1
    # Invariant: every occurrence of the hostile text sits inside a complete JSON
    # string literal. Remove those literals and nothing of it may survive as code.
    stripped = program.replace(json.dumps(url), "").replace(json.dumps(payload), "")
    assert "process.exit" not in stripped
    assert payload not in stripped


def test_each_action_emits_only_its_own_step() -> None:
    open_program = qc.build_program("https://example.test", "open", 390, 1440, "button", "")
    narrow_program = qc.build_program("https://example.test", "narrow", 390, 1440, "button", "")
    click_program = qc.build_program("https://example.test", "click", 390, 1440, "button", "검색")
    assert "getByRole" not in open_program
    assert "TARGET_CSS_WIDTH = 1440" in open_program
    assert "TARGET_CSS_WIDTH = 390" in narrow_program
    assert "getByRole" in click_program
    assert json.dumps("검색") in click_program
    # Exactly one screenshot per check: the 1-3 budget is a ceiling, not a quota.
    for program in (open_program, narrow_program, click_program):
        assert program.count("page.screenshot(") == 1


def test_viewport_is_measured_after_navigation_not_before() -> None:
    """A navigation puts the browser window back.

    The corrective pass ran before goto in the first version, so the program
    reported the width it had set and then measured a different one after the
    page loaded. Sizing must therefore settle after navigation and be read there.
    """
    program = qc.build_program("https://example.test", "narrow", 390, 1440, "button", "")
    assert program.index("page.goto(") < program.index("await reachCssWidth(TARGET_CSS_WIDTH)")
    assert program.index("await reachCssWidth(TARGET_CSS_WIDTH)") < program.index("const facts = await page.evaluate(")
    assert program.index("await reachCssWidth(TARGET_CSS_WIDTH)") < program.index("page.screenshot(")


def test_screenshot_does_not_wait_on_a_persistently_animating_surface() -> None:
    """The B62 glass shell keeps animating, which held screenshots open until the
    Playwright stability timeout. Facts are read from the DOM, so the image may
    settle animations without weakening the measurement."""
    program = qc.build_program("https://example.test", "open", 390, 1440, "button", "")
    assert "animations: 'disabled'" in program
    assert "timeout: 15000" in program
    assert program.count("page.screenshot(") == 1


def test_timeouts_stay_inside_the_supported_window() -> None:
    assert qc.clamp_timeout_ms(1) == 5_000
    assert qc.clamp_timeout_ms(90_000) == 90_000
    assert qc.clamp_timeout_ms(10_000_000) == qc.MAX_TIMEOUT_MS


def test_run_cli_hands_the_program_over_stdin_in_text_mode() -> None:
    """A real subprocess, no browser.

    Mocking run_cli let a bytes-vs-str stdin mismatch reach the first live call,
    so this pins the actual pipe contract against the interpreter itself.
    """
    program = "return {ok: true};"
    code, payload, _stderr = qc.run_cli(
        Path(sys.executable),
        ["-c", "import sys,json; sys.stdout.write(json.dumps({'ok': True, 'echo': sys.stdin.read()}))"],
        program,
    )
    assert code == 0
    assert payload is not None
    assert payload["ok"] is True
    assert payload["echo"] == program


# --- verdicts come from measurements -----------------------------------------
def facts_dict(width: int = 390, **over) -> dict:
    facts = {"url": "https://x.test", "title": "T", "innerWidth": width, "clientWidth": width}
    facts.update(over)
    return facts


def narrow_value(width: int = 390, *, overflow: bool = False, honored: bool = True) -> dict:
    return {"facts": facts_dict(width), "horizontalOverflow": overflow,
            "viewportHonored": honored, "sizing": {"achieved": width, "corrected": False, "ratio": None},
            "screenshotCount": 1, "limitExceeded": False}


def test_narrow_passes_only_without_horizontal_overflow() -> None:
    assert qc.judge("narrow", narrow_value(overflow=False), 390)[0] == qc.PASS
    verdict, observations = qc.judge("narrow", narrow_value(overflow=True), 390)
    assert verdict == qc.FAIL
    assert any("horizontalOverflow=True" in o for o in observations)


def test_a_clamped_viewport_is_never_certified_as_the_requested_width() -> None:
    """The browser window can refuse the requested size.

    A no-overflow result measured at 312px is not evidence about 390px, so the
    check has to fail loudly instead of silently answering a different question.
    """
    clamped = narrow_value(312, overflow=False, honored=False)
    verdict, observations = qc.judge("narrow", clamped, 390)
    assert verdict == qc.FAIL
    assert any("312" in o for o in observations)


def test_a_corrected_viewport_is_certified_and_an_uncorrected_one_is_not() -> None:
    assert qc.judge("narrow", narrow_value(390), 390)[0] == qc.PASS
    # The program owns the honored/not-honored call; the verdict must not certify
    # a width the program says it never rendered.
    assert qc.judge("narrow", narrow_value(390, honored=False), 390)[0] == qc.FAIL


def test_unexpected_screenshot_count_fails_the_check() -> None:
    value = dict(narrow_value(), screenshotCount=9, limitExceeded=True)
    verdict, observations = qc.judge("narrow", value, 390)
    assert verdict == qc.FAIL
    assert any("limit" in o.lower() for o in observations)


def test_blank_title_is_not_reported_as_pass() -> None:
    value = {"facts": facts_dict(title=""), "screenshotCount": 1, "limitExceeded": False}
    assert qc.judge("open", value, 390)[0] == qc.FAIL


# --- evidence handling --------------------------------------------------------
def test_screenshots_are_copied_and_missing_ones_stay_absent(tmp_path) -> None:
    source = tmp_path / "shot.png"
    source.write_bytes(b"\x89PNG fake")
    result = {"screenshotsDelta": [{"path": str(source)}, {"path": str(tmp_path / "gone.png")}]}
    names = qc.collect_screenshots(result, tmp_path / "evidence", "https://preview.example/")
    assert names == ["quickcheck-1-preview.example.png"]
    assert (tmp_path / "evidence" / names[0]).read_bytes() == b"\x89PNG fake"


def test_revision_is_shape_checked_or_none(monkeypatch) -> None:
    monkeypatch.setattr(qc.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""))
    assert qc.git_revision() is None


# --- end-to-end without a browser --------------------------------------------
def test_blocked_path_writes_evidence_and_exits_two(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(qc, "launcher_path", lambda: None)
    monkeypatch.setattr(qc, "git_revision", lambda: "0" * 40)
    code = qc.main(["--url", "https://preview.example/", "--action", "open",
                    "--evidence-dir", str(tmp_path / "ev")])
    assert code == 2
    written = json.loads((tmp_path / "ev" / "quickcheck.json").read_text(encoding="utf-8"))
    assert written["result"] == qc.BLOCKED
    assert written["url"] == "https://preview.example/"
    assert written["revision"] == "0" * 40
    assert written["screenshots"] == []
    # No fabricated success on stdout.
    assert '"result": "BLOCKED"' in capsys.readouterr().out


def test_rejected_url_never_reaches_the_launcher(monkeypatch, tmp_path) -> None:
    calls: list = []
    monkeypatch.setattr(qc, "launcher_path", lambda: Path("/supposedly/here"))
    monkeypatch.setattr(qc, "run_cli", lambda *a, **k: calls.append(a) or (0, {"ok": True}, ""))
    code = qc.main(["--url", "file:///C:/private.html", "--evidence-dir", str(tmp_path / "ev")])
    assert code == 2
    assert calls == []


def test_a_non_running_controller_is_blocked_before_navigation(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(qc, "launcher_path", lambda: Path("/supposedly/here"))
    calls: list = []

    def fake(launcher, args, program=None):
        calls.append(args[0])
        return 0, {"ok": True, "controller": "stopped"}, ""

    monkeypatch.setattr(qc, "run_cli", fake)
    code = qc.main(["--url", "https://preview.example/", "--evidence-dir", str(tmp_path / "ev")])
    assert code == 2
    # `finish` runs from the finally block on purpose; the claim under test is
    # that no program was ever submitted to the browser.
    assert "nodejs" not in calls
    assert calls == ["diagnose", "finish"]
