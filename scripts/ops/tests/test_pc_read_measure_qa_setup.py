"""#6724 2번 1단계 — QA PC 설치·승인 구간 검증의 두-sided 계약.

가짜 토큰 파일과 가짜 조회만 쓴다. 실제 PC·운영 토큰·네트워크에 닿지 않고,
토큰 값은 출력·기록·이 파일의 고정값에 넣지 않는다(존재와 형식만 검사).
기존 시험은 넓히지 않고 새 파일로만 검사를 더한다.
"""
from __future__ import annotations

import importlib.util
import pathlib
import secrets
import uuid

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]


def _load_measure():
    spec = importlib.util.spec_from_file_location(
        "pc_read_measure", REPO / "scripts" / "ops" / "pc_read_measure.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_token() -> str:
    """발급 규칙과 같은 방법으로 만든 값 — 실제 발급 토큰이 아니다."""
    return "mcp_" + uuid.uuid4().hex + "." + secrets.token_urlsafe(32)


def test_the_format_matches_the_issuance_rule():
    """발급 경로(D1McpGatewayStore.issue_token)의 규칙과 같은 값이 통과한다."""
    measure = _load_measure()
    issued_rule = "mcp_" + uuid.uuid4().hex + "." + secrets.token_urlsafe(32)
    assert measure._QA_TOKEN_FORMAT.fullmatch(issued_rule) is not None
    for other in (
        "pt_" + "a" * 32,                      # 설치 토큰 접두사
        "mcp_" + "A" * 32 + "." + "x" * 43,    # id에 대문자
        "mcp_" + "a" * 32 + "." + "x" * 42,    # 비밀부 길이 부족
        "mcp_" + "a" * 32 + "!" + "x" * 43,    # 구분자 아님
    ):
        assert measure._QA_TOKEN_FORMAT.fullmatch(other) is None


def test_missing_token_is_reported_without_reading_anything(tmp_path):
    measure = _load_measure()
    out = measure.verify_qa_pc_setup(str(tmp_path / "absent.token"))
    assert out["verdict"] == "FAIL"
    assert out["code"] == "setup_token_missing"
    assert out["token_present"] is False
    assert "token" not in out


def test_token_format_is_checked_without_ever_returning_the_value(tmp_path):
    measure = _load_measure()
    path = tmp_path / "qa.token"
    path.write_text(_fake_token(), encoding="utf-8")
    out = measure.verify_qa_pc_setup(str(path), lookup=lambda: {"approved": True, "roots": 1})
    assert out == {
        "verdict": "PASS", "code": "setup_ok", "token_present": True,
        "token_format_ok": True, "approved": True, "roots": 1,
    }
    assert _fake_token() not in str(out)

    path.write_text("bad format\n", encoding="utf-8")
    out = measure.verify_qa_pc_setup(str(path), lookup=lambda: {"approved": True, "roots": 1})
    assert out["verdict"] == "FAIL"
    assert out["code"] == "setup_token_format_invalid"
    assert out["token_format_ok"] is False


@pytest.mark.parametrize("row,code", [
    ({"approved": False, "roots": 1}, "setup_not_approved"),
    ({"approved": True, "roots": 0}, "setup_no_approved_root"),
    ({"approved": True, "roots": "1"}, "setup_no_approved_root"),
    (None, "setup_not_approved"),
])
def test_approval_and_root_are_both_required(tmp_path, row, code):
    measure = _load_measure()
    path = tmp_path / "qa.token"
    path.write_text(_fake_token(), encoding="utf-8")
    out = measure.verify_qa_pc_setup(str(path), lookup=lambda: row)
    assert out["verdict"] == "FAIL"
    assert out["code"] == code


def test_lookup_error_is_bounded_and_never_leaks_the_message(tmp_path):
    measure = _load_measure()
    path = tmp_path / "qa.token"
    path.write_text(_fake_token(), encoding="utf-8")

    def boom():
        raise RuntimeError("token=" + _fake_token() + " host=production")

    out = measure.verify_qa_pc_setup(str(path), lookup=boom)
    assert out["verdict"] == "FAIL"
    assert out["code"] == "setup_lookup_error_RuntimeError"
    assert _fake_token() not in str(out)
    assert "production" not in str(out)


def test_default_lookup_reads_only_the_sidecar_file(tmp_path):
    measure = _load_measure()
    path = tmp_path / "qa.token"
    path.write_text(_fake_token(), encoding="utf-8")
    sidecar = pathlib.Path(str(path) + ".setup.json")
    sidecar.write_text('{"approved": true, "roots": 2}', encoding="utf-8")
    out = measure.verify_qa_pc_setup(str(path))
    assert out["verdict"] == "PASS"
    assert out["code"] == "setup_ok"
    assert out["roots"] == 2
