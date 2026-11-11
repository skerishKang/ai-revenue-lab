"""The Windows retire inventory must still describe this repository.

The port-reference inventory was frozen at the #7404 private-records
migration (2026-11-11): the constant below is the inventory block exactly as
the retired document stated it. This test re-scans the repository and compares
both directions, so a new reference -- a script, a workflow, a cloudflared
config or a doc -- fails here instead of being found after the ports are gone.
A listed file that stops matching also fails.

The ports come from the document, not from this file. No host is contacted.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FROZEN_INVENTORY_BLOCK = """\

    PORTS=18764,18717,18731
    SKIP=docs/operations/WINDOWS_RUNTIME_RETIRE_INVENTORY_20261031.md
    SKIP=reference/business-42-ai-development-control-tower-v1/evidence/source-hashes.json
    SKIP=apps/korean-ai-platform/uv.lock
    SKIP=apps/padiem-chat/uv.lock
    SKIP=apps/padiem-file-lane/uv.lock
    SKIP=deploy/host-com2/file-lane/requirements.txt
    REF 18764 = apps/bookai/public/content/bible-web/book-EZK-chapter-031.json, apps/bookai/public/content/bible-web/book-GEN-chapter-038.json, apps/bookai/public/content/bible-web/book-ISA-chapter-056.json, apps/bookai/public/content/bible-web/book-JDG-chapter-017.json, apps/bookai/public/content/bible-web/book-JHN-chapter-005.json, apps/bookai/public/content/iliad/book-21.json, apps/padiem-chat/tests/test_5115_cookie_secure.py, apps/storymemory/public/content/bible-web/book-EZK-chapter-031.json, apps/storymemory/public/content/bible-web/book-GEN-chapter-038.json, apps/storymemory/public/content/bible-web/book-ISA-chapter-056.json, apps/storymemory/public/content/bible-web/book-JDG-chapter-017.json, apps/storymemory/public/content/bible-web/book-JHN-chapter-005.json, apps/storymemory/public/content/iliad/book-21.json, docs/operations/CHAT_COM2_MIGRATION_PLAN_ADDENDUM_20261031.md, docs/operations/COM2_B62_GENERATION_BINDING_20261019.md, docs/operations/COM2_HOST_FACTS_20261026.md, docs/operations/COM2_PRIMARY_RUNTIME_SUPERVISOR_AND_TUNNEL_20261019.md, docs/operations/WINDOWS_RUNTIME_RETIRE_RUNBOOK_20261031.md, scripts/ops/com2_runtime.py, scripts/ops/com2_tunnel.py, scripts/ops/tests/test_com2_runtime.py, scripts/ops/tests/test_com2_tunnel.py, scripts/ops/tests/test_windows_runtime_retire_contract.py, scripts/ops/windows_runtime_retire_check.ps1
    REF 18717 = apps/bookai/public/content/bible-web/book-1CH-chapter-015.json, apps/bookai/public/content/bible-web/book-1KI-chapter-008.json, apps/bookai/public/content/bible-web/book-1SA-chapter-005.json, apps/bookai/public/content/bible-web/book-1TI-chapter-003.json, apps/bookai/public/content/bible-web/book-ISA-chapter-053.json, apps/bookai/public/content/iliad/book-09.json, apps/bookai/public/content/metamorphoses/book-14.json, apps/storymemory/public/content/bible-web/book-1CH-chapter-015.json, apps/storymemory/public/content/bible-web/book-1KI-chapter-008.json, apps/storymemory/public/content/bible-web/book-1SA-chapter-005.json, apps/storymemory/public/content/bible-web/book-1TI-chapter-003.json, apps/storymemory/public/content/bible-web/book-ISA-chapter-053.json, apps/storymemory/public/content/iliad/book-09.json, apps/storymemory/public/content/metamorphoses/book-14.json, docs/operations/B14_FREE_ROLLOUT_REPO_WIDE_STATUS_2026-10-18.md, docs/operations/CHAT_COM2_MIGRATION_PLAN_ADDENDUM_20261031.md, docs/operations/COM2_HOST_FACTS_20261026.md, docs/operations/COM2_PRIMARY_RUNTIME_SUPERVISOR_AND_TUNNEL_20261019.md, docs/operations/WINDOWS_RUNTIME_RETIRE_RUNBOOK_20261031.md, scripts/ops/com2_runtime.py, scripts/ops/com2_tunnel.py, scripts/ops/tests/test_com2_runtime.py, scripts/ops/tests/test_com2_tunnel.py, scripts/ops/tests/test_windows_runtime_retire_contract.py, scripts/ops/windows_runtime_retire_check.ps1
    REF 18731 = apps/bookai/public/content/bible-web/book-ACT-chapter-015.json, apps/bookai/public/content/bible-web/book-ISA-chapter-048.json, apps/bookai/public/content/bible-web/book-ISA-chapter-054.json, apps/bookai/public/content/bible-web/book-REV-chapter-002.json, apps/bookai/public/content/metamorphoses/book-10.json, apps/padiem-ai-engine/tests/test_local_engine_asgi.py, apps/padiem-chat/tests/test_local_p01_engine_transport_261031.py, apps/storymemory/public/content/bible-web/book-ACT-chapter-015.json, apps/storymemory/public/content/bible-web/book-ISA-chapter-048.json, apps/storymemory/public/content/bible-web/book-ISA-chapter-054.json, apps/storymemory/public/content/bible-web/book-REV-chapter-002.json, apps/storymemory/public/content/metamorphoses/book-10.json, deploy/host-com2/README.md, deploy/host-com2/deploy_from_main.sh, deploy/host-com2/p01/README.md, deploy/host-com2/p01/install.sh, deploy/host-com2/p01/start.sh, deploy/host-com2/p01/tests/test_p01_packaging.py, docs/operations/CHAT_COM2_MIGRATION_PLAN_ADDENDUM_20261031.md, docs/operations/COM2_HOST_FACTS_20261026.md, docs/operations/COM2_PRIMARY_RUNTIME_SUPERVISOR_AND_TUNNEL_20261019.md, docs/operations/CPYTHON_P01_ENGINE_TRANSPORT_20261031.md, docs/operations/WINDOWS_RUNTIME_RETIRE_RUNBOOK_20261031.md, docs/research/REUSE_CANDIDATES_20261101.md, scripts/ops/com2_runtime.py, scripts/ops/com2_tunnel.py, scripts/ops/tests/test_com2_runtime.py, scripts/ops/tests/test_com2_tunnel.py, scripts/ops/tests/test_windows_runtime_retire_contract.py, scripts/ops/windows_runtime_retire_check.ps1
"""
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

    block = FROZEN_INVENTORY_BLOCK

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
