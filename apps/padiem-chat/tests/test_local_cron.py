"""The COM2 timer entry for the Worker's scheduled lane reports honestly.

Two CPython entries may ask for a tick: the loopback dev run
(``PADIEM_LOCAL_DEV=1``) and the COM2 parallel host
(``PADIEM_CHAT_CPYTHON_HOST=1``). The Worker's own ``scheduled()`` behaviour is
untouched by this module; it only decides how far a native tick could get.
"""
from __future__ import annotations

import pytest

from app.config import ConfigError
from app.local_cron import run_once


def _env(**overrides) -> dict[str, str]:
    base = {
        "PADIEM_LOCAL_DEV": "1",
        "PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED": "true",
    }
    base.update(overrides)
    return base


def _host_env(**overrides) -> dict[str, str]:
    base = {
        "PADIEM_CHAT_CPYTHON_HOST": "1",
        "PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED": "true",
    }
    base.update(overrides)
    return base


def test_disabled_gate_wins_before_anything_else():
    assert run_once({}).endswith("SKIPPED reason=automation_scheduler_disabled")


def test_the_local_flag_is_required_once_enabled():
    with pytest.raises(ConfigError):
        run_once(_env(PADIEM_LOCAL_DEV="0"))


def test_missing_identity_reports_not_configured_instead_of_pretending():
    assert run_once(_env()).endswith("NOT_CONFIGURED reason=identity_rpc_unbound")


def test_configured_identity_still_reports_the_missing_engine_lane():
    status = run_once(_env(
        PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN="https://identity.example",
        PADIEM_CHAT_LOCAL_IDENTITY_RPC_SECRET="local-service-secret-0123456789abcdef",
    ))
    assert status.endswith("NOT_CONFIGURED reason=p01_engine_transport_unbound")


def test_the_host_entry_reaches_the_same_gate_without_the_dev_flag():
    """The COM2 host entry used to be unreachable: it must not need LOCAL_DEV."""

    assert "PADIEM_LOCAL_DEV" not in _host_env()
    assert run_once(_host_env()).endswith("NOT_CONFIGURED reason=identity_rpc_unbound")


def test_the_host_entry_still_reports_the_missing_engine_lane():
    status = run_once(_host_env(
        PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN="https://identity.example",
        PADIEM_CHAT_LOCAL_IDENTITY_RPC_SECRET="local-service-secret-0123456789abcdef",
    ))
    assert status.endswith("NOT_CONFIGURED reason=p01_engine_transport_unbound")


def test_both_entries_at_once_is_refused():
    """Setting both flags would give the https host the loopback allowance."""

    with pytest.raises(ConfigError):
        run_once(_host_env(PADIEM_LOCAL_DEV="1"))


def test_a_typo_value_is_not_silently_treated_as_an_entry():
    with pytest.raises(ConfigError):
        run_once(_host_env(PADIEM_CHAT_CPYTHON_HOST="maybe"))
