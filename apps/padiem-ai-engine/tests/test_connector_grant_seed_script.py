"""Connector grant seed script contract tests (#2222).

Covers both reviewed READ connector grant paths:
- Gmail readonly scope grant (backwards-compatible default);
- Google Drive READ capability grant with trusted binding/actor refs.

All tests are network-free. Invalid authority input must fail before any D1
call; credential-bearing arguments are never accepted.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "connector_grant_seed.py"
_SPEC = importlib.util.spec_from_file_location("connector_grant_seed_script", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def _forbid_subprocess(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("wrangler/subprocess must never run in dry-run mode")


def _run_with_d1_probe(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> tuple[int, list[str]]:
    calls: list[str] = []

    def _probe_run_d1(sql: str) -> int:
        calls.append(sql)
        return 0

    monkeypatch.setattr(_MODULE, "run_d1", _probe_run_d1)
    return _MODULE.main(argv), calls


# --- Gmail regression / backwards-compatible default -----------------------

def test_gmail_seed_dry_run_emits_scope_and_empty_capability_columns(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(_MODULE.subprocess, "run", _forbid_subprocess)
    monkeypatch.setattr(_MODULE, "_now_iso", lambda: "2026-09-07T00:00:00+00:00")
    rc = _MODULE.main(["--action", "seed"])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("INSERT INTO padiem_engine_connector_grants")
    assert "granted_scopes_json, granted_capabilities_json" in out
    assert (
        "'b54-padiem-claw', 'agent:padiem:claw_mail_reader@1', "
        "'connector:google:gmail@1', 'bind:b54-padiem-claw:claw_mail_reader', "
        "'actor:b54-padiem-claw:claw_mail_reader', '[\"gmail.readonly\"]', "
        "'[]', 1, '2026-09-07T00:00:00+00:00', '2026-09-07T00:00:00+00:00'"
    ) in out
    assert "ON CONFLICT(app_id, connector_id) DO UPDATE SET active=1" in out
    assert "binding_ref=excluded.binding_ref, actor_ref=excluded.actor_ref" in out
    assert "granted_scopes_json=excluded.granted_scopes_json" in out
    assert "granted_capabilities_json=excluded.granted_capabilities_json" in out


def test_gmail_revoke_dry_run_targets_gmail_row(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(_MODULE.subprocess, "run", _forbid_subprocess)
    monkeypatch.setattr(_MODULE, "_now_iso", lambda: "2026-09-07T00:00:00+00:00")
    rc = _MODULE.main(["--action", "revoke"])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("UPDATE padiem_engine_connector_grants SET active=0")
    assert "WHERE app_id='b54-padiem-claw' AND connector_id='connector:google:gmail@1';" in out


def test_list_dry_run_emits_read_only_select_without_invoking_wrangler(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(_MODULE.subprocess, "run", _forbid_subprocess)
    rc = _MODULE.main(["--action", "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("SELECT app_id, canonical_agent_id, connector_id, binding_ref, actor_ref, active")
    assert "FROM padiem_engine_connector_grants;" in out


# --- Drive READ-only grant path --------------------------------------------

_DRIVE_BINDING = "bind:google-drive-owner-1"
_DRIVE_ACTOR = "actor:owner-1"


def test_drive_seed_dry_run_emits_canonical_read_only_capability(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(_MODULE.subprocess, "run", _forbid_subprocess)
    monkeypatch.setattr(_MODULE, "_now_iso", lambda: "2026-09-09T00:00:00+00:00")
    rc = _MODULE.main([
        "--action", "seed",
        "--connector", "drive",
        "--binding-ref", _DRIVE_BINDING,
        "--actor-ref", _DRIVE_ACTOR,
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert (
        "'b54-padiem-claw-drive', 'agent:padiem:claw_drive_reader@1', "
        "'connector:google:drive@1', 'bind:google-drive-owner-1', "
        "'actor:owner-1', '[]', '[\"read\"]', 1, "
        "'2026-09-09T00:00:00+00:00', '2026-09-09T00:00:00+00:00'"
    ) in out
    assert "mutation" not in out


def test_drive_revoke_targets_drive_row(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(_MODULE.subprocess, "run", _forbid_subprocess)
    monkeypatch.setattr(_MODULE, "_now_iso", lambda: "2026-09-09T00:00:00+00:00")
    rc = _MODULE.main([
        "--action", "revoke",
        "--connector", "drive",
        "--binding-ref", _DRIVE_BINDING,
        "--actor-ref", _DRIVE_ACTOR,
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "WHERE app_id='b54-padiem-claw-drive' AND connector_id='connector:google:drive@1';" in out


def test_drive_missing_binding_and_actor_fail_before_d1(monkeypatch: pytest.MonkeyPatch) -> None:
    rc, calls = _run_with_d1_probe(
        ["--action", "seed", "--connector", "drive", "--execute"],
        monkeypatch,
    )
    assert rc == 2
    assert calls == []


def test_drive_mutation_capability_fails_before_d1(monkeypatch: pytest.MonkeyPatch) -> None:
    rc, calls = _run_with_d1_probe(
        [
            "--action", "seed", "--connector", "drive",
            "--binding-ref", _DRIVE_BINDING, "--actor-ref", _DRIVE_ACTOR,
            "--capabilities", "mutation", "--execute",
        ],
        monkeypatch,
    )
    assert rc == 2
    assert calls == []


def test_drive_unknown_capability_fails_before_d1(monkeypatch: pytest.MonkeyPatch) -> None:
    rc, calls = _run_with_d1_probe(
        [
            "--action", "seed", "--connector", "drive",
            "--binding-ref", _DRIVE_BINDING, "--actor-ref", _DRIVE_ACTOR,
            "--capabilities", "read", "share", "--execute",
        ],
        monkeypatch,
    )
    assert rc == 2
    assert calls == []


def test_drive_scope_argument_fails_before_d1(monkeypatch: pytest.MonkeyPatch) -> None:
    rc, calls = _run_with_d1_probe(
        [
            "--action", "seed", "--connector", "drive",
            "--binding-ref", _DRIVE_BINDING, "--actor-ref", _DRIVE_ACTOR,
            "--scopes", "https://www.googleapis.com/auth/drive.readonly", "--execute",
        ],
        monkeypatch,
    )
    assert rc == 2
    assert calls == []


# --- shared validation / credential safety ---------------------------------

def test_invalid_app_id_exits_2_with_zero_d1_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    rc, calls = _run_with_d1_probe(
        ["--action", "seed", "--app-id", "b62; DROP TABLE padiem_engine_connector_grants", "--execute"],
        monkeypatch,
    )
    assert rc == 2
    assert calls == []


def test_invalid_agent_id_exits_2_with_zero_d1_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    rc, calls = _run_with_d1_probe(
        ["--action", "seed", "--agent-id", "agent:padiem:claw_mail_reader@0", "--execute"],
        monkeypatch,
    )
    assert rc == 2
    assert calls == []


def test_invalid_gmail_scope_exits_2_with_zero_d1_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    rc, calls = _run_with_d1_probe(
        ["--action", "seed", "--scopes", "https://www.googleapis.com/auth/gmail.send", "--execute"],
        monkeypatch,
    )
    assert rc == 2
    assert calls == []


def test_sql_injection_binding_ref_exits_2_with_zero_d1_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    rc, calls = _run_with_d1_probe(
        [
            "--action", "seed",
            "--binding-ref", "bind:x'; DROP TABLE padiem_engine_connector_grants; --",
            "--execute",
        ],
        monkeypatch,
    )
    assert rc == 2
    assert calls == []


def test_credential_argument_is_rejected() -> None:
    with pytest.raises(SystemExit) as exc:
        _MODULE.main(["--action", "seed", "--client-secret", "do-not-print"])
    assert exc.value.code == 2


def test_execute_mode_uses_exact_wrangler_d1_argument_array(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd: list[str], **_kwargs: object) -> _FakeResult:
        captured["cmd"] = cmd
        return _FakeResult()

    monkeypatch.setattr(_MODULE.subprocess, "run", _fake_run)
    rc = _MODULE.main(["--action", "seed", "--execute"])
    assert rc == 0
    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert cmd[:9] == [
        "npx", "--yes", "wrangler@4", "d1", "execute", "padiem-engine",
        "--remote", "--json", "--command",
    ]
    sql = cmd[9]
    assert isinstance(sql, str)
    assert sql.startswith("INSERT INTO padiem_engine_connector_grants")
