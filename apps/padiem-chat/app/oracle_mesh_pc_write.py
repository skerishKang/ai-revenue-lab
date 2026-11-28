"""PC write command construction (unchanged PowerShell payload)."""
from __future__ import annotations

from padiem_ai_core.powershell_literal import ps_literal
from .oracle_mesh_pc_paths import _pc_files_powershell_literal



#: Hidden per-drive backup folder. The original is copied here before anything
#: changes, so a rollback never depends on somebody remembering a path.
PC_BACKUP_FOLDER = ".padiem-backup"
#: The PC answers one write step with this line: the JSON account, base64 encoded
#: so no console code page or quoting rule can change what it says.
PC_WRITE_ACCOUNT_PREFIX = "PADIEM_PC_ACCOUNT="


def _pc_backup_dir(root: str, day: str) -> str:
    """The hidden backup folder on the drive one granted root sits on."""
    drive = (str(root).strip().rstrip(":\\/") or "C")[:1].upper()
    return drive + ":\\" + PC_BACKUP_FOLDER + "\\" + day


def _pc_ps_literal(value: str) -> str:
    """One single-quoted PowerShell literal (#7559: all five quote characters)."""
    return _pc_files_powershell_literal(value)


def _pc_write_backup_fragments(*, relative: str) -> tuple[str, str]:
    """백업·대상 없음 조각: 모든 변경이 같은 백업 단계로 시작한다."""
    backup_step = (
        "New-Item -ItemType Directory -Force -Path $backupDir | Out-Null; "
        "$backup = Join-Path $backupDir ($stamp + '-' + ("
        + _pc_ps_literal(relative) + " -replace '[^\\w.-]','_'));"
        " try { Copy-Item -LiteralPath $source_to_keep -Destination $backup -Force }"
        " catch { $backup = $null; $reason = 'backup_failed'; throw 'padiem backup failed' }"
    )
    target_missing = (
        "if (-not (Test-Path -LiteralPath $source_to_keep -PathType Leaf)) {"
        " $reason = 'path_invalid'; throw 'padiem target missing' }"
    )
    return backup_step, target_missing


def _pc_write_input_statements(
    *, op: str, target: str, backup_dir: str, content_b64: str | None = None,
    old_text_b64: str | None = None, new_text_b64: str | None = None,
    destination: str | None = None,
) -> list[str]:
    """입력 검증 단계: 초기 문장과 관찰 대상을 같은 순서로 만든다."""
    statements = [
        "$ErrorActionPreference = 'Stop'",
        "$ok = $false",
        "$reason = 'failed'",
        "$bytes = 0",
        "$op = " + _pc_ps_literal(op),
        "$target = " + _pc_ps_literal(target),
        "$backupDir = " + _pc_ps_literal(backup_dir),
        "$backup = $null",
        "$stamp = (Get-Date -Format 'yyyyMMddHHmmss') + '-' + "
        "([Guid]::NewGuid().ToString('N')).Substring(0,8)",
    ]
    if content_b64 is not None:
        statements.append(
            "$payload = [Convert]::FromBase64String(" + ps_literal(content_b64) + ")"
        )
    if old_text_b64 is not None:
        statements.append(
            "$oldText = [Convert]::FromBase64String(" + ps_literal(old_text_b64) + ")"
        )
    if new_text_b64 is not None:
        statements.append(
            "$newText = [Convert]::FromBase64String(" + ps_literal(new_text_b64) + ")"
        )
    if destination is not None:
        statements.append("$destination = " + _pc_ps_literal(destination))
    # Keep both observation targets before a move rewrites $target for the
    # legacy account. These paths come from the server's resolved grant, not
    # from model-provided verification fields.
    statements.extend([
        "$verifySource = $target",
        "$verifyTarget = " + ("$destination" if op == "move" else "$target"),
    ])
    return statements


def _pc_write_scope_guard(statements: list[str], *, root: str) -> str:
    """권한·한도 단계: 허용 범위 밖 바로가기 경로를 백업 전에 막는다."""
    # #5994 D3: the guard walks every folder from the granted root down to the
    # target (and, for a move, down to the destination) and refuses the step
    # before any backup or change when one of them is a reparse point — a
    # shortcut folder must never carry a write, a move or a deletion outside
    # the grant. The final normalized path is checked against the root as a
    # second layer. The granted root itself is not checked: a root that is a
    # link was the owner's own grant decision. A guard malfunction fails
    # closed, and the refusal names no internal component.
    link_refusal = "이 위치는 바로가기 폴더를 거쳐서 바꿀 수 없습니다."
    statements.append(
        "$guardRoot = " + _pc_ps_literal(root.rstrip("\\/") + "\\") + ";"
        "$guardHit = $null;"
        "try {"
        " foreach ($rel in (@($target) + $(if ($destination) { @($destination) } else { @() }))) {"
        "  if (-not $rel) { continue };"
        "  $walk = $guardRoot;"
        "  $rest = $rel.Substring($guardRoot.Length).TrimStart('/').Replace('/', '\\');"
        "  foreach ($seg in ($rest -split '\\\\')) {"
        "   $walk = Join-Path $walk $seg;"
        "   if (-not (Test-Path -LiteralPath $walk)) { break };"
        "   $item = Get-Item -LiteralPath $walk -Force -ErrorAction SilentlyContinue;"
        "   if ($item -and (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0))"
        "   { $guardHit = $walk; break } };"
        " if ($guardHit) { break } }"
        "} catch { $guardHit = $guardRoot };"
        "if (-not $guardHit) {"
        " $full = [IO.Path]::GetFullPath($target);"
        " if (-not $full.StartsWith($guardRoot, [System.StringComparison]::OrdinalIgnoreCase))"
        " { $guardHit = $guardRoot } };"
        "if ($destination -and -not $guardHit) {"
        " $fullDestination = [IO.Path]::GetFullPath($destination);"
        " if (-not $fullDestination.StartsWith($guardRoot, [System.StringComparison]::OrdinalIgnoreCase))"
        " { $guardHit = $guardRoot } };"
    )
    return link_refusal


def _pc_write_operation_body(
    *, op: str, append: bool, replace_all: bool, backup_step: str,
    target_missing: str,
) -> str:
    """분기 단계: 덮어쓰기·추가·편집·폴더·이동·삭제 중 하나를 고른다."""
    if op == "write" and append:
        # #7603: append keeps every existing byte and adds the caller's bytes at
        # the end. A file that is not valid UTF-8 is refused exactly like pc_edit
        # because an append is still a text-file edit; a missing file is created
        # through the same atomic temp+Move-Item step as an overwrite, and its
        # parent must already exist.
        body = (
            "try {"
            " if (Test-Path -LiteralPath $target -PathType Leaf) {"
            " $source_to_keep = $target; $appendLength = $payload.Length;"
            + backup_step +
            "; $before = [IO.File]::ReadAllBytes($target);"
            " $strict = New-Object Text.UTF8Encoding($false, $true);"
            " try { $beforeText = $strict.GetString($before) }"
            " catch { $reason = 'edit_encoding_unsupported'; throw 'padiem append encoding' };"
            " if (-not [Linq.Enumerable]::SequenceEqual($strict.GetBytes($beforeText), $before))"
            " { $reason = 'edit_encoding_unsupported'; throw 'padiem append encoding' };"
            " $payload = [byte[]]($before + $payload)"
            " } elseif (-not (Test-Path -LiteralPath "
            "([IO.Path]::GetDirectoryName($target)))) {"
            " $reason = 'path_invalid'; throw 'padiem parent missing' } else { $appendLength = $payload.Length };"
            " $temp = $target + '.padiem-write';"
            " [IO.File]::WriteAllBytes($temp, $payload);"
            " Move-Item -LiteralPath $temp -Destination $target -Force;"
            " $bytes = $payload.Length;"
            " $ok = $true; $reason = $null }"
            " catch { if ($reason -eq 'failed') { $reason = 'path_invalid' } }"
        )
    elif op == "write":
        body = (
            "try {"
            " if (Test-Path -LiteralPath $target -PathType Leaf) {"
            " $source_to_keep = $target; " + backup_step +
            " } elseif (-not (Test-Path -LiteralPath "
            "([IO.Path]::GetDirectoryName($target)))) {"
            " $reason = 'path_invalid'; throw 'padiem parent missing' };"
            " $temp = $target + '.padiem-write';"
            " [IO.File]::WriteAllBytes($temp, $payload);"
            " Move-Item -LiteralPath $temp -Destination $target -Force;"
            " $bytes = $payload.Length;"
            " $ok = $true; $reason = $null }"
            " catch { if ($reason -eq 'failed') { $reason = 'path_invalid' } }"
        )
    elif op == "edit":
        from .oracle_mesh_pc_edit import pc_edit_operation_body
        body = pc_edit_operation_body(
            backup_step=backup_step, target_missing=target_missing,
            replace_all=replace_all,
        )
    elif op == "mkdir":
        # #7603: one folder, including missing parents. An existing folder is a
        # no-change success; a file of the same name is the one refusal. There is
        # no original to copy, so the backup leg answers none, exactly like a
        # write to a new file.
        body = (
            "try {"
            " if (Test-Path -LiteralPath $target -PathType Leaf)"
            " { $reason = 'target_exists'; throw 'padiem target exists' };"
            " if (-not (Test-Path -LiteralPath $target -PathType Container))"
            " { New-Item -ItemType Directory -Force -Path $target | Out-Null };"
            " $ok = $true; $reason = $null }"
            " catch { if ($reason -eq 'failed') { $reason = 'path_invalid' } }"
        )
    elif op == "move":
        body = (
            "try { $source_to_keep = $target;"
            + target_missing
            + "; if (Test-Path -LiteralPath $destination) { $source_to_keep = $destination; "
            + backup_step +
            " }; Move-Item -LiteralPath $target -Destination $destination -Force;"
            " $target = $destination;"
            " $ok = $true; $reason = $null }"
            " catch { if ($reason -eq 'failed') { $reason = 'path_invalid' } }"
        )
    else:
        body = (
            "try { $source_to_keep = $target;"
            + target_missing
            + "; " + backup_step +
            "; Remove-Item -LiteralPath $target -Force;"
            " $ok = $true; $reason = $null }"
            " catch { if ($reason -eq 'failed') { $reason = 'path_invalid' } }"
        )
    return body


def _pc_write_record_statements(
    statements: list[str], *, body: str, link_refusal: str, append: bool, edit: bool,
) -> None:
    """기록·응답 단계: 거절 문장, 검증, 계정 줄을 같은 순서로 붙인다."""
    # A refused step changes nothing and still answers with one account line:
    # the refusal names the Korean sentence the owner sees, never an internal
    # component.
    statements.append(
        "if ($guardHit) { $reason = " + _pc_ps_literal(link_refusal) + " }"
        " else { " + body + " }"
    )
    # #7603: an append is measured where it lands. The whole-file digest above
    # answers "which file is this" and cannot equal the caller's bytes once the
    # file was not empty, so the tail of the appended length is read back and
    # hashed. Only the append command carries this probe.
    append_probe = "" if not append else (
        " $tailBytes = $null; $tailSha256 = $null;"
        " if ($targetIsFile -and $null -ne $appendLength) {"
        " $stream = [IO.File]::Open($verifyTarget, 'Open', 'Read', 'ReadWrite');"
        " try { $streamLength = $stream.Length; $tailLength = [int64]$appendLength;"
        " if ($tailLength -gt $streamLength) { $tailLength = $streamLength };"
        " $tailBuffer = New-Object byte[] $tailLength;"
        " [void]$stream.Seek(($streamLength - $tailLength), 'Begin');"
        " if ($stream.Read($tailBuffer, 0, $tailLength) -eq $tailLength) {"
        " $tailBytes = $tailLength;"
        " $tailHash = [Security.Cryptography.SHA256]::Create();"
        " try { $tailSha256 = ([BitConverter]::ToString($tailHash.ComputeHash($tailBuffer))"
        " -replace '-', '').ToLowerInvariant() } finally { $tailHash.Dispose() } } }"
        " finally { $stream.Dispose() } }"
    )
    # A command's $ok and its expected payload length are not filesystem
    # evidence. Inspect the result after the mutation's catch, even when the
    # mutation reported failure. Inspection failures have their own state and
    # never leak an exception or turn an unobserved result into success.
    statements.extend([
        "$verification = [ordered]@{version=1; status='unavailable'}",
        "try {"
        " $sourceExists = Test-Path -LiteralPath $verifySource -ErrorAction Stop;"
        " $targetExists = Test-Path -LiteralPath $verifyTarget -ErrorAction Stop;"
        " $targetIsFile = Test-Path -LiteralPath $verifyTarget -PathType Leaf -ErrorAction Stop;"
        " $targetBytes = $null; $targetSha256 = $null;"
        " if ($targetIsFile) {"
        " $targetItem = Get-Item -LiteralPath $verifyTarget -Force -ErrorAction Stop;"
        " $targetBytes = [int64]$targetItem.Length;"
        + (" if ($op -eq 'write' -or $op -eq 'edit') {" if edit
           else " if ($op -eq 'write') {")
        + " $fileHash = Get-FileHash -LiteralPath $verifyTarget -Algorithm SHA256 -ErrorAction Stop;"
        " $targetSha256 = $fileHash.Hash.ToLowerInvariant() } };"
        + append_probe
        + " $backupExists = $null; $backupIsFile = $null;"
        " if ($null -ne $backup) {"
        " $backupExists = Test-Path -LiteralPath $backup -ErrorAction Stop;"
        " $backupIsFile = Test-Path -LiteralPath $backup -PathType Leaf -ErrorAction Stop };"
        " $verification = [ordered]@{version=1; status='observed';"
        " source_exists=[bool]$sourceExists; target_exists=[bool]$targetExists;"
        " target_is_file=[bool]$targetIsFile; target_bytes=$targetBytes;"
        " target_sha256=$targetSha256; backup_exists=$backupExists;"
        " backup_is_file=$backupIsFile}"
        + ("" if not append else
           "; if ($null -ne $tailBytes) { $verification['append_bytes'] = $tailBytes;"
           " $verification['append_sha256'] = $tailSha256 }")
        + " } catch { $verification = [ordered]@{version=1; status='unavailable'} }",
    ])
    if edit:
        statements.append(
            "if ($op -eq 'edit' -and $verification['status'] -eq 'observed') {"
            " $verification['edit_verified'] = [bool]$editVerified };"
        )
    statements.append(
        "$account = [ordered]@{ok=$ok; op=$op; reason=$reason; target=$target; "
        "backup=$backup; bytes=$bytes; verification=$verification}"
    )
    if edit:
        statements.append(
            "if ($op -eq 'edit' -and $ok -and $editDetails) {"
            " foreach ($key in $editDetails.Keys) { $account[$key] = $editDetails[$key] } };"
        )
    statements.extend([
        "$json = ConvertTo-Json -InputObject $account -Compress",
        "$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))",
        "Write-Output ('" + PC_WRITE_ACCOUNT_PREFIX + "' + $encoded)",
    ])


def _pc_write_command(
    *, op: str, root: str, target: str, backup_dir: str, relative: str,
    destination: str | None = None, content_b64: str | None = None,
    old_text_b64: str | None = None, new_text_b64: str | None = None,
    append: bool = False, replace_all: bool = False,
) -> str:
    """Build one write, move or delete step for the paired PC.

    Four rules hold across all three operations. The original is copied to the
    hidden backup folder on the same drive *before* anything changes, and a
    backup that fails stops the step there, so no change is made that cannot be
    undone. The step prints exactly one account line saying what happened and
    where the original landed - including when it refused. There is no
    confirmation anywhere in it: the change happens when the account says it
    did. And the step refuses a path that crosses a reparse point (#5994 D3):
    every folder from the granted root down to the target - and the target
    itself - is checked for the ReparsePoint attribute (junctions, symbolic
    links, mounts), the final normalized path must still sit inside the granted
    root, and a refusal happens before the backup, so nothing changes.

    The command is cmdlet and .NET calls only, like the listing command: no
    native program runs, so the PC reports no exit code and the existing result
    lane stays truthful.

    It is also exactly ONE line, which is not a style choice. The agent runs a
    console command as ``powershell -noprofile -nologo -command -`` and feeds the
    script through that process's standard input: a script carrying a newline
    never completes there, so its PowerShell stays alive, and because that agent
    serves one console task at a time every later PC operation - reads included -
    waits behind it. Measured on the real machines on 2026-10-28: one line
    answered in under two seconds and wrote the file with its backup; the same
    statements on two lines never answered at all. Semicolons are what PowerShell
    needs on one line, so nothing here changed meaning.

    For the same reason the parent folder is taken with
    ``[IO.Path]::GetDirectoryName`` and not with ``Split-Path -LiteralPath ...
    -Parent``: on the PC's own Windows PowerShell 5.1 that combination is refused
    with ``AmbiguousParameterSet``, which would turn every new file into a
    refusal. Both rules are about what the customer's PC actually accepts, so
    they are checked here where the script is built.
    """
    backup_step, target_missing = _pc_write_backup_fragments(relative=relative)
    statements = _pc_write_input_statements(
        op=op,
        target=target,
        backup_dir=backup_dir,
        content_b64=content_b64,
        old_text_b64=old_text_b64,
        new_text_b64=new_text_b64,
        destination=destination,
    )
    link_refusal = _pc_write_scope_guard(statements, root=root)
    body = _pc_write_operation_body(
        op=op,
        append=append,
        replace_all=replace_all,
        backup_step=backup_step,
        target_missing=target_missing,
    )
    _pc_write_record_statements(
        statements, body=body, link_refusal=link_refusal, append=append, edit=op == "edit",
    )
    return "; ".join(statements)
