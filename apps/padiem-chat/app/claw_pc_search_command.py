"""#6460 PC file search: the one PowerShell script the server will run.

The approved roots, the query and the mode are server-owned values; the model
contributes only the query text, optionally one folder to search, and whether
it means a file name or file contents. Everything (``es.exe``) is used for name
search when it is installed, ripgrep for text/code content, and plain cmdlets
are the fallback for both, so the tool works on a PC that has neither program.

Office, PDF and HWPX documents are read through the reviewed PC-side parser
child (``kagent.document_parser_child``, Core ``document_normalization``) when
the connector interpreter is available: only the matching line travels back,
never the document. Two file classes are never opened:

* A cloud placeholder (OneDrive and similar) carries the Offline or
  RecallOnDataAccess attribute. It is reported as ``not_downloaded`` and its
  bytes are never read, so a search never pulls a file down.
* A document larger than the prefix bound is parsed from its first bytes only;
  the row says ``partial`` instead of pretending the whole file was read.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

PC_SEARCH_MAX_LIMIT = 50
PC_SEARCH_MAX_QUERY_CHARS = 200
PC_SEARCH_MODES = ("name", "content")
#: The most candidates one content search will look at across every root.
PC_SEARCH_SCAN_MAX_FILES = 2000
#: The most documents one content search opens with the parser child. Each one
#: is a separate process, so this bounds both the answer and its latency.
PC_SEARCH_MAX_OFFICE_FILES = 8
#: A document larger than this is parsed from this many leading bytes only.
PC_SEARCH_OFFICE_PREFIX_BYTES = 16 * 1024 * 1024
PC_SEARCH_OFFICE_EXTENSIONS = (".docx", ".xlsx", ".pdf", ".hwpx")
PC_SEARCH_OFFICE_MEDIA = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pdf": "application/pdf",
    ".hwpx": "application/hwp+zip",
}
PC_SEARCH_TEXT_EXTENSIONS = (
    ".txt", ".md", ".csv", ".log", ".json", ".xml", ".yml", ".yaml",
    ".html", ".css", ".js", ".ts", ".py", ".ps1", ".sql", ".ini", ".cfg",
    ".bat", ".sh",
)
PC_SEARCH_ENGINES = frozenset({"everything", "ripgrep", "select-string", "list"})
PC_SEARCH_OFFICE_READERS = frozenset({"none", "parser", "unavailable"})
PC_SEARCH_CONTENT_STATES = frozenset(
    {"matched", "name_only", "deferred", "not_downloaded", "partial"}
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


def pc_search_path(value: Any) -> str | None:
    """The optional folder the owner named: "" for all approved roots.

    A folder is a label the owner sees, optionally followed by a relative
    folder ("문서/2026"). Absolute paths and drive prefixes are refused here the
    same way the file tools refuse them; the server picks the real root.
    """
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > 2048:
        return None
    text = value.strip()
    if not text or text == ".":
        return ""
    if any(ord(ch) < 32 for ch in text):
        return None
    text = text.replace("\\", "/").rstrip("/")
    if text.startswith("/") or (len(text) >= 2 and text[1] == ":"):
        return None
    parts = text.split("/")
    if any(part in ("", ".", "..") or ":" in part for part in parts):
        return None
    return text


def pc_search_roots(value: Any) -> list[tuple[str, str]] | None:
    """The approved roots as ``(label, path)`` pairs, or None when malformed."""
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
        return None
    roots: list[tuple[str, str]] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            return None
        label, path = entry.get("label"), entry.get("path")
        if (
            not isinstance(label, str) or not label or len(label) > 120
            or any(ord(ch) < 32 for ch in label)
            or not isinstance(path, str) or not path or len(path) > 32000
            or any(ord(ch) < 32 for ch in path)
        ):
            return None
        roots.append((label, path))
    return roots or None


def _ps_literal(value: str) -> str:
    # A single-quoted PowerShell literal; the only escape is a doubled quote.
    return "'" + value.replace("'", "''") + "'"


def _ps_array(values: Iterable[str]) -> str:
    return ",".join(_ps_literal(value) for value in values)


def pc_search_command(
    *, roots: Iterable[Any], query: str, mode: str,
    limit: int = PC_SEARCH_MAX_LIMIT,
) -> str:
    """Build the search script for the approved roots.

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
    parsed_roots = pc_search_roots(roots)
    if parsed_roots is None:
        raise ValueError("approved roots are not usable")
    root_literals = ",".join(
        "@{label=" + _ps_literal(label) + ";path=" + _ps_literal(path) + "}"
        for label, path in parsed_roots
    )
    media_literals = ";".join(
        _ps_literal(ext) + "=" + _ps_literal(media)
        for ext, media in PC_SEARCH_OFFICE_MEDIA.items()
    )
    lines = [
        # The transcript is one JSON document: a non-terminating cmdlet error
        # must not print beside it, and UTF-8 keeps Korean names and snippets
        # out of the console code page.
        "$ErrorActionPreference='SilentlyContinue'",
        "[Console]::OutputEncoding=New-Object Text.UTF8Encoding $false",
        "$OutputEncoding=New-Object Text.UTF8Encoding $false",
        "$query=" + _ps_literal(text),
        "$mode=" + _ps_literal(mode),
        "$limit=" + str(limit),
        "$scan=" + str(PC_SEARCH_SCAN_MAX_FILES),
        "$maxOffice=" + str(PC_SEARCH_MAX_OFFICE_FILES),
        "$prefix=[int64]" + str(PC_SEARCH_OFFICE_PREFIX_BYTES),
        "$roots=@(" + root_literals + ")",
        "$multi=($roots.Count -gt 1)",
        "$office=@(" + _ps_array(PC_SEARCH_OFFICE_EXTENSIONS) + ")",
        "$officeMedia=@{" + media_literals + "}",
        "$textExt=@(" + _ps_array(PC_SEARCH_TEXT_EXTENSIONS) + ")",
        # Offline = 0x1000, RecallOnDataAccess = 0x400000: a cloud placeholder
        # is never opened for content.
        "$offlineMask=4096 -bor 4194304",
        "$rows=New-Object System.Collections.ArrayList",
        # A hashtable, not a script-scope variable: the transport runs this as
        # a command, where `$script:` is not the scope these names live in.
        "$flags=@{truncated=$false;scan=$false;engine='list';office='none'}",
        "function Add-Row([object]$item,[string]$label,[string]$kind,[object]$line,"
        "[string]$text,[string]$reason,[string]$base){",
        "  if($rows.Count -ge $limit){ $flags.truncated=$true; return }",
        "  $rel=$item.FullName.Substring($base.Length).TrimStart([char]92,[char]47)",
        "  if($multi){ $rel=$label + '/' + $rel }",
        "  [void]$rows.Add([ordered]@{path=$rel;size_bytes=[int64]$item.Length;"
        "modified_utc=$item.LastWriteTimeUtc.ToString('o');content_state=$kind;"
        "line=$line;snippet=$text;reason=$reason})",
        "}",
        "if($mode -eq 'name'){",
        "  $es=Get-Command es.exe -ErrorAction SilentlyContinue | Select-Object -First 1",
        "  if($es -and -not $query.StartsWith('-')){",
        "    $flags.engine='everything'",
        "    foreach($r in $roots){",
        "      $hits=@(& $es.Source -path $r.path -n ($limit+1) $query)",
        "      foreach($p in $hits){",
        "        if($rows.Count -ge $limit){ $flags.truncated=$true; break }",
        "        $full=([string]$p).Replace('/','\\')",
        "        if(-not $full){ continue }",
        "        if(-not $full.StartsWith($r.path.Replace('/','\\'),[StringComparison]::OrdinalIgnoreCase)){ continue }",
        "        $i=Get-Item -LiteralPath $full -Force -ErrorAction SilentlyContinue",
        "        if($i -eq $null -or $i.PSIsContainer){ continue }",
        "        $off=(($i.Attributes -band $offlineMask) -ne 0)",
        "        Add-Row $i $r.label $(if($off){'not_downloaded'}else{'name_only'}) $null '' '' $r.path",
        "      }",
        "    }",
        "  } else {",
        "    foreach($r in $roots){",
        "      foreach($i in (Get-ChildItem -LiteralPath $r.path -Recurse -File -Force -ErrorAction SilentlyContinue)){",
        "        if($rows.Count -ge $limit){ $flags.truncated=$true; break }",
        "        if($i.Name.IndexOf($query,[StringComparison]::OrdinalIgnoreCase) -lt 0){ continue }",
        "        $off=(($i.Attributes -band $offlineMask) -ne 0)",
        "        Add-Row $i $r.label $(if($off){'not_downloaded'}else{'name_only'}) $null '' '' $r.path",
        "      }",
        "    }",
        "  }",
        "}",
        "if($mode -eq 'content'){",
        "  $texts=New-Object System.Collections.ArrayList",
        "  $byPath=@{}",
        "  $offices=New-Object System.Collections.ArrayList",
        "  foreach($r in $roots){",
        # The scan budget is per approved root: one large folder must never
        # consume the budget of the folders that come after it.
        "    $seen=0",
        "    foreach($i in (Get-ChildItem -LiteralPath $r.path -Recurse -File -Force -ErrorAction SilentlyContinue)){",
        "      $seen++",
        "      if($seen -gt $scan){ $flags.scan=$true; break }",
        "      if($rows.Count -ge $limit){ $flags.truncated=$true; break }",
        "      $ext=$i.Extension.ToLowerInvariant()",
        "      $nameHit=($i.Name.IndexOf($query,[StringComparison]::OrdinalIgnoreCase) -ge 0)",
        "      $off=(($i.Attributes -band $offlineMask) -ne 0)",
        "      if($off){",
        "        if($nameHit){ Add-Row $i $r.label 'not_downloaded' $null '' '' $r.path }",
        "        continue",
        "      }",
        "      if($office -contains $ext){",
        "        [void]$offices.Add([pscustomobject]@{item=$i;label=$r.label;root=$r.path;type=$officeMedia[$ext]})",
        "        continue",
        "      }",
        "      if($textExt -contains $ext){",
        "        $entry=[pscustomobject]@{item=$i;label=$r.label;root=$r.path}",
        "        [void]$texts.Add($entry)",
        "        $byPath[$i.FullName]=$entry",
        "        continue",
        "      }",
        "      if($nameHit){ Add-Row $i $r.label 'name_only' $null '' '' $r.path }",
        "    }",
        "  }",
        "  $rg=Get-Command rg.exe -ErrorAction SilentlyContinue | Select-Object -First 1",
        "  if($texts.Count -gt 0 -and $rg){",
        "    $flags.engine='ripgrep'",
        "    for($start=0; $start -lt $texts.Count; $start+=100){",
        "      if($rows.Count -ge $limit){ $flags.truncated=$true; break }",
        "      $end=[Math]::Min($start+99,$texts.Count-1)",
        "      $paths=@()",
        "      for($n=$start;$n -le $end;$n++){ $paths+=$texts[$n].item.FullName }",
        "      $hits=@(& $rg.Source --no-heading --line-number --color never --no-messages"
        " --fixed-strings --max-count 1 -- $query $paths)",
        "      foreach($line in $hits){",
        "        if($rows.Count -ge $limit){ $flags.truncated=$true; break }",
        "        if($line -match '^(.*?):(\\d+):(.*)$'){",
        "          $snippet=$matches[3].Trim()",
        "          if($snippet.Length -gt 200){ $snippet=$snippet.Substring(0,200) }",
        "          $entry=$byPath[$matches[1]]",
        "          if($entry -eq $null){ continue }",
        "          Add-Row $entry.item $entry.label 'matched' ([int]$matches[2]) $snippet '' $entry.root",
        "        }",
        "      }",
        "    }",
        "  } elseif($texts.Count -gt 0){",
        "    $flags.engine='select-string'",
        "    foreach($f in $texts){",
        "      if($rows.Count -ge $limit){ $flags.truncated=$true; break }",
        "      $hit=Select-String -LiteralPath $f.item.FullName -SimpleMatch -Pattern $query"
        " -List -ErrorAction SilentlyContinue | Select-Object -First 1",
        "      if($hit){",
        "        $snippet=$hit.Line.Trim()",
        "        if($snippet.Length -gt 200){ $snippet=$snippet.Substring(0,200) }",
        "        Add-Row $f.item $f.label 'matched' $hit.LineNumber $snippet '' $f.root",
        "      }",
        "    }",
        "  }",
        "  if($offices.Count -gt 0){",
        "    $py=Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1",
        "    $parser=$false",
        "    if($py){",
        "      $probe=@('{ }' | & $py.Source -P -m kagent.document_parser_child 2>$null)",
        "      try { $parser=((($probe -join '') | ConvertFrom-Json).ok -eq $false) } catch { $parser=$false }",
        "    }",
        "    if($parser){ $flags.office='parser' } else { $flags.office='unavailable' }",
        "    $opened=0",
        "    foreach($o in $offices){",
        "      if($rows.Count -ge $limit){ $flags.truncated=$true; break }",
        "      $nameHit=($o.item.Name.IndexOf($query,[StringComparison]::OrdinalIgnoreCase) -ge 0)",
        "      if(-not $parser){",
        "        if($nameHit){ Add-Row $o.item $o.label 'deferred' $null '' 'extractor_unavailable' $o.root }",
        "        continue",
        "      }",
        "      if($opened -ge $maxOffice){",
        "        if($nameHit){ Add-Row $o.item $o.label 'deferred' $null '' 'office_cap' $o.root }",
        "        else { $flags.truncated=$true }",
        "        continue",
        "      }",
        "      $opened++",
        "      $fs=[IO.File]::OpenRead($o.item.FullName)",
        "      $len=[int][Math]::Min($fs.Length,$prefix)",
        "      $buf=New-Object byte[] $len",
        "      [void]$fs.Read($buf,0,$len)",
        "      $fs.Close()",
        "      $partial=([int64]$o.item.Length -gt [int64]$len)",
        "      $envelope=@{name=$o.item.Name;media_type=$o.type;base64=[Convert]::ToBase64String($buf)} | ConvertTo-Json -Compress",
        "      $report=@($envelope | & $py.Source -P -m kagent.document_parser_child 2>$null)",
        "      $parsed=$null",
        "      try { $parsed=(($report -join '') | ConvertFrom-Json) } catch { $parsed=$null }",
        "      if($parsed -ne $null -and $parsed.ok -eq $true -and $parsed.text -is [string]){",
        "        $idx=$parsed.text.IndexOf($query,[StringComparison]::OrdinalIgnoreCase)",
        "        if($idx -ge 0){",
        "          $startText=$parsed.text.LastIndexOf([char]10,$idx)+1",
        "          $endText=$parsed.text.IndexOf([char]10,$idx)",
        "          if($endText -lt 0){ $endText=$parsed.text.Length }",
        "          $lineText=$parsed.text.Substring($startText,$endText-$startText).Trim()",
        "          if($lineText.Length -gt 200){ $lineText=$lineText.Substring(0,200) }",
        "          Add-Row $o.item $o.label 'matched' $null $lineText $(if($partial){'prefix_only'}else{''}) $o.root",
        "        } elseif($nameHit){",
        "          Add-Row $o.item $o.label 'name_only' $null '' '' $o.root",
        "        }",
        "      } elseif($partial){",
        "        Add-Row $o.item $o.label 'partial' $null '' 'prefix_only' $o.root",
        "      } elseif($nameHit){",
        "        $code=if($parsed -ne $null -and $parsed.code){ ([string]$parsed.code -replace '[^a-z0-9_]','') } else { 'read_failed' }",
        "        if($code.Length -gt 40){ $code=$code.Substring(0,40) }",
        "        Add-Row $o.item $o.label 'deferred' $null '' $code $o.root",
        "      }",
        "    }",
        "  }",
        "}",
        "[ordered]@{ok=$true;mode=$mode;query=$query;engine=$($flags.engine);"
        "office=$($flags.office);count=$($rows.Count);truncated=$($flags.truncated);"
        "scan_truncated=$($flags.scan);entries=$rows}"
        " | ConvertTo-Json -Compress -Depth 5",
    ]
    return "\n".join(lines)


__all__ = [
    "PC_SEARCH_CONTENT_STATES",
    "PC_SEARCH_ENGINES",
    "PC_SEARCH_MAX_LIMIT",
    "PC_SEARCH_MAX_OFFICE_FILES",
    "PC_SEARCH_MAX_QUERY_CHARS",
    "PC_SEARCH_MODES",
    "PC_SEARCH_OFFICE_EXTENSIONS",
    "PC_SEARCH_OFFICE_MEDIA",
    "PC_SEARCH_OFFICE_PREFIX_BYTES",
    "PC_SEARCH_OFFICE_READERS",
    "PC_SEARCH_SCAN_MAX_FILES",
    "PC_SEARCH_TEXT_EXTENSIONS",
    "pc_search_command",
    "pc_search_mode",
    "pc_search_path",
    "pc_search_query",
    "pc_search_roots",
]
