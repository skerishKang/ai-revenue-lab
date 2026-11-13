"""#7603: two PC tools an external connector needs and the write lane lacked.

  * ``pc_write`` gains one optional argument, ``mode``: ``"overwrite"`` (the
    behavior it always had) and ``"append"`` (keep every existing byte, add the
    caller's bytes at the end, no newline invented). No ``mode`` is the old call
    byte for byte, on the wire and in the command.
  * ``pc_mkdir`` creates one folder, parents included. An existing folder is a
    no-change success; a file of the same name is the one refusal.

Both are the *write* lane, not a new one: the same scope ceiling, the same
approval question, the same backup rule and the same one-line account. What
these tests hold:

  * the command bodies say exactly that, and no caller text is ever interpolated
    into a command line;
  * an approval obtained for an overwrite cannot run an append, because the
    request digest covers every argument including the mode;
  * no path reaches a PC for ``pc_mkdir`` or an append without approval, on the
    external-connector route, the Chat engine route, or the batch wrapper;
  * the scope ceiling classifies both as write authority, so a read-only
    admission cannot reach either.
"""
from __future__ import annotations

import base64
import hashlib
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from app.oracle_mesh_read_return_routes import (  # noqa: E402
    PC_BACKUP_FOLDER,
    PC_WRITE_ACCOUNT_PREFIX,
    _PC_WRITE_OPS,
    _pc_backup_dir,
    _pc_write_command,
)

BS = chr(92)
BACKUP_DIR = "C:" + BS + PC_BACKUP_FOLDER + BS + "2026-11-09"


def _command(op, *, target, relative, content=None, append=False, destination=None):
    return _pc_write_command(
        op=op,
        root=target[:3] + BS,
        target=target,
        backup_dir=BACKUP_DIR,
        relative=relative,
        destination=destination,
        content_b64=(
            base64.b64encode(content.encode("utf-8")).decode("ascii")
            if content is not None else None
        ),
        append=append,
    )


# --- the command the server builds ------------------------------------------


def test_append_backs_up_first_and_adds_bytes_at_the_end():
    target = "C:" + BS + "docs" + BS + "log.txt"
    command = _command("write", target=target, relative="docs/log.txt",
                       content="둘째 줄", append=True)
    backup = command.index("Copy-Item -LiteralPath $source_to_keep -Destination $backup")
    written = command.index("[IO.File]::WriteAllBytes")
    assert backup < written, "an append must copy the original before it changes it"
    # Every existing byte stays; only the caller's bytes are added, and nothing
    # here invents a newline between them.
    assert "$payload = [byte[]]($before + $payload)" in command
    assert "$payload = $payload + " not in command
    assert (BS + "r" + BS + "n") not in command
    assert "Move-Item -LiteralPath $temp -Destination $target -Force" in command
    assert "throw 'padiem target missing'" not in command, "a missing file is created"


def test_append_refuses_a_file_that_is_not_utf8_before_touching_it():
    target = "C:" + BS + "docs" + BS + "ansi.txt"
    command = _command("write", target=target, relative="docs/ansi.txt",
                       content="x", append=True)
    guard = command.index("New-Object Text.UTF8Encoding($false, $true)")
    written = command.index("[IO.File]::WriteAllBytes")
    assert "edit_encoding_unsupported" in command
    # The round trip is settled on the bytes read from the file, so a refusal
    # happens before the temp file is written and the original stays as it was.
    assert guard < written


def test_overwrite_stays_the_command_it_always_was():
    target = "C:" + BS + "docs" + BS + "note.txt"
    plain = _command("write", target=target, relative="docs/note.txt", content="hi")
    explicit = _command("write", target=target, relative="docs/note.txt", content="hi",
                        append=False)
    assert plain == explicit
    assert "$before" not in plain
    assert "$appendLength" not in plain
    assert "append_bytes" not in plain


def test_append_carries_its_own_observed_tail():
    target = "C:" + BS + "docs" + BS + "log.txt"
    command = _command("write", target=target, relative="docs/log.txt", content="x",
                       append=True)
    # The whole-file digest cannot equal the added bytes once the file was not
    # empty, so the append command reads back the tail of the length it added.
    assert "$appendLength = $payload.Length" in command
    assert "$verification['append_bytes'] = $tailBytes" in command
    assert "$verification['append_sha256'] = $tailSha256" in command


def test_mkdir_creates_parents_and_refuses_only_a_name_that_is_a_file():
    target = "C:" + BS + "docs" + BS + "new" + BS + "deep"
    command = _command("mkdir", target=target, relative="docs/new/deep")
    assert "Test-Path -LiteralPath $target -PathType Leaf" in command
    assert "$reason = 'target_exists'" in command
    assert "New-Item -ItemType Directory -Force -Path $target" in command
    # No original to keep, so no backup is taken and nothing is copied.
    assert "Copy-Item" not in command
    assert "$payload" not in command
    assert "mkdir" in _PC_WRITE_OPS and "write" in _PC_WRITE_OPS


def test_no_caller_text_reaches_a_command_line():
    hostile = "a'; Remove-Item -Recurse C:" + BS + "; ` $(Get-Process) 'x.txt"
    target = "C:" + BS + "docs" + BS + hostile
    for op, extra in (("write", {"content": hostile, "append": True}),
                      ("mkdir", {})):
        relative = "docs/" + hostile
        command = _command(op, target=target, relative=relative, **extra)
        # The path travels as one single-quoted PowerShell literal with its own
        # quotes doubled, and the content only as a base64 variable. Nothing in
        # the caller's text is ever concatenated outside such a literal.
        assert "'" + target.replace("'", "''") + "'" in command
        if op == "write":
            # The backup name is built from the same literal, and the bytes
            # travel only as base64.
            assert "'" + relative.replace("'", "''") + "'" in command
            assert base64.b64encode(hostile.encode("utf-8")).decode("ascii") in command
        else:
            assert "/" not in command.split("$target = ")[1].split(";")[0]
        assert chr(10) not in command and chr(13) not in command


# --- the wire contract ------------------------------------------------------


def _gateway(tool_id, arguments):
    return {"version": 1, "source": "mcp", "token_id": "mcp_token_fixture",
            "request_id": "mcp_request_fixture", "tool_id": tool_id,
            "arguments": arguments}


def test_an_unknown_write_mode_is_refused_at_the_parser_not_the_pc():
    from kagent.pc_query_adapter import pc_file_arguments_acceptable
    from padiem_ai_core.pc_gateway import parse_pc_gateway
    from padiem_ai_engine_client.client import _parse_pc_gateway

    for bad in ("prepend", "APPEND", "", True, 1, None):
        value = _gateway("claw.pc.write_file",
                         {"path": "notes.txt", "content": "x", "mode": bad})
        for parser in (parse_pc_gateway, _parse_pc_gateway):
            with pytest.raises(ValueError):
                parser(value)
        assert pc_file_arguments_acceptable(
            "claw.pc.write_file", {"path": "notes.txt", "content": "x", "mode": bad},
        ) is False
    for good in ("overwrite", "append"):
        value = _gateway("claw.pc.write_file",
                         {"path": "notes.txt", "content": "x", "mode": good})
        assert parse_pc_gateway(value) == _parse_pc_gateway(value)
        assert pc_file_arguments_acceptable(
            "claw.pc.write_file", {"path": "notes.txt", "content": "x", "mode": good},
        ) is True


def test_an_overwrite_approval_cannot_run_an_append():
    from app.mcp_gateway_store import mcp_request_digest

    overwrite = mcp_request_digest("pc_write", {"path": "notes.txt", "content": "x"})
    explicit = mcp_request_digest("pc_write",
                                 {"path": "notes.txt", "content": "x", "mode": "overwrite"})
    append = mcp_request_digest("pc_write",
                               {"path": "notes.txt", "content": "x", "mode": "append"})
    same_bytes = mcp_request_digest("pc_write",
                                   {"path": "notes.txt", "content": "x", "mode": "append"})
    assert append != overwrite and append != explicit
    assert append == same_bytes, "the same append must reuse one digest"
    # pc_mkdir is its own tool name, so no write approval can cover it either.
    assert mcp_request_digest("pc_mkdir", {"path": "new"}) not in {overwrite, append}


def test_mkdir_declares_the_write_lane_everywhere_it_is_classified():
    from app.mcp_gateway_execution import _PC_FILE_PATH_TOOLS, _TOOLS
    from kagent.pc_query_adapter import (
        PC_FILE_TOOL_ARGUMENT_KEYS, PC_MKDIR_SCOPE, PC_MKDIR_TOOL_ID,
        PC_WRITE_FILE_SCOPE,
    )

    assert _TOOLS["pc_mkdir"] == ("files_write", "claw.pc.mkdir", {"path"})
    assert "pc_mkdir" in _PC_FILE_PATH_TOOLS
    # The same scope string the write tool uses: one authority, not a new one.
    assert PC_MKDIR_SCOPE == PC_WRITE_FILE_SCOPE
    assert PC_FILE_TOOL_ARGUMENT_KEYS[PC_MKDIR_TOOL_ID] == frozenset({"path"})


def test_the_scope_ceiling_puts_append_and_mkdir_under_write_authority():
    from kagent.pc_query_adapter import (
        PC_MKDIR_TOOL_ID, PC_REQUEST_SCOPE_TOOLS, PC_WRITE_FILE_TOOL_ID,
    )
    from kagent.pc_remote_tools import operation_actions

    write = PC_REQUEST_SCOPE_TOOLS["files_write"]
    read = PC_REQUEST_SCOPE_TOOLS["files"] | PC_REQUEST_SCOPE_TOOLS["files_list"]
    assert {PC_WRITE_FILE_TOOL_ID, PC_MKDIR_TOOL_ID} <= write
    assert not ({PC_WRITE_FILE_TOOL_ID, PC_MKDIR_TOOL_ID} & read)
    # The batch wrapper asks the same question per step: a read-only admission
    # cannot carry a write or a folder, so the whole batch is refused.
    assert all(tool in read for tool, _ in operation_actions(
        {"operations": [{"op": "list", "path": "."}]}, batch=True))
    assert not all(tool in read for tool, _ in operation_actions(
        {"operations": [{"op": "mkdir", "path": "new"}]}, batch=True))
    assert not all(tool in read for tool, _ in operation_actions(
        {"operations": [{"op": "write", "path": "n.txt", "content": "x",
                         "mode": "append"}]}, batch=True))


def test_a_batch_of_a_mkdir_is_held_before_it_runs():
    from padiem_ai_core.pc_batch import run_batch

    # No confirm_batch is bound, so no step of a batch carrying a mutation may
    # run: not the read in front of it and not the folder itself.
    outcome = run_batch([{"op": "list", "args": {"path": "."}},
                         {"op": "mkdir", "args": {"path": "new"}}],
                        owner="owner_fixture", stop_on_error=True, total_timeout=None)
    assert outcome["requires_confirmation"] is True
    assert outcome["results"] == [] and outcome["completed"] == 0


# --- the real command on the real PowerShell --------------------------------

SANDBOX = Path("E:" + BS + "pc-append-sandbox-7603")
ROOT = SANDBOX / "work"
TODAY = "2026-11-09"
POWERSHELL = ["powershell", "-NoProfile", "-NonInteractive", "-nologo", "-command", "-"]


def _run(command: str) -> dict:
    import json
    import subprocess

    raw = subprocess.run(POWERSHELL, input=command.encode("utf-8"),
                        capture_output=True, timeout=240)
    text = raw.stdout.decode("utf-8", errors="replace")
    lines = [line for line in text.splitlines() if line.startswith(PC_WRITE_ACCOUNT_PREFIX)]
    assert lines, f"account line missing: rc={raw.returncode} out={text[:300]!r}"
    return json.loads(base64.b64decode(lines[-1][len(PC_WRITE_ACCOUNT_PREFIX):]))


def _real(op, *, relative, content=None, append=False):
    # ASCII names only: this lane's stdin reaches PowerShell 5.1 as the console
    # code page (ks_c_5601-1987 here), which cannot carry non-ASCII script text.
    root = str(ROOT)
    return _pc_write_command(
        op=op, root=root, target=root + BS + relative.replace("/", BS),
        relative=relative, backup_dir=_pc_backup_dir(root + BS, TODAY),
        content_b64=(base64.b64encode(content).decode("ascii")
                     if content is not None else None),
        append=append,
    )


@pytest.fixture()
def sandbox():
    import shutil

    shutil.rmtree(SANDBOX, ignore_errors=True)
    (ROOT / "docs").mkdir(parents=True, exist_ok=True)
    try:
        yield ROOT
    finally:
        shutil.rmtree(SANDBOX, ignore_errors=True)


@pytest.mark.skipif(sys.platform != "win32", reason="real Windows PowerShell only")
def test_real_append_keeps_the_prefix_and_adds_no_newline(sandbox):
    target = sandbox / "docs" / "log.txt"
    target.write_bytes(b"first")
    account = _run(_real("write", relative="docs/log.txt", content=b"second", append=True))
    assert account["ok"] is True and account["op"] == "write"
    assert target.read_bytes() == b"firstsecond"
    assert account["verification"]["append_bytes"] == 6
    assert account["verification"]["append_sha256"] == hashlib.sha256(b"second").hexdigest()
    assert Path(account["backup"]).read_bytes() == b"first", "the original is recoverable"


@pytest.mark.skipif(sys.platform != "win32", reason="real Windows PowerShell only")
def test_real_append_creates_a_missing_file_without_a_backup(sandbox):
    target = sandbox / "docs" / "new.txt"
    target.unlink(missing_ok=True)
    account = _run(_real("write", relative="docs/new.txt", content=b"only", append=True))
    assert account["ok"] is True
    assert account["backup"] is None
    assert target.read_bytes() == b"only"


@pytest.mark.skipif(sys.platform != "win32", reason="real Windows PowerShell only")
def test_real_append_refuses_bytes_that_are_not_utf8(sandbox):
    target = sandbox / "docs" / "ansi.txt"
    target.write_bytes(b"\xb0\xa1")  # cp949 '가', not UTF-8
    account = _run(_real("write", relative="docs/ansi.txt", content=b"x", append=True))
    assert account["ok"] is False
    assert account["reason"] == "edit_encoding_unsupported"
    assert target.read_bytes() == b"\xb0\xa1", "a refused append changes nothing"


@pytest.mark.skipif(sys.platform != "win32", reason="real Windows PowerShell only")
def test_real_mkdir_makes_parents_and_refuses_a_name_that_is_a_file(sandbox):
    account = _run(_real("mkdir", relative="docs/one/two"))
    assert account["ok"] is True and account["op"] == "mkdir"
    assert (sandbox / "docs" / "one" / "two").is_dir()
    # Existing folder: nothing to change, and still a success.
    again = _run(_real("mkdir", relative="docs/one/two"))
    assert again["ok"] is True
    (sandbox / "docs" / "taken").write_bytes(b"blocking")
    refused = _run(_real("mkdir", relative="docs/taken"))
    assert refused["ok"] is False and refused["reason"] == "target_exists"
    assert (sandbox / "docs" / "taken").is_file()
