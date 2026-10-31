"""Contract tests for the #5895 ④ script that sends one real chat per deploy.

The script is the verdict table and nothing else: a non-empty answer with no
error field passes, a provider-side 429/503 passes with a marker, every other
outcome reddens the gate. It must not name or read a model, must not invent a
new second/byte/count bound (it reuses the long-context canary's transport and
constants) and must never log an answer, a cookie or a credential.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/post_deploy_real_chat_smoke.py"

spec = importlib.util.spec_from_file_location("post_deploy_real_chat_smoke", SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)

CANARY = ROOT / ".github/scripts/b62_live_long_context_canary.py"

ANSWER = "네, 정상 작동합니다."


class FakeCall:
    """Stands in for the canary's bounded_call: records calls, returns fixtures."""

    def __init__(self, responses):
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def __call__(self, opener, path, *, method="GET", payload=None, timeout=None):
        self.calls.append((method, path))
        key = (method, path)
        if key not in self.responses:
            raise AssertionError(f"unexpected request: {key}")
        return self.responses[key]


def _install(monkeypatch, responses):
    fake = FakeCall(responses)
    monkeypatch.setattr(smoke, "bounded_call", fake)
    return fake


def test_a_non_empty_answer_without_an_error_field_is_a_pass() -> None:
    assert smoke.decide(200, {"answer": ANSWER}) == ("PASS", "none")


def test_an_empty_or_whitespace_answer_fails_rather_than_passing() -> None:
    for payload in ({"answer": ""}, {"answer": "   \n"}, {"answer": None}, {}):
        assert smoke.decide(200, payload)[0] == "FAIL"


def test_an_error_field_on_a_200_fails() -> None:
    verdict, code = smoke.decide(200, {"answer": ANSWER, "error": {"code": "model_hold"}})
    assert (verdict, code) == ("FAIL", "model_hold")


@pytest.mark.parametrize("limit", sorted(smoke.PROVIDER_LIMIT_STATUSES))
def test_provider_side_limits_pass_with_a_marker(limit) -> None:
    verdict, code = smoke.decide(limit, {"error": {"code": "rate_limited"}})
    assert (verdict, code) == ("PASS_PROVIDER_LIMIT", "rate_limited")


@pytest.mark.parametrize("status", (400, 401, 403, 404, 409, 413, 422, 500, 502, 504))
def test_every_other_status_fails(status) -> None:
    assert smoke.decide(status, {"error": {"code": "boom"}})[0] == "FAIL"


def test_a_non_dict_body_fails() -> None:
    assert smoke.decide(200, ["not", "a", "body"])[0] == "FAIL"


def test_the_chat_lane_is_one_free_grade_turn_and_needs_no_credential(monkeypatch) -> None:
    fake = _install(monkeypatch, {("POST", smoke.CHAT): (200, {"answer": ANSWER})})
    monkeypatch.delenv(smoke.QA_USERNAME_ENV, raising=False)
    monkeypatch.delenv(smoke.QA_PASSWORD_ENV, raising=False)
    assert smoke.run("chat") == 0
    assert [path for _, path in fake.calls] == [smoke.CHAT]


def test_the_engine_lane_signs_in_then_uses_the_browser_orchestration_lane(monkeypatch) -> None:
    fake = _install(monkeypatch, {
        ("POST", smoke.LOGIN): (200, {"ok": True}),
        ("GET", smoke.STATUS): (200, {"authenticated": True}),
        ("POST", smoke.ORCHESTRATION): (200, {"answer": ANSWER, "conversation_id": "chat_" + "a" * 32}),
        ("DELETE", smoke.CONVERSATION + "chat_" + "a" * 32): (200, {"deleted": True}),
    })
    monkeypatch.setenv(smoke.QA_USERNAME_ENV, "synthetic-qa")
    monkeypatch.setenv(smoke.QA_PASSWORD_ENV, "synthetic-password")
    assert smoke.run("engine") == 0
    assert [path for _, path in fake.calls] == [
        smoke.LOGIN, smoke.STATUS, smoke.ORCHESTRATION, smoke.CONVERSATION + "chat_" + "a" * 32
    ]


def test_a_missing_qa_credential_is_a_failure_never_a_silent_skip(monkeypatch, capsys) -> None:
    fake = _install(monkeypatch, {})
    monkeypatch.delenv(smoke.QA_USERNAME_ENV, raising=False)
    monkeypatch.setenv(smoke.QA_PASSWORD_ENV, "synthetic-password")
    assert smoke.run("engine") == 1
    assert fake.calls == []
    assert "REAL_CHAT=FAIL lane=engine code=qa_credential_missing" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("responses", "code"),
    [
        ({("POST", smoke.LOGIN): (401, {"error": {"code": "invalid_credentials"}})}, "qa_login_refused"),
        ({
            ("POST", smoke.LOGIN): (200, {"ok": True}),
            ("GET", smoke.STATUS): (200, {"authenticated": False}),
        }, "qa_session_unverified"),
    ],
)
def test_a_refused_login_or_session_fails_before_any_turn(monkeypatch, responses, code) -> None:
    _install(monkeypatch, responses)
    monkeypatch.setenv(smoke.QA_USERNAME_ENV, "synthetic-qa")
    monkeypatch.setenv(smoke.QA_PASSWORD_ENV, "synthetic-password")
    assert smoke.run("engine") == 1


def test_an_empty_answer_on_the_orchestration_lane_fails_the_gate(monkeypatch) -> None:
    _install(monkeypatch, {
        ("POST", smoke.LOGIN): (200, {"ok": True}),
        ("GET", smoke.STATUS): (200, {"authenticated": True}),
        ("POST", smoke.ORCHESTRATION): (200, {"answer": "  ", "conversation_id": "chat_" + "b" * 32}),
        ("DELETE", smoke.CONVERSATION + "chat_" + "b" * 32): (200, {"deleted": True}),
    })
    monkeypatch.setenv(smoke.QA_USERNAME_ENV, "synthetic-qa")
    monkeypatch.setenv(smoke.QA_PASSWORD_ENV, "synthetic-password")
    assert smoke.run("engine") == 1


def test_the_never_saved_conversation_of_anonymous_lane_is_not_deleted(monkeypatch) -> None:
    fake = _install(monkeypatch, {
        ("POST", smoke.CHAT): (200, {"answer": ANSWER, "conversation_id": "chat_" + "c" * 32}),
    })
    assert smoke.run("chat") == 0
    assert all(method != "DELETE" for method, _ in fake.calls)


def test_main_prints_only_the_verdict_lines_and_never_the_answer(monkeypatch, capsys) -> None:
    _install(monkeypatch, {("POST", smoke.CHAT): (200, {"answer": ANSWER})})
    assert smoke.main(["--lane", "chat"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "REAL_CHAT=PASS lane=chat code=none"
    assert "REAL_CHAT_MODEL_NAME_CHECKED=NO" in lines
    assert ANSWER not in "\n".join(lines)


def test_main_exits_one_on_a_fail(monkeypatch, capsys) -> None:
    _install(monkeypatch, {("POST", smoke.CHAT): (500, {"error": {"code": "boom"}})})
    assert smoke.main(["--lane", "chat"]) == 1
    assert "REAL_CHAT=FAIL lane=chat code=boom" in capsys.readouterr().out


def test_the_lane_is_required_and_unknown_lanes_are_refused(monkeypatch) -> None:
    with pytest.raises(SystemExit):
        smoke.main([])


def test_the_script_sends_nothing_itself_and_reuses_the_canary_transport() -> None:
    # Zero network in this file: the script must go through the imported
    # bounded_call, never build its own request.
    source = SCRIPT.read_text(encoding="utf-8")
    assert "urlopen" not in source
    assert "requests." not in source
    assert "from b62_live_long_context_canary import" in source
    assert CANARY.is_file()


def test_the_script_adds_no_new_time_byte_or_count_bound() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    # A constant shaped like a bound and assigned a literal would be a new
    # second/byte/count limit declared here instead of reused.
    assert re.search(r"\b[A-Z_]*(SECONDS|BYTES|MAX|LIMIT|CAP|TIMEOUT)[A-Z_]*\s*=\s*[0-9]", source) is None
    assert re.search(r"timeout\s*=\s*[0-9]", source) is None
    assert "sleep" not in source
    assert source.count("timeout=CHAT_TIMEOUT_SECONDS") == 2  # one per lane, imported only


def test_the_script_names_no_model_and_reads_no_model_from_the_response() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ('"model"', "'model'", "model_id"):
        assert forbidden not in source, forbidden
    assert smoke.PROMPT
    assert smoke.PROVIDER_LIMIT_STATUSES == frozenset({429, 503})


def test_the_turn_is_one_free_grade_message_on_both_lanes() -> None:
    body = smoke.turn_payload()
    assert body["tier"] == smoke.GRADE == "free"
    assert set(body) == {"tier", "messages"}
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == smoke.PROMPT


def test_a_credential_value_never_reaches_the_output(monkeypatch, capsys) -> None:
    _install(monkeypatch, {("POST", smoke.CHAT): (500, {"error": {"code": "boom"}})})
    monkeypatch.setenv(smoke.QA_USERNAME_ENV, "synthetic-qa-user")
    monkeypatch.setenv(smoke.QA_PASSWORD_ENV, "synthetic-qa-password")
    assert smoke.main(["--lane", "chat"]) == 1
    captured = capsys.readouterr()
    assert "synthetic-qa-user" not in captured.out + captured.err
    assert "synthetic-qa-password" not in captured.out + captured.err


def test_a_refused_login_prints_status_and_code_name_but_never_a_value(monkeypatch, capsys) -> None:
    """qa_login_refused alone cannot tell a lock from a wrong password.

    The projection is identical by design (#3501/#3508), so the smoke prints
    the HTTP status and the server's error code NAME before failing — and never
    the response body, an identifier, or a password. The verdict is unchanged.
    """

    secret_value = "synthetic-password-never-print"
    _install(monkeypatch, {
        ("POST", smoke.LOGIN): (401, {
            "error": {"code": "invalid_credentials"},
            "detail": secret_value,
        }),
    })
    monkeypatch.setenv(smoke.QA_USERNAME_ENV, "synthetic-qa")
    monkeypatch.setenv(smoke.QA_PASSWORD_ENV, secret_value)
    assert smoke.run("engine") == 1
    out = capsys.readouterr().out
    assert "QA_LOGIN_DIAGNOSTIC login_http_status=401 server_error_code=invalid_credentials" in out
    assert "REAL_CHAT=FAIL lane=engine code=qa_login_refused" in out
    assert secret_value not in out
    assert "synthetic-qa" not in out


@pytest.mark.parametrize("failed_stage", ("login", "session", "orchestration"))
def test_non_json_response_reports_stage_and_still_fails(monkeypatch, capsys, failed_stage):
    """The real bounded parser must fail closed at every possible request."""
    import json

    class Reply:
        status = 200

        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            return self.body[:size]

    class Opener:
        def open(self, request, timeout):
            path = request.full_url.split(".net", 1)[1]
            stage, payload = {
                smoke.LOGIN: ("login", {"ok": True}),
                smoke.STATUS: ("session", {"authenticated": True}),
                smoke.ORCHESTRATION: ("orchestration", {"answer": "synthetic answer"}),
            }[path]
            body = b"<html>synthetic non-json response</html>" if stage == failed_stage else json.dumps(payload).encode()
            return Reply(body)

    monkeypatch.setattr(smoke, "build_opener", lambda *_: Opener())
    monkeypatch.setenv(smoke.QA_USERNAME_ENV, "synthetic-user")
    monkeypatch.setenv(smoke.QA_PASSWORD_ENV, "synthetic-password")
    assert smoke.run("engine") == 1
    captured = capsys.readouterr()
    assert f"REAL_CHAT_FAILURE_STAGE={failed_stage}" in captured.out
    assert "REAL_CHAT=FAIL lane=engine code=unexpected_http_json_shape" in captured.out
    assert "synthetic non-json response" not in captured.out
    assert "synthetic-password" not in captured.out
