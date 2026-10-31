"""#5573 follow-up: the byte work the connect program's build cannot get from ``csc``.

Two jobs:

  * make two builds of one source produce one file. The Framework compiler writes a
    random module id and a compile-time stamp, so identical code hashes differently
    every run; both are replaced with values derived from the source.
  * put the product's own name in the file. There is no code signature, so the name
    Windows shows in the elevation prompt and in a file list is whatever the version
    resource says - and it says PADIEM, with no other operator name anywhere.

The version resource is written here by hand because no resource compiler ships with
Windows. Only the strings change: the string-table key and the translation pair are
read back from the block the compiler did write, so the locale stays exactly where
the compiler put it.

Nothing in this file is Windows-specific to run - it reads and writes bytes - which
is why the test can read the same artifact back instead of trusting the builder.
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import sys

#: What the file says about itself on a machine that has never seen this product.
#: Company and product are the brand; the description is the sentence in the
#: elevation prompt. No other name for the operator appears in the file.
PRODUCT_NAME = "PADIEM"
COMPANY_NAME = "PADIEM"
FILE_DESCRIPTION = "PADIEM PC 연결"
INTERNAL_NAME = "padiem-pc-connect"
ORIGINAL_FILENAME = "padiem-pc-connect.exe"
LEGAL_COPYRIGHT = "PADIEM"
FILE_VERSION = (1, 0, 0, 0)

#: Sorted by key: the resource a properties dialog shows, and the test that reads it.
VERSION_STRINGS: tuple[tuple[str, str], ...] = (
    ("CompanyName", COMPANY_NAME),
    ("FileDescription", FILE_DESCRIPTION),
    ("FileVersion", "%d.%d.%d.%d" % FILE_VERSION),
    ("InternalName", INTERNAL_NAME),
    ("LegalCopyright", LEGAL_COPYRIGHT),
    ("OriginalFilename", ORIGINAL_FILENAME),
    ("ProductName", PRODUCT_NAME),
    ("ProductVersion", "%d.%d.%d.%d" % FILE_VERSION),
)

_RT_VERSION = 16
_METADATA_SIGNATURE = b"BSJB"
_GUID_STREAM = b"#GUID"
_MVID_PREFIX = "PADIEM-MVID|"
_FIXED_FILE_INFO_SIZE = 52


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _sections(data: bytes) -> list[tuple[int, int, int, int]]:
    """(virtual address, virtual size, raw offset, raw size) for every section."""
    pe = _u32(data, 0x3C)
    count = _u16(data, pe + 6)
    table = pe + 24 + _u16(data, pe + 20)
    found = []
    for index in range(count):
        # The header stores the sizes before the addresses they belong to.
        virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
            "<IIII", data, table + 40 * index + 8)
        found.append((virtual_address, virtual_size, raw_offset, raw_size))
    return found


def _section_table_offset(data: bytes) -> int:
    pe = _u32(data, 0x3C)
    return pe + 24 + _u16(data, pe + 20)


def _data_directory(data: bytes, index: int) -> tuple[int, int]:
    """One directory entry as (RVA, size), read from the compiler's own layout."""
    pe = _u32(data, 0x3C)
    optional_size = _u16(data, pe + 20)
    # The sixteen entries end exactly where SizeOfOptionalHeader says the optional
    # header does, so the directory start is that size minus 128 bytes of entries.
    directories = pe + 24 + optional_size - 128
    return struct.unpack_from("<II", data, directories + 8 * index)


def _file_offset(sections: list[tuple[int, int, int, int]], rva: int) -> int:
    for virtual_address, virtual_size, raw_offset, raw_size in sections:
        span = max(virtual_size, raw_size)
        if virtual_address <= rva < virtual_address + span:
            return raw_offset + (rva - virtual_address)
    raise ValueError("pe_rva_outside_section")


class _Node:
    """One block of the version tree: a key, an optional value, optional children.

    Every offset inside a block is measured from that block's own start, which is
    what the compiler does and what Windows reads, and every block is padded to a
    multiple of four so the next one begins where the last ended.
    """

    __slots__ = ("key", "value", "kind", "children")

    def __init__(self, key: str, value: bytes = b"", kind: int = 1) -> None:
        self.key = key
        self.value = value
        self.kind = kind
        self.children: list[_Node] = []

    def add(self, child: "_Node") -> "_Node":
        self.children.append(child)
        return child

    def build(self) -> bytes:
        key_bytes = self.key.encode("utf-16-le") + b"\x00\x00"
        value_length = len(self.value) // 2 if self.kind == 1 else len(self.value)
        parts = [key_bytes]
        consumed = 6 + len(key_bytes)
        pad = (-consumed) % 4
        parts.append(b"\x00" * pad)
        consumed += pad
        parts.append(self.value)
        consumed += len(self.value)
        for child in self.children:
            pad = (-consumed) % 4
            parts.append(b"\x00" * pad)
            consumed += pad
            blob = child.build()
            parts.append(blob)
            consumed += len(blob)
        pad = (-consumed) % 4
        parts.append(b"\x00" * pad)
        # consumed already counts the six-byte header the caller is about to write.
        total = consumed + pad
        return struct.pack("<HHH", total, value_length, self.kind) + b"".join(parts)


def _text(value: str) -> bytes:
    return (value + "\x00").encode("utf-16-le")


def _fixed_file_info() -> bytes:
    high = (FILE_VERSION[0] << 16) | FILE_VERSION[1]
    low = (FILE_VERSION[2] << 16) | FILE_VERSION[3]
    fields = (0xFEEF04BD, 0x00010000, high, low, high, low,
              0x0000003F, 0x00000000, 0x00040004, 0x00000001, 0x00000000,
              0x00000000, 0x00000000)
    packed = struct.pack("<" + "I" * len(fields), *fields)
    if len(packed) != _FIXED_FILE_INFO_SIZE:
        raise ValueError("fixed_file_info_size")
    return packed


def build_version_info(language: int, codepage: int, table_key: str) -> bytes:
    """The whole VS_VERSION_INFO tree, lengths already summed."""
    root = _Node("VS_VERSION_INFO", _fixed_file_info(), kind=0)
    strings = root.add(_Node("StringFileInfo", kind=1))
    table = strings.add(_Node(table_key, kind=1))
    for key, value in VERSION_STRINGS:
        table.add(_Node(key, _text(value), kind=1))
    variables = root.add(_Node("VarFileInfo", kind=1))
    variables.add(_Node("Translation", struct.pack("<HH", language, codepage), kind=0))
    return root.build()


def _resource_image(data: bytes) -> tuple[bytes, int, int]:
    """(the resource section's bytes, its RVA, its file offset)."""
    rva, size = _data_directory(data, 2)
    if not rva or not size:
        raise ValueError("pe_no_resource_section")
    base = _file_offset(_sections(data), rva)
    return data[base:base + size], rva, base


def _walk(directory: bytes, offset: int) -> list[tuple[int, int]]:
    """Every (data-entry file offset, entry's own index) below one directory."""
    named = _u16(directory, offset + 12)
    by_id = _u16(directory, offset + 14)
    found: list[tuple[int, int]] = []
    for index in range(named + by_id):
        entry = offset + 16 + 8 * index
        second = _u32(directory, entry + 4)
        if second & 0x80000000:
            found.extend(_walk(directory, second & 0x7FFFFFFF))
        else:
            found.append((second & 0x7FFFFFFF, index))
    return found


def _version_entry(tree: bytes) -> int:
    """The file offset of the RT_VERSION data entry, or a refusal.

    Only the id-named path is followed: a resource somebody renamed is not the
    version block Windows reads, and writing to the wrong leaf would say nothing.
    """
    named = _u16(tree, 12)
    by_id = _u16(tree, 14)
    for index in range(named + by_id):
        entry = 16 + 8 * index
        if _u32(tree, entry) != _RT_VERSION:
            continue
        second = _u32(tree, entry + 4)
        if not (second & 0x80000000):
            return second & 0x7FFFFFFF
        for language in _walk(tree, second & 0x7FFFFFFF):
            return language[0]
    raise ValueError("pe_no_version_resource")


def with_product_version(data: bytes) -> bytes:
    """The same executable, whose version resource says PADIEM.

    The new block does not replace the one the compiler wrote - that block is
    followed in the file by the manifest, and a longer description would overwrite
    it. It is appended after the last byte any resource touches, and the directory
    entry is repointed, so nothing that was already there moves. Then the section
    grows, and only the sections that sit after it in the file change their raw
    offset; every RVA a caller reads is virtual and stays exactly as it was.
    """
    tree, rva, base = _resource_image(data)
    entry = _version_entry(tree)
    used = 0
    named = _u16(tree, 12) + _u16(tree, 14)
    for index in range(named):
        # The second word of a directory entry says where it points, and its high
        # bit says whether that is another directory or the data itself.
        second = _u32(tree, 16 + 8 * index + 4)
        if second & 0x80000000:
            for leaf, _ in _walk(tree, second & 0x7FFFFFFF):
                leaf_rva, leaf_size = struct.unpack_from("<II", tree, leaf)
                used = max(used, leaf_rva - rva + leaf_size)
        else:
            leaf_rva, leaf_size = struct.unpack_from("<II", tree, second & 0x7FFFFFFF)
            used = max(used, leaf_rva - rva + leaf_size)
    language, codepage, table_key = _locale_of_default_block(data)
    block = build_version_info(language, codepage, table_key)
    placed = used + ((4 - (used % 4)) % 4)
    patched = bytearray(tree[:used])
    patched += b"\x00" * (placed - used)
    patched += block
    struct.pack_into("<II", patched, entry, rva + placed, len(block))
    return _replace_resource_section(data, base, bytes(patched))


def _parse_node(block: bytes, offset: int) -> dict[str, object] | None:
    """One version block and everything under it, read the way it was written.

    Offsets inside a block are counted from that block's own start and rounded up to
    a four-byte boundary before a value or a child begins - the rule the builder
    above follows, and the one a properties dialog depends on.
    """
    if offset + 6 > len(block):
        return None
    total = _u16(block, offset)
    if total == 0 or offset + total > len(block):
        return None
    value_length = _u16(block, offset + 2)
    kind = _u16(block, offset + 4)
    key_end = offset + 6
    while key_end + 1 < len(block) and _u16(block, key_end) != 0:
        key_end += 2
    key = block[offset + 6:key_end].decode("utf-16-le", errors="replace")
    position = key_end + 2 - offset
    position += (-position) % 4
    size = value_length if kind == 0 else value_length * 2
    node: dict[str, object] = {
        "key": key,
        "kind": kind,
        "value": block[offset + position: offset + position + size],
        "children": [],
    }
    children = node["children"]
    cursor = position + size
    cursor += (-cursor) % 4
    while cursor < total:
        child = _parse_node(block, offset + cursor)
        if child is None:
            break
        assert isinstance(children, list)
        children.append(child)
        step = _u16(block, offset + cursor)
        step += (-step) % 4
        cursor += step
    return node


def _version_tree(data: bytes) -> dict[str, object] | None:
    tree, rva, _ = _resource_image(data)
    entry = _version_entry(tree)
    block_rva, block_size = struct.unpack_from("<II", tree, entry)
    return _parse_node(tree[block_rva - rva: block_rva - rva + block_size], 0)


def _descend(node: dict[str, object] | None, *keys: str) -> dict[str, object] | None:
    current = node
    for key in keys:
        direct = [child for child in (current or {}).get("children", [])  # type: ignore[union-attr]
                  if child.get("key") == key]
        current = direct[0] if direct else None
    return current


def _locale_of_default_block(data: bytes) -> tuple[int, int, str]:
    """The string table the compiler named, and the same name as a language pair.

    Only the table key is read back. A properties dialog finds its strings by
    formatting the Translation pair as eight hex digits and looking up a table of
    that name, so the two must agree; carrying the compiler's own key over is what
    keeps them agreeing without guessing.
    """
    root = _version_tree(data)
    table_key = "000004b0"
    strings = _descend(root, "StringFileInfo")
    if strings and strings.get("children"):
        table_key = str(strings["children"][0]["key"]) or table_key  # type: ignore[index]
    try:
        language = int(table_key[0:4], 16)
        codepage = int(table_key[4:8], 16)
    except ValueError:
        language, codepage = 0x0000, 0x04B0
    return language, codepage, table_key


def read_version_info(data: bytes) -> dict[str, str]:
    """The strings a person sees in a file's properties, read back from the bytes.

    The test reads through this instead of trusting the builder: a version block
    Windows cannot parse reports no name at all, and the whole point of writing one
    is what shows up on somebody's screen.
    """
    names = {key for key, _ in VERSION_STRINGS}
    found: dict[str, str] = {}
    table = _descend(_version_tree(data), "StringFileInfo")
    if table is None:
        return found
    for entry in table.get("children", []):  # type: ignore[union-attr]
        for value in entry.get("children", []):  # type: ignore[union-attr]
            key = str(value.get("key"))
            if key in names and value.get("kind") == 1:
                found[key] = bytes(value["value"]).decode(
                    "utf-16-le", errors="replace").rstrip("\x00")
    return found


def _replace_resource_section(data: bytes, base: int, grown: bytes) -> bytes:
    """Put the resource section's new bytes in and move what follows them."""
    sections = _sections(data)
    table = _section_table_offset(data)
    index = next(slot for slot, (_, _, raw_offset, raw_size) in enumerate(sections)
                 if raw_offset <= base < raw_offset + raw_size)
    entry = table + 40 * index
    raw_offset, raw_size = sections[index][2], sections[index][3]
    file_alignment = _u32(data, _u32(data, 0x3C) + 24 + 60)
    aligned = -(-len(grown) // file_alignment) * file_alignment
    if aligned < raw_size:
        # A section only grows here: shrinking one that Windows already maps would
        # move data nothing in this file knows about.
        aligned = raw_size
    delta = aligned - raw_size
    out = bytearray(data[:raw_offset])
    out += grown
    out += b"\x00" * (aligned - len(grown))
    out += data[raw_offset + raw_size:]
    struct.pack_into("<I", out, entry + 8, len(grown))
    struct.pack_into("<I", out, entry + 16, aligned)
    # The resource directory carries the same size the section header does; leaving
    # it at the old value would tell a reader the tree is shorter than it is, and
    # the block appended past the end would simply not exist.
    directories = _section_table_offset(data) - 128
    struct.pack_into("<I", out, directories + 8 * 2 + 4, len(grown))
    for later in range(index + 1, len(sections)):
        other = table + 40 * later
        struct.pack_into("<I", out, other + 20, _u32(bytes(out), other + 20) + delta)
    return bytes(out)


def make_reproducible(data: bytes, seed: str, *, product_version: bool = True) -> bytes:
    """The two values the compiler invents, replaced; then the product's own name."""
    out = bytearray(data)
    pe = _u32(out, 0x3C)
    struct.pack_into("<I", out, pe + 8, 0)
    root = bytes(out).find(_METADATA_SIGNATURE)
    if root < 0:
        raise ValueError("no_cli_metadata_root")
    version_length = _u32(out, root + 12)
    cursor = root + 16 + ((version_length + 3) & ~3)
    streams = _u16(out, cursor + 2)
    cursor += 4
    patched = 0
    for _ in range(streams):
        offset, size = struct.unpack_from("<II", out, cursor)
        name_start = cursor + 8
        name_end = name_start
        while out[name_end] != 0:
            name_end += 1
        name = bytes(out[name_start:name_end])
        cursor += 8 + (((name_end - name_start) + 1 + 3) & ~3)
        if name != _GUID_STREAM:
            continue
        heap = root + offset
        for index in range(size // 16):
            digest = hashlib.sha256(
                f"{_MVID_PREFIX}{index}|{seed}".encode("utf-8")).digest()[:16]
            out[heap + 16 * index: heap + 16 * index + 16] = digest
            patched += 1
    if patched == 0:
        raise ValueError("no_module_id_in_compiled_file")
    return with_product_version(bytes(out)) if product_version else bytes(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="make a compiled exe reproducible")
    parser.add_argument("--in", dest="source", required=True)
    parser.add_argument("--out", dest="target", required=True)
    parser.add_argument("--seed", required=True)
    arguments = parser.parse_args(argv)
    with open(arguments.source, "rb") as handle:
        data = handle.read()
    with open(arguments.target, "wb") as handle:
        handle.write(make_reproducible(data, arguments.seed))
    print("WIN32_BYTES_OK=1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
