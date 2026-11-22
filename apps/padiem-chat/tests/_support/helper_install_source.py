"""Read the shipped installer lane for the #7564 lockdown contracts
(#8060 48차, #8061 방향: 원문 읽기는 _support가 담당).

The lockdown test pins the shipped text itself — the SDDL descriptors, the
account SIDs and the install order — so these reads stay byte-faithful (the
wrapper keeps its BOM via utf-8-sig) and the test module keeps no raw file
read. The installer files are edited by other lanes; nothing here writes them.
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]


def wrapper_source() -> str:
    """The one-click PowerShell wrapper, BOM included (utf-8-sig)."""
    return (_REPO / "scripts" / "pc_pairing" / "install-padiem-pc.ps1").read_text(
        encoding="utf-8-sig")


def program_source() -> str:
    """The double-click program (C#) source."""
    return (_REPO / "scripts" / "pc_pairing" / "connect-exe" / "PadiemPcConnect.cs").read_text(
        encoding="utf-8")


def guide_source() -> str:
    """The operations guide that states what the install leaves behind."""
    return (_REPO / "docs" / "operations" / "PC_CONNECT_EXE_20261028.md").read_text(
        encoding="utf-8")
