"""#3232 → #4489 — the sidebar Library entry and its project-file authority.

#3232 wired ``#filesNavButton`` into the existing Project UI and disabled it
unless project-file storage was provisioned. #4489 supersedes that routing: the
entry is now a real destination owned by ``static/library.js`` and stays
navigable for any signed-in owner, while every project-file read and open still
goes through the canonical #2319/#2342 authority.
2026-10-17 supersedes the signed-out part of that contract: the entry is no
longer inert for a visitor, because the owner decision is that every screen
stays browsable without a session. The data guard moved from ``disabled`` to
``loadFiles()``, which still issues no read when unauthenticated.

What this file still guarantees:

- SIGNED_OUT_FAIL_CLOSED: the entry is inert and issues zero project API calls.
- No new backend route, storage authority, upload or delete path is introduced.
- The #2319/#2342 request contracts in ``app.js`` are byte-for-byte preserved.
- ``library.js`` reads only the two canonical owner-scoped list endpoints and
  never fetches file bytes or a file detail route.
- Storage that is not provisioned disables the *listing*, never the navigation.
- A session flip drops the previous owner's rows before they can be re-rendered.

Behavior is proven with a Node harness executing the REAL app.js + library.js in
one vm context against a minimal DOM shim (same technique #3232 shipped with).

#8060 62차: 원문 read와 노드 하네스는 _support(web_files_sidebar_source)로
옮기고, 단언은 파싱 팩트·파싱 선택자·동작 스냅샷으로 확인한다(의미 약화 없음).
"""

from __future__ import annotations

from _support.web_files_sidebar_source import (  # noqa: E402
    app_seam_facts,
    backend_routes_facts,
    destination_facts,
    library_boundary_facts,
    library_css_facts,
    library_reader_facts,
    run_harness,
    sidebar_entry_facts,
    view_block_facts,
)


# ── markup and module wiring ────────────────────────────────────────────────


def test_sidebar_still_renders_the_library_entry() -> None:
    facts = sidebar_entry_facts()
    assert facts["has_id"] is True
    assert facts["locale_key"] is True
    # Owner decision: the entry stays reachable for a visitor. The data guard
    # lives in library.js (no read without a session), not in an inert button.
    assert facts["not_disabled"] is True
    assert facts["aria_current_false"] is True


def test_library_destination_is_wired_before_the_chat_surface() -> None:
    facts = destination_facts()
    for key in (
        "view_id", "tablist", "tabs", "band_order_ok", "css_link",
        "css_before_head_end", "app_before_library", "library_before_adapter",
    ):
        assert facts[key] is True


def test_library_view_is_gated_on_the_shared_surface_state() -> None:
    facts = library_css_facts()
    assert facts["missing_selectors"] == []
    # The chat column and composer are hidden here, exactly like Calendar and Claw.
    assert facts["important_display_none"] is True


def test_library_view_stacks_above_the_glass_portrait_decoration() -> None:
    facts = view_block_facts()
    # The glass theme paints a fixed decorative portrait at z-index 1 with
    # pointer-events disabled. An unpositioned destination renders its own
    # controls underneath it, so the view must be stacked above it.
    assert facts["position_relative"] is True
    assert facts["z_index_two"] is True


def test_library_entry_moves_out_of_app_js_into_the_module() -> None:
    facts = app_seam_facts()
    # The old gate that also required project-file storage is gone, so storage
    # provisioning can no longer make a signed-in owner's navigation inert.
    assert facts["legacy_tokens"] == []
    # app.js keeps only the narrow trusted seam, and it resolves the project from
    # the already-loaded owner list rather than from a caller-supplied object.
    for key in ("find_project", "open_dialog", "seam_guard"):
        assert facts[key] is True


def test_library_reads_only_canonical_owner_scoped_pages() -> None:
    facts = library_reader_facts()
    # One bounded, owner-scoped keyset read and nothing else.
    for key in ("owner_endpoint", "limit_param", "cursor_param"):
        assert facts[key] is True
    # The per-project fan-out is gone: the Library no longer walks projects one by one,
    # and an account's older history cannot be hidden behind a project cap again.
    assert facts["removed_tokens"] == []
    # No file detail, no bytes, no upload, no delete, no second authority.
    assert facts["forbidden_tokens"] == []
    assert facts["fetch_count"] == 1  # one shared page reader


def test_library_module_keeps_the_privacy_and_sink_boundaries() -> None:
    facts = library_boundary_facts()
    assert facts["forbidden_tokens"] == []
    assert facts["text_content"] is True
    # The repository's raw-text gates scan comments too, so the module names
    # none of those primitives anywhere and logs nothing.
    assert facts["no_console"] is True


def test_no_new_file_backend_routes_or_storage_in_app_js() -> None:
    facts = backend_routes_facts()
    assert facts["missing_templates"] == []
    assert facts["files_count"] == 3  # GET list, POST upload, DELETE (unchanged)
    # #6579: binaries go through the shared tus module; the retired direct
    # octet-stream POST must not come back to app.js.
    assert facts["upload_seam"] is True
    assert facts["forbidden_tokens"] == []
    assert facts["payload_builder"] is True
    assert facts["no_console"] is True


# ── behavioral proof via Node harness executing real app.js + library.js ────

_SIGNED_OUT_AUTH = {"ready": True, "authenticated": False, "user": None, "history_ready": False, "project_files_ready": False}
_SIGNED_IN_AUTH = {
    "ready": True,
    "authenticated": True,
    "user": {"name": "owner"},
    "history_ready": True,
    "project_files_ready": True,
}
_PROJECT_A = {"id": "pa", "name": "PA", "instructions": "", "created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-01T00:00:00Z"}
_PROJECT_B = {"id": "pb", "name": "PB", "instructions": "", "created_at": "2026-09-02T00:00:00Z", "updated_at": "2026-09-02T00:00:00Z"}
_FILE_A = {
    "id": "file_a",
    "project_id": "pa",
    "name": "A 소유 문서",
    "media_type": "text/plain",
    "content_chars": 12,
    "created_at": "2026-09-01T00:00:00Z",
    "updated_at": "2026-09-01T00:00:00Z",
}
_FILE_B = {
    "id": "file_b",
    "project_id": "pb",
    "name": "B 소유 문서",
    "media_type": "text/plain",
    "content_chars": 7,
    "created_at": "2026-09-02T00:00:00Z",
    "updated_at": "2026-09-02T00:00:00Z",
}
_SESSIONS = {
    "a": {"projects": [_PROJECT_A], "filesByProject": {"pa": [_FILE_A]}},
    "b": {"projects": [_PROJECT_B], "filesByProject": {"pb": [_FILE_B]}},
}


def test_signed_out_library_entry_is_fail_closed_and_issues_no_reads() -> None:
    run_harness("signed_out", _SIGNED_OUT_AUTH, _SESSIONS)


def test_missing_project_file_storage_stays_navigable_and_explains_itself() -> None:
    run_harness("storage_off", _SIGNED_IN_AUTH, _SESSIONS)


def test_signed_in_library_lists_real_files_and_opens_the_canonical_project() -> None:
    run_harness("with_files", _SIGNED_IN_AUTH, _SESSIONS)


def test_account_switch_drops_the_previous_owner_rows() -> None:
    run_harness("account_switch", _SIGNED_IN_AUTH, _SESSIONS)


def test_same_flag_account_switch_drops_stale_owner_rows_without_logout_event() -> None:
    run_harness("account_switch_same_flags", _SIGNED_IN_AUTH, _SESSIONS)


_FILE_A1 = {
    "id": "file_a1",
    "project_id": "pa",
    "name": "A 문서 최신",
    "media_type": "text/plain",
    "content_chars": 5,
    "created_at": "2026-09-03T00:00:00Z",
    "updated_at": "2026-09-03T00:00:00Z",
}
_FILE_A2 = {
    "id": "file_a2",
    "project_id": "pa",
    "name": "A 문서 중간",
    "media_type": "text/plain",
    "content_chars": 6,
    "created_at": "2026-09-02T00:00:00Z",
    "updated_at": "2026-09-02T00:00:00Z",
}
_FILE_A3 = {
    "id": "file_a3",
    "project_id": "pa",
    "name": "A 문서 이전",
    "media_type": "text/plain",
    "content_chars": 7,
    "created_at": "2026-09-01T00:00:00Z",
    "updated_at": "2026-09-01T00:00:00Z",
}
_PAGE_SESSIONS = {
    "a": {
        "projects": [_PROJECT_A],
        "files": [_FILE_A1, _FILE_A2, _FILE_A3],
        "filesByProject": {"pa": [_FILE_A1, _FILE_A2, _FILE_A3]},
    },
    "b": _SESSIONS["b"],
}


def test_empty_first_page_with_more_pending_is_never_an_empty_library() -> None:
    result = run_harness(
        "incomplete_empty", _SIGNED_IN_AUTH, _PAGE_SESSIONS, {"emptyFirstPage": True}
    )
    assert result["snapshot"]["hasMore"] is True
    assert result["snapshot"]["complete"] is False


def test_cursor_walk_reaches_the_oldest_file_exactly_once() -> None:
    result = run_harness("walk_to_end", _SIGNED_IN_AUTH, _PAGE_SESSIONS, {"pageCap": 1})
    snapshot = result["snapshot"]
    assert snapshot["complete"] is True
    assert snapshot["hasMore"] is False
    assert len(snapshot["fileRows"]) == 3
    assert len(set(snapshot["fileRows"])) == 3


def test_a_failed_page_never_reports_the_walk_as_finished() -> None:
    result = run_harness(
        "page_failure", _SIGNED_IN_AUTH, _PAGE_SESSIONS, {"pageCap": 1, "failAfterPages": 1}
    )
    snapshot = result["snapshot"]
    assert snapshot["complete"] is False
    assert snapshot["partial"] is True
    assert len(snapshot["fileRows"]) == 1


def test_successful_page_retry_clears_partial_warning_and_can_finish() -> None:
    result = run_harness(
        "page_failure_recovery", _SIGNED_IN_AUTH, _PAGE_SESSIONS,
        {"pageCap": 1, "failPageOnce": True},
    )
    snapshot = result["snapshot"]
    assert snapshot["complete"] is True
    assert snapshot["partial"] is False
    assert snapshot["hasMore"] is False
    assert len(snapshot["fileRows"]) == 3
    assert snapshot["ownerFileApiCalls"] == 4


def test_auth_session_events_clear_owner_rows_once_and_ignore_same_session() -> None:
    run_harness("auth_session_owner_events", _SIGNED_IN_AUTH, _SESSIONS)
