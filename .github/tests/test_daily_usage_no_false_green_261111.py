"""#7440 4번 계약: 실사용 점검은 아무 흐름도 검사하지 않고 success 로 끝나지
않는다(2026-11-11).

#7449 가 QA 계정을 용도별로 분리하면서 daily_real_usage_check.py 가 읽는 env
이름은 QA_SMOKE_USERNAME / QA_SMOKE_PASSWORD 가 됐다. 워크플로가 옛 이름
(B66_CGI_ALPHA_*)만 넘기면 8흐름이 전부 SKIPPED qa_credential_missing 으로
끝나는데 결론은 success 였다 — 매일 밤 아무 것도 검사하지 않는 거짓 녹색.
이 파일은 세 가지를 고정한다:

  1. 스크립트가 읽는 env 이름은 QA_SMOKE_* 다(이름이 바뀌면 이 시험이 깨진다).
  2. 실제로 검사한 흐름(PASS + FAIL)이 0개면 실행 결론은 FAIL 이고 0이 아닌
     종료 코드로 끝난다. 흐름 기록 자체는 #6720 대로 SKIPPED 로 남는다.
  3. 워크플로는 QA_SMOKE_* 시크릿을 스크립트가 읽는 이름으로 그대로 넘기고,
     자격 증명이 없는 단계도 success 로 끝나지 않는다.

실행:
    python -m pytest .github/tests/test_daily_usage_no_false_green_261111.py -q
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CHECK = HERE.parent / "scripts" / "daily_real_usage_check.py"
WORKFLOW = HERE.parent / "workflows" / "daily-real-usage-check.yml"


def _load_module():
    spec = importlib.util.spec_from_file_location("daily_real_usage_check", CHECK)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_script_reads_the_qa_smoke_env_names():
    """#7449 뒤 스크립트가 읽는 이름은 smoke 모듈의 QA_SMOKE_* 다."""
    mod = _load_module()
    from post_deploy_real_chat_smoke import QA_PASSWORD_ENV, QA_USERNAME_ENV

    assert (mod.QA_USERNAME_ENV, mod.QA_PASSWORD_ENV) == (
        "QA_SMOKE_USERNAME", "QA_SMOKE_PASSWORD")
    assert (QA_USERNAME_ENV, QA_PASSWORD_ENV) == (
        "QA_SMOKE_USERNAME", "QA_SMOKE_PASSWORD")
    assert mod._credential_verdict() == ("SKIPPED", "qa_credential_missing")


def test_run_verdict_fails_when_nothing_was_checked():
    """전부 SKIPPED 인 실행(checked=0)은 PASS 가 아니라 FAIL 이다."""
    mod = _load_module()
    assert mod.run_verdict(failed=0, checked=8) == "PASS"
    assert mod.run_verdict(failed=1, checked=7) == "FAIL"
    assert mod.run_verdict(failed=0, checked=0) == "FAIL"
    assert mod.run_verdict(failed=0, checked=-1) == "FAIL"


def test_main_returns_nonzero_when_every_flow_is_skipped(tmp_path, monkeypatch, capsys):
    """자격 증명이 없으면 8흐름이 전부 SKIPPED 고 결론은 실패다(#6720 + #7440)."""
    mod = _load_module()
    for name in ("QA_SMOKE_USERNAME", "QA_SMOKE_PASSWORD",
                 "B66_CGI_ALPHA_USERNAME", "B66_CGI_ALPHA_PASSWORD",
                 "PADIEM_QA_PC_TOKEN", "GITHUB_RUN_ID", "GITHUB_STEP_SUMMARY",
                 "GITHUB_REPOSITORY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PADIEM_USAGE_METRICS_PATH", str(tmp_path / "metrics.json"))

    exit_code = mod.main()

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "USAGE_CHECK verdict=FAIL" in output
    assert "checked=0" in output
    assert "skipped=8" in output
    # 흐름 기록은 #6720 대로 SKIPPED 로 남는다(수집기가 코드를 읽는다).
    assert "USAGE_FLOW name=chat_turn verdict=SKIPPED" in output
    assert output.count("code=qa_credential_missing") >= 8


def test_workflow_passes_the_qa_smoke_pair_the_script_reads():
    """워크플로 env 는 스크립트가 읽는 QA_SMOKE_* 이고 옛 이름이 남지 않는다."""
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = document["jobs"]["real-usage"]
    env = job["env"]

    assert env["QA_SMOKE_USERNAME"] == "${{ secrets.QA_SMOKE_USERNAME }}"
    assert env["QA_SMOKE_PASSWORD"] == "${{ secrets.QA_SMOKE_PASSWORD }}"
    rendered = WORKFLOW.read_text(encoding="utf-8")
    assert "B66_CGI_ALPHA" not in rendered, (
        "the workflow must not pass env names the script never reads — that "
        "left every nightly run SKIPPED qa_credential_missing yet success")

    steps = {step.get("name"): step for step in job["steps"] if step.get("name")}
    absent = steps["Fail when the QA credential is absent"]
    assert "exit 1" in absent["run"], (
        "an absent credential must not end the workflow green")
    run_step = steps["Run the eight real-usage flows"]
    assert "env.QA_SMOKE_USERNAME != ''" in run_step["if"]
    assert "env.QA_SMOKE_PASSWORD != ''" in run_step["if"]
