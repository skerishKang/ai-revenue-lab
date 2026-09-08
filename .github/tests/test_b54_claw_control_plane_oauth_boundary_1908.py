from __future__ import annotations

import ast
from pathlib import Path
import re

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CLAW_KAGENT_DIR = REPO_ROOT / "apps" / "korean-ai-code-agent" / "src" / "kagent"
CONTROL_PLANE_DIR = REPO_ROOT / "packages" / "padiem-control-plane"
BOUNDARY_DOC = REPO_ROOT / "docs" / "architecture" / "B54_CLAW_CONTROL_PLANE_GOOGLE_OAUTH_BOUNDARY_1908.md"


def test_boundary_documentation_exists_and_contains_required_sections() -> None:
    assert BOUNDARY_DOC.exists(), "Boundary doc B54_CLAW_CONTROL_PLANE_GOOGLE_OAUTH_BOUNDARY_1908.md must exist"
    content = BOUNDARY_DOC.read_text(encoding="utf-8")

    required_snippets = [
        "GOOGLE_OAUTH_PROVIDER_CLIENT_CONFIG_OWNER = SPLIT",
        "GOOGLE_TOKEN_REFRESH_AUTHORITY            = SPLIT",
        "GOOGLE_CANONICAL_IDENTITY_AUTHORITY       = CONTROL_PLANE",
        "CONNECT_TICKET_ISSUANCE                   = CONTROL_PLANE",
        "DEVICE_CREDENTIAL_AND_PAIRING_AUTHORITY   = CONTROL_PLANE",
        "GMAIL_DRIVE_API_CALL_EXECUTION            = CLAW_CONNECTOR_RUNTIME",
        "WINDOWS_LOCAL_EXECUTION                   = CLAW",
        "DUPLICATE_AUTHORITY_DETECTED = YES",
        "SEPARATE_CONSOLIDATION_ISSUE_NEEDED = YES",
    ]
    for snippet in required_snippets:
        # Normalize whitespace comparison
        norm_snippet = re.sub(r"\s+", " ", snippet.strip())
        norm_content = re.sub(r"\s+", " ", content)
        assert norm_snippet in norm_content, f"Missing required ownership snippet: {snippet}"

    # Check for corruption: no control characters other than \t, \n, \r
    raw_bytes = BOUNDARY_DOC.read_bytes()
    bad_control_chars = [b for b in raw_bytes if b < 32 and b not in (9, 10, 13)]
    assert not bad_control_chars, f"Boundary doc contains control characters: {bad_control_chars}"

    # Must contain proper apps paths and not corrupted pps/ paths
    assert "apps/korean-ai-code-agent/src/kagent/" in content
    assert not re.search(r"(?<![a-zA-Z0-9_-])pps/korean-ai-code-agent", content), (
        "Boundary doc contains corrupted pps/ path without leading a"
    )

    # Must contain proper ```text code fences
    assert "```text\nGOOGLE_OAUTH_PROVIDER_CLIENT_CONFIG_OWNER = SPLIT" in content or "```text\r\nGOOGLE_OAUTH_PROVIDER_CLIENT_CONFIG_OWNER = SPLIT" in content, (
        "Boundary doc contains malformed code block fence"
    )
    assert "\n```\n\n### Detailed Ownership Breakdown" in content or "\r\n```\r\n\r\n### Detailed Ownership Breakdown" in content, (
        "Boundary doc contains malformed closing code block fence"
    )


def test_claw_source_must_not_mint_canonical_identity_or_sessions() -> None:
    """Claw must not act as the canonical identity authority or mint canonical sessions."""
    assert CLAW_KAGENT_DIR.exists(), f"Claw directory {CLAW_KAGENT_DIR} must exist"

    forbidden_symbols = {
        "CanonicalIdentityDurableObject",
        "CanonicalSubjectRef",
        "SubjectType",
    }

    for py_file in CLAW_KAGENT_DIR.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                assert node.name not in forbidden_symbols, (
                    f"{py_file.name} defines forbidden canonical identity class {node.name}"
                )
            elif isinstance(node, ast.FunctionDef):
                assert not node.name.startswith("mint_canonical_session"), (
                    f"{py_file.name} defines forbidden canonical session minter {node.name}"
                )
                assert not node.name.startswith("mint_canonical_identity"), (
                    f"{py_file.name} defines forbidden canonical identity minter {node.name}"
                )


def test_claw_source_must_not_issue_connect_tickets() -> None:
    """Claw source must not issue connect tickets or own ticket signing keys."""
    assert CLAW_KAGENT_DIR.exists()

    forbidden_symbols = {
        "GoogleConnectTicketIssuer",
        "ConnectorConnectTicketAuthority",
        "decode_connect_ticket_key",
    }

    for py_file in CLAW_KAGENT_DIR.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                assert node.name not in forbidden_symbols, (
                    f"{py_file.name} defines forbidden connect ticket issuer symbol {node.name}"
                )
            if isinstance(node, ast.ImportFrom):
                if node.module and "connector_connect_ticket" in node.module:
                    for alias in node.names:
                        assert alias.name not in {"GoogleConnectTicketIssuer", "ConnectorConnectTicketAuthority"}, (
                            f"{py_file.name} imports connect ticket issuing authority from {node.module}"
                        )


def test_claw_source_must_not_claim_device_pairing_authority() -> None:
    """Claw must not define device pairing authority (reserved for Control Plane)."""
    assert CLAW_KAGENT_DIR.exists()

    for py_file in CLAW_KAGENT_DIR.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                assert "DevicePairingAuthority" not in node.name, (
                    f"{py_file.name} defines forbidden device pairing authority class {node.name}"
                )


def test_control_plane_must_not_perform_windows_local_execution() -> None:
    """Control Plane runs in serverless edge environment and must not perform Windows execution."""
    assert CONTROL_PLANE_DIR.exists(), f"Control plane directory {CONTROL_PLANE_DIR} must exist"

    forbidden_modules = {"subprocess", "winreg", "msvcrt", "ctypes"}

    for py_file in CONTROL_PLANE_DIR.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".")[0]
                    assert root_mod not in forbidden_modules, (
                        f"{py_file.name} imports forbidden local execution module {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root_mod = node.module.split(".")[0]
                    assert root_mod not in forbidden_modules, (
                        f"{py_file.name} imports from forbidden local execution module {node.module}"
                    )


def test_secret_hygiene_no_hardcoded_secret_literals() -> None:
    """Secret material must be referenced by name only; no raw literal secrets."""
    secret_literal_patterns = [
        re.compile(r"""client_secret\s*=\s*['"][a-zA-Z0-9_\-]{24,}['"]"""),
        re.compile(r"""refresh_token\s*=\s*['"]1//[a-zA-Z0-9_\-]{30,}['"]"""),
        re.compile(r"""-----BEGIN PRIVATE KEY-----"""),
    ]

    for scan_dir in (CLAW_KAGENT_DIR, CONTROL_PLANE_DIR):
        for py_file in scan_dir.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            for pat in secret_literal_patterns:
                match = pat.search(text)
                assert match is None, (
                    f"Possible hardcoded secret literal found in {py_file.name}: {match.group(0)[:20]}..."
                )
