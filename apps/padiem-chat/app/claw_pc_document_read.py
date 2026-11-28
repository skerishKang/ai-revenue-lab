"""#8953 3b: scoped PDF page / XLSX range from complete bounded source bytes.

Emits one PowerShell command body under the existing caller's registered-root
and ReparsePoint checks. The isolated child is a fixed module; it receives
only bytes and literal page/sheet selectors, not a filesystem path.
"""
from __future__ import annotations

import re
from padiem_ai_core.powershell_literal import ps_literal

PC_DOCUMENT_MAX_BYTES = 64 * 1024 * 1024
PC_DOCUMENT_RESPONSE_MAX_BYTES = 256 * 1024
PC_PDF_MAX_PAGES = 10
PC_XLSX_MAX_CELLS = 2000
_RANGE = re.compile(r"([A-Z]{1,3})([1-9][0-9]{0,6}):([A-Z]{1,3})([1-9][0-9]{0,6})\Z")


def valid_xlsx_range(cell_range: str) -> bool:
    if not isinstance(cell_range, str):
        return False
    match = _RANGE.fullmatch(cell_range)
    if match is None:
        return False
    a, first, b, last = match.groups()
    def col_index(value: str) -> int:
        index = 0
        for char in value:
            index = index * 26 + ord(char) - 64
        return index
    x, y = col_index(a), col_index(b)
    r, s = int(first), int(last)
    return (1 <= x <= y <= 16384 and 1 <= r <= s <= 1048576
            and (y - x + 1) * (s - r + 1) <= PC_XLSX_MAX_CELLS)


def pc_document_lines(*, name: str, page: int | None = None,
                      page_count: int | None = None,
                      sheet: str | None = None, cell_range: str | None = None) -> list[str]:
    pdf = page is not None or page_count is not None
    xlsx = sheet is not None or cell_range is not None
    if pdf == xlsx:
        raise ValueError("select one exact PDF or XLSX range")
    if pdf:
        if (not name.lower().endswith(".pdf") or type(page) is not int
                or not 1 <= page <= (1 << 40) or type(page_count) is not int
                or not 1 <= page_count <= PC_PDF_MAX_PAGES):
            raise ValueError("invalid PDF page range")
        selector = "$selection=[ordered]@{name=" + ps_literal(name)
        selector += ";media_type='application/pdf';base64=$base64;page=" + str(page)
        selector += ";page_count=" + str(page_count) + "}"
    else:
        if (not name.lower().endswith(".xlsx") or not isinstance(sheet, str)
                or not 0 < len(sheet) <= 128
                or any(ord(c) < 32 for c in sheet)
                or not valid_xlsx_range(cell_range)):
            raise ValueError("invalid XLSX sheet or rectangle")
        selector = "$selection=[ordered]@{name=" + ps_literal(name)
        selector += ";media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'"
        selector += ";base64=$base64;sheet=" + ps_literal(sheet)
        selector += ";range=" + ps_literal(cell_range) + "}"
    # No 16 MiB prefix; either the entire verified file is passed or it is
    # refused as source_limit_exceeded. The child cannot read arbitrary paths.
    return [
        "$maximum=[int64]" + str(PC_DOCUMENT_MAX_BYTES),
        "if($size -gt $maximum){",
        '  \'{"ok":false,"error":"source_limit_exceeded"}\'',
        "  return",
        "}",
        "$py=Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1",
        "if($null -eq $py){",
        '  \'{"ok":false,"error":"extractor_unavailable"}\'',
        "  return",
        "}",
        "try{$complete=[IO.File]::ReadAllBytes($path)}catch{",
        '  \'{"ok":false,"error":"read_failed"}\'',
        "  return",
        "}",
        "if($complete.Length -ne $size -or $complete.Length -gt $maximum){",
        '  \'{"ok":false,"error":"source_limit_exceeded"}\'',
        "  return",
        "}",
        "$base64=[Convert]::ToBase64String($complete)",
        selector,
        "$frame=ConvertTo-Json -InputObject $selection -Compress -Depth 4",
        "$reply=@($frame | & $py.Source -P -m kagent.document_selection_child 2>$null)",
        "if($LASTEXITCODE -ne 0 -or $reply.Count -ne 1){",
        '  \'{"ok":false,"error":"extractor_unavailable"}\'',
        "  return",
        "}",
        "$raw=[string]$reply[0]",
        "if([Text.Encoding]::UTF8.GetByteCount($raw) -gt "
        + str(PC_DOCUMENT_RESPONSE_MAX_BYTES) + "){",
        '  \'{"ok":false,"error":"response_bytes_limit"}\'',
        "  return",
        "}",
        "try{$report=ConvertFrom-Json -InputObject $raw}catch{$report=$null}",
        "if($null -eq $report -or $report.ok -isnot [bool]){",
        '  \'{"ok":false,"error":"read_failed"}\'',
        "  return",
        "}",
        "$raw",
    ]
