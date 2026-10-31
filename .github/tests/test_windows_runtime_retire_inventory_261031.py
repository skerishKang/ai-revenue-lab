"""The Windows retire inventory must still describe this repository.

``docs/operations/WINDOWS_RUNTIME_RETIRE_INVENTORY_20261031.md`` lists every
file that mentions the three Windows-release ports. This test re-scans the
repository and compares both directions, so a new reference -- a script, a
workflow, a cloudflared config or a doc -- fails here instead of being found
after the ports are gone. A listed file that stops matching also fails, so the
document cannot quietly drift.

The ports come from the document, not from this file. No host is contacted.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "operations" / "WINDOWS_RUNTIME_RETIRE_INVENTORY_20261031.md"
START = "<!-- port-reference-inventory:start -->"
END = "<!-- port-reference-inventory:end -->"
SKIP_DIRS = {
    ".git",
    ".playwright-mcp",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "site-packages",
}


def inventory() -> tuple[list[str], dict[str, set[str]], set[str]]:
    """Parse ``PORTS``, ``REF <port> = a, b`` and ``SKIP`` lines."""

    text = DOC.read_text(encoding="utf-8")
    block = text.split(START, 1)[1].split(END, 1)[0]

    ports: list[str] = []
    listed: dict[str, set[str]] = {}
    skipped: set[str] = set()
    for raw in block.splitlines():
        line = raw.strip()
        if line.startswith("PORTS="):
            ports = [part.strip() for part in line.split("=", 1)[1].split(",") if part.strip()]
        elif line.startswith("SKIP="):
            skipped.add(line.split("=", 1)[1].strip())
        elif line.startswith("REF "):
            _, port, values = line.split(" ", 2)
            entries = values.split("=", 1)[1]
            listed.setdefault(port.strip(), set()).update(
                entry.strip() for entry in entries.split(",") if entry.strip()
            )
    return ports, listed, skipped


def references(ports: list[str]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {port: set() for port in ports}
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if any(part in SKIP_DIRS for part in relative.split("/")):
            continue
        try:
            text = path.read_bytes().decode("utf-8", "ignore")
        except OSError:
            continue
        for port in ports:
            if port in text:
                found[port].add(relative)
    return found


def test_the_document_declares_its_ports():
    ports, listed, _skipped = inventory()
    assert ports, "no PORTS= line in the inventory block"
    assert set(listed) == set(ports)
    for port in ports:
        assert listed[port], f"{port} has no REF line"


def test_every_reference_is_listed_and_every_listed_file_still_matches():
    ports, listed, skipped = inventory()
    found = references(ports)

    for port in ports:
        discovered = found[port] - skipped
        expected = listed[port]
        new = sorted(discovered - expected)
        stale = sorted(expected - discovered)
        assert not new, f"{port}: unlisted reference(s) {new}"
        assert not stale, f"{port}: listed file(s) no longer match {stale}"


def test_listed_files_exist():
    _ports, listed, _skipped = inventory()
    missing = [
        relative
        for paths in listed.values()
        for relative in paths
        if not (ROOT / relative).is_file()
    ]
    assert missing == []


def test_every_skip_really_matches_a_port():
    # A skip that no longer matches is dead weight in the document.
    ports, _listed, skipped = inventory()
    matched = set().union(*references(ports).values())
    assert skipped <= matched
