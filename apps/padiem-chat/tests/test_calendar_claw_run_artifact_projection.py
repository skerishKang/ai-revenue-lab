"""Focused tests for #2834 A2: claw-run artifact projection into Native Calendar.

Covers:
- Valid bounded {document_id, filename, media_type} projects as a 3-key dict.
- Missing / null / empty / malformed / extra-key artifacts fail closed (None)
  while the run itself still projects.
- Today + range include artifact; upcoming excludes claw runs (unchanged).
- Foreign / tenant workspace runs still omitted (owner-scope fail-closed).
- safe_dict JSON never leaks credentials, tokens, secrets, filesystem paths,
  storage keys, R2/provider identifiers, or D1 row ids.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import sys
from pathlib import Path
from typing import Any

CHAT_ROOT = Path(__file__).resolve().parents[1]
KAGENT_SRC = CHAT_ROOT.parent / "korean-ai-code-agent" / "src"
for candidate in (str(CHAT_ROOT), str(KAGENT_SRC)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.calendar_contracts import CalendarItemProjection
from app.calendar_projection import (
    build_range_projection,
    build_today_projection,
    build_upcoming_projection,
    project_claw_run,
)
from app.calendar_store import InMemoryCalendarStore

DOC_ID = "doc_0123456789abcdef0123456789abcdef"
NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
USER = "usr_alice"
OWNER_WS = f"owner:{USER}"


class FakeHistoryStore:
    def __init__(self) -> None:
        self.claw_runs: dict[str, list[dict[str, Any]]] = {}

    async def list_recent_claw_runs(
        self, user_id: str, limit: int = 30
    ) -> list[dict[str, Any]]:
        return list(self.claw_runs.get(user_id, []))[:limit]


def _run(
    run_id: str = "run_a1",
    artifact: Any = "__omit__",
    **extra: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "run_id": run_id,
        "title": "Artifact Run",
        "status": "success",
        "result_summary": "Done",
        "created_at": "2026-09-20T10:00:00Z",
        "updated_at": "2026-09-20T10:00:00Z",
    }
    if artifact != "__omit__":
        row["artifact"] = artifact
    row.update(extra)
    return row


def _valid_artifact(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "document_id": DOC_ID,
        "filename": "report.docx",
        "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    base.update(overrides)
    return base


def _find_run_item(items: list[dict[str, Any]], run_id: str) -> dict[str, Any] | None:
    for item in items:
        if item.get("source_ref") == f"claw_run:{run_id}":
            return item
    return None


async def _today(history: FakeHistoryStore) -> dict[str, Any]:
    return await build_today_projection(
        workspace_id=OWNER_WS,
        tz_name="UTC",
        calendar_store=InMemoryCalendarStore(),
        history_store=history,
        user_id=USER,
        now_utc=NOW,
    )


def test_valid_artifact_projects_bounded_3_key_dict() -> None:
    proj = project_claw_run(_run(artifact=_valid_artifact()), OWNER_WS, tz=None)
    assert proj.artifact == {
        "document_id": DOC_ID,
        "filename": "report.docx",
        "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    assert set(proj.artifact) == {"document_id", "filename", "media_type"}
    assert proj.source_ref == "claw_run:run_a1"
    assert proj.workspace_id == OWNER_WS
    assert proj.title == "Artifact Run"
    assert proj.date == "2026-09-20"


def test_missing_artifact_key_projects_run_with_none() -> None:
    proj = project_claw_run(_run(), OWNER_WS, tz=None)
    assert proj.artifact is None
    assert proj.calendar_item_id == "item_run_run_a1"


def test_null_and_empty_artifact_fail_closed() -> None:
    for bad in (None, {}, []):
        proj = project_claw_run(_run(artifact=bad), OWNER_WS, tz=None)
        assert proj.artifact is None, f"artifact={bad!r} must fail closed"
        assert proj.source_ref == "claw_run:run_a1"


def test_non_dict_artifact_fail_closed() -> None:
    for bad in ("doc_x", 123, True, ("doc_x",)):
        proj = project_claw_run(_run(artifact=bad), OWNER_WS, tz=None)
        assert proj.artifact is None, f"artifact={bad!r} must fail closed"
        assert proj.source_ref == "claw_run:run_a1"


def test_malformed_document_id_fail_closed() -> None:
    malformed_ids = (
        "",
        "doc_short",
        "doc_" + "a" * 31,
        "doc_" + "a" * 33,
        "DOC_" + "a" * 32,
        "document_" + "a" * 32,
        "doc_" + "!" * 32,
        "doc_" + "a" * 16 + "-" + "b" * 15,
        DOC_ID[4:],
    )
    for bad_id in malformed_ids:
        proj = project_claw_run(
            _run(artifact=_valid_artifact(document_id=bad_id)),
            OWNER_WS,
            tz=None,
        )
        assert proj.artifact is None, f"document_id={bad_id!r} must fail closed"
        assert proj.source_ref == "claw_run:run_a1"


def test_missing_or_empty_value_or_non_string_fail_closed() -> None:
    cases = [
        _valid_artifact(filename=""),
        _valid_artifact(media_type=""),
        _valid_artifact(document_id=None),
        _valid_artifact(filename=None),
        _valid_artifact(filename=123),
        {"document_id": DOC_ID},
        {"document_id": DOC_ID, "filename": "report.docx"},
    ]
    for bad in cases:
        proj = project_claw_run(_run(artifact=bad), OWNER_WS, tz=None)
        assert proj.artifact is None, f"artifact={bad!r} must fail closed"
        assert proj.source_ref == "claw_run:run_a1"


def test_extra_keys_fail_closed_whitelist_only() -> None:
    extra = {
        **_valid_artifact(),
        "credential": "super-secret",
        "storage_key": "r2://bucket/secret",
        "path": "C:\\Users\\secret\\file.docx",
    }
    proj = project_claw_run(_run(artifact=extra), OWNER_WS, tz=None)
    assert proj.artifact is None
    assert proj.source_ref == "claw_run:run_a1"

    missing_one = {
        "document_id": DOC_ID,
        "filename": "report.docx",
    }
    proj2 = project_claw_run(_run(artifact=missing_one), OWNER_WS, tz=None)
    assert proj2.artifact is None


def test_safe_dict_json_leaks_no_secret_fields() -> None:
    hostile = {
        **_valid_artifact(),
        "credential": "credential://leak",
        "token": "tok_abcdef",
        "secret": "hunter2",
        "storage_key": "r2://leak/key",
        "r2_key": "obj/leak",
        "provider": "google",
        "d1_row_id": "row_42",
        "path": "/var/lib/leak.docx",
    }
    proj = project_claw_run(_run(artifact=hostile), OWNER_WS, tz=None)
    assert proj.artifact is None
    payload = json.dumps(proj.safe_dict(), ensure_ascii=False)
    for needle in (
        "credential://leak",
        "tok_abcdef",
        "hunter2",
        "r2://leak",
        "obj/leak",
        "row_42",
        "/var/lib/leak.docx",
        "google",
    ):
        assert needle not in payload, f"leaked {needle!r}"

    good = json.dumps(project_claw_run(_run(), OWNER_WS, tz=None).safe_dict())
    for needle in ("token", "secret", "storage_key", "d1_row_id", "credential"):
        assert needle not in good


def test_other_item_types_default_artifact_none() -> None:
    for kwargs in (
        {},
        {"artifact": None},
    ):
        item = CalendarItemProjection(
            calendar_item_id="item_x",
            workspace_id=OWNER_WS,
            item_type="task",
            title="T",
            summary=None,
            date="2026-09-20",
            start_at=None,
            end_at=None,
            timezone=None,
            all_day=False,
            source_type="task",
            source_ref="task:1",
            created_at="2026-09-20T00:00:00Z",
            updated_at="2026-09-20T00:00:00Z",
            **kwargs,
        )
        assert item.artifact is None
        assert item.safe_dict()["artifact"] is None


async def test_today_projection_includes_artifact() -> None:
    history = FakeHistoryStore()
    history.claw_runs[USER] = [_run(artifact=_valid_artifact())]
    res = await _today(history)
    item = _find_run_item(res["items"], "run_a1")
    assert item is not None, "claw run missing from today projection"
    assert item["artifact"] == {
        "document_id": DOC_ID,
        "filename": "report.docx",
        "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    assert item["source_ref"] == "claw_run:run_a1"
    assert item["date"] == "2026-09-20"


async def test_today_projection_missing_artifact_still_projects_run() -> None:
    history = FakeHistoryStore()
    history.claw_runs[USER] = [_run()]
    res = await _today(history)
    item = _find_run_item(res["items"], "run_a1")
    assert item is not None
    assert item["artifact"] is None


async def test_today_projection_malformed_artifact_fails_closed() -> None:
    history = FakeHistoryStore()
    history.claw_runs[USER] = [
        _run(artifact=_valid_artifact(document_id="not-a-doc-id")),
        _run(run_id="run_ok", artifact=_valid_artifact()),
    ]
    res = await _today(history)
    bad = _find_run_item(res["items"], "run_a1")
    good = _find_run_item(res["items"], "run_ok")
    assert bad is not None and bad["artifact"] is None
    assert good is not None and good["artifact"]["document_id"] == DOC_ID


async def test_range_projection_includes_artifact() -> None:
    history = FakeHistoryStore()
    history.claw_runs[USER] = [_run(artifact=_valid_artifact())]
    res = await build_range_projection(
        workspace_id=OWNER_WS,
        start_date=datetime(2026, 9, 20).date(),
        end_date=datetime(2026, 9, 20).date(),
        tz_name="UTC",
        calendar_store=InMemoryCalendarStore(),
        history_store=history,
        user_id=USER,
    )
    item = _find_run_item(res["items"], "run_a1")
    assert item is not None
    assert item["artifact"] == {
        "document_id": DOC_ID,
        "filename": "report.docx",
        "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }


async def test_upcoming_excludes_claw_runs_semantics_unchanged() -> None:
    history = FakeHistoryStore()
    history.claw_runs[USER] = [_run()]
    res = await build_upcoming_projection(
        workspace_id=OWNER_WS,
        tz_name="UTC",
        calendar_store=InMemoryCalendarStore(),
        user_id=USER,
        now_utc=NOW,
    )
    item_types = {item["item_type"] for item in res["items"]}
    assert "claw_run" not in item_types
    assert _find_run_item(res["items"], "run_a1") is None


async def test_tenant_and_foreign_workspace_runs_still_omitted() -> None:
    history = FakeHistoryStore()
    history.claw_runs[USER] = [_run()]

    tenant = await build_today_projection(
        workspace_id="tenant_canonical_corp_123",
        tz_name="UTC",
        calendar_store=InMemoryCalendarStore(),
        history_store=history,
        user_id=USER,
        now_utc=NOW,
    )
    assert _find_run_item(tenant["items"], "run_a1") is None

    foreign = await build_today_projection(
        workspace_id="owner:usr_bob",
        tz_name="UTC",
        calendar_store=InMemoryCalendarStore(),
        history_store=history,
        user_id="usr_bob",
        now_utc=NOW,
    )
    assert _find_run_item(foreign["items"], "run_a1") is None


async def test_today_projection_json_never_leaks_secret_needles() -> None:
    history = FakeHistoryStore()
    history.claw_runs[USER] = [
        _run(
            artifact={
                **_valid_artifact(),
                "credential": "credential://leak",
                "storage_key": "r2://leak/key",
            }
        )
    ]
    res = await _today(history)
    payload = json.dumps(res, ensure_ascii=False)
    for needle in ("credential://leak", "r2://leak", "storage_key", "credential"):
        assert needle not in payload
