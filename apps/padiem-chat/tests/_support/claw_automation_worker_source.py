"""#8061: shared Worker scheduled-source fixtures for Claw automation tests.

Moved verbatim from ``test_claw_automation_async_composition_seam.py`` so sibling
test modules no longer import a test file. Paths, values and assertions unchanged.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from _support.automation_seam_source import read_text
from _support.claw_automation import (
    MIGRATION_019_PATH,
    MIGRATION_PATH,
    NOW,
    RecordingHistoryStore,
    resolver,
)

_CHAT = Path(__file__).resolve().parents[2]


def _route_db():
    # FakeD1 already applies migration 050 and returns D1-shaped ``results``;
    # the durable automation store needs its own 018/019 schema on top.
    from test_4428_central_tier_routes_261019 import FakeD1

    db = FakeD1()
    for path in (MIGRATION_PATH, MIGRATION_019_PATH):
        db.conn.executescript(read_text(path))
    return db


class _IdentityBinding:
    async def resolve_active_tenant_membership(self, payload: dict[str, Any]):
        return {
            "ok": True,
            "membership": {
                "tenant_id": payload["tenant_id"],
                "canonical_subject_id": payload["canonical_subject_id"],
                "state": "active",
                "created_at": "2025-01-01T00:00:00+00:00",
                "role": "owner",
            },
        }


def _load_worker(monkeypatch: pytest.MonkeyPatch):
    workers_stub = types.ModuleType("workers")
    workers_stub.Request = object

    class _Response:
        def __init__(self, body="", *, status=200, headers=None):
            self.body = body
            self.status = status
            self.headers = dict(headers or {})

    class _WorkerEntrypoint:
        def __init__(self, env=None, ctx=None):
            self.env = env
            self.ctx = ctx

    workers_stub.Response = _Response
    workers_stub.WorkerEntrypoint = _WorkerEntrypoint
    monkeypatch.setitem(sys.modules, "workers", workers_stub)

    spec = importlib.util.spec_from_file_location(
        "padiem_chat_worker_route_proof", _CHAT / "worker.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def _worker_env(db) -> SimpleNamespace:
    from app.worker_config import (
        D1_BINDING_NAME,
        IDENTITY_AUTHORITY_SERVICE_BINDING_NAME,
    )

    return SimpleNamespace(**{
        D1_BINDING_NAME: db,
        IDENTITY_AUTHORITY_SERVICE_BINDING_NAME: _IdentityBinding(),
        "PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED": True,
    })


async def _run_worker_source(db, adapter, monkeypatch):
    module = _load_worker(monkeypatch)
    return await module.run_scheduled_automation_source(
        _worker_env(db),
        now=NOW,
        execution_ports=SimpleNamespace(
            adapter=adapter,
            owner_resolver=resolver(),
            history_store=RecordingHistoryStore(),
        ),
    )
