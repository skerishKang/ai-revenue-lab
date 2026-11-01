"""#6460 PC large-file reads: one bounded range of one approved file.

A file is never sent whole. The model asks for a byte range of a text file or a
character range of an already-extracted document, and this module builds the
one PowerShell script that answers it:

* text files are read as UTF-8 and cut on a character boundary, so the answer
  never ends inside a multi-byte Korean character; ``next_offset`` is the
  first byte of the next chunk, and repeating the same request after an
  interruption returns exactly the same range;
* office/PDF/HWPX files are parsed by the existing reviewed parser child
  (``kagent.document_parser_child`` -> Core ``document_normalization``), never
  by a new parser, and the extracted text is sliced by characters. A document
  larger than the prefix bound is parsed from its leading bytes and says so.

Offsets are always server-declared: the caller may name a range, the PC never
expands it.
"""

from __future__ import annotations

from typing import Any

#: One answer carries at most this many bytes/characters. The Engine sends an
#: explicit length from its own setting; this is the transport ceiling.
PC_READ_CHUNK_MAX_BYTES = 1_000_000
PC_READ_OFFSET_MAX = 1 << 40
PC_READ_OFFICE_EXTENSIONS = (".docx", ".xlsx", ".pdf", ".hwpx")
PC_READ_OFFICE_MEDIA = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pdf": "application/pdf",
    ".hwpx": "application/hwp+zip",
}
PC_READ_OFFICE_PREFIX_BYTES = 16 * 1024 * 1024


def pc_read_offset(value: Any) -> int | None:
    if type(value) is not int or value < 0 or value > PC_READ_OFFSET_MAX:
        return None
    return value


def pc_read_length(value: Any) -> int | None:
    if type(value) is not int or not 0 < value <= PC_READ_CHUNK_MAX_BYTES:
        return None
    return value


def is_office_name(filename: str) -> bool:
    return isinstance(filename, str) and filename.lower().endswith(
        PC_READ_OFFICE_EXTENSIONS
    )


def office_media_type(filename: str) -> str | None:
    text = filename.lower()
    for ext, media in PC_READ_OFFICE_MEDIA.items():
        if text.endswith(ext):
            return media
    return None


def _ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def pc_read_chunk_command(
    *, root: str, relative: str, offset: int, length: int,
) -> str:
    """Build the one range-read script for ``root/relative``.

    ``ValueError`` means the caller did not validate its own values; the route
    refuses instead of running a widened command.
    """
    if (
        not isinstance(root, str) or not root or len(root) > 32000
        or any(ord(ch) < 32 for ch in root)
    ):
        raise ValueError("approved root is not usable")
    if (
        not isinstance(relative, str) or not relative or len(relative) > 2048
        or any(ord(ch) < 32 for ch in relative)
    ):
        raise ValueError("relative path is not usable")
    if pc_read_offset(offset) is None:
        raise ValueError("offset is not usable")
    if pc_read_length(length) is None:
        raise ValueError("length is not usable")
    file_name = relative.replace("\\", "/").rsplit("/", 1)[-1]
    office = is_office_name(file_name)
    lines = [
        "$ErrorActionPreference='SilentlyContinue'",
        "[Console]::OutputEncoding=New-Object Text.UTF8Encoding $false",
        "$OutputEncoding=New-Object Text.UTF8Encoding $false",
        "$path=" + _ps_literal(root.rstrip("/") + "/" + relative.replace("\\", "/")),
        "$offset=[int64]" + str(offset),
        "$length=[int64]" + str(length),
        "$items=Get-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue",
        "if($items -eq $null -or $items.PSIsContainer){",
        '  \'{"ok":false,"error":"not_a_file"}\'',
        "  return",
        "}",
        "$size=[int64]$items.Length",
    ]
    if office:
        lines.extend(_office_lines(file_name))
    else:
        lines.extend(_text_lines())
    return "\n".join(lines)


def _text_lines() -> list[str]:
    return [
        "if($offset -gt $size){",
        '  \'{"ok":false,"error":"offset_out_of_range","size_bytes":\' + $size + \'}\'',
        "  return",
        "}",
        "$fs=[IO.File]::OpenRead($path)",
        "$want=[int][Math]::Min($length+3,$size-$offset)",
        "$buf=New-Object byte[] $want",
        "[void]$fs.Seek($offset,[IO.SeekOrigin]::Begin)",
        "[void]$fs.Read($buf,0,$want)",
        "$fs.Close()",
        # Align the start: a model may name any offset (a search hit), so a
        # leading continuation byte moves to the next character's first byte.
        "$start=0",
        "while($start -lt $want -and ($buf[$start] -band 0xC0) -eq 0x80 -and $start -lt 3){ $start++ }",
        "$n=$want-$start",
        "$cut=0",
        "if($n -ge 0){",
        "  $i=0",
        "  while($i -lt $n){",
        "    $b=$buf[$start+$i]",
        "    $need=1",
        "    if(($b -band 0xE0) -eq 0xC0){ $need=2 }",
        "    elseif(($b -band 0xF0) -eq 0xE0){ $need=3 }",
        "    elseif(($b -band 0xF8) -eq 0xF0){ $need=4 }",
        "    if($i+$need -gt $n){ break }",
        "    $i=$i+$need",
        "  }",
        "  $cut=$i",
        "}",
        "if($cut -le 0){",
        '  \'{"ok":false,"error":"no_complete_character","size_bytes":\' + $size + \'}\'',
        "  return",
        "}",
        "$text=[Text.Encoding]::UTF8.GetString($buf,$start,$cut)",
        "$next=$offset+$start+$cut",
        "$eof=($next -ge $size)",
        "if($text.IndexOf([char]0) -ge 0){",
        '  \'{"ok":false,"error":"binary_text_rejected","size_bytes":\' + $size + \'}\'',
        "  return",
        "}",
        "[ordered]@{ok=$true;unit='bytes';size_bytes=$size;offset=$offset;"
        "length_bytes=($start+$cut);next_offset=$next;eof=$eof;text=$text}"
        " | ConvertTo-Json -Compress -Depth 4",
    ]


def _office_lines(file_name: str) -> list[str]:
    media = office_media_type(file_name) or ""
    return [
        "$py=Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1",
        "if($py -eq $null){",
        '  \'{"ok":false,"error":"extractor_unavailable","size_bytes":\' + $size + \'}\'',
        "  return",
        "}",
        "$prefix=[int64]" + str(PC_READ_OFFICE_PREFIX_BYTES),
        "$len=[int][Math]::Min($size,$prefix)",
        "$fs=[IO.File]::OpenRead($path)",
        "$buf=New-Object byte[] $len",
        "[void]$fs.Read($buf,0,$len)",
        "$fs.Close()",
        "$partial=($size -gt $len)",
        "$envelope=@{name=" + _ps_literal(file_name) + ";media_type="
        + _ps_literal(media) + ";base64=[Convert]::ToBase64String($buf)}"
        " | ConvertTo-Json -Compress",
        "$report=@($envelope | & $py.Source -P -m kagent.document_parser_child 2>$null)",
        "$parsed=$null",
        "try { $parsed=(($report -join '') | ConvertFrom-Json) } catch { $parsed=$null }",
        "if($parsed -eq $null -or $parsed.ok -ne $true -or $parsed.text -isnot [string]){",
        "  $code=if($parsed -ne $null -and $parsed.code){ ([string]$parsed.code"
        " -replace '[^a-z0-9_]','') } else { 'read_failed' }",
        "  if($code.Length -gt 40){ $code=$code.Substring(0,40) }",
        '  \'{"ok":false,"error":"\' + $code + \'","size_bytes":\' + $size + \'}\'',
        "  return",
        "}",
        "$text=$parsed.text",
        "$chars=[int64]$text.Length",
        "if($offset -gt $chars){",
        '  \'{"ok":false,"error":"offset_out_of_range","size_bytes":\' + $size'
        ' + \',"text_chars":\' + $chars + \'}\'',
        "  return",
        "}",
        "$take=[int][Math]::Min($length,$chars-$offset)",
        "$slice=if($take -gt 0){ $text.Substring([int]$offset,$take) } else { '' }",
        "$next=$offset+$take",
        "$eof=($next -ge $chars) -and (-not $partial)",
        "[ordered]@{ok=$true;unit='chars';size_bytes=$size;text_chars=$chars;"
        "offset=$offset;length_chars=$take;next_offset=$next;eof=$eof;"
        "partial=$partial;text=$slice} | ConvertTo-Json -Compress -Depth 4",
    ]


__all__ = [
    "PC_READ_CHUNK_MAX_BYTES",
    "PC_READ_OFFICE_EXTENSIONS",
    "PC_READ_OFFICE_MEDIA",
    "PC_READ_OFFICE_PREFIX_BYTES",
    "PC_READ_OFFSET_MAX",
    "is_office_name",
    "office_media_type",
    "pc_read_chunk_command",
    "pc_read_length",
    "pc_read_offset",
]
