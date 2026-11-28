"""#8953 2/5: bounded, byte-safe partial UTF-8 edit for the PC write lane.

The generated PowerShell stays one physical command line for the legacy PC
console transport. Nothing here authorizes a path or changes a grant.
"""
from __future__ import annotations


def pc_edit_operation_body(*, backup_step: str, target_missing: str,
                           replace_all: bool) -> str:
    # Literal PowerShell is deliberately readable here and joined to one line.
    # Both payloads are base64-decoded by the existing authenticated write lane.
    command = r"""
try {
 $temp = $null; $source_to_keep = $target; $editVerified = $false;
 __TARGET_MISSING__
 $before = [IO.File]::ReadAllBytes($target);
 $strict = New-Object Text.UTF8Encoding($false, $true);
 try { $beforeText = $strict.GetString($before);
       $oldPlain = $strict.GetString($oldText);
       $newPlain = $strict.GetString($newText) }
 catch { $reason = 'edit_encoding_unsupported'; throw 'padiem edit encoding' };
 if (-not [Linq.Enumerable]::SequenceEqual($strict.GetBytes($beforeText), $before))
 { $reason = 'edit_encoding_unsupported'; throw 'padiem edit encoding' };
 if ($oldPlain.Length -eq 0) { $reason = 'edit_not_found'; throw 'padiem edit empty' };
 $positions = New-Object 'System.Collections.Generic.List[int]';
 $hits = 0; $lastEnd = 0;
 $at = $beforeText.IndexOf($oldPlain, 0, [StringComparison]::Ordinal);
 while ($at -ge 0) {
   $hits += 1;
   if ($at -ge $lastEnd) { [void]$positions.Add($at); $lastEnd = $at + $oldPlain.Length };
   $at = $beforeText.IndexOf($oldPlain, $at + 1, [StringComparison]::Ordinal)
 };
 if ($hits -eq 0) { $reason = 'edit_not_found'; throw 'padiem edit miss' };
 if ($hits -gt 1 -and -not __REPLACE_ALL__) { $reason = 'edit_not_unique'; throw 'padiem edit ambiguous' };
 $crlf = [string][char]13 + [string][char]10; $lf = [string][char]10;
 $crlfCount = [regex]::Matches($beforeText, '\r\n').Count;
 $lfOnlyCount = [regex]::Matches($beforeText, '(?<!\r)\n').Count;
 $normalized = $newPlain.Replace($crlf, $lf).Replace([string][char]13, $lf);
 $builder = New-Object System.Text.StringBuilder;
 $cursor = 0; $firstReplacement = $null; $newlineConverted = $false;
 foreach ($position in $positions) {
   [void]$builder.Append($beforeText.Substring($cursor, $position - $cursor));
   $chosen = $lf;
   if ($crlfCount -gt 0 -and $lfOnlyCount -eq 0) { $chosen = $crlf }
   elseif ($crlfCount -gt 0 -and $lfOnlyCount -gt 0) {
     $prior = -1;
     if ($position -gt 0) { $prior = $beforeText.LastIndexOf([char]10, $position - 1) };
     if ($prior -ge 0) {
       if ($prior -gt 0 -and $beforeText[$prior - 1] -eq [char]13) { $chosen = $crlf }
     } else {
       $following = $beforeText.IndexOf([char]10, $position);
       if ($following -gt 0 -and $beforeText[$following - 1] -eq [char]13) { $chosen = $crlf }
     }
   };
   $inserted = $normalized.Replace($lf, $chosen);
   if ($inserted -cne $newPlain) { $newlineConverted = $true };
   if ($null -eq $firstReplacement) { $firstReplacement = $inserted };
   [void]$builder.Append($inserted);
   $cursor = $position + $oldPlain.Length
 };
 [void]$builder.Append($beforeText.Substring($cursor));
 $afterText = $builder.ToString();
 $payload = [Text.Encoding]::UTF8.GetBytes($afterText);
 $hasher = [Security.Cryptography.SHA256]::Create();
 $beforeHash = ([BitConverter]::ToString($hasher.ComputeHash($before))).Replace('-', '').ToLowerInvariant();
 $expectedHash = ([BitConverter]::ToString($hasher.ComputeHash($payload))).Replace('-', '').ToLowerInvariant();

 $firstPosition = $positions[0];
 $lineStart = 1 + [regex]::Matches($beforeText.Substring(0, $firstPosition), '\n').Count;
 $oldEndLine = $lineStart + [regex]::Matches($oldPlain, '\n').Count;
 $lineEnd = $lineStart + [regex]::Matches($firstReplacement, '\n').Count;
 $beforeLines = [regex]::Split($beforeText, '\r\n|\n|\r');
 $afterLines = [regex]::Split($afterText, '\r\n|\n|\r');
 $beforeFrom = [Math]::Max(0, $lineStart - 3);
 $afterFrom = [Math]::Max(0, $lineStart - 3);
 $beforeTo = [Math]::Min($beforeLines.Length - 1, $oldEndLine + 1);
 $afterTo = [Math]::Min($afterLines.Length - 1, $lineEnd + 1);
 $beforeContext = [string]::Join($lf, [string[]]$beforeLines[$beforeFrom..$beforeTo]);
 $afterContext = [string]::Join($lf, [string[]]$afterLines[$afterFrom..$afterTo]);
 $truncated = $positions.Count -gt 1;
 if ([Text.Encoding]::UTF8.GetByteCount($beforeContext) -gt 2048) {
   $truncated = $true;
   $beforeContext = $beforeContext.Substring(0, [Math]::Min($beforeContext.Length, 2048));
   while ([Text.Encoding]::UTF8.GetByteCount($beforeContext) -gt 2048) {
     $beforeContext = $beforeContext.Substring(0, $beforeContext.Length - 1)
   }
 };
 if ([Text.Encoding]::UTF8.GetByteCount($afterContext) -gt 2048) {
   $truncated = $true;
   $afterContext = $afterContext.Substring(0, [Math]::Min($afterContext.Length, 2048));
   while ([Text.Encoding]::UTF8.GetByteCount($afterContext) -gt 2048) {
     $afterContext = $afterContext.Substring(0, $afterContext.Length - 1)
   }
 };
 $editDetails = [ordered]@{
   line_start = [int]$lineStart; line_end = [int]$lineEnd;
   before_context = [string]$beforeContext; after_context = [string]$afterContext;
   replacement_count = [int]$positions.Count; truncated = [bool]$truncated;
   newline_converted = [bool]$newlineConverted; edit_expected_sha256 = $expectedHash
 };
 $fresh = [IO.File]::ReadAllBytes($target);
 $freshHash = ([BitConverter]::ToString($hasher.ComputeHash($fresh))).Replace('-', '').ToLowerInvariant();
 if ($freshHash -cne $beforeHash) { $reason = 'edit_conflict'; throw 'padiem edit conflict' };
 __BACKUP_STEP__
 $temp = $target + '.padiem-write-' + $stamp;
 [IO.File]::WriteAllBytes($temp, $payload);
 $fresh = [IO.File]::ReadAllBytes($target);
 $freshHash = ([BitConverter]::ToString($hasher.ComputeHash($fresh))).Replace('-', '').ToLowerInvariant();
 if ($freshHash -cne $beforeHash) { $reason = 'edit_conflict'; throw 'padiem edit conflict' };
 Move-Item -LiteralPath $temp -Destination $target -Force;
 $persisted = [IO.File]::ReadAllBytes($target);
 $persistedHash = ([BitConverter]::ToString($hasher.ComputeHash($persisted))).Replace('-', '').ToLowerInvariant();
 if ($persistedHash -cne $expectedHash -or
     -not [Linq.Enumerable]::SequenceEqual($persisted, $payload)) {
   $reason = 'edit_verification_failed'; throw 'padiem edit readback' };
 $editVerified = $true; $bytes = $persisted.Length;
 $ok = $true; $reason = $null
} catch {
 if ($temp -and (Test-Path -LiteralPath $temp)) {
   Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue };
 if ($reason -eq 'failed') { $reason = 'path_invalid' }
} finally { if ($hasher) { $hasher.Dispose() } }
"""
    command = command.replace("__TARGET_MISSING__", target_missing, 1)
    command = command.replace("__BACKUP_STEP__", backup_step, 1)
    command = command.replace("__REPLACE_ALL__", "$true" if replace_all else "$false", 1)
    # The legacy command transport cannot complete a multi-line PowerShell script.
    return " ".join(line.strip() for line in command.splitlines() if line.strip())
