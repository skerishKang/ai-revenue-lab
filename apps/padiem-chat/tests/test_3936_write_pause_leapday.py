"""Regression: WRITE pause upper bound must not crash on leap day (Feb 29).

The previous bound used ``now.replace(year=now.year + 1)``, which raises
``ValueError: day is out of range for month`` whenever ``now`` is Feb 29.
Freezing the clock to a leap day and calling ``commit`` must not raise.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from app.claw_web_xlsx_quote_write_pause_store import D1WebQuoteWritePauseStore
from app.claw_web_xlsx_quote_write_store import D1WebQuoteWriteReceiptStore

SEL = "sel_" + "a" * 32
ROW = {
    "selection_ref": SEL,
    "user_id": "u1",
    "workspace_id": "ws1",
    "run_id": "run1",
    "source_document_id": "doc_" + "b" * 32,
    "source_sha256": "c" * 64,
    "workcopy_document_id": "doc_" + "d" * 32,
    "edit_sha256": "e" * 64,
    "school_name": "School",
    "supply_amount": 100,
}


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2028, 2, 29, 12, 0, 0, tzinfo=timezone.utc)


class _NullD1:
    """D1 stub: commit's validation/bound checks run before any DB write."""

    def prepare(self, query):
        return self

    def bind(self, *args):
        return self

    async def run(self):
        return {}

    async def first(self):
        return None


@pytest.mark.asyncio
async def test_write_pause_commit_does_not_crash_on_leap_day(monkeypatch):
    import app.claw_web_xlsx_quote_write_pause_store as mod

    monkeypatch.setattr(mod, "datetime", FrozenDateTime)

    store = D1WebQuoteWritePauseStore(_NullD1())
    now = FrozenDateTime.now(timezone.utc)
    expires_at = (now + timedelta(minutes=5)).isoformat()

    # With the old ``now.replace(year=now.year + 1)`` this raises ValueError
    # on Feb 29. The corrected bound must not raise.
    result = await store.commit(ROW, pause_id="pause:" + "b" * 32,
                                continuation_ref="cont_" + "c" * 32,
                                expires_at=expires_at)
    assert result is False
