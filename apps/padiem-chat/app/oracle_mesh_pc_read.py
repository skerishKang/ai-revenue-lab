"""PC read, search and listing command construction."""
from __future__ import annotations

from padiem_ai_core.powershell_literal import ps_utf8_literal
from .claw_pc_search_command import PC_SEARCH_MAX_LIMIT, PC_SEARCH_SCAN_MAX_FILES
from .oracle_mesh_pc_paths import PC_FILES_LIST_PAGE_SIZE

#: One deep pc_list answer carries at most this many rows, whatever the depth.
_PC_LIST_DEPTH_ROW_CAP = 200



#: Characters the provider's own -Filter can carry harmlessly. Anything else (a
#: wildcard, a quote, a path separator, a semicolon) makes the coarse pre-filter '*'
#: and lets the exact -like test decide — so a term can never become a pattern or a
#: second statement, and correctness never depends on which branch ran.
_FILTER_PREFILTER_SAFE = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-.,()")


def _pc_files_filter_prefilter(term: str) -> str:
    if term and all(ch in _FILTER_PREFILTER_SAFE or ord(ch) > 127 for ch in term):
        return "*" + term + "*"
    return "*"


def _pc_files_windows_folder(root: str, relative: str) -> str:
    """The folder to list: a bare drive is the volume root, not ``D:``.

    Windows reads ``-LiteralPath 'D:'`` as the *current directory on D:*, not
    the drive root. Spelling it ``D:/`` makes a granted drive list the drive.
    #7978: a network share reaches PowerShell in its own Windows spelling —
    the stored ``//server/share`` becomes ``\\\\server\\share\\relative``. A
    single leading slash would be a drive-relative path, never the share.
    """
    trimmed = str(root or "").replace("\\", "/").rstrip("/")
    if trimmed.startswith("//"):
        unc = "\\\\" + trimmed[2:].replace("/", "\\")
        if not relative:
            return unc
        return unc + "\\" + str(relative).replace("/", "\\")
    bare_drive = len(trimmed) == 2 and trimmed[1] == ":"
    base = trimmed + "/" if bare_drive else trimmed
    return base.rstrip("/") + "/" + relative if relative else base


def _pc_files_command(*, op: str, root: str, relative: str,
                      offset: int = 0, page_size: int = PC_FILES_LIST_PAGE_SIZE,
                      filter_term: str | None = None,
                      recursive: bool = False, depth: int = 1) -> str:
    """Build the one command this server will execute for a file tool call.

    Only ``list`` uses the PowerShell command lane. ``read`` uses the existing
    kind="read" MeshCentral download lane: the former ``ReadAllText`` command
    timed out through the MeshCentral PowerShell reply, and replacing it with
    another shell command is not the contract.

    A listing is one page of a **fixed order**: folders first, then name. Without a
    fixed order an offset means nothing — two calls could sort the same folder
    differently and skip or repeat rows. The reply carries the folder's own total
    and whether this page was the last, so the caller never has to guess that a
    short page was the end.

    The list command is cmdlet-only on purpose: no native program runs, so the
    PC reports no exit code (``no_exit_code``) and the existing result lane
    stays truthful.

    depth > 1 walks that many levels in one answer: every row carries its
    relative path and level, the walk stops at 200 rows with ``truncated``,
    and offset paging does not apply (the walk is one bounded answer).
    Hidden, system and reparse-point directories are listed but never
    descended into, so a shortcut cannot widen the walk past the granted
    root. recursive keeps the pre-#7447 name search rules instead: it matches
    the caller's name fragment while walking, stops at
    ``PC_SEARCH_SCAN_MAX_FILES`` walked entries or ``PC_SEARCH_MAX_LIMIT``
    matched rows and reports the cut through ``has_more``/``truncated``.
    """
    if op != "list":
        raise ValueError("only list uses the read-only command builder")
    if (not isinstance(offset, int) or isinstance(offset, bool) or offset < 0
            or not isinstance(page_size, int) or isinstance(page_size, bool)
            or not 1 <= page_size <= 2000):
        raise ValueError("a paging offset and a page size are required")
    if type(recursive) is not bool or type(depth) is not int or isinstance(depth, bool):
        raise ValueError("a depth and a recursive flag are validated booleans and integers")
    if not 1 <= depth <= 3 or (recursive and depth > 1):
        raise ValueError("depth is 1..3 and cannot combine with a recursive name search")
    if depth > 1 and (offset != 0 or filter_term is not None):
        raise ValueError("a deep walk is one bounded answer, not a page")
    if recursive and offset != 0:
        raise ValueError("a recursive search is one bounded answer, not a page")
    if recursive and (not isinstance(filter_term, str) or not filter_term):
        # The walk matches this fragment on the PC; without it the caller is
        # asking for an unbounded listing, which stays a depth-1 feature.
        raise ValueError("a recursive name search requires a filter term")
    if filter_term is not None:
        # The term is a name fragment, never a pattern: it travels as a single-quoted
        # literal and is escaped with the wildcard escaper before -like sees it. No
        # length cap is imposed here — the exec boundary already refuses an argument
        # the OS cannot carry — but a control character or an empty term is refused.
        if not isinstance(filter_term, str) or not filter_term:
            raise ValueError("a filter term must be non-empty text")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in filter_term):
            raise ValueError("a filter term may not carry control characters")
    # #7976: a bare drive is the volume root, not a drive-relative directory.
    folder = _pc_files_windows_folder(root, relative)
    # #7973: a path, a relative segment or a name fragment is carried as base64
    # of its UTF-8 bytes, never as characters in the command text. The MeshCentral
    # agent hands that text to a PowerShell console whose input decoder is the
    # PC's legacy code page on a Korean installation; Korean written into the
    # command arrives as mojibake, Get-ChildItem cannot find the folder and the
    # answer is an error instead of JSON (stage pc_list_output_invalid). An
    # ASCII-only command decodes to the exact value on the PC whatever that code
    # page is. The root/relative grant and reparse checks below are unchanged.
    # Measured through the same wrapper the executor sends: one page of 200 rows on
    # 컴1's System32 came back as 20,647 transcript bytes in 1,240 ms, and the
    # matching 500-row page as 53,979 bytes in 1,454 ms. `-First` alone silently cut
    # the folder at 200; `-Skip`/`-First` over a fixed sort is a page of the whole
    # list, and total/has_more make the cut visible.
    # #5994 D3: a listing must not open a shortcut folder either — the same
    # reparse walk the write lane uses refuses a folder that is reached through
    # a junction or a symbolic link below the granted root.
    guard_root = root.rstrip("\\/") + "\\"
    if guard_root.startswith("//"):
        # #7978: a UNC root reaches the guard in its Windows spelling, the same
        # way _pc_files_windows_folder spells the folder itself.
        guard_root = "\\\\" + guard_root[2:].replace("/", "\\")
    guard = (
        "$folder = " + ps_utf8_literal(folder) + ";"
        "$guardRoot = " + ps_utf8_literal(guard_root) + ";"
        "$relText = " + ps_utf8_literal(relative) + ";"
        "$guardHit = $null;"
        "try {"
        " $walk = $guardRoot;"
        " foreach ($seg in ($relText.Replace('/', '\\') -split '\\\\')) {"
        "  if (-not $seg) { continue };"
        "  $walk = Join-Path $walk $seg;"
        "  if (-not (Test-Path -LiteralPath $walk)) { break };"
        "  $item = Get-Item -LiteralPath $walk -Force -ErrorAction SilentlyContinue;"
        "  if ($item -and (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0))"
        "  { $guardHit = $walk; break } };"
        "} catch { $guardHit = $guardRoot };"
        "if ($guardHit) {"
        " @{error=" + ps_utf8_literal("이 위치는 바로가기 폴더를 거쳐서 볼 수 없습니다.")
        + "} | ConvertTo-Json -Compress"
        " } elseif (-not (Test-Path -LiteralPath $folder)) {"
        # A folder that is not there is a closed verdict, not a malformed page.
        # The engine can then answer pc_path_not_found instead of output_invalid.
        " @{error='path_not_found'} | ConvertTo-Json -Compress"
        " } else {"
    )
    if recursive:
        # A recursive name search walks the granted subtree and keeps only the
        # matching rows: at most PC_SEARCH_SCAN_MAX_FILES entries visited and
        # PC_SEARCH_MAX_LIMIT rows returned, with both cuts reported. The
        # descent never enters hidden, system or reparse-point directories, so
        # a shortcut cannot carry the walk past the granted root.
        # A literal substring, never a wildcard pattern: IndexOf keeps every
        # caller character (quote, semicolon, backtick, $()) a character on
        # both Windows PowerShell 5.1 and pwsh 7, where -like treats the
        # backtick differently. -like would also need an escape the caller
        # never asked for.
        match = (
            "$needle=" + ps_utf8_literal(filter_term) + ";"
        )
        walk = (
            "$ErrorActionPreference='SilentlyContinue';"
            "[Console]::OutputEncoding=New-Object Text.UTF8Encoding $false;"
            "$cap=" + str(PC_SEARCH_MAX_LIMIT) + ";"
            "$scan=" + str(PC_SEARCH_SCAN_MAX_FILES) + ";"
            "$skip=2 -bor 4 -bor 1024;"
            "$rows=New-Object System.Collections.ArrayList;"
            "$flags=@{truncated=$false;scan=$false};"
            "$scanned=0;"
            "$stop=$false;"
            "$full=$false;"
            "function Add-Match([object]$item,[string]$rel){"
            "  if($rows.Count -ge $cap){ $flags.truncated=$true; return };"
            "  [void]$rows.Add([ordered]@{Name=$item.Name; Length=$item.Length;"
            "  Modified=$item.LastWriteTimeUtc.ToString('o'); PSIsContainer=$item.PSIsContainer;"
            "  relative_path=$rel})"
            "};"
            "$frontier=@(@{dir=$folder; rel=''});"
            "while($frontier.Count -gt 0 -and -not $stop){"
            "  $next=@();"
            "  foreach($f in $frontier){"
            "    if($stop){ break };"
            "    foreach($i in @(Get-ChildItem -LiteralPath $f.dir -Force"
            " -ErrorAction SilentlyContinue)){"
            "      $scanned++;"
            "      if($scanned -gt $scan){ $flags.scan=$true; $stop=$true; break };"
            "      $rel=if($f.rel){ $f.rel + [char]92 + $i.Name } else { $i.Name };"
            # A name search answers with files: a folder name that matches is
            # not a result the caller can open, and it must not take one of the
            # 50 rows away from a file that does.
            "      if(-not $i.PSIsContainer -and $i.Name.IndexOf($needle,"
            "        [StringComparison]::OrdinalIgnoreCase) -ge 0){"
            # The first match past the cap is the proof that has_more is true;
            # a run of exactly 50 with nothing left is a complete answer.
            "        if($full){ $flags.truncated=$true; $stop=$true; break };"
            "        Add-Match $i $rel;"
            "        if($rows.Count -ge $cap){ $full=$true }"
            "      };"
            "      if($full){ continue };"
            "      if($i.PSIsContainer -and (($i.Attributes -band $skip) -eq 0)){"
            "        $next+=[ordered]@{dir=$i.FullName; rel=$rel}"
            "      }"
            "    }"
            "  };"
            "  $frontier=$next"
            "};"
            "$s=@($rows | Sort-Object -Property @{Expression={$_.relative_path}});"
            "@{offset=0; total=$s.Count; has_more=$flags.truncated;"
            " truncated=$flags.truncated; scan_truncated=$flags.scan;"
            " recursive=$true; items=$s}"
            " | ConvertTo-Json -Compress -Depth 3"
            + " }"
        )
        return guard + match + walk
    if depth > 1:
        # A depth walk answers in one bounded response: per level the children
        # are listed with their relative path and level, the walk descends
        # only into directories that are not hidden, system or reparse-point
        # folders, and the whole answer stops at 200 rows with ``truncated``.
        # Offset paging stays a depth-1 feature.
        walk = (
            "$ErrorActionPreference='SilentlyContinue';"
            "[Console]::OutputEncoding=New-Object Text.UTF8Encoding $false;"
            "$cap=" + str(_PC_LIST_DEPTH_ROW_CAP) + ";"
            "$maxDepth=" + str(depth) + ";"
            "$skip=2 -bor 4 -bor 1024;"
            "$rows=New-Object System.Collections.ArrayList;"
            "$flags=@{truncated=$false};"
            "$baseLen=" + str(len(folder.replace("/", "\\"))) + ";"
            "function Add-DepthRow([object]$item,[string]$rel,[int]$level){"
            "  if($rows.Count -ge $cap){ $flags.truncated=$true; return };"
            "  [void]$rows.Add([ordered]@{Name=$item.Name; Length=$item.Length;"
            "  Modified=$item.LastWriteTimeUtc.ToString('o'); PSIsContainer=$item.PSIsContainer;"
            "  relative_path=$rel; depth=$level})"
            "};"
            "$frontier=@(@{dir=$folder; rel=''});"
            "$level=1;"
            "while($frontier.Count -gt 0 -and $level -le $maxDepth){"
            "  $next=@();"
            "  $ordered=@();"
            "  foreach($f in $frontier){"
            "    foreach($i in @(Get-ChildItem -LiteralPath $f.dir -Force"
            " -ErrorAction SilentlyContinue)){"
            "      $rel=if($f.rel){ $f.rel + [char]92 + $i.Name } else { $i.Name };"
            "      $ordered+=[ordered]@{item=$i; rel=$rel}"
            "    }"
            "  };"
            "  $ordered=@($ordered | Sort-Object -Property rel);"
            "  foreach($e in $ordered){"
            "    if($rows.Count -ge $cap){ $flags.truncated=$true; break };"
            "    Add-DepthRow $e.item $e.rel $level"
            "  };"
            "  foreach($e in $ordered){"
            "    if($e.item.PSIsContainer"
            " -and (($e.item.Attributes -band $skip) -eq 0)){"
            "      $next+=[ordered]@{dir=$e.item.FullName; rel=$e.rel}"
            "    }"
            "  };"
            "  if($rows.Count -ge $cap){"
            # Exactly at the cap is only a cut when something was left: another
            # row at this level, or a deeper folder still to walk.
            "    if($flags.truncated -or ($next.Count -gt 0 -and $level -lt $maxDepth))"
            "    { $flags.truncated=$true };"
            "    break"
            "  };"
            "  $frontier=$next;"
            "  $level++"
            "};"
            "$s=@($rows | Sort-Object -Property @{Expression={$_.relative_path}});"
            "@{offset=0; total=$s.Count; has_more=$false;"
            " truncated=$flags.truncated; depth=" + str(depth) + "; items=$s}"
            " | ConvertTo-Json -Compress -Depth 3"
            + " }"
        )
        return guard + walk
    if filter_term is None:
        scan = ("$p=@(Get-ChildItem -LiteralPath $folder"
                " -Force -ErrorAction Stop);")
    else:
        scan = (
            "$needle=" + ps_utf8_literal(filter_term) + ";"
            "$filter=" + ps_utf8_literal(_pc_files_filter_prefilter(filter_term)) + ";"
            "$p=@(Get-ChildItem -LiteralPath $folder -Filter $filter"
            " -Force -ErrorAction Stop"
            " | Where-Object { $_.Name.IndexOf($needle,"
            "[StringComparison]::OrdinalIgnoreCase) -ge 0 });"
        )
    return (
        guard
        + scan
        + "$s=@($p | Sort-Object -Property @{Expression={-not $_.PSIsContainer}}, Name);"
        "$n=$s.Count;"
        "$pg=@($s | Select-Object -Skip " + str(offset) + " -First " + str(page_size)
        + " | Select-Object Name, Length, "
        "@{n='Modified';e={$_.LastWriteTimeUtc.ToString('o')}}, PSIsContainer);"
        "@{offset=" + str(offset) + "; total=$n;"
        " has_more=(($pg.Count + " + str(offset) + ") -lt $n); items=@($pg)}"
        " | ConvertTo-Json -Compress -Depth 3"
        + " }"
    )


