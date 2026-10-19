"""#4976 — the PC file search adapter and its result conversion.

The adapter reuses the existing local index through an injected port and
converts the matches into the existing file item contract, so a chosen file
can be handed to the existing read path. The fixture port below stands in for
the local index: it is a test double, not a second search engine.

A search success here is an offline adapter proof. It is not a PC
connection, not an index build, and not an operational transition.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kagent.pc_file_search_adapter import (
    EverythingEsCliSearchPort,
    PcFileSearchError,
    PcFileSearchScope,
    PcFileSearcherStatus,
    SEARCH_INDEX_NOT_READY,
    SEARCH_NOT_INSTALLED,
    SEARCH_NO_RESULTS,
    SEARCH_OK,
    SEARCH_SEARCH_FAILED,
    search_pc_files,
)

DEVICE_ID = "pc-com2"
OTHER_DEVICE_ID = "pc-other"
QUERY = "한글 파일"


class _FixtureIndexPort:
    """A test double for the local index: it returns the rows it is given."""

    def __init__(self, rows, *, installed=True, index_ready=True, error=None):
        self._rows = list(rows)
        self._installed = installed
        self._index_ready = index_ready
        self._error = error
        self.calls: list[dict] = []

    def status(self) -> PcFileSearcherStatus:
        return PcFileSearcherStatus(
            installed=self._installed, index_ready=self._index_ready,
        )

    def search(self, *, query, root, limit):
        self.calls.append({"query": query, "root": root, "limit": limit})
        if self._error is not None:
            raise self._error
        return self._rows


def _scope(root: Path, *, device_id: str = DEVICE_ID) -> PcFileSearchScope:
    return PcFileSearchScope(
        root=str(root), device_id=device_id, local_device_id=DEVICE_ID,
    )


def _make_tree(root: Path) -> dict[str, Path]:
    """A temp folder with Korean and space-separated file names."""
    (root / "nested").mkdir(parents=True, exist_ok=True)
    created = {
        "korean": root / "한글 파일.txt",
        "spaces": root / "공백 포함 이름.txt",
        "nested": root / "nested" / "중첩 파일.txt",
    }
    for path in created.values():
        path.write_text("검색 대상 내용\n", encoding="utf-8")
    return created


def test_matches_are_converted_into_the_existing_file_item_contract(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    created = _make_tree(root)
    port = _FixtureIndexPort([str(created["korean"]), str(created["nested"])])

    result = search_pc_files(scope=_scope(root), query=QUERY, port=port)

    assert result.status == SEARCH_OK
    assert result.ok is True
    relative = sorted(entry.relative_path for entry in result.entries)
    assert relative == ["nested/중첩 파일.txt", "한글 파일.txt"]
    by_relative = {entry.relative_path: entry for entry in result.entries}
    entry = by_relative["한글 파일.txt"]
    assert entry.name == "한글 파일.txt"
    assert entry.is_directory is False
    assert entry.size_bytes == created["korean"].stat().st_size
    assert entry.modified_at is not None and entry.modified_at.endswith("Z")
    # The existing file item contract, with no body and no absolute path.
    safe = entry.safe_dict()
    assert safe["Name"] == "한글 파일.txt"
    assert safe["relative_path"] == "한글 파일.txt"
    assert safe["PSIsContainer"] is False
    assert "content" not in safe
    assert str(root) not in str(safe)
    # The envelope the existing file list already returns.
    envelope = result.safe_dict()
    assert envelope["ok"] is True
    assert envelope["search_status"] == SEARCH_OK
    assert len(envelope["entries"]) == 2


def test_a_chosen_file_is_handed_to_the_existing_read_path(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    created = _make_tree(root)
    port = _FixtureIndexPort([str(created["spaces"])])

    result = search_pc_files(scope=_scope(root), query=QUERY, port=port)
    entry = result.entries[0]

    assert entry.read_payload() == {
        "op": "read", "path": "공백 포함 이름.txt",
    }


def test_no_match_is_reported_as_no_results(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    _make_tree(root)
    port = _FixtureIndexPort([])

    result = search_pc_files(scope=_scope(root), query="없는 이름", port=port)

    assert result.status == SEARCH_NO_RESULTS
    assert result.ok is False
    assert result.entries == ()
    assert result.safe_dict()["ok"] is False


def test_a_missing_searcher_is_not_an_empty_result(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    port = _FixtureIndexPort([], installed=False, index_ready=False)

    result = search_pc_files(scope=_scope(root), query=QUERY, port=port)

    assert result.status == SEARCH_NOT_INSTALLED
    assert result.ok is False
    assert result.entries == ()


def test_an_unready_index_is_not_an_empty_result(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    port = _FixtureIndexPort([], installed=True, index_ready=False)

    result = search_pc_files(scope=_scope(root), query=QUERY, port=port)

    assert result.status == SEARCH_INDEX_NOT_READY
    assert result.ok is False
    assert result.entries == ()


def test_a_failing_search_is_reported_as_a_failure(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    port = _FixtureIndexPort([], error=PcFileSearchError("the local searcher failed"))

    result = search_pc_files(scope=_scope(root), query=QUERY, port=port)

    assert result.status == SEARCH_SEARCH_FAILED
    assert result.ok is False
    assert result.entries == ()


def test_a_result_outside_the_allowed_folder_is_never_returned(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    _make_tree(root)
    outside = tmp_path / "other" / "다른 기기 파일.txt"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("다른 범위\n", encoding="utf-8")

    port = _FixtureIndexPort([str(outside), str(root / "한글 파일.txt")])
    result = search_pc_files(scope=_scope(root), query=QUERY, port=port)

    assert result.status == SEARCH_OK
    assert [entry.relative_path for entry in result.entries] == ["한글 파일.txt"]
    assert result.excluded_count == 1
    assert str(outside) not in str(result.safe_dict())


def test_only_out_of_scope_results_are_not_a_correlated_hit(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "other" / "다른 기기 파일.txt"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("다른 범위\n", encoding="utf-8")

    port = _FixtureIndexPort([str(outside)])
    result = search_pc_files(scope=_scope(root), query=QUERY, port=port)

    assert result.status == SEARCH_NO_RESULTS
    assert result.entries == ()
    assert result.excluded_count == 1


def test_a_symlink_out_of_the_allowed_folder_is_excluded(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "other"
    outside.mkdir()
    (outside / "탈출 파일.txt").write_text("탈출\n", encoding="utf-8")
    link = root / "탈출 링크"
    try:
        os.symlink(outside / "탈출 파일.txt", link)
    except (OSError, NotImplementedError):
        pytest.skip("this host does not allow symlink creation")

    port = _FixtureIndexPort([str(link)])
    result = search_pc_files(scope=_scope(root), query=QUERY, port=port)

    assert result.entries == ()
    assert result.excluded_count == 1


def test_another_device_scope_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    with pytest.raises(PcFileSearchError):
        PcFileSearchScope(
            root=str(root), device_id=OTHER_DEVICE_ID, local_device_id=DEVICE_ID,
        )


def test_the_search_request_is_bounded_but_the_result_reports_truncation(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    _make_tree(root)
    port = _FixtureIndexPort([
        str(root / "한글 파일.txt"), str(root / "공백 포함 이름.txt"),
    ])

    result = search_pc_files(scope=_scope(root), query=QUERY, port=port, limit=1)

    assert result.status == SEARCH_OK
    assert result.truncated is True
    assert port.calls[0]["limit"] == 1
    assert port.calls[0]["root"] == str(root)


def test_the_everything_port_reports_a_missing_installation(tmp_path: Path) -> None:
    port = EverythingEsCliSearchPort(executable=str(tmp_path / "no-es.exe"))
    status = port.status()
    assert status.installed is False
    assert status.index_ready is False


def test_the_everything_port_queries_the_existing_index(tmp_path: Path) -> None:
    executable = tmp_path / "es.exe"
    executable.write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    def runner(argv, timeout):
        calls.append(list(argv))
        if "-get-everything-version" in argv:
            return 0, "1.4.3\n", ""
        return 0, str(tmp_path / "한글 파일.txt") + "\n", ""

    port = EverythingEsCliSearchPort(executable=str(executable), runner=runner)
    status = port.status()
    assert status.installed is True
    assert status.index_ready is True

    rows = port.search(query="한글", root=str(tmp_path), limit=10)
    assert rows == [str(tmp_path / "한글 파일.txt")]

    argv = calls[1]
    # The documented ES switches: the search stays inside the verified folder,
    # the request limit is passed on, and the query is a literal search text.
    assert "-path" in argv
    assert argv[argv.index("-path") + 1] == str(tmp_path)
    assert "-n" in argv
    assert argv[argv.index("-n") + 1] == "10"
    assert "-full-path" in argv
    assert "-timeout" in argv
    assert "-search*" in argv
    assert argv[-1] == "한글"


def test_the_everything_port_reports_a_failed_query(tmp_path: Path) -> None:
    executable = tmp_path / "es.exe"
    executable.write_text("", encoding="utf-8")

    def runner(argv, timeout):
        if "-get-everything-version" in argv:
            return 0, "1.4.3\n", ""
        return 1, "", "index error"

    port = EverythingEsCliSearchPort(executable=str(executable), runner=runner)
    assert port.status().index_ready is True
    with pytest.raises(PcFileSearchError):
        port.search(query="한글", root=str(tmp_path), limit=10)


def test_an_unreachable_everything_service_is_not_an_empty_result(tmp_path: Path) -> None:
    """ES exit code 8 (no Everything window) means the index cannot answer."""
    executable = tmp_path / "es.exe"
    executable.write_text("", encoding="utf-8")

    def runner(argv, timeout):
        return 8, "", "the Everything IPC window was not found"

    port = EverythingEsCliSearchPort(executable=str(executable), runner=runner)
    status = port.status()
    assert status.installed is True
    assert status.index_ready is False


def test_a_failed_index_query_is_reported_as_index_not_ready(tmp_path: Path) -> None:
    """ES exit code 7 (IPC query failed) is an unusable index, not a failure."""
    root = tmp_path / "allowed"
    root.mkdir()
    executable = tmp_path / "es.exe"
    executable.write_text("", encoding="utf-8")

    def runner(argv, timeout):
        if "-get-everything-version" in argv:
            return 0, "1.4.3\n", ""
        return 7, "", "failed to send an Everything IPC query"

    port = EverythingEsCliSearchPort(executable=str(executable), runner=runner)
    result = search_pc_files(scope=_scope(root), query=QUERY, port=port)

    assert result.status == SEARCH_INDEX_NOT_READY
    assert result.ok is False
    assert result.entries == ()
