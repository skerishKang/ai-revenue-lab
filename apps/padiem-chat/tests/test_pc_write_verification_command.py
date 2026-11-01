"""The server's PC command observes the filesystem after its mutation.

These are command-contract checks for the deployed Windows PowerShell 5.1
transport. Engine tests consume the resulting evidence and decide the outcome.
"""
from __future__ import annotations

import base64

import pytest

from app.oracle_mesh_read_return_routes import _pc_write_command


def command(op):
    return _pc_write_command(
        op=op, root="C:/granted", target="C:/granted/original.txt", relative="original.txt",
        backup_dir="C:/.padiem-backup/2026-11-01",
        destination="C:/granted/moved.txt" if op == "move" else None,
        content_b64=base64.b64encode("본문".encode()).decode() if op == "write" else None,
    )


@pytest.mark.parametrize("op,mutation", [
    ("write", "[IO.File]::WriteAllBytes"),
    ("move", "Move-Item -LiteralPath $target -Destination $destination"),
    ("delete", "Remove-Item -LiteralPath $target"),
])
def test_observation_follows_mutation_catch_before_the_account(op, mutation):
    script = command(op)
    observe = script.index("$verification =")
    changed = script.index(mutation)
    assert changed < script.index("} catch {", changed) < observe
    assert observe < script.index("$account =")
    assert "verification=$verification" in script
    # The existing executor feeds one line through powershell -command -.
    assert "\n" not in script and "\r" not in script


def test_write_measures_actual_file_size_and_sha256_instead_of_expected_payload():
    observation = command("write").split("$verification =", 1)[1].split("$account =", 1)[0]
    assert "Test-Path -LiteralPath $verifyTarget -PathType Leaf -ErrorAction Stop" in observation
    assert "Get-Item -LiteralPath $verifyTarget -Force -ErrorAction Stop" in observation
    assert "$targetBytes = [int64]$targetItem.Length" in observation
    assert "Get-FileHash -LiteralPath $verifyTarget -Algorithm SHA256 -ErrorAction Stop" in observation
    assert "target_sha256=$targetSha256" in observation
    assert "$payload" not in observation
    assert "$bytes" not in observation
    assert "$ok" not in observation


def test_move_observes_original_and_destination_after_target_is_reassigned():
    script = command("move")
    assert script.index("$verifySource = $target") < script.index("$target = $destination")
    assert script.index("$verifyTarget = $destination") < script.index("$target = $destination")
    observation = script.split("$verification =", 1)[1]
    assert "Test-Path -LiteralPath $verifySource -ErrorAction Stop" in observation
    assert "Test-Path -LiteralPath $verifyTarget -PathType Leaf -ErrorAction Stop" in observation
    assert "source_exists=[bool]$sourceExists" in observation
    assert "target_is_file=[bool]$targetIsFile" in observation


def test_delete_observes_both_removed_path_and_actual_backup_file():
    script = command("delete")
    observation = script.split("$verification =", 1)[1]
    assert "Test-Path -LiteralPath $verifySource -ErrorAction Stop" in observation
    assert "Test-Path -LiteralPath $backup -ErrorAction Stop" in observation
    assert "Test-Path -LiteralPath $backup -PathType Leaf -ErrorAction Stop" in observation
    assert "backup_exists=$backupExists" in observation
    assert "backup_is_file=$backupIsFile" in observation
    assert "source_exists=[bool]$sourceExists" in observation


@pytest.mark.parametrize("op", ["write", "move", "delete"])
def test_unavailable_inspection_is_separate_from_mutation_success_and_drops_partial_facts(op):
    observation = command(op).split("$verification =", 1)[1].split("$account =", 1)[0]
    # No optimistic status is set before all reads finish. An access/hash error
    # resets the entire evidence object without printing the exception.
    assert observation.index("$backupIsFile = Test-Path") < observation.index("status='observed'")
    assert "catch { $verification = [ordered]@{version=1; status='unavailable'} }" in observation
    assert "$ok =" not in observation and "$reason =" not in observation
    assert "Write-" not in observation and "$_" not in observation
