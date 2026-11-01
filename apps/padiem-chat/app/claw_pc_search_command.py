"""#6460 PC file search: the one PowerShell script the server will run.

The approved root, the query and the mode are server-owned values; the model
contributes only the query text and whether it means a file name or file
contents. Everything (``es.exe``) is used for name search when it is installed,
ripgrep for text/code content, and plain cmdlets are the fallback for both, so
the tool works on a PC that has neither program.

Two file classes are never opened:

* Office/PDF/HWPX documents are matched by file name only in this stage; their
  content is reported as ``deferred`` instead of being decoded here.
* A cloud placeholder (OneDrive and similar) carries the Offline or
  RecallOnDataAccess attribute. It is reported as ``not_downloaded`` and its
  bytes are never read, so a search never pulls a file down.
"""

from __future__ import annotations

from typing import Any

PC_SEARCH_MAX_LIMIT = 50
PC_SEARCH_MAX_QUERY_CHARS = 200
PC_SEARCH_MODES = ("name", "content")
#: The most files one content search will look at. A folder larger than this is
#: reported as ``scan_truncated`` rather than scanned for an unbounded time.
PC_SEARCH_SCAN_MAX_FILES = 2000
PC_SEARCH_OFFICE_EXTENSIONS = (".docx", ".xlsx", ".pdf", ".hwpx")
PC_SEARCH_TEXT_EXTENSIONS = (
    ".txt", ".md", ".csv", ".log", ".json", ".xml", ".yml", ".yaml",
    ".html", ".css", ".js", ".ts", ".py", ".ps1", ".sql", ".ini", ".cfg",
    ".bat", ".sh",
)
PC_SEARCH_ENGINES = frozenset({"everything", "ripgrep", "select-string", "list"})
PC_SEARCH_CONTENT_STATES = frozenset(
    {"matched", "name_only", "deferred", "not_downloaded"}
)


def pc_search_query(value: Any) -> str | None:
    """The one caller-supplied search text, or None when it is not usable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not 0 < len(text) <= PC_SEARCH_MAX_QUERY_CHARS:
        return None
    if any(ord(ch) < 32 for ch in text):
        return None
    return text


def pc_search_mode(value: Any) -> str | None:
    return value if isinstance(value, str) and value in PC_SEARCH_MODES else None


def _ps_literal(value: str) -> str:
    # A single-quoted PowerShell literal; the only escape is a doubled quote.
    return "'" + value.replace("'", "''") + "'"


def pc_search_command(
    *, root: str, query: str, mode: str, limit: int = PC_SEARCH_MAX_LIMIT,
) -> str:
    """Build the search script for one approved root.

    Raises ``ValueError`` for anything the caller did not already validate; the
    route refuses the request instead of running a widened command.
    """
    if mode not in PC_SEARCH_MODES:
        raise ValueError("unsupported search mode")
    if type(limit) is not int or not 0 < limit <= PC_SEARCH_MAX_LIMIT:
        raise ValueError("search limit out of range")
    text = pc_search_query(query)
    if text is None:
        raise ValueError("search query is not usable")
    if not isinstance(root, str) or not root or len(root) > 32000 or any(
        ord(ch) < 32 for ch in root
    ):
        raise ValueError("approved root is not usable")
    office = ",".join(_ps_literal(ext) for ext in PC_SEARCH_OFFICE_EXTENSIONS)
    text_ext = ",".join(_ps_literal(ext) for ext in PC_SEARCH_TEXT_EXTENSIONS)
    lines = [
        # The transcript is one JSON document: a non-terminating cmdlet error
        # must not print beside it, and UTF-8 keeps Korean names and snippets
        # out of the console code page.
        "$ErrorActionPreference='SilentlyContinue'",
        "[Console]::OutputEncoding=New-Object Text.UTF8Encoding $false",
        "$OutputEncoding=New-Object Text.UTF8Encoding $false",
        "$root=" + _ps_literal(root),
        "$query=" + _ps_literal(text),
        "$mode=" + _ps_literal(mode),
        "$limit=" + str(limit),
        "$scan=" + str(PC_SEARCH_SCAN_MAX_FILES),
        "$office=@(" + office + ")",
        "$textExt=@(" + text_ext + ")",
        # Offline = 0x1000, RecallOnDataAccess = 0x400000: a cloud placeholder
        # is never opened for content.
        "$offlineMask=4096 -bor 4194304",
        "$body=$root.Replace('/','\\')",
        "$rows=New-Object System.Collections.ArrayList",
        # A hashtable, not a script-scope variable: the transport runs this as
        # a command, where `$script:` is not the scope these names live in.
        "$flags=@{truncated=$false;scan=$false}",
        "$engine='list'",
        "function Add-Row([object]$item,[string]$kind,[object]$line,[string]$text){",
        "  if($rows.Count -ge $limit){ $flags.truncated=$true; return }",
        "  $rel=$item.FullName.Substring($body.Length).TrimStart([char]92,[char]47)",
        "  [void]$rows.Add([ordered]@{path=$rel;size_bytes=[int64]$item.Length;"
        "modified_utc=$item.LastWriteTimeUtc.ToString('o');content_state=$kind;"
        "line=$line;snippet=$text})",
        "}",
        "if($mode -eq 'name'){",
        "  $es=Get-Command es.exe -ErrorAction SilentlyContinue | Select-Object -First 1",
        "  if($es -and -not $query.StartsWith('-')){",
        "    $engine='everything'",
        "    $hits=@(& $es.Source -path $root -n ($limit+1) $query)",
        "    foreach($p in $hits){",
        "      if($rows.Count -ge $limit){ $flags.truncated=$true; break }",
        "      $full=[string]$p",
        "      if(-not $full){ continue }",
        "      $full=$full.Replace('/','\\')",
        "      if(-not $full.StartsWith($body,[StringComparison]::OrdinalIgnoreCase)){ continue }",
        "      $i=Get-Item -LiteralPath $full -Force -ErrorAction SilentlyContinue",
        "      if($i -eq $null -or $i.PSIsContainer){ continue }",
        "      $off=(($i.Attributes -band $offlineMask) -ne 0)",
        "      Add-Row $i $(if($off){'not_downloaded'}else{'name_only'}) $null ''",
        "    }",
        "  } else {",
        "    foreach($i in (Get-ChildItem -LiteralPath $root -Recurse -File -Force -ErrorAction SilentlyContinue)){",
        "      if($rows.Count -ge $limit){ $flags.truncated=$true; break }",
        "      if($i.Name.IndexOf($query,[StringComparison]::OrdinalIgnoreCase) -lt 0){ continue }",
        "      $off=(($i.Attributes -band $offlineMask) -ne 0)",
        "      Add-Row $i $(if($off){'not_downloaded'}else{'name_only'}) $null ''",
        "    }",
        "  }",
        "}",
        "if($mode -eq 'content'){",
        "  $files=New-Object System.Collections.ArrayList",
        "  $seen=0",
        "  foreach($i in (Get-ChildItem -LiteralPath $root -Recurse -File -Force -ErrorAction SilentlyContinue)){",
        "    $seen++",
        "    if($seen -gt $scan){ $flags.scan=$true; break }",
        "    if($rows.Count -ge $limit){ $flags.truncated=$true; break }",
        "    $ext=$i.Extension.ToLowerInvariant()",
        "    $nameHit=($i.Name.IndexOf($query,[StringComparison]::OrdinalIgnoreCase) -ge 0)",
        "    $off=(($i.Attributes -band $offlineMask) -ne 0)",
        "    if($office -contains $ext){",
        "      if($nameHit){ Add-Row $i 'deferred' $null '' }",
        "      continue",
        "    }",
        "    if($off){",
        "      if($nameHit){ Add-Row $i 'not_downloaded' $null '' }",
        "      continue",
        "    }",
        "    if($textExt -contains $ext){ [void]$files.Add($i) }",
        "    elseif($nameHit){ Add-Row $i 'name_only' $null '' }",
        "  }",
        "  $rg=Get-Command rg.exe -ErrorAction SilentlyContinue | Select-Object -First 1",
        "  if($files.Count -gt 0 -and $rg){",
        "    $engine='ripgrep'",
        "    for($start=0; $start -lt $files.Count; $start+=100){",
        "      if($rows.Count -ge $limit){ $flags.truncated=$true; break }",
        "      $end=[Math]::Min($start+99,$files.Count-1)",
        "      $paths=@()",
        "      for($n=$start;$n -le $end;$n++){ $paths+=$files[$n].FullName }",
        "      $hits=@(& $rg.Source --no-heading --line-number --color never --no-messages"
        " --fixed-strings --max-count 1 -- $query $paths)",
        "      foreach($line in $hits){",
        "        if($rows.Count -ge $limit){ $flags.truncated=$true; break }",
        "        if($line -match '^(.*?):(\\d+):(.*)$'){",
        "          $i=Get-Item -LiteralPath $matches[1] -Force -ErrorAction SilentlyContinue",
        "          if($i -eq $null){ continue }",
        "          $snippet=$matches[3].Trim()",
        "          if($snippet.Length -gt 200){ $snippet=$snippet.Substring(0,200) }",
        "          Add-Row $i 'matched' ([int]$matches[2]) $snippet",
        "        }",
        "      }",
        "    }",
        "  } elseif($files.Count -gt 0){",
        "    $engine='select-string'",
        "    foreach($f in $files){",
        "      if($rows.Count -ge $limit){ $flags.truncated=$true; break }",
        "      $hit=Select-String -LiteralPath $f.FullName -SimpleMatch -Pattern $query"
        " -List -ErrorAction SilentlyContinue | Select-Object -First 1",
        "      if($hit){",
        "        $snippet=$hit.Line.Trim()",
        "        if($snippet.Length -gt 200){ $snippet=$snippet.Substring(0,200) }",
        "        Add-Row $f 'matched' $hit.LineNumber $snippet",
        "      }",
        "    }",
        "  }",
        "}",
        "[ordered]@{ok=$true;mode=$mode;query=$query;engine=$engine;count=$rows.Count;"
        "truncated=$($flags.truncated);scan_truncated=$($flags.scan);entries=$rows}"
        " | ConvertTo-Json -Compress -Depth 5",
    ]
    return "\n".join(lines)


__all__ = [
    "PC_SEARCH_CONTENT_STATES",
    "PC_SEARCH_ENGINES",
    "PC_SEARCH_MAX_LIMIT",
    "PC_SEARCH_MAX_QUERY_CHARS",
    "PC_SEARCH_MODES",
    "PC_SEARCH_OFFICE_EXTENSIONS",
    "PC_SEARCH_SCAN_MAX_FILES",
    "PC_SEARCH_TEXT_EXTENSIONS",
    "pc_search_command",
    "pc_search_mode",
    "pc_search_query",
]
