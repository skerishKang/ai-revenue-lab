"""Shared pytest fixtures for Personal Edition tests.

The ``isolated_sys_modules`` fixture protects the test session from
module-identity drift.  Several tests re-import runtime/repository modules
to assert that importing opens no network connection.  Re-importing creates
fresh class objects (e.g. a new ``DatabaseError``); if those replace the
originals in ``sys.modules``, later tests that compare exception classes
across module boundaries (route ``except`` clauses vs. raised errors) break
in an order-dependent way.  This fixture snapshots ``sys.modules`` before the
test and restores the exact original module objects afterwards, so re-import
tests can never leak fresh class objects into the rest of the session.
"""

from __future__ import annotations

import sys

import pytest


@pytest.fixture
def isolated_sys_modules():
    """Snapshot ``sys.modules`` and restore it after the test.

    Modules added during the test are removed; modules that were present
    before the test are restored to their original objects.  This keeps
    class identity stable across the whole test session even when a test
    deletes and re-imports application modules.
    """
    snapshot = dict(sys.modules)
    yield
    for mod in list(sys.modules):
        if mod not in snapshot:
            del sys.modules[mod]
    sys.modules.update(snapshot)
