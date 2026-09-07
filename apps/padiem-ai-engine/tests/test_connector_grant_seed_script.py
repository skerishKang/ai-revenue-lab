"""WO-10 ACT-1 commit 1: connector grant seed script contract tests.

- dry-run prints SQL and never invokes wrangler (seed/revoke/list);
- invalid identifiers/scopes exit 2 with zero D1 calls even with ``--execute``;
- credential-bearing arguments are rejected (argparse, exit 2);
- ``--execute`` shells through the exact wrangler d1 argument array.

Script is loaded by path like ``test_deploy_packaging_staging.py`` does.
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


# --- dry-run SQL snapshots (no wrangler) ------------------------------------

def test_seed_dry_run_emits_upsert_sql_without_invoking_wrangler(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(_MODULE.subprocess, "run", _forbid_subprocess)
    monkeypatch.setattr(_MODULE, "_now_iso", lambda: "2026-09-07T00:00:00+00:00")
    rc = _MODULE.main(["--action", "seed"])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("INSERT INTO padiem_engine_connector_grants")
    assert (
        "'b54-padiem-claw', 'agent:padiem:claw_mail_reader@1', "
        "'connector:google:gmail@1', 'bind:b54-padiem-claw:claw_mail_reader', "
        "'actor:b54-padiem-claw:claw_mail_reader', '[\"gmail.readonly\"]', 1, "
        "'2026-09-07T00:00:00+00:00', '2026-09-07T00:00:00+00:00'"
    ) in out
    assert "ON CONFLICT(app_id, connector_id) DO UPDATE SET active=1" in out
    assert "binding_ref=excluded.binding_ref, actor_ref=excluded.actor_ref" in out


def test_revoke_dry_run_emits_active_zero_sql_without_invoking_wrangler(
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
    assert out.startswith("SELECT app_id, canonical_agent_id, binding_ref, actor_ref, active")
    assert "FROM padiem_engine_connector_grants;" in out


# --- validation failures exit 2 and never reach D1 --------------------------

def _run_with_d1_probe(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> tuple[int, list[str]]:
    calls: list[str] = []

    def _probe_run_d1(_sql: str) -> int:
        calls.append(_sql)
        return 0

    monkeypatch.setattr(_MODULE, "run_d1", _probe_run_d1)
    return _MODULE.main(argv), calls


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


def test_invalid_scope_exits_2_with_zero_d1_calls(monkeypatch: pytest.MonkeyPatch) -> None:
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


# --- credential-bearing arguments are never accepted -----------------------

def test_credential_argument_is_rejected() -> None:
    with pytest.raises(SystemExit) as exc:
        _MODULE.main(["--action", "seed", "--client-secret", "do-not-print"])
    assert exc.value.code == 2


# --- execute mode shells through wrangler d1 with exact argv ---------------

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
