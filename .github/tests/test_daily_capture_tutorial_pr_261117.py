"""#6724 3번 1단계 — 일일 캡처 → 튜토리얼 자산 아티팩트 계약.

캡처 원본도 재생성 자산도 저장소에 커밋하지 않는다. PR은 사람이 확인한 뒤
연다. 계정 표시는 생성물에 남지 않아야 한다. 가짜 캡처·가짜 계정값만 쓴다.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SCRIPT = ROOT / "tools" / "tutorial" / "daily_capture_refresh.py"
WORKFLOW = ROOT / ".github" / "workflows" / "daily-real-usage-check.yml"
E2E = ROOT / ".github" / "workflows" / "web-desktop-nonmodel-e2e.yml"


def _load():
    spec = importlib.util.spec_from_file_location("daily_capture_refresh", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_workflow_uploads_artifact_without_write_permissions():
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = document["jobs"]["real-usage"]
    assert "permissions" not in job
    steps = {step.get("name"): step for step in job["steps"] if step.get("name")}
    stage = steps["Stage tutorial refresh artifact"]
    assert "daily_capture_refresh.py" in stage["run"]
    assert "--out tutorial-daily-refresh" in stage["run"]
    assert "GH_TOKEN" not in stage.get("env", {})
    upload = steps["Upload the tutorial refresh artifact"]
    assert upload["with"]["name"] == "daily-tutorial-refresh"
    assert upload["with"]["path"] == "tutorial-daily-refresh"


def test_refresh_step_failure_never_fails_the_daily_verdict():
    """#7935 마무리: 이 단계가 실패해도 일일 점검 판정은 FAIL 이 되지 않는다.

    워크플로 단계는 continue-on-error 로 예상 밖 종료까지 흡수하고, 스크립트는
    알려진 실패를 상태로 CHANGE_SUMMARY.md 에 적고 0 으로 끝난다.
    """
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = document["jobs"]["real-usage"]
    steps = {step.get("name"): step for step in job["steps"] if step.get("name")}
    stage = steps["Stage tutorial refresh artifact"]
    assert stage.get("continue-on-error") is True


def test_workflow_installs_pillow_before_the_refresh_step():
    """#7935 후속: 갱신 단계 전에 Pillow 설치가 선행한다(재생성 빌드 의존).

    버전은 저장소 기존 요구사항의 고정값(Pillow==11.3.0)이다. 흐름이 FAIL 인
    날에도 갱신 단계가 실행되므로 설치 단계도 항상 실행된다.
    """
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = document["jobs"]["real-usage"]["steps"]
    installs = [i for i, step in enumerate(steps)
                if "Pillow" in (step.get("run") or "")]
    assert len(installs) == 1
    install = steps[installs[0]]
    assert "Pillow==11.3.0" in install["run"]
    assert install.get("if") == "always()"
    stage_idx = next(i for i, step in enumerate(steps)
                     if step.get("name") == "Stage tutorial refresh artifact")
    assert installs[0] < stage_idx


def test_no_pr_creation_and_no_raw_capture_commit():
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("gh\", \"pr", "git\", \"commit", "permissions"):
        assert forbidden not in source
    assert "docs/help/tutorials" in source
    assert "apps/padiem-chat/static/help-tutorials" in source


def test_layout_captures_uses_the_documented_scene_mapping(tmp_path):
    mod = _load()
    captures = tmp_path / "captures"
    captures.mkdir()
    for name in ("browser_chat_01_open.png", "browser_chat_02_question.png",
                 "browser_chat_03_answer.png", "browser_stamp_01_app-version.png",
                 "browser_shared_login_04_logged-in.png",
                 "browser_shared_login_01_open.png"):
        (captures / name).write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 32)
    shots = tmp_path / "shots"
    assert mod.layout_captures(captures, shots) == 4
    assert sorted(p.name for p in (shots / "01-first-visit").iterdir()) == [
        "step-01.png", "step-02.png", "step-03.png", "step-04.png",
    ]


def test_step_capture_mapping_takes_only_the_tutorial_step(tmp_path):
    """#7943 후속: 공용 로그인 흐름은 4단계 한 장만 시나리오로 가져온다.

    로그인 폼·콜백 캡처(1–3)는 튜토리얼 화면이 아니므로 매핑 밖이다.
    """
    mod = _load()
    assert mod.CAPTURE_STEP_TO_SCENE == {"browser_shared_login": {4: "01-first-visit"}}
    assert set(mod.CAPTURE_TO_SCENE) == {"browser_chat"}


def test_summary_lists_changed_files_and_per_scene_state(tmp_path):
    mod = _load()
    mod.write_summary(tmp_path, [
        "docs/help/tutorials/01-first-visit.md",
        "apps/padiem-chat/static/help-tutorials/assets/01-first-visit/step-01.webp",
    ], "artifact_ready")
    text = (tmp_path / "CHANGE_SUMMARY.md").read_text(encoding="utf-8")
    assert "status=artifact_ready" in text
    assert "## changed files" in text
    assert "01-first-visit.md" in text
    assert "step-01.webp" in text
    assert "01-first-visit: changed" in text


def test_account_display_is_checked_without_printing_the_value(tmp_path):
    mod = _load()
    fake_user = "qa-" + "u" * 12
    clean = tmp_path / "clean.md"
    clean.write_text("튜토리얼 단계", encoding="utf-8")
    dirty = tmp_path / "dirty.md"
    dirty.write_text("튜토리얼 단계 " + fake_user, encoding="utf-8")
    assert mod.account_masked([clean], fake_user) is True
    assert mod.account_masked([clean, dirty], fake_user) is False
    assert mod.account_masked([dirty], "") is True


def test_no_captures_is_a_no_op(tmp_path, capsys):
    mod = _load()
    out = tmp_path / "out"
    assert mod.main(["--captures", str(tmp_path), "--out", str(out)]) == 0
    assert "tutorial_daily=no_captures" in capsys.readouterr().out
    # #7935: 산출물은 항상 CHANGE_SUMMARY.md 를 갖는다(상태 포함).
    summary = (out / "CHANGE_SUMMARY.md").read_text(encoding="utf-8")
    assert "status=no_captures" in summary


def test_build_failure_exits_zero_and_records_the_status(tmp_path, capsys, monkeypatch):
    """#7935: 자산 재생성 실패도 일일 점검 판정을 바꾸지 않는다.

    스크립트는 0 으로 끝나고 실패 상태가 CHANGE_SUMMARY.md 에 남는다.
    """
    mod = _load()

    class _FailRun:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **kwargs: _FailRun())
    captures = tmp_path / "captures"
    captures.mkdir()
    (captures / "browser_chat_01_open.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 32)
    out = tmp_path / "out"
    assert mod.main(["--captures", str(captures), "--out", str(out)]) == 0
    assert "tutorial_daily=build_failed" in capsys.readouterr().out
    summary = (out / "CHANGE_SUMMARY.md").read_text(encoding="utf-8")
    assert "status=build_failed" in summary


def test_refresh_build_uses_partial_mode_and_records_scene_state(
        tmp_path, capsys, monkeypatch):
    """#7943 후속: 빌드는 부분 모드로 돌고 요약에 regenerated/kept 를 적는다.

    캡처가 있는 단계(1–3)만 재생성하고 일일 흐름이 못 찍는 단계(4)는 커밋된
    webp 를 그대로 둔다. 재생성 결과가 커밋분과 같으면 status 는 no_change.
    """
    mod = _load()
    build_cmds: list[str] = []

    class _FakeRun:
        def __init__(self, returncode, stdout=""):
            self.returncode = returncode
            self.stdout = stdout

    def fake_run(cmd, **kwargs):
        rendered = " ".join(str(part) for part in cmd)
        if "--partial" in rendered:
            build_cmds.append(rendered)
            return _FakeRun(0, stdout="tutorials_written=6\n"
                            "TUTORIAL_PARTIAL scene=01-first-visit "
                            "regenerated=1,2,3 kept=4\n")
        if "--check" in rendered:
            return _FakeRun(0, stdout="tutorials_up_to_date\n")
        return _FakeRun(0, stdout="")  # git diff — 변경 없음

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    captures = tmp_path / "captures"
    captures.mkdir()
    (captures / "browser_chat_01_open.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 32)
    out = tmp_path / "out"
    assert mod.main(["--captures", str(captures), "--out", str(out)]) == 0
    assert len(build_cmds) == 1 and "--partial" in build_cmds[0]
    assert "TUTORIAL_PARTIAL scene=01-first-visit" in capsys.readouterr().out
    summary = (out / "CHANGE_SUMMARY.md").read_text(encoding="utf-8")
    assert "status=no_change" in summary
    assert "- 01-first-visit: regenerated=1,2,3 kept=4" in summary


def test_mask_failure_is_still_recorded_for_regenerated_assets(
        tmp_path, capsys, monkeypatch):
    """#7943 후속: 부분 모드에서도 재생성 자산의 마스킹 확인이 그대로다."""
    mod = _load()
    fake_user = "qa-" + "u" * 12
    dirty = tmp_path / "step-01.webp"
    dirty.write_bytes(b"WEBP " + fake_user.encode("utf-8"))

    class _FakeRun:
        def __init__(self, returncode, stdout=""):
            self.returncode = returncode
            self.stdout = stdout

    def fake_run(cmd, **kwargs):
        rendered = " ".join(str(part) for part in cmd)
        if "--partial" in rendered or "--check" in rendered:
            return _FakeRun(0, stdout="tutorials_written=6\n")
        return _FakeRun(0, stdout=str(dirty))  # git diff — 재생성 자산 1개

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setenv("QA_SMOKE_USERNAME", fake_user)
    captures = tmp_path / "captures"
    captures.mkdir()
    (captures / "browser_chat_01_open.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 32)
    out = tmp_path / "out"
    assert mod.main(["--captures", str(captures), "--out", str(out)]) == 0
    assert "tutorial_daily=mask_failed" in capsys.readouterr().out
    summary = (out / "CHANGE_SUMMARY.md").read_text(encoding="utf-8")
    assert "status=mask_failed" in summary
    # 계정 값 자체는 요약에 남지 않는다.
    assert fake_user not in summary


def test_unexpected_refresh_error_exits_zero_and_is_recorded(tmp_path, capsys, monkeypatch):
    """#7935: 예상 밖 오류도 0 으로 끝내고 CHANGE_SUMMARY.md 에 남긴다."""
    mod = _load()

    def _boom(*args, **kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(mod, "_refresh", _boom)
    out = tmp_path / "out"
    assert mod.main(["--captures", str(tmp_path), "--out", str(out)]) == 0
    assert "tutorial_daily=unexpected_error" in capsys.readouterr().out
    summary = (out / "CHANGE_SUMMARY.md").read_text(encoding="utf-8")
    assert "status=unexpected_error" in summary


def test_e2e_3098_contract_is_untouched():
    rendered = E2E.read_text(encoding="utf-8")
    assert "  push:\n" not in rendered
    assert "apps/padiem-chat/static/*.js" in rendered
