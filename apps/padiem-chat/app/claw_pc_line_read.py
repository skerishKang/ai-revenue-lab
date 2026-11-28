"""#8953 3a: PowerShell line-page body for the approved PC text file lane.

No new authority: the same scoped ReparsePoint guard runs before these lines.
"""
from __future__ import annotations

PC_READ_LINE_MAX_COUNT = 1000
PC_READ_LINE_MAX_BYTES = 256 * 1024


def pc_read_line_lines() -> list[str]:
    """Stream at most 1000 whole UTF-8 lines and cap the final JSON at 256 KiB.

    A single enormous line is refused rather than silently skipped.
    """
    return r"""
$strict=New-Object Text.UTF8Encoding($false,$true)
$reader=$null
$rows=New-Object 'System.Collections.Generic.List[string]'
try {
  $reader=New-Object IO.StreamReader($path,$strict,$false)
  $number=[int64]1
  while($number -lt $startLine -and -not $reader.EndOfStream){
    [void]$reader.ReadLine()
    $number++
  }
  if($number -lt $startLine){
    '{"ok":false,"error":"line_out_of_range"}'
    return
  }
  while($rows.Count -lt $lineCount -and -not $reader.EndOfStream){
    $line=$reader.ReadLine()
    if($line.IndexOf([char]0) -ge 0){
      '{"ok":false,"error":"binary_text_rejected"}'
      return
    }
    [void]$rows.Add($line)
  }
  $more=(-not $reader.EndOfStream)
  $reason=if($more){'line_count_limit'}else{$null}
  while($true){
    if($more -and $rows.Count -eq 0){
      '{"ok":false,"error":"line_too_large"}'
      break
    }
    $returned=$rows.Count
    $next=if($more){[int64]($startLine+$returned)}else{$null}
    $answer=[ordered]@{
      ok=$true; unit='lines'; size_bytes=[int64]$size
      start_line=[int64]$startLine; line_count=[int]$returned
      text=[string]::Join([string][char]10,$rows.ToArray())
      eof=(-not $more); partial=$false
      truncated=[bool]$more; truncation_reason=$reason
      has_more=[bool]$more; next_cursor=$next; source_complete=$true
    }
    $json=ConvertTo-Json -InputObject $answer -Compress -Depth 5
    if([Text.Encoding]::UTF8.GetByteCount($json) -le 262144){
      $json
      break
    }
    if($rows.Count -eq 0){
      '{"ok":false,"error":"line_too_large"}'
      break
    }
    $rows.RemoveAt($rows.Count-1)
    $more=$true
    $reason='response_bytes_limit'
  }
} catch {
  '{"ok":false,"error":"encoding_unsupported"}'
} finally {
  if($null -ne $reader){$reader.Dispose()}
}
""".strip().splitlines()
