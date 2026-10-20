"""#4976 — the PC file search adapter and its result conversion.

The adapter reuses the existing local index through an injected port and
converts the matches into the existing file item contract, so a chosen file
can be handed to the existing read path. The fixture port below stands in for
the local index: it is a test double, not a second search engine.

The ES CLI path is verified through the **real** default runner with only the
subprocess boundary replaced, so the argv, the timeout contract, the output
encoding and the row parsing are all exercised as they run on a PC.

A search success here is an offline adapter proof. It is not a PC
connection, not an index build, and not an operational transition.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from kagent import pc_file_search_adapter as adapter
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
KOREAN_NAME = "한글 파일.txt"
SPACED_NAME = "공백 포함 이름.txt"


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
    _make_tree(root)
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


# --- the request limit and the truncation verdict -------------------------


def test_the_result_never_holds_more_than_the_requested_count(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    _make_tree(root)
    port = _FixtureIndexPort([
        str(root / "한글 파일.txt"), str(root / "공백 포함 이름.txt"),
        str(root / "nested" / "중첩 파일.txt"),
    ])

    result = search_pc_files(scope=_scope(root), query=QUERY, port=port, limit=2)

    assert result.status == SEARCH_OK
    assert len(result.entries) == 2
    # One row beyond the limit is requested, to learn whether more exist.
    assert port.calls[0]["limit"] == 3
    assert port.calls[0]["root"] == str(root)


def test_truncation_is_reported_only_when_more_results_exist(tmp_path: Path) -> None:
    """Exactly the requested number of results is not a truncated result."""
    root = tmp_path / "allowed"
    root.mkdir()
    _make_tree(root)
    port = _FixtureIndexPort([str(root / "한글 파일.txt")])

    result = search_pc_files(scope=_scope(root), query=QUERY, port=port, limit=1)

    assert result.status == SEARCH_OK
    assert len(result.entries) == 1
    assert result.truncated is False


def test_truncation_is_reported_when_the_probe_row_proves_more_exist(
    tmp_path: Path,
) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    _make_tree(root)
    port = _FixtureIndexPort([
        str(root / "한글 파일.txt"), str(root / "공백 포함 이름.txt"),
    ])

    result = search_pc_files(scope=_scope(root), query=QUERY, port=port, limit=1)

    assert result.status == SEARCH_OK
    assert len(result.entries) == 1
    assert result.truncated is True


def test_an_excluded_probe_row_still_reports_that_more_results_may_exist(
    tmp_path: Path,
) -> None:
    """An out-of-scope row does not make the result look complete."""
    root = tmp_path / "allowed"
    root.mkdir()
    _make_tree(root)
    outside = tmp_path / "other" / "다른 기기 파일.txt"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("다른 범위\n", encoding="utf-8")
    port = _FixtureIndexPort([str(root / "한글 파일.txt"), str(outside)])

    result = search_pc_files(scope=_scope(root), query=QUERY, port=port, limit=1)

    assert result.status == SEARCH_OK
    assert len(result.entries) == 1
    assert result.excluded_count == 1
    assert result.truncated is True


# --- the ES CLI port -------------------------------------------------------


def test_the_everything_port_reports_a_missing_installation(tmp_path: Path) -> None:
    port = EverythingEsCliSearchPort(executable=str(tmp_path / "no-es.exe"))
    status = port.status()
    assert status.installed is False
    assert status.index_ready is False


def test_the_everything_port_queries_the_existing_index(tmp_path: Path) -> None:
    executable = tmp_path / "es.exe"
    executable.write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    def runner(argv, *, timeout):
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
    # The literal form only holds while it is the last switch, so no later
    # switch can be swallowed as search text.
    assert argv.index("-search*") == len(argv) - 2


def test_the_everything_port_reports_a_failed_query(tmp_path: Path) -> None:
    executable = tmp_path / "es.exe"
    executable.write_text("", encoding="utf-8")

    def runner(argv, *, timeout):
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

    def runner(argv, *, timeout):
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

    def runner(argv, *, timeout):
        if "-get-everything-version" in argv:
            return 0, "1.4.3\n", ""
        return 7, "", "failed to send an Everything IPC query"

    port = EverythingEsCliSearchPort(executable=str(executable), runner=runner)
    result = search_pc_files(scope=_scope(root), query=QUERY, port=port)

    assert result.status == SEARCH_INDEX_NOT_READY
    assert result.ok is False
    assert result.entries == ()


# --- the official ES search-text form --------------------------------------


def test_a_double_quote_in_the_search_text_is_escaped_the_official_way() -> None:
    """The official syntax writes a literal double quote as a triple quote."""
    assert adapter.everything_search_argument('a"b') == 'a"""b'
    assert adapter.everything_search_argument("한글 파일") == "한글 파일"


def test_a_search_text_that_could_end_the_command_line_is_refused() -> None:
    for text in ("a\nb", "a\rb", "a\x00b"):
        with pytest.raises(PcFileSearchError):
            adapter.everything_search_argument(text)


def test_the_search_text_is_escaped_in_the_actual_argv(tmp_path: Path) -> None:
    executable = tmp_path / "es.exe"
    executable.write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    def runner(argv, *, timeout):
        calls.append(list(argv))
        if "-get-everything-version" in argv:
            return 0, "1.4.3\n", ""
        return 0, "", ""

    port = EverythingEsCliSearchPort(executable=str(executable), runner=runner)
    port.search(query='이름"따옴표', root=str(tmp_path), limit=5)

    argv = calls[0]
    assert argv[-1] == '이름"""따옴표'
    assert argv[-2] == "-search*"


# --- the default runner path (only the subprocess boundary is replaced) ----


def _es_executable(tmp_path: Path) -> Path:
    executable = tmp_path / "es.exe"
    executable.write_text("", encoding="utf-8")
    return executable


def test_the_default_runner_is_used_with_the_keyword_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default runner takes the timeout as a keyword, and it is given."""
    seen: list[dict] = []

    def fake_run(argv, **kwargs):
        seen.append({"argv": list(argv), **kwargs})
        if "-get-everything-version" in argv:
            return SimpleNamespace(returncode=0, stdout=b"1.4.3\n", stderr=b"")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(adapter.subprocess, "run", fake_run)
    port = EverythingEsCliSearchPort(executable=str(_es_executable(tmp_path)))
    status = port.status()

    assert status.installed is True
    assert status.index_ready is True
    assert seen, "the default runner must reach the subprocess boundary"
    assert seen[0]["argv"][1] == "-get-everything-version"
    assert seen[0]["timeout"] == port._timeout
    # The output is decoded explicitly, never through the host encoding.
    assert "text" not in seen[0]
    assert "encoding" not in seen[0]


def test_the_default_runner_decodes_utf8_and_keeps_a_korean_file_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Korean file name must survive the ES output boundary unchanged."""
    root = tmp_path / "allowed"
    root.mkdir()
    created = _make_tree(root)
    payload = (str(created["korean"]) + "\n").encode("utf-8")

    def fake_run(argv, **kwargs):
        if "-get-everything-version" in argv:
            return SimpleNamespace(returncode=0, stdout=b"1.4.3\n", stderr=b"")
        return SimpleNamespace(returncode=0, stdout=payload, stderr=b"")

    monkeypatch.setattr(adapter.subprocess, "run", fake_run)
    port = EverythingEsCliSearchPort(executable=str(_es_executable(tmp_path)))
    result = search_pc_files(scope=_scope(root), query=QUERY, port=port)

    assert result.status == SEARCH_OK
    assert [entry.relative_path for entry in result.entries] == ["한글 파일.txt"]
    assert result.entries[0].name == "한글 파일.txt"


def test_output_that_is_not_utf8_is_a_failure_and_not_a_mojibake_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A byte that is not UTF-8 must fail loudly, never become a name."""
    root = tmp_path / "allowed"
    root.mkdir()
    _make_tree(root)

    def fake_run(argv, **kwargs):
        if "-get-everything-version" in argv:
            return SimpleNamespace(returncode=0, stdout=b"1.4.3\n", stderr=b"")
        return SimpleNamespace(
            returncode=0, stdout=b"\xff\xfe bad bytes\n", stderr=b"",
        )

    monkeypatch.setattr(adapter.subprocess, "run", fake_run)
    port = EverythingEsCliSearchPort(executable=str(_es_executable(tmp_path)))
    result = search_pc_files(scope=_scope(root), query=QUERY, port=port)

    assert result.status == SEARCH_SEARCH_FAILED
    assert result.entries == ()


def test_the_default_runner_reports_a_missing_executable_as_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(argv, **kwargs):
        raise FileNotFoundError("no such file")

    monkeypatch.setattr(adapter.subprocess, "run", fake_run)
    port = EverythingEsCliSearchPort(executable=str(_es_executable(tmp_path)))
    status = port.status()

    assert status.installed is True
    assert status.index_ready is False
