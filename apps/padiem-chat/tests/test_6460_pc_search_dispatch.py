"""#6460: the one PowerShell search script and the signed scope ceiling.

No Mesh, Identity or PC is contacted here. The command is built exactly as the
route builds it, and the claim is verified with the real route helper.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from types import SimpleNamespace

import pytest

from app import oracle_mesh_read_return_routes as routes
from app.claw_pc_search_command import (
    PC_SEARCH_MAX_LIMIT,
    PC_SEARCH_MAX_OFFICE_FILES,
    PC_SEARCH_MAX_QUERY_CHARS,
    PC_SEARCH_OFFICE_PREFIX_BYTES,
    PC_SEARCH_PROGRESS_INTERVAL_SECONDS,
    PC_SEARCH_SCAN_MAX_FILES,
    PC_SEARCH_TIME_LIMIT_SECONDS,
    pc_search_command,
    pc_search_mode,
    pc_search_path,
    pc_search_query,
)

ROOT = "C:/Users/limone/Documents/견적"
SECRET = "s" * 48


def _carried_values(script: str) -> list[str]:
    """Every server value the script rebuilds from ASCII base64 (#7973/#7974)."""
    return [
        base64.b64decode(blob, validate=True).decode("utf-8")
        for blob in re.findall(r"FromBase64String\('([A-Za-z0-9+/=]+)'\)", script)
    ]


def test_query_and_mode_are_bounded():
    assert pc_search_query("  견적  ") == "견적"
    assert pc_search_query("장성군") == "장성군"
    for bad in ("", "   ", "x" * (PC_SEARCH_MAX_QUERY_CHARS + 1), "a\nb", "a\tb", None, 3):
        assert pc_search_query(bad) is None, bad
    assert pc_search_mode("name") == "name"
    assert pc_search_mode("content") == "content"
    for bad in ("files", "NAME", "", None, 1):
        assert pc_search_mode(bad) is None


ROOTS = [{"label": "문서", "path": ROOT}]
TWO_ROOTS = [
    {"label": "검토", "path": "C:/Users/limone/Documents/PADIEM-REVIEW"},
    {"label": "문서", "path": ROOT},
]


def test_name_search_prefers_everything_and_never_opens_a_cloud_file():
    script = pc_search_command(roots=ROOTS, query="견적", mode="name")
    assert "\r" not in script
    # Everything first, with each approved root as the only path filter.
    assert "Get-Command es.exe" in script
    assert "-path $r.path -n ($limit+1) $query" in script
    # Fallback stays inside a root and matches the name as a substring. #7974:
    # folders are results too, so the walk no longer narrows to -File.
    assert "Get-ChildItem -LiteralPath $r.path -Recurse -Force" in script
    assert "IndexOf($query,[StringComparison]::OrdinalIgnoreCase)" in script
    # Offline (0x1000) and RecallOnDataAccess (0x400000) are reported, not read.
    assert "$offlineMask=4096 -bor 4194304" in script
    assert "'not_downloaded'" in script
    assert "$limit=" + str(PC_SEARCH_MAX_LIMIT) in script
    assert "[Console]::OutputEncoding" in script
    assert "ConvertTo-Json -Compress -Depth 5" in script


def test_two_approved_roots_are_searched_one_after_the_other():
    script = pc_search_command(roots=TWO_ROOTS, query="견적", mode="name")
    carried = _carried_values(script)
    assert "검토" in carried and "C:/Users/limone/Documents/PADIEM-REVIEW" in carried
    assert "문서" in carried and ROOT in carried and "견적" in carried
    assert script.isascii(), "a Korean console code page must not be able to change the command"
    assert "foreach($r in $roots)" in script
    assert "$multi=($roots.Count -gt 1)" in script
    # Every root gets its own scan budget: a big first folder can never hide
    # the folders after it. The name-mode fallback walks with the same budget
    # (one counter per root), the content mode adds its own.
    assert script.count("$seen=0") == 2
    assert "$flags.scan=$true" in script


def test_content_search_uses_ripgrep_and_defers_office_documents():
    script = pc_search_command(roots=ROOTS, query="장성군", mode="content")
    assert "\r" not in script
    assert "Get-Command rg.exe" in script
    # -H keeps path:line:byte:text even when one chunk holds one file, and
    # --byte-offset is what a range read starts from.
    assert "rg.Source -H --no-heading --line-number --byte-offset" in script
    assert "--fixed-strings --max-count 1 -- $query $paths" in script
    # The scan is bounded and says so instead of running unbounded.
    assert "$scan=" + str(PC_SEARCH_SCAN_MAX_FILES) in script
    assert "scan_truncated" in script
    # Without ripgrep the same search still runs, through the shell's own cmdlet.
    assert "Select-String -LiteralPath $f.item.FullName -SimpleMatch" in script


def test_office_documents_are_read_by_the_reviewed_parser_child():
    script = pc_search_command(roots=ROOTS, query="프린터", mode="content")
    # The existing PC-side parser, not a new one: the reviewed child that
    # calls Core document_normalization over stdin.
    assert "Get-Command python" in script
    assert "-P -m kagent.document_parser_child" in script
    assert "ConvertTo-Json -Compress" in script and "@{name=$o.item.Name" in script
    for ext, media in (
        (".docx", "wordprocessingml.document"),
        (".xlsx", "spreadsheetml.sheet"),
        (".pdf", "application/pdf"),
        (".hwpx", "application/hwp+zip"),
    ):
        assert "'" + ext + "'" in script
        assert media in script
    # One prefix read per document, and the unread part is reported.
    assert "$prefix=[int64]" + str(PC_SEARCH_OFFICE_PREFIX_BYTES) in script
    assert "$partial=([int64]$o.item.Length -gt [int64]$len)" in script
    assert "'prefix_only'" in script
    assert "'extractor_unavailable'" in script
    assert "$maxOffice=" + str(PC_SEARCH_MAX_OFFICE_FILES) in script


def test_owner_root_and_query_reach_the_pc_as_exact_base64_values():
    script = pc_search_command(
        roots=[{"label": "O'Brien", "path": "C:/Users/O'Brien/Documents"}],
        query="it's", mode="name",
    )
    carried = _carried_values(script)
    assert "O'Brien" in carried
    assert "C:/Users/O'Brien/Documents" in carried
    assert "it's" in carried
    assert script.isascii()
    # The model text can never add a statement: no raw value is in the command.
    assert "O'Brien" not in script and "it's" not in script


def test_bad_shapes_are_refused_before_a_command_exists():
    with pytest.raises(ValueError):
        pc_search_command(roots=ROOTS, query="견적", mode="path")
    for limit in (0, PC_SEARCH_MAX_LIMIT + 1, True, 1.5):
        with pytest.raises(ValueError):
            pc_search_command(roots=ROOTS, query="견적", mode="name", limit=limit)
    with pytest.raises(ValueError):
        pc_search_command(roots=ROOTS, query="", mode="name")
    for roots in ([], [{"label": "", "path": ROOT}], [{"label": "a", "path": ""}],
                  [{"path": ROOT}], "C:/x", [{"label": "a", "path": "C:/x" + chr(10) + "y"}]):
        with pytest.raises(ValueError):
            pc_search_command(roots=roots, query="견적", mode="name")


def test_the_optional_folder_is_a_label_or_a_relative_folder():
    assert pc_search_path(None) == ""
    assert pc_search_path("") == ""
    assert pc_search_path(" . ") == ""
    assert pc_search_path("문서") == "문서"
    assert pc_search_path("문서/2026") == "문서/2026"
    assert pc_search_path(r"문서\2026") == "문서/2026"
    for bad in ("/abs", "C:/Windows", "C:notes", "a/../b", "a//b", "ab", 5):
        assert pc_search_path(bad) is None, bad


def test_search_needs_the_matching_scope_operation():
    assert routes._pc_files_claim_op("search", "name") == "search_name"
    assert routes._pc_files_claim_op("search", "content") == "search_content"
    assert routes._pc_files_claim_op("search", "files") is None
    assert routes._pc_files_claim_op("search", None) is None
    assert routes._pc_files_claim_op("list", None) == "list"
    assert routes._pc_files_claim_op("read", None) == "read"
    assert routes._pc_files_claim_op("unknown", None) is None


def _claim(*, admitted, ops, requested=None, product="claw"):
    return {
        "version": 1, "requested": requested or admitted, "admitted": admitted,
        "source": "declared", "ops": ops,
        "app_id": "b54-padiem-claw" if product == "claw" else "padiem-chat",
    }


def _request_for(claim, *, product="claw", raw=b'{"mode":"context"}'):
    encoded = json.dumps(claim, sort_keys=True, separators=(",", ":"))
    timestamp = "1762000000"
    proof = hmac.new(
        SECRET.encode(), timestamp.encode() + b"." + raw + b"." + encoded.encode(),
        hashlib.sha256,
    ).hexdigest()
    return SimpleNamespace(
        headers={
            "X-Claw-PC-Scope": encoded, "X-Claw-PC-Scope-Proof": proof,
            "X-Claw-Engine-Time": timestamp,
        },
        app=SimpleNamespace(state=SimpleNamespace(
            claw_engine_desktop_secret=SECRET,
        )),
    )


def test_signed_claim_accepts_the_search_operations():
    listing = _claim(admitted="files_list", ops=["list", "search_name"])
    parsed, error = routes._engine_pc_scope_claim(
        _request_for(listing), b'{"mode":"context"}', product="claw",
    )
    assert error is None and parsed == listing

    files = _claim(
        admitted="files", requested="files",
        ops=["list", "read", "search_name", "search_content"],
    )
    parsed, error = routes._engine_pc_scope_claim(
        _request_for(files), b'{"mode":"context"}', product="claw",
    )
    assert error is None and parsed == files


def test_a_legacy_claim_still_verifies_and_blocks_the_new_operation():
    # A claim minted before the search capability existed names a real subset
    # of its admitted scope; Chat accepts it (rolling deploy) and the dispatch
    # still refuses the operation that claim never offered.
    stale = _claim(admitted="files_list", ops=["list"])
    parsed, error = routes._engine_pc_scope_claim(
        _request_for(stale), b'{"mode":"context"}', product="claw",
    )
    assert error is None and parsed == stale
    assert routes._pc_files_claim_op("search", "name") not in parsed["ops"]
    assert routes._pc_files_claim_op("list", None) in parsed["ops"]


def test_a_claim_can_never_offer_more_than_its_scope():
    # files_list never offers a content search, whatever the ops list says.
    over = _claim(admitted="files_list", ops=["list", "search_content"])
    _, error = routes._engine_pc_scope_claim(
        _request_for(over), b'{"mode":"context"}', product="claw",
    )
    assert error is not None and error.status_code == 422
    # A duplicated op is a malformed ceiling, not a second grant.
    duplicated = _claim(admitted="files", requested="files", ops=["list", "list"])
    _, error = routes._engine_pc_scope_claim(
        _request_for(duplicated), b'{"mode":"context"}', product="claw",
    )
    assert error is not None and error.status_code == 422


def test_owner_search_sentences_reach_the_pc_file_tools():
    from app.claw_general_routes import _requested_natural_pc_files

    assert _requested_natural_pc_files("내 PC에서 '견적' 들어간 엑셀 찾아줘")
    assert _requested_natural_pc_files("내 PC에서 본문에 '장성군' 있는 문서 찾아줘")
    assert _requested_natural_pc_files("내 컴퓨터에서 xlsx 파일 검색해줘")
    # Not this lane: a drive inventory question, a backtick command, or a
    # sentence that never names the PC.
    assert not _requested_natural_pc_files("내 PC에 어떤 드라이브가 있어?")
    assert not _requested_natural_pc_files("내 PC에서 `hostname` 실행해줘")
    assert not _requested_natural_pc_files("본문에 '장성군' 있는 문서 찾아줘")


def test_recursive_search_absolute_inside_a_registered_drive_resolves_to_a_root():
    """#8048: the search route must accept the absolute folder Engine folds
    for a recursive search, and still refuse unregistered drives."""
    roots = [{"label": "C:", "path": "C:"}, {"label": "D:", "path": "D:"},
             {"label": "E:", "path": "E:"}, {"label": "G:", "path": "G:"}]
    resolved = routes._pc_files_search_roots(
        roots, "G:/Ddrive/BatangD/task/workdiary/worktrees")
    assert resolved == [{"label": "G:", "path": "G:/Ddrive/BatangD/task/workdiary/worktrees"}]
    assert routes._pc_files_search_roots(roots, "G:") == [{"label": "G:", "path": "G:"}]
    # A label/relative folder keeps the old behavior.
    assert routes._pc_files_search_roots(roots, "G:/Ddrive") == [
        {"label": "G:", "path": "G:/Ddrive"}]
    assert routes._pc_files_search_roots(roots, None) == roots
    # Unregistered drives stay refused.
    for outside in ("H:/outside", "Z:/secret"):
        assert routes._pc_files_search_roots(roots, outside) is None


def test_recursive_search_carries_a_wall_clock_bound_and_time_truncated_flag():
    """#8048: a recursive walk ends at its own 180 s bound with a partial
    result, never holding the executor until the silence bound cuts it."""
    script = pc_search_command(roots=ROOTS, query="견적", mode="name")
    # The stopwatch and the time check are in the walk loops.
    assert "$sw=[Diagnostics.Stopwatch]::StartNew()" in script
    assert "$timeLimit=" + str(PC_SEARCH_TIME_LIMIT_SECONDS) in script
    assert "if(Test-Time){ $flags.truncated=$true; break }" in script
    # The result carries the time flag so the caller can tell a partial walk
    # from a complete one.
    assert "time_truncated=$($flags.time)" in script
    assert "\r" not in script


def test_recursive_search_writes_a_progress_side_file_when_a_dispatch_id_is_named():
    """#8048: the walk keeps a side file fresh so the executor's silence clock
    reads a live search as activity, not as a dead PC."""
    dispatch_id = "dsp_" + "a" * 32
    script = pc_search_command(
        roots=ROOTS, query="견적", mode="name", dispatch_id=dispatch_id)
    assert "padiem_search_" + dispatch_id + ".progress" in script
    assert "Set-Content -LiteralPath $progressFile" in script
    # Without a dispatch id there is no side file — the walk is unchanged.
    bare = pc_search_command(roots=ROOTS, query="견적", mode="name")
    assert "$progressFile=$null" in bare
    assert "padiem_search_" not in bare


def test_recursive_search_progress_interval_is_bounded_and_positive():
    """#8048: the progress interval is a small positive number of seconds, so
    the side file is refreshed well inside the 60 s default silence bound."""
    assert 0 < PC_SEARCH_PROGRESS_INTERVAL_SECONDS <= 30


def test_search_script_ends_with_a_newline_for_the_console_lane():
    """#8048: the SYSTEM lane streams this script to ``powershell -command -``
    over stdin. Without a final newline the console never flushes the last
    statement (the JSON reply), so a small folder ended in a 210 s
    silent_timeout with a 17-byte result. The newline is load-bearing.
    """
    script = pc_search_command(roots=ROOTS, query="release", mode="name")
    assert script.endswith("\n")
    assert not script.endswith("\n\n")
    # The final statement is the JSON projection the parser needs.
    assert script.splitlines()[-1].strip().endswith("| ConvertTo-Json -Compress -Depth 5")
