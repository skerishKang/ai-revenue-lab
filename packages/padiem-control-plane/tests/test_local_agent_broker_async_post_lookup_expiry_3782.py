"""#3782 pre-Production async Engine P01 latency must not resurrect expired work.

Hermetic owner/Engine/SQLite data only. The per-runtime injected clock changes
*after* the asynchronous Engine/source read; real Worker defaults to UTC now.
No public device route, real human approval, desktop Input or Production wiring.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from test_local_agent_broker_async_engine_p01_3782 import (
    _prepared as prepared_engine,
)
from test_local_agent_broker_async_engine_p01_3782 import (
    _register as register_engine,
)
from test_local_agent_broker_async_engine_p01_3782 import (
    _take as take_engine,
)
from test_local_agent_broker_async_original_engine_source_3782 import (
    _bind as bind_original,
)
from test_local_agent_broker_async_original_engine_source_3782 import (
    _count as original_join_count,
)
from test_local_agent_broker_async_original_engine_source_3782 import (
    _prepared as prepared_original,
)
from test_local_agent_broker_browser_authenticated_take_3782 import NOW
from test_local_agent_broker_browser_control_take_3782 import taken_count
from test_local_agent_broker_browser_registration_3782 import registered_rows
from test_local_agent_broker_pending_browser_issue_3782 import (
    CURRENT,
    _commands,
    _issue,
    _rows,
    _setup,
)


def test_late_engine_approval_cannot_register_material_after_command_ttl():
    storage, broker, scope, material, source = prepared_engine()
    # The canonical Broker command expires at NOW + 120s. Engine read is
    # synthetically late, even though it returns the old approved P01.
    broker._browser_admission_clock = lambda: NOW + timedelta(seconds=180)
    with pytest.raises(ValueError):
        register_engine(broker, scope, material)
    assert source.calls == 1
    assert registered_rows(storage) == 0
    assert taken_count(storage) == 0


def test_late_engine_recheck_cannot_take_expired_p01_or_spend_cas():
    storage, broker, scope, material, source = prepared_engine()
    assert register_engine(broker, scope, material)["stored"] is True
    assert registered_rows(storage) == 1
    broker._browser_admission_clock = lambda: NOW + timedelta(seconds=80)
    with pytest.raises(ValueError):
        take_engine(broker, scope)
    assert source.calls == 2
    assert registered_rows(storage) == 1
    assert taken_count(storage) == 0
    # A second valid read before the actual expiry still takes once.
    broker._browser_admission_clock = lambda: NOW
    assert take_engine(broker, scope) == material
    assert taken_count(storage) == 1


def test_late_original_engine_d1_read_does_not_register_stale_join():
    storage, broker, scope, _material, _join, _receipt, _local, assoc, engine = (
        prepared_original()
    )
    broker._browser_admission_clock = lambda: NOW + timedelta(seconds=180)
    with pytest.raises(ValueError):
        bind_original(broker, scope)
    assert assoc.calls == 1
    assert len(engine.calls) == 1
    assert original_join_count(storage) == 0


def test_late_pending_ticket_lookup_does_not_issue_any_broker_command(tmp_path):
    _file, broker, source = _setup(tmp_path)
    broker._browser_admission_clock = lambda: CURRENT + timedelta(minutes=6)
    with pytest.raises(ValueError, match="not current"):
        _issue(broker)
    assert source.calls == 1
    assert _commands(broker) == ()
    assert _rows(broker) == []
