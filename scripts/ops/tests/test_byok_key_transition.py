from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "byok_key_transition.py"


def _load():
    spec = importlib.util.spec_from_file_location("byok_key_transition_ops", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


transition = _load()
SECRET = transition.SECRET_NAME


def _completed(returncode=0, stdout="", stderr=""):
    return transition._Completed(returncode, stdout, stderr)


def test_name_parsers_ignore_values_and_count_lines():
    assert transition._parse_dpapi_names(
        "PADIEM_CHAT_SESSION_SECRET\nPADIEM_CHAT_CUSTOM_KEY_SECRET\nCOUNT 2\n"
    ) == {"PADIEM_CHAT_SESSION_SECRET", SECRET}
    assert transition._parse_dpapi_names("sk-value\nlowercase\n\n") == set()
    assert transition._parse_worker_names(
        json.dumps([{"name": SECRET}, {"name": "PADIEM_CHAT_SESSION_SECRET"}])
    ) == {SECRET, "PADIEM_CHAT_SESSION_SECRET"}
    assert transition._parse_worker_names(json.dumps({"result": [{"name": SECRET}]})) == {SECRET}


def test_preflight_ready_requires_all_four_signals(monkeypatch):
    monkeypatch.setattr(transition, "read_dpapi_names", lambda *_: {SECRET})
    monkeypatch.setattr(transition, "read_worker_secret_names", lambda *_: {SECRET})
    monkeypatch.setattr(
        transition,
        "read_d1_state",
        lambda *_: {"migration_053": "APPLIED", "rows": 0},
    )
    monkeypatch.setattr(transition, "probe_route", lambda *_: "PRESENT")

    result, errors = transition.preflight(account_id="account")
    assert errors == []
    assert result["ready"] is True
    assert result["secret_values_printed"] == 0

    monkeypatch.setattr(transition, "read_dpapi_names", lambda *_: set())
    result, _ = transition.preflight(account_id="account")
    assert result["dpapi_custom_key_secret"] == "MISSING"
    assert result["ready"] is False

    monkeypatch.setattr(transition, "read_dpapi_names", lambda *_: {SECRET})
    monkeypatch.setattr(transition, "probe_route", lambda *_: "ABSENT")
    result, _ = transition.preflight(account_id="account")
    assert result["deployed_byok_route"] == "ABSENT"
    assert result["ready"] is False


def test_preflight_keeps_checks_independent_when_one_fails(monkeypatch):
    monkeypatch.setattr(
        transition,
        "read_dpapi_names",
        lambda *_: (_ for _ in ()).throw(transition.TransitionError("dpapi_list_failed")),
    )
    monkeypatch.setattr(transition, "read_worker_secret_names", lambda *_: {SECRET})
    monkeypatch.setattr(
        transition,
        "read_d1_state",
        lambda *_: {"migration_053": "MISSING", "rows": None},
    )
    monkeypatch.setattr(transition, "probe_route", lambda *_: "PRESENT")

    result, errors = transition.preflight(account_id="account")
    assert errors == ["dpapi_list_failed"]
    assert result["dpapi_custom_key_secret"] == "ERROR:dpapi_list_failed"
    assert result["worker_custom_key_secret"] == "PRESENT"
    assert result["d1_migration_053"] == "MISSING"
    assert result["custom_credential_rows"] == "TABLE_MISSING"
    assert result["ready"] is False


def test_preflight_output_has_no_secret_and_plan_orders_steps(monkeypatch, capsys):
    monkeypatch.setattr(transition, "read_dpapi_names", lambda *_: set())
    monkeypatch.setattr(transition, "read_worker_secret_names", lambda *_: set())
    monkeypatch.setattr(
        transition,
        "read_d1_state",
        lambda *_: {"migration_053": "MISSING", "rows": None},
    )
    monkeypatch.setattr(transition, "probe_route", lambda *_: "ABSENT")

    result, errors = transition.preflight(account_id="account")
    transition._print_preflight(result, errors)
    output = capsys.readouterr()
    assert "BYOK_TRANSITION_READY=NO" in output.out
    assert "SECRET_VALUES_PRINTED=0" in output.out

    transition.print_plan(result)
    planned = capsys.readouterr().out
    assert "STEP_1_DEPLOY_EXACT_MAIN_BYOK_CODE=PENDING" in planned
    assert "STEP_2_APPLY_MIGRATION_053=PENDING" in planned
    assert "STEP_3_REGISTER_COM2_DPAPI_SECRET=PENDING" in planned
    assert "STEP_4_UPLOAD_WORKER_SECRET=PENDING" in planned
    assert "NEXT=deploy_exact_main_to_worker_and_refresh_local_release" in planned


def test_upload_worker_uses_stdin_and_never_prints_the_value(monkeypatch, capsys, tmp_path):
    secret = "unit-test-custom-key-value-with-at-least-32-characters"
    monkeypatch.setenv(SECRET, secret)
    calls = []
    wrangler = tmp_path / "wrangler.cmd"
    wrangler.write_text("@echo off\n", encoding="utf-8")

    def fake_run(command, *, env=None, input_bytes=None, cwd=None, timeout=120):
        calls.append({"command": list(command), "input": input_bytes})
        if "put" in command:
            return _completed(0)
        return _completed(0, json.dumps([{"name": SECRET}]))

    monkeypatch.setattr(transition, "_run", fake_run)
    transition.upload_worker(
        wrangler=wrangler,
        worker="padiem-chat",
        account_id="account",
        confirm=True,
    )
    output = capsys.readouterr()
    assert "WORKER_SECRET_UPLOADED=YES" in output.out
    assert "SECRET_VALUES_PRINTED=0" in output.out
    assert secret not in output.out and secret not in output.err
    put_call = next(call for call in calls if "put" in call["command"])
    assert put_call["input"] == secret.encode()
    assert all(secret not in " ".join(call["command"]) for call in calls)


def test_upload_worker_requires_hidden_store_environment(monkeypatch):
    monkeypatch.delenv(SECRET, raising=False)
    with pytest.raises(transition.TransitionError) as error:
        transition.upload_worker(
            wrangler=Path("wrangler.cmd"), account_id="account", confirm=True
        )
    assert str(error.value) == "custom_key_secret_missing_run_under_store_py"


def test_upload_worker_scrubs_failed_output(monkeypatch):
    secret = "unit-test-custom-key-value-with-at-least-32-characters"
    monkeypatch.setenv(SECRET, secret)
    monkeypatch.setattr(
        transition,
        "_run",
        lambda *_, **__: _completed(1, "", f"failed {secret}"),
    )
    with pytest.raises(transition.TransitionError) as error:
        transition.upload_worker(
            wrangler=Path("wrangler.cmd"), account_id="account", confirm=True
        )
    assert secret not in str(error.value)
    assert "[REDACTED]" in str(error.value)


def test_register_local_generates_without_printing_and_refuses_existing(monkeypatch, capsys):
    stored = []

    def fake_run(command, *, env=None, input_bytes=None, cwd=None, timeout=120):
        stored.append(input_bytes)
        return _completed(0, f"STORED {SECRET}\n")

    names = iter([set(), {SECRET}])
    monkeypatch.setattr(transition, "read_dpapi_names", lambda *_: next(names))
    monkeypatch.setattr(transition, "_run", fake_run)
    transition.register_local(
        store_script=Path("store.py"), confirm=True
    )
    output = capsys.readouterr()
    assert "DPAPI_SECRET_STORED=YES" in output.out
    assert "SECRET_VALUES_PRINTED=0" in output.out
    generated = stored[0].decode()
    assert len(generated) >= transition.MIN_SECRET_CHARS
    assert generated not in output.out

    monkeypatch.setattr(transition, "read_dpapi_names", lambda *_: {SECRET})
    with pytest.raises(transition.TransitionError) as error:
        transition.register_local(store_script=Path("store.py"), confirm=True)
    assert str(error.value) == "custom_key_secret_already_present_use_replace"


def test_apply_migration_requires_phrase_exact_main_and_file(monkeypatch, tmp_path):
    expected = "a" * 40
    with pytest.raises(transition.TransitionError) as error:
        transition.apply_migration(
            wrangler=Path("wrangler.cmd"),
            account_id="account",
            expected_main=expected,
            confirmation="",
        )
    assert str(error.value) == "migration_confirmation_required"

    monkeypatch.setattr(transition, "_git_head", lambda *_: expected)
    calls = []

    def fake_run(command, *, env=None, input_bytes=None, cwd=None, timeout=120):
        calls.append(list(command))
        return _completed(0)

    monkeypatch.setattr(transition, "_run", fake_run)
    monkeypatch.setattr(
        transition,
        "read_d1_state",
        lambda *_: {"migration_053": "APPLIED", "rows": 0},
    )
    transition.apply_migration(
        account_id="account",
        expected_main=expected,
        confirmation=transition.MIGRATION_CONFIRMATION,
    )
    assert calls
    joined = " ".join(calls[0])
    assert "--remote" in joined
    assert "053_chat_custom_provider_credentials.sql" in joined


def test_apply_migration_refuses_stale_main(monkeypatch):
    monkeypatch.setattr(transition, "_git_head", lambda *_: "b" * 40)
    monkeypatch.setattr(
        transition,
        "_run",
        lambda *_, **__: (_ for _ in ()).throw(
            AssertionError("mutation must not run on a stale main")
        ),
    )
    with pytest.raises(transition.TransitionError) as error:
        transition.apply_migration(
            account_id="account",
            expected_main="a" * 40,
            confirmation=transition.MIGRATION_CONFIRMATION,
        )
    assert str(error.value) == "expected_main_mismatch"


def test_probe_classifies_waf_challenge_as_unknown_and_json_auth_as_present():
    assert transition._classify_probe(403, "text/html") == "UNKNOWN"
    assert transition._classify_probe(403, "application/json") == "PRESENT"
    assert transition._classify_probe(401, "application/json; charset=utf-8") == "PRESENT"
    assert transition._classify_probe(404, "application/json") == "ABSENT"
    assert transition._classify_probe(200, "application/json") == "UNEXPECTED_200"


def test_probe_sends_explicit_user_agent_and_surfaces_waf_as_unknown(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["user_agent"] = request.get_header("User-agent")
        raise transition.urllib.error.HTTPError(
            request.full_url, 403, "Forbidden", {"Content-Type": "text/html"}, None
        )

    monkeypatch.setattr(transition.urllib.request, "urlopen", fake_urlopen)
    assert transition.probe_route("https://chat.example.test") == "UNKNOWN"
    assert seen["user_agent"] == transition._USER_AGENT
