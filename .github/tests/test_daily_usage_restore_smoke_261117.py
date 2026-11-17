"""#6724 시나리오 6 — 일일 점검의 격리 복구 스모크 계약.

기존 계약 시험은 넓히지 않고 새 파일로만 검사를 더한다:
  - 워크플로가 복구 스모크 패키지를 설치하고 스모크 단계를 `always()` 로 둔다.
  - 스모크가 `USAGE_FLOW name=restore_smoke` 한 줄을 남기고 실패 시 0이 아닌
    종료 코드를 반환한다(수집기가 흐름 이름을 읽을 수 있어야 한다).
  - 실패 알림 경로(`nightly-qa-failure-issue`)가 Daily Real Usage Check 를
    여전히 감지한다.
  - e2e 3098 계약(schedule·dispatch·static JS PR 만, push 금지)은 그대로다.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WORKFLOW = ROOT / "workflows" / "daily-real-usage-check.yml"
SMOKE = ROOT / "scripts" / "daily_restore_smoke.py"
ISSUE_WF = ROOT / "workflows" / "nightly-qa-failure-issue.yml"
E2E_WF = ROOT / "workflows" / "web-desktop-nonmodel-e2e.yml"


def _load():
    spec = importlib.util.spec_from_file_location("daily_restore_smoke", SMOKE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _steps():
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return {step.get("name"): step for step in document["jobs"]["real-usage"]["steps"]
            if step.get("name")}


def test_workflow_installs_and_runs_the_isolated_restore_smoke():
    steps = _steps()
    install = steps["Install the restore smoke package"]
    assert "cryptography" in install["run"]
    smoke = steps["Scenario 6 isolated restore smoke"]
    assert "daily_restore_smoke.py" in smoke["run"]
    assert smoke.get("if") == "always()"


def test_the_smoke_uses_only_a_temporary_backup_and_a_test_key():
    source = SMOKE.read_text(encoding="utf-8")
    assert "USAGE_FLOW name=restore_smoke" in source
    assert "test_restore_script.py" in source
    for forbidden in ("COM2_OFFSITE_KEY_FILE", "QA_SMOKE_PASSWORD", "secrets."):
        assert forbidden not in source


def test_verdict_is_bounded_and_failure_is_nonzero(monkeypatch, capsys):
    mod = _load()
    assert mod._verdict("Ran 6 tests in 1.0s\n\nOK", 0) == ("PASS", "restore_ok")
    assert mod._verdict("Ran 6 tests in 1.0s\n\nOK (skipped=6)", 0) == (
        "SKIPPED", "restore_all_skipped")
    assert mod._verdict("Ran 6 tests in 1.0s\n\nFAILED (failures=1)", 1) == (
        "FAIL", "restore_test_failure")
    assert mod._verdict("", 0) == ("FAIL", "restore_no_tests")

    monkeypatch.setattr(mod, "BUNDLE", ROOT / "scripts" / "no_such_bundle.py")
    assert mod.main() == 1
    output = capsys.readouterr().out
    assert "USAGE_FLOW name=restore_smoke verdict=FAIL" in output
    assert "code=restore_bundle_missing" in output


def test_failure_issue_workflow_still_reads_daily_usage():
    rendered = ISSUE_WF.read_text(encoding="utf-8")
    assert "Daily Real Usage Check" in rendered


def test_e2e_3098_contract_is_untouched():
    rendered = E2E_WF.read_text(encoding="utf-8")
    assert "  push:\n" not in rendered
    assert 'apps/padiem-chat/static/*.js' in rendered
