"""#6460: the one PowerShell search script and the signed scope ceiling.

No Mesh, Identity or PC is contacted here. The command is built exactly as the
route builds it, and the claim is verified with the real route helper.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest

from app import oracle_mesh_read_return_routes as routes
from app.claw_pc_search_command import (
    PC_SEARCH_MAX_LIMIT,
    PC_SEARCH_MAX_QUERY_CHARS,
    pc_search_command,
    pc_search_mode,
    pc_search_query,
)

ROOT = "C:/Users/limone/Documents/견적"
SECRET = "s" * 48


def test_query_and_mode_are_bounded():
    assert pc_search_query("  견적  ") == "견적"
    assert pc_search_query("장성군") == "장성군"
    for bad in ("", "   ", "x" * (PC_SEARCH_MAX_QUERY_CHARS + 1), "a\nb", "a\tb", None, 3):
        assert pc_search_query(bad) is None, bad
    assert pc_search_mode("name") == "name"
    assert pc_search_mode("content") == "content"
    for bad in ("files", "NAME", "", None, 1):
        assert pc_search_mode(bad) is None


def test_name_search_prefers_everything_and_never_opens_a_cloud_file():
    script = pc_search_command(root=ROOT, query="견적", mode="name")
    assert "\r" not in script
    # Everything first, with the approved root as the only path filter.
    assert "Get-Command es.exe" in script
    assert "-path $root -n ($limit+1) $query" in script
    # Fallback stays inside the root and matches the name as a substring.
    assert "Get-ChildItem -LiteralPath $root -Recurse -File" in script
    assert "IndexOf($query,[StringComparison]::OrdinalIgnoreCase)" in script
    # Offline (0x1000) and RecallOnDataAccess (0x400000) are reported, not read.
    assert "$offlineMask=4096 -bor 4194304" in script
    assert "'not_downloaded'" in script
    assert "$limit=" + str(PC_SEARCH_MAX_LIMIT) in script
    assert "[Console]::OutputEncoding" in script
    assert "ConvertTo-Json -Compress -Depth 5" in script


def test_content_search_uses_ripgrep_and_defers_office_documents():
    script = pc_search_command(root=ROOT, query="장성군", mode="content")
    assert "\r" not in script
    assert "Get-Command rg.exe" in script
    assert "--fixed-strings --max-count 1 -- $query $paths" in script
    # Office/PDF/HWPX match by name only in this stage.
    assert "'deferred'" in script
    for ext in (".docx", ".xlsx", ".pdf", ".hwpx"):
        assert "'" + ext + "'" in script
    # The scan is bounded and says so instead of running unbounded.
    assert "$scan=2000" in script
    assert "scan_truncated" in script
    # Without ripgrep the same search still runs, through the shell's own cmdlet.
    assert "Select-String -LiteralPath $f.FullName -SimpleMatch" in script


def test_root_and_query_are_single_quoted_literals():
    script = pc_search_command(
        root="C:/Users/O'Brien/Documents", query="it's", mode="name",
    )
    assert "$root='C:/Users/O''Brien/Documents'" in script
    assert "$query='it''s'" in script
    # The model text can never add a statement: a quote is doubled, not closed.
    assert "$query='it's'" not in script


def test_bad_shapes_are_refused_before_a_command_exists():
    with pytest.raises(ValueError):
        pc_search_command(root=ROOT, query="견적", mode="path")
    for limit in (0, PC_SEARCH_MAX_LIMIT + 1, True, 1.5):
        with pytest.raises(ValueError):
            pc_search_command(root=ROOT, query="견적", mode="name", limit=limit)
    with pytest.raises(ValueError):
        pc_search_command(root=ROOT, query="", mode="name")
    with pytest.raises(ValueError):
        pc_search_command(root="", query="견적", mode="name")


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


def test_a_stale_listing_claim_without_a_name_search_is_refused():
    stale = _claim(admitted="files_list", ops=["list"])
    _, error = routes._engine_pc_scope_claim(
        _request_for(stale), b'{"mode":"context"}', product="claw",
    )
    assert error is not None and error.status_code == 422


def test_a_name_search_cannot_ride_a_content_only_claim():
    # The ceiling names one operation; a claim that never offered name search
    # can not be widened by the dispatch's mode argument.
    only_content = _claim(
        admitted="files", requested="files",
        ops=["list", "read", "search_content"],
    )
    _, error = routes._engine_pc_scope_claim(
        _request_for(only_content), b'{"mode":"context"}', product="claw",
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
