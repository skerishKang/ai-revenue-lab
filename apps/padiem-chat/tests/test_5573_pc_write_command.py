"""#4434: the PC write lane's command is built here, on the server.

The model and the PC never agree on a command between themselves: this server
turns one operation, one picked root and one relative path into the script the
paired PC runs. What these tests hold:

  * a write, a move and a delete each copy the original into the hidden backup
    folder on the same drive *before* the change, and report where it landed;
  * a failed backup stops the step before the change, so nothing is altered
    without a way back;
  * the customer's own characters - Korean, emoji, apostrophes, spaces - reach
    the PC as data, never as shell syntax;
  * every step prints exactly one account line and no confirmation prompt.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(HERE))

from app.oracle_mesh_read_return_routes import (  # noqa: E402
    PC_BACKUP_FOLDER,
    PC_WRITE_ACCOUNT_PREFIX,
    _pc_backup_dir,
    _pc_write_command,
)

BS = chr(92)
BACKUP_DIR = "C:" + BS + PC_BACKUP_FOLDER + BS + "2026-10-28"


def _command(op, *, target, relative, destination=None, content=None):
    return _pc_write_command(
        op=op,
        target=target,
        backup_dir=BACKUP_DIR,
        relative=relative,
        destination=destination,
        content_b64=(
            base64.b64encode(content.encode("utf-8")).decode("ascii")
            if content is not None else None
        ),
    )


def test_the_backup_folder_sits_on_the_drive_being_changed():
    assert _pc_backup_dir("C:" + BS + "Users" + BS + "owner", "2026-10-28") == (
        "C:" + BS + PC_BACKUP_FOLDER + BS + "2026-10-28"
    )
    assert _pc_backup_dir("d:/", "2026-10-28").startswith("D:")
    assert _pc_backup_dir("E:" + BS + "shared" + BS + "docs", "2026-11-01") == (
        "E:" + BS + PC_BACKUP_FOLDER + BS + "2026-11-01"
    )


def test_overwrite_copies_the_original_before_the_new_bytes_land():
    target = "C:" + BS + "Users" + BS + "owner" + BS + "문서" + BS + "견적서.txt"
    command = _command("write", target=target, relative="Users/owner/문서/견적서.txt",
                       content="본문")
    backup = command.index("$backup = Join-Path")
    written = command.index("[IO.File]::WriteAllBytes")
    assert "Copy-Item -LiteralPath $source_to_keep -Destination $backup -Force" in command
    assert "$source_to_keep = $target" in command
    assert backup < written, "the change must never precede the backup"


def test_a_new_file_needs_no_backup_and_still_refuses_a_missing_parent():
    command = _command("write", target="C:" + BS + "new.txt", relative="new.txt",
                       content="x")
    assert "padiem parent missing" in command
    assert "$reason = 'path_invalid'" in command


def test_a_failed_backup_stops_the_step_before_any_change():
    for op, rest in (
        ("delete", "Remove-Item"),
        ("write", "WriteAllBytes"),
        ("move", "Move-Item -LiteralPath $target"),
    ):
        command = _command(op, target="C:" + BS + "a.txt", relative="a.txt",
                           destination="C:/a2.txt", content="x")
        refusal = command.index("$reason = 'backup_failed'")
        action = command.index(rest)
        assert refusal < action, op
        assert "throw 'padiem backup failed'" in command


def test_a_move_backs_up_the_file_it_would_replace():
    command = _command("move", target="C:" + BS + "a.txt", relative="a.txt",
                       destination="C:" + BS + "b.txt")
    assert "if (Test-Path -LiteralPath $destination)" in command
    assert "$source_to_keep = $destination" in command
    assert "Copy-Item -LiteralPath $source_to_keep -Destination $backup -Force" in command
    assert "Move-Item -LiteralPath $target -Destination $destination -Force" in command


def test_delete_only_removes_a_file_it_has_copied():
    command = _command("delete", target="C:" + BS + "a.txt", relative="a.txt")
    assert "padiem target missing" in command
    assert command.index("Copy-Item -LiteralPath $source_to_keep") < command.index(
        "Remove-Item -LiteralPath $target -Force"
    )


def test_customer_characters_reach_the_pc_as_data_never_as_syntax():
    awkward = "C:" + BS + "고객" + BS + "팀's " + chr(128196) + " 파일.txt"
    command = _command("write", target=awkward, relative="고객/팀's " + chr(128196) + " 파일.txt",
                       content="가나다")
    # One single-quoted literal with the apostrophe doubled: the only escape
    # PowerShell needs, and the only one this builder applies.
    assert "'C:" + BS + "고객" + BS + "팀''s " + chr(128196) + " 파일.txt'" in command
    assert command.count("$ErrorActionPreference") == 1
    # The bytes cross as Base64, so no console code page can rewrite them.
    assert "[Convert]::FromBase64String('" in command
    assert "가나다" not in command.split("$payload")[1]


def test_every_step_prints_one_account_line_and_no_confirmation_prompt():
    for op, kwargs in (
        ("write", {"target": "C:" + BS + "a.txt", "relative": "a.txt",
                   "content_b64": base64.b64encode("x".encode("utf-8")).decode("ascii")}),
        ("move", {"target": "C:" + BS + "a.txt", "relative": "a.txt",
                  "destination": "C:/b.txt"}),
        ("delete", {"target": "C:" + BS + "a.txt", "relative": "a.txt"}),
    ):
        command = _pc_write_command(op=op, backup_dir=BACKUP_DIR, **kwargs)
        assert command.count("Write-Output ('" + PC_WRITE_ACCOUNT_PREFIX + "' + $encoded)") == 1
        lowered = command.lower()
        for prompt in ("read-host", "confirm", "shouldcontinue", "-whatif"):
            assert prompt not in lowered, (op, prompt)


def test_the_command_is_one_line_because_the_agent_cannot_finish_more():
    """A newline in the script is not a formatting choice; it is a stuck PC.

    The agent runs the console command as ``powershell -noprofile -nologo -command
    -`` and feeds the script through that process's standard input. Measured on
    the two real PCs on 2026-10-28: this script on one line answered in under two
    seconds and wrote the file with its backup; the same statements spread over
    two lines never answered, that PowerShell stayed alive, and because the agent
    serves one console task at a time every later operation on that PC - a plain
    folder listing included - waited behind it. Nothing in the product ends that
    wait, so the check has to be here, where the script is built.
    """
    for op, kwargs in (
        ("write", {"target": "C:" + BS + "a.txt", "relative": "a.txt",
                   "content_b64": base64.b64encode("x".encode("utf-8")).decode("ascii")}),
        ("move", {"target": "C:" + BS + "a.txt", "relative": "a.txt",
                  "destination": "C:/b.txt"}),
        ("delete", {"target": "C:" + BS + "a.txt", "relative": "a.txt"}),
    ):
        command = _pc_write_command(op=op, backup_dir=BACKUP_DIR, **kwargs)
        assert "\n" not in command and "\r" not in command, op
        # One line is only readable if the statements are separated, and the
        # concatenation has to be an expression: bare ``Write-Output 'a' + $b``
        # would reach PowerShell as three arguments, not one line.
        assert "; " in command
        assert "Write-Output '" + PC_WRITE_ACCOUNT_PREFIX + "' + $encoded)" not in command


def test_the_parent_folder_is_taken_where_the_pc_can_understand_it():
    """``Split-Path -LiteralPath X -Parent`` is refused by the PC's own shell.

    Measured on the real PC on 2026-10-28: Windows PowerShell 5.1 answers that
    combination with ``AmbiguousParameterSet``, so the parent check would fail for
    every file the owner has not written yet - a refusal the account would report
    as ``path_invalid`` for a folder that plainly exists. .NET's directory name has
    no parameter sets to choose between and treats the path as data.
    """
    command = _command("write", target="C:" + BS + "new.txt", relative="new.txt",
                       content="x")
    assert "Split-Path" not in command
    assert "[IO.Path]::GetDirectoryName($target)" in command
    for op, kwargs in (
        ("move", {"target": "C:" + BS + "a.txt", "relative": "a.txt",
                  "destination": "C:/b.txt"}),
        ("delete", {"target": "C:" + BS + "a.txt", "relative": "a.txt"}),
    ):
        assert "Split-Path" not in _pc_write_command(op=op, backup_dir=BACKUP_DIR, **kwargs)


def test_the_account_round_trips_through_the_engine_marker_shape():
    """The account the PC prints is the record the Engine and the run keep."""
    account = {
        "ok": True, "op": "write", "reason": None,
        "target": "C:" + BS + "고객" + BS + "견적서.txt",
        "backup": BACKUP_DIR + BS + "20261028-abc12345-C______.txt",
        "bytes": 12,
    }
    line = PC_WRITE_ACCOUNT_PREFIX + base64.b64encode(
        json.dumps(account, ensure_ascii=False).encode("utf-8"),
    ).decode("ascii")
    decoded = json.loads(
        base64.b64decode(line.split("=", 1)[1].encode("ascii"), validate=True).decode("utf-8"),
    )
    assert decoded == account
    assert decoded["backup"].startswith("C:" + BS + PC_BACKUP_FOLDER)


def test_a_refused_change_reports_why_instead_of_silently_doing_nothing():
    command = _command("delete", target="C:" + BS + "a.txt", relative="a.txt")
    assert "$reason = 'backup_failed'" in command
    assert "$reason = 'path_invalid'" in command
    # The account is printed after the catch, so a refusal is still an answer.
    assert command.index("} catch {") < command.index(
        "Write-Output ('" + PC_WRITE_ACCOUNT_PREFIX
    )


@pytest.mark.parametrize("op", ["write", "move", "delete"])
def test_no_command_names_an_absolute_path_the_caller_supplied(op):
    """Every target is built from the root this server picked, never from text."""
    command = _command(op, target="C:" + BS + "granted" + BS + "a.txt",
                       relative="granted/a.txt", destination="C:/granted/b.txt")
    assert "C:" + BS + "granted" in command
    assert "D:" not in command.replace(BACKUP_DIR, "")
