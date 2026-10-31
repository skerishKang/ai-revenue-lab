"""#4976 — the PC file search adapter and its result conversion.

The adapter reuses the existing local index through an injected port and
converts the matches into the existing file item contract, so a chosen file
can be handed to the existing read path. The fixture port below stands in for
the local index: it is a test double, not a second search engine.

The ES CLI path is verified through the **real** default runner with only the
subprocess boundary replaced, so the argv, the timeout contract, the requested
output code page, the output encoding, the version gate and the row parsing
are all exercised as they run on a PC.

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
    PcFileSearchUnsupported,
    SEARCH_INDEX_NOT_READY,
    SEARCH_NOT_INSTALLED,
    SEARCH_NO_RESULTS,
    SEARCH_OK,
    SEARCH_SEARCH_FAILED,
    SEARCH_UNSUPPORTED,
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
    assert status.supported is False
    assert status.index_ready is False


# --- the Everything version gate -------------------------------------------


def _versioned_runner(version_output: str, calls: list[list[str]], rows: list[str]):
    def runner(argv, *, timeout):
        calls.append(list(argv))
        if "-get-everything-version" in argv:
            return 0, version_output, ""
        return 0, "".join(row + "\n" for row in rows), ""

    return runner


def test_an_everything_older_than_15_is_unsupported_and_never_searched(
    tmp_path: Path,
) -> None:
    """1.4 has no character entities, so the literal search is not run."""
    root = tmp_path / "allowed"
    root.mkdir()
    _make_tree(root)
    executable = tmp_path / "es.exe"
    executable.write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    port = EverythingEsCliSearchPort(
        executable=str(executable),
        runner=_versioned_runner("1.4.1.1005\n", calls, [str(root / "한글 파일.txt")]),
    )
    status = port.status()
    assert status.installed is True
    assert status.supported is False
    assert status.index_ready is False

    result = search_pc_files(scope=_scope(root), query=QUERY, port=port)

    assert result.status == SEARCH_UNSUPPORTED
    assert result.ok is False
    assert result.entries == ()
    with pytest.raises(PcFileSearchUnsupported):
        port.search(query=QUERY, root=str(root), limit=5)
    assert all("-search*" not in call for call in calls)


def test_a_version_that_cannot_be_read_is_unsupported_and_never_searched(
    tmp_path: Path,
) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    executable = tmp_path / "es.exe"
    executable.write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    port = EverythingEsCliSearchPort(
        executable=str(executable),
        runner=_versioned_runner("not a version\n", calls, []),
    )
    result = search_pc_files(scope=_scope(root), query=QUERY, port=port)

    assert port.status().supported is False
    assert result.status == SEARCH_UNSUPPORTED
    assert all("-search*" not in call for call in calls)


def test_a_version_check_failure_is_unsupported_and_never_searched(
    tmp_path: Path,
) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    executable = tmp_path / "es.exe"
    executable.write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    def runner(argv, *, timeout):
        calls.append(list(argv))
        raise PcFileSearchError("the local searcher could not be executed")

    port = EverythingEsCliSearchPort(executable=str(executable), runner=runner)
    status = port.status()
    assert status.installed is True
    assert status.supported is False

    result = search_pc_files(scope=_scope(root), query=QUERY, port=port)

    assert result.status == SEARCH_UNSUPPORTED
    assert all("-search*" not in call for call in calls)


def test_the_everything_port_queries_the_existing_index(tmp_path: Path) -> None:
    executable = tmp_path / "es.exe"
    executable.write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    def runner(argv, *, timeout):
        calls.append(list(argv))
        if "-get-everything-version" in argv:
            return 0, "1.5.0.1391\n", ""
        return 0, str(tmp_path / "한글 파일.txt") + "\n", ""

    port = EverythingEsCliSearchPort(executable=str(executable), runner=runner)
    status = port.status()
    assert status.installed is True
    assert status.supported is True
    assert status.index_ready is True

    rows = port.search(query="한글", root=str(tmp_path), limit=10)
    assert rows == [str(tmp_path / "한글 파일.txt")]

    # The version probe precedes the query; the query is the last call.
    argv = calls[-1]
    # The documented ES switches: the search stays inside the verified folder,
    # the request limit is passed on, and the query is a literal search text.
    assert "-path" in argv
    assert argv[argv.index("-path") + 1] == str(tmp_path)
    assert "-n" in argv
    assert argv[argv.index("-n") + 1] == "10"
    assert "-full-path" in argv
    assert "-timeout" in argv
    # ES writes a pipe in its current code page; the adapter asks for UTF-8.
    assert "-code-page" in argv
    assert argv[argv.index("-code-page") + 1] == "65001"
    assert "-search*" in argv
    assert argv[-1] == adapter.everything_search_argument("한글") + " " + adapter._everything_exclusions(str(tmp_path))
    # The literal form only holds while it is the last switch, so no later
    # switch can be swallowed as search text.
    assert argv.index("-search*") == len(argv) - 2


def test_the_everything_port_reports_a_failed_query(tmp_path: Path) -> None:
    executable = tmp_path / "es.exe"
    executable.write_text("", encoding="utf-8")

    def runner(argv, *, timeout):
        if "-get-everything-version" in argv:
            return 0, "1.5.0\n", ""
        return 1, "", "index error"

    port = EverythingEsCliSearchPort(executable=str(executable), runner=runner)
    assert port.status().index_ready is True
    with pytest.raises(PcFileSearchError):
        port.search(query="한글", root=str(tmp_path), limit=10)


def test_an_unreachable_everything_service_is_unsupported_not_an_empty_result(
    tmp_path: Path,
) -> None:
    """ES exit code 8 (no Everything window) leaves the version unconfirmed.

    The searcher is never assumed to be usable: it is reported as unsupported
    and is not searched, rather than as an empty result.
    """
    executable = tmp_path / "es.exe"
    executable.write_text("", encoding="utf-8")

    def runner(argv, *, timeout):
        return 8, "", "the Everything IPC window was not found"

    port = EverythingEsCliSearchPort(executable=str(executable), runner=runner)
    status = port.status()
    assert status.installed is True
    # The version could not be confirmed, so it is not assumed to be usable.
    assert status.supported is False
    assert status.index_ready is False


def test_a_failed_index_query_is_reported_as_index_not_ready(tmp_path: Path) -> None:
    """ES exit code 7 (IPC query failed) is an unusable index, not a failure."""
    root = tmp_path / "allowed"
    root.mkdir()
    executable = tmp_path / "es.exe"
    executable.write_text("", encoding="utf-8")

    def runner(argv, *, timeout):
        if "-get-everything-version" in argv:
            return 0, "1.5.0\n", ""
        return 7, "", "failed to send an Everything IPC query"

    port = EverythingEsCliSearchPort(executable=str(executable), runner=runner)
    result = search_pc_files(scope=_scope(root), query=QUERY, port=port)

    assert result.status == SEARCH_INDEX_NOT_READY
    assert result.ok is False
    assert result.entries == ()


# --- the official ES search-text form --------------------------------------


def test_a_search_text_is_escaped_with_the_official_character_entities() -> None:
    """Every search-syntax character becomes its documented literal entity.

    The official entity terminator is a colon, not an HTML semicolon, and the
    entities are Everything 1.5 syntax. The ES CLI accepts both ``-search*``
    and ``-code-page`` in the same release.
    """
    assert adapter.everything_search_argument('a"b') == "a&quot:b"
    assert adapter.everything_search_argument("한글 파일") == "한글&sp:파일"
    assert (
        adapter.everything_search_argument(r'a b"c|d!e<f>g*h?i:j&k\l')
        == "a&sp:b&quot:c&vert:d&excl:e&lt:f&gt:g&#42:h&#63:i&#58:j&#38:k&#92:l"
    )
    assert adapter.everything_search_argument("탭\t문자") == "탭&#9:문자"


def test_the_escaped_search_text_needs_no_windows_argv_quoting() -> None:
    """The escaped text holds no space, tab or quote, so the argv stays literal.

    ``-search*`` copies the rest of the raw command line; if the escaping left
    a space or a quote, the Windows argument quoting would put those bytes
    into the search text and the literal form would no longer hold.
    """
    escaped = adapter.everything_search_argument('a b"c d\te')
    assert not any(character.isspace() or character == '"' for character in escaped)


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
            return 0, "1.5.0\n", ""
        return 0, "", ""

    port = EverythingEsCliSearchPort(executable=str(executable), runner=runner)
    port.search(query='이름"따옴표', root=str(tmp_path), limit=5)

    # The version probe is the first call; the query is the last one.
    argv = calls[-1]
    assert argv[-1] == adapter.everything_search_argument('이름"따옴표') + " " + adapter._everything_exclusions(str(tmp_path))
    assert argv[-2] == "-search*"
    # Piped output follows the requested code page, which is the one decoded
    # as UTF-8 above; without it the same Korean text would arrive as an ANSI
    # code page's bytes and fail (or worse, become a mojibake name).
    assert argv[argv.index("-code-page") + 1] == "65001"
    assert argv.index("-code-page") < argv.index("-search*")


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
            return SimpleNamespace(returncode=0, stdout=b"1.5.0\n", stderr=b"")
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
    seen: list[list[str]] = []

    def fake_run(argv, **kwargs):
        seen.append(list(argv))
        if "-get-everything-version" in argv:
            return SimpleNamespace(returncode=0, stdout=b"1.5.0\n", stderr=b"")
        return SimpleNamespace(returncode=0, stdout=payload, stderr=b"")

    monkeypatch.setattr(adapter.subprocess, "run", fake_run)
    port = EverythingEsCliSearchPort(executable=str(_es_executable(tmp_path)))
    result = search_pc_files(scope=_scope(root), query=QUERY, port=port)

    assert result.status == SEARCH_OK
    assert [entry.relative_path for entry in result.entries] == ["한글 파일.txt"]
    assert result.entries[0].name == "한글 파일.txt"
    # The decoding is correct because the same run asked ES for that code
    # page; the two halves are one contract, not two separate choices.
    assert seen[-1][seen[-1].index("-code-page") + 1] == str(
        adapter.EVERYTHING_OUTPUT_CODE_PAGE
    )
    assert adapter.EVERYTHING_OUTPUT_ENCODING == "utf-8"


def test_output_that_is_not_utf8_is_a_failure_and_not_a_mojibake_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A byte that is not UTF-8 must fail loudly, never become a name."""
    root = tmp_path / "allowed"
    root.mkdir()
    _make_tree(root)

    def fake_run(argv, **kwargs):
        if "-get-everything-version" in argv:
            return SimpleNamespace(returncode=0, stdout=b"1.5.0\n", stderr=b"")
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


def test_server_folder_label_is_preserved_for_multi_root_read(tmp_path):
    root = tmp_path / "drive"
    root.mkdir()
    file = root / "document.txt"
    file.write_text("x", encoding="utf8")
    scope = PcFileSearchScope(root=str(root), device_id=DEVICE_ID, local_device_id=DEVICE_ID, label="DriveOne", multiple_roots=True)
    result = search_pc_files(scope=scope, query="document", port=_FixtureIndexPort([str(file)]))
    assert result.entries[0].read_payload() == {"op": "read", "path": "DriveOne/document.txt"}


def test_single_root_read_keeps_existing_path(tmp_path):
    root = tmp_path / "drive"
    root.mkdir()
    file = root / "document.txt"
    file.write_text("x", encoding="utf8")
    scope = PcFileSearchScope(root=str(root), device_id=DEVICE_ID, local_device_id=DEVICE_ID, label="DriveOne")
    result = search_pc_files(scope=scope, query="document", port=_FixtureIndexPort([str(file)]))
    assert result.entries[0].read_payload() == {"op": "read", "path": "document.txt"}


@pytest.mark.parametrize("label", [None, "", ".", "..", "C:", "a/b", "a\\b", "a\n"])
def test_multi_root_rejects_invalid_label(tmp_path, label):
    with pytest.raises(PcFileSearchError):
        PcFileSearchScope(root=str(tmp_path), device_id=DEVICE_ID, local_device_id=DEVICE_ID, label=label, multiple_roots=True)


def test_excluded_directories_and_hidden_system_never_return(tmp_path, monkeypatch):
    root = tmp_path / "drive"
    files = [root / "Users" / "person" / "AppData" / "secret.txt",
             root / "Users" / "person" / ".ssh" / "private.txt",
             root / "hidden-system.txt", root / "ordinary.txt"]
    for file in files:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("x", encoding="utf8")
    real_stat = adapter.os.stat
    def stat_with_attributes(path, *args, **kwargs):
        info = real_stat(path, *args, **kwargs)
        if str(path).casefold() == str(files[2]).casefold():
            return SimpleNamespace(st_file_attributes=6, st_size=info.st_size, st_mtime=info.st_mtime)
        return info
    monkeypatch.setattr(adapter.os, "stat", stat_with_attributes)
    result = search_pc_files(scope=_scope(root), query="x", port=_FixtureIndexPort([str(p) for p in files]))
    assert [e.relative_path for e in result.entries] == ["ordinary.txt"]
    assert result.excluded_count == 3


def test_everything_query_applies_path_exclusion(tmp_path):
    exe = tmp_path / "es.exe"
    exe.write_text("", encoding="utf8")
    calls = []
    def runner(argv, *, timeout):
        calls.append(argv)
        return (0, "1.5.0" if "-get-everything-version" in argv else "", "")
    EverythingEsCliSearchPort(executable=str(exe), runner=runner).search(query="report", root=str(tmp_path), limit=5)
    assert calls[-1][-1] == "report " + adapter._everything_exclusions(str(tmp_path))
    for name in ("appdata", "windows", "programdata", "ssh", "git"):
        assert name in calls[-1][-1].lower()


def test_multi_root_pages_continue_without_duplicates(tmp_path):
    roots = [tmp_path / "one", tmp_path / "two"]
    labels = ["One", "Two"]
    rows = {}
    scopes = []
    for root, label in zip(roots, labels):
        root.mkdir()
        files = [root / "a.txt", root / "b.txt"]
        for file in files:
            file.write_text("x", encoding="utf8")
        rows[str(root)] = [str(f) for f in files]
        scopes.append(PcFileSearchScope(root=str(root), device_id=DEVICE_ID, local_device_id=DEVICE_ID, label=label, multiple_roots=True))
    class Port:
        def search_page(self, *, query, root, offset, limit, timeout):
            return rows[root][offset:offset + limit]
    all_paths, cursor = [], None
    for _ in range(8):
        page = adapter.search_pc_files_page(scopes=scopes, query="x", port=Port(), cursor=cursor, limit=1)
        all_paths.extend(item["read"]["path"] for item in page["entries"])
        if page["cursor"] is None:
            assert page["complete"] is False and page["reason"] == "index_unverified"
            break
        assert page["reason"] == "limit"
        cursor = page["cursor"]
    assert all_paths == ["One/a.txt", "One/b.txt", "Two/a.txt", "Two/b.txt"]
    assert len(set(all_paths)) == 4


def test_paged_timeout_preserves_complete_rows_and_cursor(tmp_path):
    root = tmp_path / "drive"
    root.mkdir()
    file = root / "ready.txt"
    file.write_text("x", encoding="utf8")
    scope = PcFileSearchScope(root=str(root), device_id=DEVICE_ID, local_device_id=DEVICE_ID, label="One", multiple_roots=True)
    class Port:
        def search_page(self, **kwargs):
            raise adapter.PcFileSearchTimeout([str(file)])
    page = adapter.search_pc_files_page(scopes=[scope], query="x", port=Port(), limit=2)
    assert page["complete"] is False and page["reason"] == "timeout"
    assert page["cursor"] == {"label": "One", "offset": 1}
    assert page["entries"][0]["read"]["path"] == "One/ready.txt"


def test_paged_result_rejects_excluded_matches(tmp_path):
    root = tmp_path / "drive"
    blocked = root / ".ssh" / "secret"
    blocked.parent.mkdir(parents=True)
    blocked.write_text("x", encoding="utf8")
    good = root / "good"
    good.write_text("x", encoding="utf8")
    scope = PcFileSearchScope(root=str(root), device_id=DEVICE_ID, local_device_id=DEVICE_ID, label="One", multiple_roots=True)
    class Port:
        def search_page(self, *, offset, **kwargs):
            return [str(blocked), str(good)][offset:]
    page = adapter.search_pc_files_page(scopes=[scope], query="x", port=Port(), limit=4)
    assert [x["read"]["path"] for x in page["entries"]] == ["One/good"]
    assert page["complete"] is True


def test_paged_es_uses_offset_and_fails_closed_on_old_version(tmp_path):
    executable = tmp_path / "es.exe"
    executable.write_text("", encoding="utf8")
    calls = []
    def runner(argv, *, timeout):
        calls.append(argv)
        return (0, "1.5.0" if "-get-everything-version" in argv else "", "")
    port = EverythingEsCliSearchPort(executable=str(executable), runner=runner)
    assert port.search_page(query="x", root=str(tmp_path), offset=7, limit=2, timeout=10) == []
    assert calls[-1][calls[-1].index("-offset") + 1] == "7"
    assert "-s" in calls[-1] and "!path:regex:" in calls[-1][-1]
    calls.clear()
    def old(argv, *, timeout):
        calls.append(argv)
        return 0, "1.4.1", ""
    port = EverythingEsCliSearchPort(executable=str(executable), runner=old)
    with pytest.raises(PcFileSearchUnsupported):
        port.search_page(query="x", root=str(tmp_path), offset=0, limit=1, timeout=10)
    assert all("-search*" not in call for call in calls)


def test_runner_timeout_keeps_only_complete_output_lines(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"], output=b"first\npartial")
    monkeypatch.setattr(adapter.subprocess, "run", timeout)
    with pytest.raises(adapter.PcFileSearchTimeout) as caught:
        adapter._default_process_runner(["fake"], timeout=0.1)
    assert caught.value.rows == ("first",)


def test_empty_timeout_is_not_success(tmp_path):
    scope = PcFileSearchScope(root=str(tmp_path), device_id=DEVICE_ID, local_device_id=DEVICE_ID, label="one", multiple_roots=True)
    class Port:
        def search_page(self, **kwargs):
            raise adapter.PcFileSearchTimeout()
    page = adapter.search_pc_files_page(scopes=[scope], query="x", port=Port())
    assert page["entries"] == [] and page["complete"] is False
    assert page["reason"] == "timeout" and page["cursor"] == {"label": "one", "offset": 0}
